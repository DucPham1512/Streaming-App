"""Media service — Feature 5 business logic.

Mirrors ``stream_manager`` patterns: a service object that wraps the
DB model, exposes high-level operations to routes, and isolates
storage concerns behind ``storage_service``.

Owns:
    - Filename sanitization (Unicode-aware; replaces secure_filename)
    - Mimetype sniffing + allowlist enforcement (via ``filetype``)
    - Per-user quota enforcement
    - Storage-key generation (D4)
    - Bucket selection by visibility (D6)
    - Transactional safety: upload-first, commit-second, compensate (D7)
    - Soft-delete semantics (D5) and orphan cleanup helper

Does NOT own:
    - Auth (in ``auth_service``)
    - HTTP request parsing (in ``media_routes``)
    - Raw boto3 calls (in ``storage_service``)
"""

import logging
import os
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import BinaryIO, Optional

import filetype
from flask import current_app
from sqlalchemy import func

from app.extensions import db, socketio
from app.models.media import VISIBILITY_VALUES, MediaItem
from app.models.user import User
from app.services.exceptions import (
    Forbidden,
    InvalidField,
    NotFound,
    QuotaExceeded,
    UnsupportedMimetype,
)
from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)


# --- Filename + key helpers ------------------------------------------------

_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/ogg": ".ogv",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
}


def sanitize_filename(name: str) -> str:
    """Unicode-aware filename sanitizer.

    Differs from ``werkzeug.utils.secure_filename``: it KEEPS Unicode
    characters (Vietnamese, etc.) and only strips path separators,
    null bytes, and control characters. Length capped at 255 bytes UTF-8
    after normalization. Empty result becomes ``untitled-<uuid8>``.
    """
    if not name:
        return f"untitled-{uuid.uuid4().hex[:8]}"

    normalized = unicodedata.normalize("NFKC", name)
    cleaned = re.sub(r"[/\\\x00-\x1f\x7f]", "", normalized).strip()
    if not cleaned:
        return f"untitled-{uuid.uuid4().hex[:8]}"

    base, ext = os.path.splitext(cleaned)
    encoded = base.encode("utf-8")
    while len(encoded) + len(ext.encode("utf-8")) > 255:
        base = base[:-1]
        encoded = base.encode("utf-8")
        if not base:
            break
    if not base:
        base = f"untitled-{uuid.uuid4().hex[:8]}"
    return base + ext


def make_storage_key(owner_id: str, mimetype: str, original_filename: str) -> str:
    """Generate the canonical storage key (D4).

    Format: ``{owner_id}/{yyyy}/{mm}/{media_uuid}{ext}``
    """
    now = datetime.now(timezone.utc)
    media_uuid = uuid.uuid4().hex
    ext = _MIME_EXT.get(mimetype) or os.path.splitext(original_filename)[1] or ""
    ext = ext.lower()
    return f"{owner_id}/{now.year:04d}/{now.month:02d}/{media_uuid}{ext}"


# --- Mimetype sniffing -----------------------------------------------------


def sniff_mimetype(stream: BinaryIO) -> Optional[str]:
    """Sniff the first 261 bytes of ``stream``; return mimetype or None.

    Leaves the stream rewound to position 0 so the caller can re-read.
    """
    pos = stream.tell()
    head = stream.read(261)
    stream.seek(pos)
    kind = filetype.guess(head)
    return kind.mime if kind else None


# --- Bucket selection -------------------------------------------------------


def bucket_for_visibility(visibility: str) -> str:
    """Pick the bucket for the given visibility (D6).

    Public + unlisted live in the public bucket (unlisted = obscurity-only).
    Private lives in the private bucket.
    """
    cfg = current_app.config
    if visibility in ("public", "unlisted"):
        return cfg["MEDIA_PUBLIC_BUCKET"]
    return cfg["MEDIA_PRIVATE_BUCKET"]


# --- Service ---------------------------------------------------------------


class MediaService:
    """High-level media operations used by the route layer."""

    # --- Reads ------------------------------------------------------------

    def get_media(self, media_id: str, *, include_deleted: bool = False) -> Optional[MediaItem]:
        item = db.session.get(MediaItem, media_id)
        if item is None:
            return None
        if not include_deleted and item.deleted_at is not None:
            return None
        return item

    def list_media(
        self,
        *,
        viewer: Optional[User],
        owner_id: Optional[str] = None,
        visibility: Optional[str] = None,
        mimetype_prefix: Optional[str] = None,
        page: int = 1,
        per_page: int = 12,
    ) -> tuple[list[MediaItem], int]:
        """Paginated list with auth-aware visibility filter."""
        per_page = max(1, min(per_page, 100))
        page = max(1, page)

        q = MediaItem.query.filter(MediaItem.deleted_at.is_(None))
        if owner_id:
            q = q.filter(MediaItem.owner_id == owner_id)
        if mimetype_prefix:
            q = q.filter(MediaItem.mimetype.like(f"{mimetype_prefix}%"))

        # Visibility filter — viewer must own the item to see private.
        viewer_id = viewer.id if viewer else None
        if owner_id and owner_id == viewer_id:
            if visibility and visibility in VISIBILITY_VALUES:
                q = q.filter(MediaItem.visibility == visibility)
        else:
            visible = ("public", "unlisted")
            if visibility and visibility in visible:
                q = q.filter(MediaItem.visibility == visibility)
            else:
                q = q.filter(MediaItem.visibility.in_(visible))

        total = q.count()
        items = (
            q.order_by(MediaItem.created_at.desc(), MediaItem.id.asc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return items, total

    # --- Quota helper -----------------------------------------------------

    def used_quota_bytes(self, owner_id: str) -> int:
        total = (
            db.session.query(func.coalesce(func.sum(MediaItem.file_size), 0))
            .filter(MediaItem.owner_id == owner_id)
            .filter(MediaItem.deleted_at.is_(None))
            .scalar()
        )
        return int(total or 0)

    # --- Upload (the big one) --------------------------------------------

    def upload_media(
        self,
        *,
        owner: User,
        stream: BinaryIO,
        original_filename: str,
        title: str = "",
        description: str = "",
        visibility: str = "private",
        request_content_type: Optional[str] = None,
    ) -> MediaItem:
        """Upload a media file end-to-end.

        Order (D7): validate → upload → DB insert → on-DB-failure delete object.
        Emits ``media_uploaded`` SocketIO event after successful commit.
        """
        cfg = current_app.config

        if visibility not in VISIBILITY_VALUES:
            raise InvalidField(
                f"visibility must be one of {VISIBILITY_VALUES}",
                field="visibility",
            )

        sniffed = sniff_mimetype(stream)
        allowlist = cfg["MEDIA_ALLOWED_MIMETYPES"]
        if sniffed is None or sniffed not in allowlist:
            raise UnsupportedMimetype(
                f"Detected mimetype {sniffed!r} is not allowed",
                detected_mimetype=sniffed,
            )

        # Compute size by streaming-tally so we can abort early if oversize.
        max_bytes = cfg["MEDIA_MAX_SIZE_MB"] * 1024 * 1024
        quota_bytes = cfg["MEDIA_QUOTA_MB_PER_USER"] * 1024 * 1024
        used = self.used_quota_bytes(owner.id)

        sanitized_filename = sanitize_filename(original_filename)
        storage_key = make_storage_key(owner.id, sniffed, sanitized_filename)
        bucket = bucket_for_visibility(visibility)

        # Wrap the stream with a counting reader that aborts at max_bytes.
        from app.services.exceptions import FileTooLarge

        size_holder = {"n": 0}

        class _CountingReader:
            def __init__(self, inner):
                self._inner = inner

            def read(self, n=-1):
                chunk = self._inner.read(n)
                if not chunk:
                    return chunk
                size_holder["n"] += len(chunk)
                if size_holder["n"] > max_bytes:
                    raise FileTooLarge(
                        f"Upload exceeds {cfg['MEDIA_MAX_SIZE_MB']} MB",
                        max_size_mb=cfg["MEDIA_MAX_SIZE_MB"],
                    )
                if used + size_holder["n"] > quota_bytes:
                    raise QuotaExceeded(
                        "Per-user storage quota exceeded",
                        quota_mb=cfg["MEDIA_QUOTA_MB_PER_USER"],
                    )
                return chunk

        # Upload (raises StorageUnavailable on backend errors).
        storage_service.upload_fileobj(
            _CountingReader(stream),
            bucket=bucket,
            key=storage_key,
            content_type=sniffed,
        )

        # Insert DB row; on commit failure, delete the just-uploaded object.
        title_value = title or os.path.splitext(sanitized_filename)[0]
        item = MediaItem(
            owner_id=owner.id,
            original_filename=sanitized_filename,
            mimetype=sniffed,
            file_size=size_holder["n"],
            storage_bucket=bucket,
            storage_key=storage_key,
            title=title_value,
            description=description or "",
            visibility=visibility,
        )
        try:
            db.session.add(item)
            db.session.commit()
        except Exception:
            db.session.rollback()
            try:
                storage_service.delete_object(bucket, storage_key)
            except Exception as cleanup_exc:  # pragma: no cover
                logger.error(
                    "compensating delete failed for orphan %s/%s: %s",
                    bucket,
                    storage_key,
                    cleanup_exc,
                )
            raise

        logger.info(
            "media uploaded",
            extra={
                "media_id": item.id,
                "owner_id": owner.id,
                "bytes": size_holder["n"],
                "bucket": bucket,
            },
        )

        try:
            socketio.emit(
                "media_uploaded",
                {
                    "event": "media_uploaded",
                    "data": {"media": item.to_dict()},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                to=f"user:{owner.id}",
            )
        except Exception as exc:  # pragma: no cover — emission is best-effort
            logger.warning("media_uploaded emit failed: %s", exc)

        return item

    # --- Update -----------------------------------------------------------

    def update_media(
        self,
        item: MediaItem,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        visibility: Optional[str] = None,
    ) -> MediaItem:
        """Update mutable fields. Visibility change triggers bucket move."""
        old_bucket = item.storage_bucket
        old_visibility = item.visibility
        moved_to_bucket = None

        if title is not None:
            item.title = title
        if description is not None:
            item.description = description
        if visibility is not None:
            if visibility not in VISIBILITY_VALUES:
                raise InvalidField(
                    f"visibility must be one of {VISIBILITY_VALUES}",
                    field="visibility",
                )
            if visibility != item.visibility:
                new_bucket = bucket_for_visibility(visibility)
                if new_bucket != item.storage_bucket:
                    storage_service.move_object(
                        item.storage_bucket, new_bucket, item.storage_key
                    )
                    item.storage_bucket = new_bucket
                    moved_to_bucket = new_bucket
                item.visibility = visibility

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            # Compensate visibility move on commit failure so metadata/storage stay aligned.
            if visibility is not None and visibility != old_visibility and moved_to_bucket:
                try:
                    storage_service.move_object(moved_to_bucket, old_bucket, item.storage_key)
                except Exception as move_back_exc:  # pragma: no cover
                    logger.error(
                        "failed to compensate visibility move for media %s after commit failure: %s",
                        item.id,
                        move_back_exc,
                    )
            raise
        return item

    # --- Soft delete ------------------------------------------------------

    def delete_media(self, item: MediaItem) -> MediaItem:
        """Soft-delete: stamps ``deleted_at`` but keeps the object."""
        if item.deleted_at is None:
            item.deleted_at = datetime.now(timezone.utc)
            db.session.commit()
        return item

    # --- Admin / cleanup --------------------------------------------------

    def purge_deleted_media(self, *, older_than_days: int = 30) -> int:
        """Hard-delete soft-deleted items older than the cutoff.

        Returns the number of items purged. Object delete is best-effort —
        if storage delete fails, the row stays so a retry can clean it up.
        """
        cutoff = datetime.now(timezone.utc).timestamp() - older_than_days * 86400
        cutoff_dt = datetime.fromtimestamp(cutoff, tz=timezone.utc)
        candidates = (
            MediaItem.query.filter(MediaItem.deleted_at.isnot(None))
            .filter(MediaItem.deleted_at <= cutoff_dt)
            .all()
        )
        purged = 0
        for item in candidates:
            try:
                storage_service.delete_object(item.storage_bucket, item.storage_key)
            except Exception as exc:
                logger.warning(
                    "skipping purge of %s — storage delete failed: %s", item.id, exc
                )
                continue
            db.session.delete(item)
            purged += 1
        db.session.commit()
        return purged


media_service = MediaService()
