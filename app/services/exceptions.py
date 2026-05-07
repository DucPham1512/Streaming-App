"""Typed business exceptions for the service layer.

Routes catch these (or rely on the global error handler in app/__init__.py)
and map them to the canonical error taxonomy:
{"error": "<message>", "code": "<UPPER_SNAKE>"} with the right HTTP status.

Each exception carries a default ``code`` and ``status_code`` that Flask's
error handler reads. Routes never raise generic ``ValueError`` for business
errors — they raise one of these.
"""


class ServiceError(Exception):
    """Base class for service-layer business exceptions."""

    code: str = "INTERNAL_ERROR"
    status_code: int = 500

    def __init__(self, message: str = "", **extra):
        super().__init__(message or self.__doc__ or self.code)
        self.message = message or (self.__doc__ or self.code).strip()
        self.extra = extra

    def to_dict(self) -> dict:
        payload = {"error": self.message, "code": self.code}
        payload.update(self.extra)
        return payload


class Unauthorized(ServiceError):
    """Authentication required or token invalid."""

    code = "UNAUTHORIZED"
    status_code = 401


class Forbidden(ServiceError):
    """Authenticated but not allowed to access this resource."""

    code = "FORBIDDEN"
    status_code = 403


class NotFound(ServiceError):
    """Requested resource does not exist or is soft-deleted."""

    code = "NOT_FOUND"
    status_code = 404


class FileTooLarge(ServiceError):
    """File exceeds the configured maximum upload size."""

    code = "FILE_TOO_LARGE"
    status_code = 413


class QuotaExceeded(ServiceError):
    """User would exceed their per-user storage quota."""

    code = "QUOTA_EXCEEDED"
    status_code = 413


class UnsupportedMimetype(ServiceError):
    """File mimetype is not in the allowlist."""

    code = "UNSUPPORTED_MEDIA_TYPE"
    status_code = 415


class StorageUnavailable(ServiceError):
    """Object storage backend is unreachable or returned an error."""

    code = "STORAGE_UNAVAILABLE"
    status_code = 503


class InvalidField(ServiceError):
    """A submitted field is present but its value is rejected."""

    code = "INVALID_FIELD"
    status_code = 400


class InvalidRequest(ServiceError):
    """The request format or query parameters are invalid."""

    code = "INVALID_REQUEST"
    status_code = 400


class InvalidRange(ServiceError):
    """Requested byte range cannot be fulfilled for this resource."""

    code = "INVALID_RANGE"
    status_code = 416
