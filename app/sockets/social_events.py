"""Socket.IO event handlers for social interactions — Member 4.

Events (Client → Server)
------------------------
comment_send      — Post a comment to a stream room
emote_send        — Send a live emote reaction in a stream room

Events (Server → Client, broadcast to room)
--------------------------------------------
comment_received  — New comment posted in the room
emote_received    — New emote fired in the room
"""

import logging

from flask import request as flask_request
from flask_socketio import emit

from app.extensions import socketio, db
from app.models.comment import Comment
from app.models.emote import Emote, VALID_EMOTE_TYPES
from app.models.user import User

logger = logging.getLogger(__name__)


def _get_user_from_sid() -> User | None:
    """Resolve the authenticated user for the current socket.

    Two paths:
    1. The handshake `auth` payload (preferred — works for all transports
       including browser websocket). Stashed per-sid at connect time.
    2. Legacy Authorization header (for clients that still send it; only
       reaches us on polling transport in browsers).
    """
    from app.sockets.session import get_user_for_sid
    user = get_user_for_sid(flask_request.sid)
    if user is not None:
        return user
    auth_header = flask_request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    api_key = auth_header[len("Bearer "):].strip()
    return User.query.filter_by(api_key=api_key).first() if api_key else None


@socketio.on("comment_send")
def handle_comment_send(data):
    """Client sends a comment to a stream room.

    Expected payload:
        {"stream_id": "<uuid>", "content": "<text up to 500 chars>"}

    Broadcasts ``comment_received`` to every client in the room (including sender).
    """
    if not isinstance(data, dict):
        emit("error", {"message": "Invalid payload"})
        return

    stream_id = data.get("stream_id")
    content = (data.get("content") or "").strip()

    if not stream_id:
        emit("error", {"message": "stream_id is required"})
        return
    if not content:
        emit("error", {"message": "content is required"})
        return
    if len(content) > 500:
        emit("error", {"message": "content must be 500 characters or fewer"})
        return

    user = _get_user_from_sid()
    if user is None:
        emit("error", {"message": "Authentication required"})
        return

    comment = Comment(stream_id=stream_id, user_id=user.id, content=content)
    db.session.add(comment)
    db.session.commit()

    logger.info("Comment %d posted in stream %s by user %s", comment.id, stream_id, user.id)
    payload = comment.to_dict()
    emit("comment_received", payload)                                   # sender always gets own message
    emit("comment_received", payload, to=stream_id, include_self=False) # broadcast to other viewers


@socketio.on("emote_send")
def handle_emote_send(data):
    """Client fires a live emote reaction in a stream room.

    Expected payload:
        {"stream_id": "<uuid>", "emote_type": "heart|fire|clap|laugh|wow|sad"}

    Broadcasts ``emote_received`` to every client in the room (including sender).
    """
    if not isinstance(data, dict):
        emit("error", {"message": "Invalid payload"})
        return

    stream_id = data.get("stream_id")
    emote_type = data.get("emote_type")

    if not stream_id:
        emit("error", {"message": "stream_id is required"})
        return
    if emote_type not in VALID_EMOTE_TYPES:
        emit("error", {"message": f"emote_type must be one of: {', '.join(sorted(VALID_EMOTE_TYPES))}"})
        return

    user = _get_user_from_sid()
    if user is None:
        emit("error", {"message": "Authentication required"})
        return

    emote = Emote(stream_id=stream_id, user_id=user.id, emote_type=emote_type)
    db.session.add(emote)
    db.session.commit()

    logger.info("Emote '%s' in stream %s by user %s", emote_type, stream_id, user.id)
    emit("emote_received", emote.to_dict(), to=stream_id)
