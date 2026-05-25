"""Per-sid auth state for Socket.IO connections.

`extraHeaders` in socket.io-client is silently dropped by browsers on
websocket transport, so we read the api_key from the handshake `auth`
payload at connect time and stash it here keyed by sid. Later events
(comment_send, emote_send) look up the user via this map instead of
trying to re-parse request headers.

In-memory, single-process — fine for the demo. If we ever run multiple
flask processes we'd move this to redis.
"""
from threading import Lock
from typing import Optional

from app.models.user import User

_lock = Lock()
_sid_to_key: dict[str, str] = {}


def set_sid_api_key(sid: str, api_key: str) -> None:
    with _lock:
        _sid_to_key[sid] = api_key


def clear_sid(sid: str) -> None:
    with _lock:
        _sid_to_key.pop(sid, None)


def get_user_for_sid(sid: str) -> Optional[User]:
    with _lock:
        api_key = _sid_to_key.get(sid)
    if not api_key:
        return None
    return User.query.filter_by(api_key=api_key).first()
