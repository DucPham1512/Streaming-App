"""WebSocket connection event handlers.

Events: connect, disconnect, join_room, leave_room
"""

import logging
from flask import request as flask_request
from flask_socketio import emit, join_room, leave_room

from app.extensions import socketio, db
from app.services.stream_manager import stream_manager

logger = logging.getLogger(__name__)


@socketio.on("connect")
def handle_connect():
    """Client connected to the WebSocket server."""
    sid = flask_request.sid
    logger.info("Client connected: %s", sid)
    emit("connection_ack", {"status": "connected", "sid": sid})


@socketio.on("disconnect")
def handle_disconnect():
    """Client disconnected — clean up from any rooms."""
    sid = flask_request.sid
    logger.info("Client disconnected: %s", sid)

    # Remove client from all active streams they were in
    for stream_id in stream_manager.get_active_stream_ids():
        stream_manager.remove_client(stream_id, sid)


@socketio.on("join_room")
def handle_join_room(data):
    """Client requests to join a specific stream room.

    Expected payload:
        {"stream_id": "<uuid>"}
    """
    sid = flask_request.sid
    stream_id = data.get("stream_id") if isinstance(data, dict) else None

    if not stream_id:
        emit("error", {"message": "stream_id is required"})
        return

    # Allow joining any stream that exists in the DB; active-only enforcement
    # would block dev/demo streams that haven't received a Mux webhook yet.
    if not stream_manager.is_active(stream_id):
        from app.models.stream import Stream
        if not db.session.get(Stream, stream_id):
            emit("error", {"message": f"Stream {stream_id} not found"})
            return

    join_room(stream_id)
    stream_manager.add_client(stream_id, sid)

    logger.info("Client %s joined room %s", sid, stream_id)
    emit("room_joined", {"stream_id": stream_id, "sid": sid})
    emit("viewer_joined", {"sid": sid}, to=stream_id, include_self=False)


@socketio.on("leave_room")
def handle_leave_room(data):
    """Client requests to leave a stream room.

    Expected payload:
        {"stream_id": "<uuid>"}
    """
    sid = flask_request.sid
    stream_id = data.get("stream_id") if isinstance(data, dict) else None

    if not stream_id:
        emit("error", {"message": "stream_id is required"})
        return

    leave_room(stream_id)
    stream_manager.remove_client(stream_id, sid)

    logger.info("Client %s left room %s", sid, stream_id)
    emit("room_left", {"stream_id": stream_id, "sid": sid})
    emit("viewer_left", {"sid": sid}, to=stream_id, include_self=False)
