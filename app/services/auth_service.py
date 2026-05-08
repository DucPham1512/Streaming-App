"""Authentication service — Foundation primitive.

Generic auth boundary used by any blueprint that opts in. Reads
``Authorization: Bearer <api_key>`` from the request and looks up the
matching ``User``. Stashes the user on ``flask.g`` so downstream code
can read it without hitting the DB twice.

Decorators:
    @require_auth                 — 401 if no/invalid token
    @require_owner(getter)        — 403 if g.current_user.id != obj.owner_id
                                    where obj = getter(**view_kwargs)

Note: this module is intentionally NOT media-specific. The ``@require_owner``
decorator takes a generic getter callable so it can guard any owned resource
(MediaItem now, Stream/Comment/etc later).
"""

from functools import wraps

from flask import g, request

from app.models.user import User
from app.services.exceptions import Forbidden, NotFound, Unauthorized


_BEARER_PREFIX = "Bearer "


def _extract_api_key() -> str | None:
    """Pull the API key out of the Authorization header, if present."""
    header = request.headers.get("Authorization", "")
    if not header.startswith(_BEARER_PREFIX):
        return None
    return header[len(_BEARER_PREFIX) :].strip() or None


def current_user() -> User:
    """Return the User identified by the Authorization header.

    Raises ``Unauthorized`` if the header is missing, malformed, or doesn't
    match a known user. The result is stashed on ``flask.g`` so views called
    after ``@require_auth`` can read ``g.current_user`` without a second
    DB hit, but the lookup itself ALWAYS re-validates the header — never
    trust a cached value to gate a fresh request (g is app-context scoped,
    which can outlive a single request in tests).
    """
    api_key = _extract_api_key()
    if api_key is None:
        raise Unauthorized("Missing or malformed Authorization header")

    user = User.query.filter_by(api_key=api_key).first()
    if user is None:
        raise Unauthorized("Invalid API key")

    g.current_user = user
    return user


def current_user_optional() -> User | None:
    """Return the current user if authenticated, else None.

    Used by endpoints whose visibility depends on auth state (e.g. listing
    a user's media: authed → may see private; unauthed → public only).
    """
    try:
        return current_user()
    except Unauthorized:
        return None


def require_auth(view):
    """Decorator: 401 if request is not authenticated."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        current_user()  # raises Unauthorized if not authed
        return view(*args, **kwargs)

    return wrapper


def require_owner(getter, *, owner_attr: str = "owner_id"):
    """Decorator factory: 403 unless the authed user owns the target object.

    Parameters
    ----------
    getter : callable
        Receives the view's kwargs and returns the owned object (or None
        to signal "not found"). Example::

            def _get_media(media_id):
                return media_service.get_media(media_id)

            @media_bp.route("/<media_id>", methods=["DELETE"])
            @require_auth
            @require_owner(_get_media)
            def delete_media(media_id):
                ...

    owner_attr : str
        Attribute on the fetched object that holds the owner's user id.
        Default ``"owner_id"`` matches MediaItem; future models may differ.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            obj = getter(**kwargs)
            if obj is None:
                raise NotFound("Resource not found")
            user = current_user()
            owner_id = getattr(obj, owner_attr, None)
            if owner_id != user.id:
                raise Forbidden("You do not own this resource")
            g.current_owned_object = obj
            return view(*args, **kwargs)

        return wrapper

    return decorator
