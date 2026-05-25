"""Socket.IO events the streamer dashboard fires at the broadcaster.

Events (Client → Server)
------------------------
recording_start         — { stream_id, name } — ask broadcaster to record a gesture
streamer_authenticated  — { stream_id, api_key } — propagate the streamer's
                          api_key to the broadcaster so it can refetch per-user
                          gesture overrides and custom templates without a
                          restart. Verified server-side before broadcasting.

Events (Server → Room, picked up by the broadcaster)
----------------------------------------------------
recording_start         — { stream_id, name } — re-broadcast to the stream room
recording_ack           — { stream_id, name } — confirmed to the dashboard
streamer_authenticated  — { stream_id, api_key, user_id, username } — pushed
                          into the stream's room. Broadcaster swaps identity.
streamer_auth_ack       — { stream_id, user_id, username } — pushed back to
                          the dashboard's sid (no api_key in this leg) so the
                          dashboard knows the broadcaster was informed.

The broadcaster joins its own stream room (see broadcaster/client.py) and
is the only consumer of these events it cares about. Viewers in the room
also receive recording_start (they ignore it). streamer_authenticated is
emitted only to the room — but it does carry the api_key, so any sniffing
viewer in the same room could read it. In v1 we accept this: the stream
room is per-stream and viewers are presumed trusted (no public auth on
join_room yet). When auth on join_room lands, this concern goes away;
until then, do not run the demo on a hostile LAN.
"""
import logging

from flask import request as flask_request
from flask_socketio import emit

from app.extensions import socketio
from app.models.user import User

logger = logging.getLogger(__name__)


@socketio.on("recording_start")
def handle_recording_start(data):
    if not isinstance(data, dict):
        emit("error", {"message": "Invalid payload"})
        return

    stream_id = data.get("stream_id")
    name = (data.get("name") or "").strip()

    if not stream_id:
        emit("error", {"message": "stream_id is required"})
        return
    if not name:
        emit("error", {"message": "name is required"})
        return
    if len(name) > 50:
        emit("error", {"message": "name must be 50 characters or fewer"})
        return

    sid = flask_request.sid
    logger.info("recording_start requested by %s for stream %s, name=%r", sid, stream_id, name)

    payload = {"stream_id": stream_id, "name": name}
    # Re-broadcast to the room — the broadcaster process is a member.
    emit("recording_start", payload, to=stream_id)
    # Confirm to the dashboard so it can update its UI.
    emit("recording_ack", payload)


@socketio.on("streamer_authenticated")
def handle_streamer_authenticated(data):
    """Dashboard signed in — push the api_key to the broadcaster.

    We verify the api_key here (it must resolve to a real user) before
    broadcasting, so a malformed/stolen string can't poison the broadcaster.
    """
    if not isinstance(data, dict):
        emit("error", {"message": "Invalid payload"})
        return

    stream_id = data.get("stream_id")
    api_key = (data.get("api_key") or "").strip()

    if not stream_id:
        emit("error", {"message": "stream_id is required"})
        return
    if not api_key:
        emit("error", {"message": "api_key is required"})
        return

    user = User.query.filter_by(api_key=api_key).first()
    if user is None:
        emit("error", {"message": "Invalid api_key"})
        return

    sid = flask_request.sid
    logger.info(
        "streamer_authenticated: sid=%s stream=%s user=%s(%s)",
        sid, stream_id, user.username, user.id,
    )

    # Also stash in the per-sid session table so subsequent events from
    # this dashboard tab (e.g. recording_start) carry user identity if
    # we ever want to gate them.
    from app.sockets.session import set_sid_api_key
    set_sid_api_key(sid, api_key)

    room_payload = {
        "stream_id": stream_id,
        "api_key": api_key,
        "user_id": user.id,
        "username": user.username,
    }
    emit("streamer_authenticated", room_payload, to=stream_id)

    # Dashboard ack without the api_key (dashboard already has it).
    emit("streamer_auth_ack", {
        "stream_id": stream_id,
        "user_id": user.id,
        "username": user.username,
    })
