"""Application configuration classes."""
import os
from dotenv import load_dotenv

# Load .env into os.environ — must run before any os.environ reads below.
# In production, env vars are typically set by the deployment platform,
# and load_dotenv() is a no-op if no .env file exists.
load_dotenv()

from platformdirs import user_data_dir


def _default_db_uri() -> str:
    data_dir = user_data_dir("streaming_app", ensure_exists=True)
    return f"sqlite:///{os.path.join(data_dir, 'streaming_app.db')}"


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")

    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_DEFAULT = os.environ.get("RATELIMIT_DEFAULT", "1000 per hour")
    RATELIMIT_STRATEGY = "fixed-window"
    RATELIMIT_HEADERS_ENABLED = True
    # LiveKit credentials — see docs/decisions/001-livekit-over-mux.md.
    LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY")
    LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET")
    LIVEKIT_URL = os.environ.get("LIVEKIT_URL")

    # --- MinIO / S3-compatible object storage ---
    MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
    MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
    MINIO_REGION = os.environ.get("MINIO_REGION", "us-east-1")
    MINIO_SECURE = os.environ.get("MINIO_SECURE", "false").lower() == "true"

    # --- Media (Content Library) ---
    MEDIA_PUBLIC_BUCKET = os.environ.get(
        "MEDIA_PUBLIC_BUCKET", "streaming-app-media-public"
    )
    MEDIA_PRIVATE_BUCKET = os.environ.get(
        "MEDIA_PRIVATE_BUCKET", "streaming-app-media-private"
    )
    MEDIA_MAX_SIZE_MB = int(os.environ.get("MEDIA_MAX_SIZE_MB", "100"))
    MEDIA_ALLOWED_MIMETYPES = os.environ.get(
        "MEDIA_ALLOWED_MIMETYPES",
        "image/jpeg,image/png,image/gif,image/webp,"
        "video/mp4,video/webm,video/ogg,"
        "audio/mpeg,audio/ogg,audio/wav",
    ).split(",")
    MEDIA_QUOTA_MB_PER_USER = int(os.environ.get("MEDIA_QUOTA_MB_PER_USER", "1024"))
    MEDIA_PRESIGNED_TTL_SECONDS = int(
        os.environ.get("MEDIA_PRESIGNED_TTL_SECONDS", "300")
    )
    MEDIA_EXTRACT_METADATA = (
        os.environ.get("MEDIA_EXTRACT_METADATA", "false").lower() == "true"
    )

    # Set on the Flask app from MEDIA_MAX_SIZE_MB; declared here for clarity.
    MAX_CONTENT_LENGTH = int(os.environ.get("MEDIA_MAX_SIZE_MB", "100")) * 1024 * 1024


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or _default_db_uri()


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    RATELIMIT_ENABLED = False


class ProductionConfig(Config):
    """Production configuration.

    Enforces production safety guards: any default/insecure setting raises
    RuntimeError at instantiation time so misconfigured deploys fail loudly.
    """

    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")

    def __init__(self):
        if self.SECRET_KEY == "dev-secret-key-change-in-production":
            raise RuntimeError(
                "SECRET_KEY must be set to a non-default value in production"
            )
        if not self.SQLALCHEMY_DATABASE_URI:
            raise RuntimeError("DATABASE_URL must be set in production")
        if self.SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
            raise RuntimeError(
                "Production must use a non-SQLite DATABASE_URL "
                "(SQLite + eventlet has database-locked failure mode)"
            )
        if not self.MINIO_SECURE:
            raise RuntimeError(
                "MINIO_SECURE must be true in production "
                "(plaintext credentials over the wire is unacceptable)"
            )


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}