"""REST API routes for the Content Library.

Endpoints (under /api/v1/media):
    POST   /upload            multipart upload
    GET    /                  paginated list (auth-aware)
    GET    /<id>              single-item metadata
    GET    /<id>/stream       Flask download proxy (Range-aware)
    GET    /<id>/url          presigned URL (public bucket only)
    PATCH  /<id>              update metadata
    DELETE /<id>              soft delete

Error envelope (all non-2xx): {"error": "...", "code": "..."}
"""

import logging
from urllib.parse import quote

from flask import Blueprint, Response, current_app, g, jsonify, request, stream_with_context

from app.extensions import limiter
from app.services.auth_service import (
    current_user,
    current_user_optional,
    require_auth,
    require_owner,
)
from app.services.exceptions import (
    FileTooLarge,
    Forbidden,
    InvalidField,
    InvalidRequest,
    NotFound,
    Unauthorized,
)
from app.services.media_service import media_service
from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)

media_bp = Blueprint("media", __name__, url_prefix="/api/v1/media")


# --- Helpers ---------------------------------------------------------------
def _serialize(item) -> dict:
    return {"media": item.to_dict()}


def _check_content_length(cfg) -> None:
    """Layer 2 of size enforcement (D3) — header check before reading."""
    cl = request.content_length
    if cl is not None and cl > cfg["MEDIA_MAX_SIZE_MB"] * 1024 * 1024:
        raise FileTooLarge(
            f"Upload exceeds {cfg['MEDIA_MAX_SIZE_MB']} MB",
            max_size_mb=cfg["MEDIA_MAX_SIZE_MB"],
        )


# --- POST /upload ----------------------------------------------------------


@media_bp.route("/upload", methods=["POST"])
@limiter.limit("10 per minute", key_func=lambda: g.current_user.id if hasattr(g, "current_user") else request.remote_addr)
@require_auth
def upload_media():
    cfg = current_app.config
    _check_content_length(cfg)

    if "file" not in request.files:
        raise InvalidField("Missing 'file' part in multipart upload", field="file")

    fs = request.files["file"]
    if not fs.filename:
        raise InvalidField("Uploaded file has no filename", field="file")

    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    visibility = (request.form.get("visibility") or "private").strip()

    item = media_service.upload_media(
        owner=g.current_user,
        stream=fs.stream,
        original_filename=fs.filename,
        title=title,
        description=description,
        visibility=visibility,
        request_content_type=fs.mimetype,
    )

    return jsonify(_serialize(item)), 201


# --- GET / -----------------------------------------------------------------


@media_bp.route("", methods=["GET"])
def list_media():
    viewer = current_user_optional()

    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = max(1, min(100, int(request.args.get("per_page", 12))))
    except (ValueError, TypeError) as exc:
        raise InvalidRequest(
            "Query params 'page' and 'per_page' must be integers",
            fields=["page", "per_page"],
        ) from exc
    owner_id = request.args.get("owner_id")
    visibility = request.args.get("visibility")
    mimetype_prefix = request.args.get("mimetype_prefix")

    items, total = media_service.list_media(
        viewer=viewer,
        owner_id=owner_id,
        visibility=visibility,
        mimetype_prefix=mimetype_prefix,
        page=page,
        per_page=per_page,
    )

    total_pages = (total + per_page - 1) // per_page if per_page else 0
    return jsonify(
        {
            "items": [it.to_dict() for it in items],
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        }
    ), 200


# --- GET /<id> -------------------------------------------------------------


@media_bp.route("/<media_id>", methods=["GET"])
def get_media(media_id):
    item = media_service.get_media(media_id)
    if item is None:
        raise NotFound("Media item not found")
    if item.visibility == "private":
        viewer = current_user_optional()
        if viewer is None:
            raise Unauthorized("Authentication required for private media")
        if viewer.id != item.owner_id:
            raise Forbidden("You do not own this resource")
    return jsonify(_serialize(item)), 200


# --- GET /<id>/stream (download proxy) -------------------------------------


@media_bp.route("/<media_id>/stream", methods=["GET"])
def stream_media(media_id):
    item = media_service.get_media(media_id)
    if item is None:
        raise NotFound("Media item not found")
    if item.visibility == "private":
        viewer = current_user_optional()
        if viewer is None:
            raise Unauthorized("Authentication required for private media")
        if viewer.id != item.owner_id:
            raise Forbidden("You do not own this resource")

    range_header = request.headers.get("Range")
    iterator, meta = storage_service.get_object_stream(
        item.storage_bucket, item.storage_key, range_header=range_header
    )

    headers = {
        "Content-Type": item.mimetype,
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(item.original_filename)}",
    }
    if meta.get("content_length") is not None:
        headers["Content-Length"] = str(meta["content_length"])
    if meta.get("content_range"):
        headers["Content-Range"] = meta["content_range"]
        headers["Accept-Ranges"] = "bytes"
    headers["Cache-Control"] = (
        "public, max-age=3600" if item.visibility == "public" else "private, no-cache"
    )

    return Response(
        stream_with_context(iterator),
        status=meta.get("status_code", 200),
        headers=headers,
    )


# --- GET /<id>/url (presigned, public bucket only) -------------------------


@media_bp.route("/<media_id>/url", methods=["GET"])
def get_media_url(media_id):
    item = media_service.get_media(media_id)
    if item is None:
        raise NotFound("Media item not found")
    cfg = current_app.config
    if item.storage_bucket != cfg["MEDIA_PUBLIC_BUCKET"]:
        raise InvalidField(
            "Presigned URLs only available for public-bucket items; use /stream",
            field="visibility",
        )
    ttl = cfg["MEDIA_PRESIGNED_TTL_SECONDS"]
    url = storage_service.generate_presigned_url(
        item.storage_bucket, item.storage_key, expires_in=ttl
    )
    from datetime import datetime, timedelta, timezone

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    return jsonify(
        {"url": url, "expires_at": expires_at.isoformat(), "expires_in_seconds": ttl}
    ), 200


# --- PATCH /<id> -----------------------------------------------------------


def _get_for_owner(media_id):
    return media_service.get_media(media_id)


@media_bp.route("/<media_id>", methods=["PATCH"])
@require_auth
@require_owner(_get_for_owner)
def update_media(media_id):
    item = g.current_owned_object

    data = request.get_json(silent=True) or {}
    item = media_service.update_media(
        item,
        title=data.get("title"),
        description=data.get("description"),
        visibility=data.get("visibility"),
    )
    return jsonify(_serialize(item)), 200


# --- DELETE /<id> ----------------------------------------------------------


@media_bp.route("/<media_id>", methods=["DELETE"])
@require_auth
@require_owner(_get_for_owner)
def delete_media(media_id):
    item = g.current_owned_object

    media_service.delete_media(item)
    return jsonify({"media": item.to_dict(), "message": "Media item deleted"}), 200
