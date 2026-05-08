"""Unit tests for app.services.storage_service.

Backed by ``moto.mock_aws`` (configured in conftest). Covers upload,
streaming download, range requests, presigned URL, move, delete, and
the not-found path.
"""

import io

import pytest

from app.services.exceptions import InvalidRange, NotFound, StorageUnavailable
from app.services.storage_service import storage_service


class TestUploadAndDownload:
    def test_upload_and_get_object_stream(self, app, fresh_buckets):
        pub, _ = fresh_buckets
        with app.app_context():
            payload = b"hello world"
            storage_service.upload_fileobj(
                io.BytesIO(payload), pub, "test/object.txt", "text/plain"
            )
            it, meta = storage_service.get_object_stream(pub, "test/object.txt")
            data = b"".join(it)
            assert data == payload
            assert meta["content_length"] == len(payload)
            assert meta["status_code"] == 200

    def test_get_object_stream_with_range(self, app, fresh_buckets):
        pub, _ = fresh_buckets
        with app.app_context():
            payload = b"abcdefghijklmnop"
            storage_service.upload_fileobj(
                io.BytesIO(payload), pub, "ranged.bin", "application/octet-stream"
            )
            it, meta = storage_service.get_object_stream(
                pub, "ranged.bin", range_header="bytes=2-5"
            )
            data = b"".join(it)
            assert data == b"cdef"
            assert meta["status_code"] == 206
            assert meta["content_range"] is not None

    def test_get_object_stream_invalid_range_raises_invalid_range(self, app, fresh_buckets):
        pub, _ = fresh_buckets
        with app.app_context():
            payload = b"abc"
            storage_service.upload_fileobj(
                io.BytesIO(payload), pub, "small.bin", "application/octet-stream"
            )
            with pytest.raises(InvalidRange):
                storage_service.get_object_stream(
                    pub, "small.bin", range_header="bytes=99-100"
                )

    def test_get_object_stream_missing_raises_not_found(self, app, fresh_buckets):
        pub, _ = fresh_buckets
        with app.app_context():
            with pytest.raises(NotFound):
                it, _meta = storage_service.get_object_stream(pub, "does/not/exist")
                # Materialize the iterator (some clients only fail on read).
                list(it)


class TestPresignedUrl:
    def test_generates_url_with_bucket_and_key(self, app, fresh_buckets):
        pub, _ = fresh_buckets
        with app.app_context():
            url = storage_service.generate_presigned_url(pub, "any-key", expires_in=120)
            assert pub in url
            assert "any-key" in url
            assert "Signature=" in url or "X-Amz-Signature" in url


class TestMoveAndDelete:
    def test_move_object_between_buckets(self, app, fresh_buckets, s3_client):
        pub, priv = fresh_buckets
        with app.app_context():
            storage_service.upload_fileobj(io.BytesIO(b"x"), priv, "k", "text/plain")
            storage_service.move_object(priv, pub, "k")
            # Now in pub, gone from priv.
            assert s3_client.get_object(Bucket=pub, Key="k")["Body"].read() == b"x"
            with pytest.raises(Exception):
                s3_client.get_object(Bucket=priv, Key="k")

    def test_move_same_bucket_is_noop(self, app, fresh_buckets, s3_client):
        pub, _ = fresh_buckets
        with app.app_context():
            storage_service.upload_fileobj(io.BytesIO(b"y"), pub, "k2", "text/plain")
            storage_service.move_object(pub, pub, "k2")
            assert s3_client.get_object(Bucket=pub, Key="k2")["Body"].read() == b"y"

    def test_delete_object(self, app, fresh_buckets, s3_client):
        pub, _ = fresh_buckets
        with app.app_context():
            storage_service.upload_fileobj(io.BytesIO(b"z"), pub, "del-me", "text/plain")
            storage_service.delete_object(pub, "del-me")
            with pytest.raises(Exception):
                s3_client.get_object(Bucket=pub, Key="del-me")


class TestEventletWrapperContract:
    def test_network_calls_route_through_await_io(
        self, app, fresh_buckets, monkeypatch, s3_client
    ):
        pub, priv = fresh_buckets
        calls = []

        with app.app_context():
            original = storage_service._await_io

            def spy_await_io(fn, *args, **kwargs):
                calls.append(fn.__name__)
                return original(fn, *args, **kwargs)

            monkeypatch.setattr(storage_service, "_await_io", spy_await_io)

            storage_service.upload_fileobj(io.BytesIO(b"u"), pub, "up.bin", "text/plain")
            storage_service.get_object_stream(pub, "up.bin")
            storage_service.delete_object(pub, "up.bin")

            storage_service.upload_fileobj(io.BytesIO(b"m"), priv, "mv.bin", "text/plain")
            storage_service.move_object(priv, pub, "mv.bin")

            assert "upload_fileobj" in calls
            assert "get_object" in calls
            assert "copy_object" in calls
            assert calls.count("delete_object") >= 2
            assert s3_client.get_object(Bucket=pub, Key="mv.bin")["Body"].read() == b"m"
