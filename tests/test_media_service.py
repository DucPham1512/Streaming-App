"""Unit tests for app.services.media_service.

Covers sanitize_filename (Vietnamese!), make_storage_key uniqueness,
upload happy path + transactional rollback, list visibility filter,
soft-delete semantics, update + bucket move, quota enforcement.
"""

import io

import pytest
from botocore.exceptions import ClientError

from app.models.media import MediaItem
from app.services.exceptions import (
    InvalidField,
    QuotaExceeded,
    UnsupportedMimetype,
)
from app.services.media_service import (
    bucket_for_visibility,
    make_storage_key,
    media_service,
    sanitize_filename,
    sniff_mimetype,
)
from app.services.storage_service import storage_service


# Minimal valid PNG (1x1 transparent) — recognized by ``filetype``.
_PNG = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
    "0000000D49444154789C6300010000000500010D0A2DB40000000049454E44AE426082"
)
# Minimal valid JPEG header — recognized by ``filetype``.
_JPEG = bytes.fromhex(
    "FFD8FFE000104A46494600010100000100010000FFDB004300080606070605080707"
    "07090908"
) + b"\xff\xd9"


def _png_stream() -> io.BytesIO:
    return io.BytesIO(_PNG)


def _jpeg_stream() -> io.BytesIO:
    return io.BytesIO(_JPEG)


class TestSanitizeFilename:
    def test_keeps_vietnamese(self):
        assert sanitize_filename("Sao đen thui zậy.jpg") == "Sao đen thui zậy.jpg"

    def test_strips_path_separators(self):
        assert sanitize_filename("../etc/passwd.png") == "..etcpasswd.png"

    def test_strips_null_and_control(self):
        assert sanitize_filename("a\x00b\x01c.png") == "abc.png"

    def test_empty_falls_back_to_untitled(self):
        out = sanitize_filename("")
        assert out.startswith("untitled-")

    def test_only_separators_falls_back(self):
        out = sanitize_filename("///\x00")
        assert out.startswith("untitled-")

    def test_preserves_extension(self):
        out = sanitize_filename("foo.JPG")
        assert out.endswith(".JPG")


class TestStorageKey:
    def test_format_includes_owner_and_uuid_and_ext(self):
        key = make_storage_key("user-123", "image/jpeg", "any.jpg")
        parts = key.split("/")
        assert parts[0] == "user-123"
        assert len(parts[1]) == 4  # year
        assert len(parts[2]) == 2  # month
        assert parts[3].endswith(".jpg")

    def test_collisions_are_uuid_random(self):
        a = make_storage_key("u", "image/png", "x.png")
        b = make_storage_key("u", "image/png", "x.png")
        assert a != b


class TestSniffMimetype:
    def test_sniff_png(self):
        assert sniff_mimetype(_png_stream()) == "image/png"

    def test_sniff_jpeg(self):
        assert sniff_mimetype(_jpeg_stream()) == "image/jpeg"

    def test_sniff_garbage_returns_none(self):
        assert sniff_mimetype(io.BytesIO(b"not a real file at all")) is None

    def test_stream_rewound_after_sniff(self):
        s = _png_stream()
        sniff_mimetype(s)
        assert s.tell() == 0


class TestBucketForVisibility:
    def test_public_and_unlisted_use_public_bucket(self, app):
        with app.app_context():
            assert bucket_for_visibility("public") == app.config["MEDIA_PUBLIC_BUCKET"]
            assert bucket_for_visibility("unlisted") == app.config["MEDIA_PUBLIC_BUCKET"]

    def test_private_uses_private_bucket(self, app):
        with app.app_context():
            assert (
                bucket_for_visibility("private") == app.config["MEDIA_PRIVATE_BUCKET"]
            )


class TestUploadMedia:
    def test_happy_path_creates_row_and_object(
        self, app, db, auth_user, fresh_buckets, s3_client
    ):
        pub, priv = fresh_buckets
        with app.app_context():
            item = media_service.upload_media(
                owner=auth_user,
                stream=_png_stream(),
                original_filename="hello.png",
                title="Hello",
                visibility="public",
            )
            assert item.id
            assert item.owner_id == auth_user.id
            assert item.mimetype == "image/png"
            assert item.storage_bucket == pub
            assert item.visibility == "public"
            # Object exists in S3.
            obj = s3_client.get_object(Bucket=pub, Key=item.storage_key)
            assert obj["Body"].read() == _PNG

    def test_rejects_unsupported_mimetype(self, app, db, auth_user, fresh_buckets):
        with app.app_context():
            with pytest.raises(UnsupportedMimetype):
                media_service.upload_media(
                    owner=auth_user,
                    stream=io.BytesIO(b"PK\x03\x04random zip-like garbage"),
                    original_filename="evil.zip",
                )

    def test_rejects_invalid_visibility(self, app, db, auth_user, fresh_buckets):
        with app.app_context():
            with pytest.raises(InvalidField):
                media_service.upload_media(
                    owner=auth_user,
                    stream=_png_stream(),
                    original_filename="x.png",
                    visibility="weird",
                )

    def test_unicode_filename_round_trips(
        self, app, db, auth_user, fresh_buckets, s3_client
    ):
        with app.app_context():
            item = media_service.upload_media(
                owner=auth_user,
                stream=_png_stream(),
                original_filename="Sao đen thui zậy.png",
            )
            assert item.original_filename == "Sao đen thui zậy.png"

    def test_quota_exceeded_raises(self, app, db, auth_user, fresh_buckets, monkeypatch):
        with app.app_context():
            # Set quota to 0 MB so any upload exceeds it.
            app.config["MEDIA_QUOTA_MB_PER_USER"] = 0
            try:
                with pytest.raises(QuotaExceeded):
                    media_service.upload_media(
                        owner=auth_user,
                        stream=_png_stream(),
                        original_filename="big.png",
                    )
            finally:
                app.config["MEDIA_QUOTA_MB_PER_USER"] = 1024

    def test_compensating_delete_on_db_failure(
        self, app, db, auth_user, fresh_buckets, s3_client, monkeypatch
    ):
        """If db.commit fails after upload, the object must be deleted."""
        from app.extensions import db as ext_db

        original_commit = ext_db.session.commit
        with app.app_context():
            calls = {"n": 0}

            def fail_once():
                if calls["n"] == 0:
                    calls["n"] += 1
                    raise RuntimeError("simulated db failure")
                return original_commit()

            monkeypatch.setattr(ext_db.session, "commit", fail_once)
            with pytest.raises(RuntimeError):
                media_service.upload_media(
                    owner=auth_user,
                    stream=_png_stream(),
                    original_filename="orphan.png",
                )
            # No row, no object — verify by listing pub bucket.
            objs = (
                s3_client.list_objects_v2(Bucket=app.config["MEDIA_PRIVATE_BUCKET"]).get(
                    "Contents", []
                )
                or []
            )
            assert all("orphan" not in (o.get("Key") or "") for o in objs)

    def test_upload_emits_step5_socket_payload(
        self, app, db, auth_user, fresh_buckets, monkeypatch
    ):
        with app.app_context():
            captured = {}

            def fake_emit(event_name, payload, to=None):
                captured["event_name"] = event_name
                captured["payload"] = payload
                captured["to"] = to

            monkeypatch.setattr("app.services.media_service.socketio.emit", fake_emit)

            item = media_service.upload_media(
                owner=auth_user,
                stream=_png_stream(),
                original_filename="socket.png",
            )

            assert captured["event_name"] == "media_uploaded"
            assert captured["to"] == f"user:{auth_user.id}"
            assert captured["payload"]["event"] == "media_uploaded"
            assert captured["payload"]["data"]["media"]["id"] == item.id
            assert "timestamp" in captured["payload"]


class TestListAndVisibility:
    def _seed(self, app, db, auth_user, other_user, fresh_buckets):
        with app.app_context():
            for vis in ("public", "private", "unlisted"):
                media_service.upload_media(
                    owner=auth_user,
                    stream=_png_stream(),
                    original_filename=f"{vis}.png",
                    visibility=vis,
                )
            for vis in ("public", "private"):
                media_service.upload_media(
                    owner=other_user,
                    stream=_png_stream(),
                    original_filename=f"o-{vis}.png",
                    visibility=vis,
                )

    def test_anonymous_sees_only_public_and_unlisted(
        self, app, db, auth_user, other_user, fresh_buckets
    ):
        self._seed(app, db, auth_user, other_user, fresh_buckets)
        with app.app_context():
            items, total = media_service.list_media(viewer=None)
            for it in items:
                assert it.visibility in ("public", "unlisted")

    def test_owner_sees_their_own_private(
        self, app, db, auth_user, other_user, fresh_buckets
    ):
        self._seed(app, db, auth_user, other_user, fresh_buckets)
        with app.app_context():
            items, _ = media_service.list_media(viewer=auth_user, owner_id=auth_user.id)
            visibilities = {it.visibility for it in items}
            assert "private" in visibilities

    def test_other_user_does_not_see_private(
        self, app, db, auth_user, other_user, fresh_buckets
    ):
        self._seed(app, db, auth_user, other_user, fresh_buckets)
        with app.app_context():
            items, _ = media_service.list_media(viewer=auth_user, owner_id=other_user.id)
            for it in items:
                assert it.visibility != "private"

    def test_per_page_capped(self, app, db, auth_user, fresh_buckets):
        with app.app_context():
            items, _ = media_service.list_media(viewer=None, per_page=999999)
            # No items exist yet but the call must not blow up.
            assert items == []


class TestUpdateAndDelete:
    def test_visibility_change_moves_bucket(
        self, app, db, auth_user, fresh_buckets, s3_client
    ):
        pub, priv = fresh_buckets
        with app.app_context():
            item = media_service.upload_media(
                owner=auth_user,
                stream=_png_stream(),
                original_filename="x.png",
                visibility="private",
            )
            assert item.storage_bucket == priv
            updated = media_service.update_media(item, visibility="public")
            assert updated.storage_bucket == pub
            # Object is in pub, gone from priv.
            assert s3_client.get_object(Bucket=pub, Key=item.storage_key)["Body"].read()
            with pytest.raises(Exception):
                s3_client.get_object(Bucket=priv, Key=item.storage_key)

    def test_soft_delete_excludes_from_list(self, app, db, auth_user, fresh_buckets):
        with app.app_context():
            item = media_service.upload_media(
                owner=auth_user,
                stream=_png_stream(),
                original_filename="trash.png",
                visibility="public",
            )
            media_service.delete_media(item)
            items, total = media_service.list_media(viewer=auth_user, owner_id=auth_user.id)
            assert all(it.id != item.id for it in items)
            assert total == 0
            # Row still present when include_deleted=True via direct query.
            row = MediaItem.query.get(item.id)
            assert row is not None
            assert row.deleted_at is not None

    def test_visibility_change_keeps_db_update_when_source_delete_fails(
        self, app, db, auth_user, fresh_buckets, s3_client, monkeypatch
    ):
        pub, priv = fresh_buckets
        with app.app_context():
            item = media_service.upload_media(
                owner=auth_user,
                stream=_png_stream(),
                original_filename="partial.png",
                visibility="private",
            )
            original = storage_service._await_io

            def flaky_await_io(fn, *args, **kwargs):
                if (
                    fn.__name__ == "delete_object"
                    and kwargs.get("Bucket") == priv
                    and kwargs.get("Key") == item.storage_key
                ):
                    raise ClientError(
                        {"Error": {"Code": "AccessDenied", "Message": "no delete"}},
                        "DeleteObject",
                    )
                return original(fn, *args, **kwargs)

            monkeypatch.setattr(storage_service, "_await_io", flaky_await_io)

            updated = media_service.update_media(item, visibility="public")
            assert updated.visibility == "public"
            assert updated.storage_bucket == pub
            assert s3_client.get_object(Bucket=pub, Key=item.storage_key)["Body"].read()
            # Source may remain because delete failed; operation should still be successful.
            assert s3_client.get_object(Bucket=priv, Key=item.storage_key)["Body"].read()

    def test_visibility_change_commit_failure_moves_object_back(
        self, app, db, auth_user, fresh_buckets, s3_client, monkeypatch
    ):
        pub, priv = fresh_buckets
        with app.app_context():
            item = media_service.upload_media(
                owner=auth_user,
                stream=_png_stream(),
                original_filename="rollback.png",
                visibility="private",
            )
            original_commit = db.session.commit
            calls = {"n": 0}

            def fail_first_commit():
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("commit failed")
                return original_commit()

            monkeypatch.setattr(db.session, "commit", fail_first_commit)
            with pytest.raises(RuntimeError):
                media_service.update_media(item, visibility="public")

            # Object should be moved back to original bucket by compensation logic.
            assert s3_client.get_object(Bucket=priv, Key=item.storage_key)["Body"].read()
            with pytest.raises(Exception):
                s3_client.get_object(Bucket=pub, Key=item.storage_key)
