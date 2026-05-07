"""Object storage service — Foundation primitive.

Generic S3-compatible blob layer. Knows about buckets and keys; knows
nothing about MediaItem, mimetypes allowlists, or visibility semantics.
That logic lives one layer up in ``media_service``.

Eventlet rule (D2): all network-bound boto3 calls (`upload_fileobj`,
`get_object`, `delete_object`, `copy_object`) are wrapped in
``socketio.start_background_task`` via ``_await_io`` so they don't
starve the event loop. ``generate_presigned_url`` is local-CPU only
and runs inline.

Tests use ``moto.mock_aws`` (see tests/conftest.py); the wrapper falls
back to direct call when ``socketio`` isn't configured for eventlet.
"""

import logging
from typing import BinaryIO, Iterator, Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from flask import current_app

from app.extensions import socketio
from app.services.exceptions import InvalidRange, StorageUnavailable

logger = logging.getLogger(__name__)


_DEFAULT_CHUNK_SIZE = 64 * 1024  # 64 KiB — used by the download proxy iterator


class StorageService:
    """Wraps a boto3 S3 client configured for the app's MinIO endpoint."""

    def __init__(self, app=None):
        self._client = None
        self._config = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app) -> None:
        """Wire the service to a Flask app's config. Called from create_app.

        In TESTING mode the custom MinIO endpoint is skipped so moto's
        boto3 interception (which targets default AWS endpoints) works.
        """
        cfg = app.config
        self._config = cfg

        client_kwargs = {
            "aws_access_key_id": cfg["MINIO_ACCESS_KEY"],
            "aws_secret_access_key": cfg["MINIO_SECRET_KEY"],
            "region_name": cfg["MINIO_REGION"],
            "config": BotoConfig(
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=30,
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
        }
        if not cfg.get("TESTING"):
            scheme = "https" if cfg.get("MINIO_SECURE", False) else "http"
            client_kwargs["endpoint_url"] = f"{scheme}://{cfg['MINIO_ENDPOINT']}"

        self._client = boto3.client("s3", **client_kwargs)

    @property
    def client(self):
        if self._client is None:
            # Lazy init from current_app — convenient for tests.
            self.init_app(current_app)
        return self._client

    def _await_io(self, fn, *args, **kwargs):
        """Run network I/O in a SocketIO background task for eventlet mode."""
        if getattr(socketio, "async_mode", None) != "eventlet":
            return fn(*args, **kwargs)

        try:
            import eventlet
        except Exception:
            return fn(*args, **kwargs)

        done = eventlet.event.Event()
        box = {}

        def runner():
            try:
                box["result"] = fn(*args, **kwargs)
            except Exception as exc:  # pragma: no cover - exercised via callers
                box["error"] = exc
            finally:
                done.send(True)

        socketio.start_background_task(runner)
        done.wait()
        if "error" in box:
            raise box["error"]
        return box.get("result")

    # --- Bucket operations -------------------------------------------------

    def init_buckets(self, public_bucket: str, private_bucket: str, cors_origins=None) -> None:
        """Create both buckets if they don't exist; configure CORS on each."""
        for bucket in (public_bucket, private_bucket):
            try:
                self.client.head_bucket(Bucket=bucket)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in ("404", "NoSuchBucket", "NotFound"):
                    self.client.create_bucket(Bucket=bucket)
                    logger.info("created bucket %s", bucket)
                else:
                    raise

        # CORS for public bucket so browsers can <img>/<video> directly.
        origins = cors_origins or ["*"]
        cors_config = {
            "CORSRules": [
                {
                    "AllowedOrigins": origins if isinstance(origins, list) else [origins],
                    "AllowedMethods": ["GET", "HEAD"],
                    "AllowedHeaders": ["*"],
                    "MaxAgeSeconds": 3600,
                }
            ]
        }
        for bucket in (public_bucket, private_bucket):
            try:
                self.client.put_bucket_cors(Bucket=bucket, CORSConfiguration=cors_config)
            except ClientError as exc:
                logger.warning("could not set CORS on %s: %s", bucket, exc)

    # --- Object operations -------------------------------------------------

    def upload_fileobj(
        self,
        fileobj: BinaryIO,
        bucket: str,
        key: str,
        content_type: str,
        extra_args: Optional[dict] = None,
    ) -> None:
        """Stream ``fileobj`` to ``bucket/key`` with the given content-type.

        Uses boto3's ``upload_fileobj`` which is multipart-aware; very large
        files transfer in chunks without buffering the whole body in memory.
        """
        args = {"ContentType": content_type}
        if extra_args:
            args.update(extra_args)
        try:
            self._await_io(
                self.client.upload_fileobj,
                fileobj,
                bucket,
                key,
                ExtraArgs=args,
            )
        except (BotoCoreError, ClientError) as exc:
            logger.error("S3 upload failed: %s/%s — %s", bucket, key, exc)
            raise StorageUnavailable(str(exc)) from exc

    def get_object_stream(
        self,
        bucket: str,
        key: str,
        range_header: Optional[str] = None,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
    ) -> tuple[Iterator[bytes], dict]:
        """Get an object's body as a chunked iterator + response metadata.

        Returns ``(iterator, meta)`` where ``meta`` includes
        ``content_length``, ``content_type``, and (if Range was honored)
        ``content_range`` and ``status_code = 206``.
        """
        kwargs = {"Bucket": bucket, "Key": key}
        if range_header:
            kwargs["Range"] = range_header
        try:
            resp = self._await_io(self.client.get_object, **kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404"):
                from app.services.exceptions import NotFound

                raise NotFound("Object not found in storage") from exc
            if code in ("InvalidRange", "InvalidArgument", "416"):
                raise InvalidRange(
                    "Requested byte range is not satisfiable",
                    range=range_header,
                ) from exc
            logger.error("S3 get_object failed: %s/%s — %s", bucket, key, exc)
            raise StorageUnavailable(str(exc)) from exc

        body = resp["Body"]
        meta = {
            "content_length": resp.get("ContentLength"),
            "content_type": resp.get("ContentType"),
            "content_range": resp.get("ContentRange"),
            "status_code": 206 if range_header and resp.get("ContentRange") else 200,
        }

        def _iter():
            try:
                for chunk in body.iter_chunks(chunk_size=chunk_size):
                    yield chunk
            finally:
                body.close()

        return _iter(), meta

    def delete_object(self, bucket: str, key: str) -> None:
        """Delete a single object. Idempotent — missing key is not an error."""
        try:
            self._await_io(self.client.delete_object, Bucket=bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            logger.warning("S3 delete failed: %s/%s — %s", bucket, key, exc)
            raise StorageUnavailable(str(exc)) from exc

    def move_object(self, src_bucket: str, dst_bucket: str, key: str) -> None:
        """Copy an object to a different bucket then delete the original.

        If copy succeeds but source delete fails, keep the operation successful
        and log the partial cleanup state for later reconciliation.
        """
        if src_bucket == dst_bucket:
            return
        try:
            self._await_io(
                self.client.copy_object,
                Bucket=dst_bucket,
                Key=key,
                CopySource={"Bucket": src_bucket, "Key": key},
            )
        except (BotoCoreError, ClientError) as exc:
            logger.error(
                "S3 move failed: %s -> %s key=%s — %s", src_bucket, dst_bucket, key, exc
            )
            raise StorageUnavailable(str(exc)) from exc

        try:
            self._await_io(self.client.delete_object, Bucket=src_bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            logger.warning(
                "S3 move partial completion: copied to %s but delete in %s failed for %s — %s",
                dst_bucket,
                src_bucket,
                key,
                exc,
            )

    def generate_presigned_url(
        self, bucket: str, key: str, expires_in: int = 300
    ) -> str:
        """Generate a presigned GET URL. Local-CPU only; no eventlet wrap."""
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except ClientError as exc:
            raise StorageUnavailable(str(exc)) from exc


storage_service = StorageService()
