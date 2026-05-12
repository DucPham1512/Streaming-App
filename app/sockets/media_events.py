"""WebSocket media event handlers.

Events: stream_audio_chunk, gesture_command_received
"""

import logging
from flask import request as flask_request
from flask_socketio import emit

from app.extensions import socketio
from app.services.stt_engine import stt_engine
from app.services.stream_manager import stream_manager

logger = logging.getLogger(__name__)


@socketio.on("stream_audio_chunk")
def handle_audio_chunk(data):
    """Receive an audio chunk from a client, run STT, and broadcast subtitle.

    Expected payload (dict or raw bytes):
        If dict: {"stream_id": "<uuid>", "audio": <base64 or bytes>}
        If bytes: raw audio blob (stream_id must be inferred from room)
    """
    sid = flask_request.sid

    if isinstance(data, dict):
        stream_id = data.get("stream_id")
        audio_data = data.get("audio", b"")
        if isinstance(audio_data, str):
            import base64
            try:
                audio_data = base64.b64decode(audio_data)
            except Exception:
                emit("error", {"message": "Invalid base64 audio data"})
                return
    elif isinstance(data, bytes):
        audio_data = data
        # Try to find which room this client is in
        active_ids = stream_manager.get_active_stream_ids()
        stream_id = active_ids[0] if active_ids else None
    else:
        emit("error", {"message": "Invalid audio chunk format"})
        return

    if not stream_id or not stream_manager.is_active(stream_id):
        emit("error", {"message": "No active stream for audio processing"})
        return

    # Process audio through STT engine
    text = stt_engine.transcribe(audio_data)

    if text:
        from datetime import datetime, timezone
        subtitle_payload = {
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stream_id": stream_id,
        }

        # Broadcast subtitle to all clients in the room
        emit("broadcast_subtitle", subtitle_payload, to=stream_id)
        logger.info("Subtitle broadcast to room %s: %s", stream_id, text[:80])


# Maps a gesture command to the visual effect name sent to viewers.
_COMMAND_EFFECTS: dict[str, str] = {
    "mute_toggle":             "mute",
    "end_stream":              "end_stream",
    "like_stream":             "like",
    "entertainment_confetti":  "confetti",
    "entertainment_heart":     "heart_burst",
    "entertainment_fireworks": "fireworks",
}

_VALID_COMMANDS = frozenset(_COMMAND_EFFECTS.keys())

# Approximate Mux HLS playback delay. Effects are buffered server-side for
# this many seconds so viewers see the visual effect at the same moment
# their video shows the streamer performing the gesture.
# end_stream and mute_toggle are control commands — they fire immediately
# (we'd rather end the stream early than have it linger after the streamer
# already walked away).
EFFECT_BROADCAST_DELAY_SECONDS = 22
_INSTANT_COMMANDS = frozenset({"end_stream", "mute_toggle"})


@socketio.on("gesture_command_received")
def handle_gesture_command(data):
    """Gesture detection client sends a recognized hand gesture command.

    Expected payload:
        {"command": "entertainment_heart", "confidence": 0.95, "stream_id": "<uuid>"}

    Broadcasts stream_state_update to all viewers in the stream room with
    an `effect` field so the React Native app knows which animation to play.
    """
    sid = flask_request.sid
    logger.info("gesture_command_received raw payload from %s: %r", sid, data)

    if not isinstance(data, dict):
        emit("error", {"message": "Gesture command must be a JSON object"})
        return

    command = data.get("command")
    confidence = data.get("confidence", 0.0)
    stream_id = data.get("stream_id")

    if not command:
        emit("error", {"message": "'command' field is required"})
        return

    if command not in _VALID_COMMANDS:
        emit("error", {"message": f"Unknown command '{command}'"})
        return

    if not stream_id or not stream_manager.is_active(stream_id):
        emit("error", {"message": "No active stream for gesture command"})
        return

    # Acknowledge to sender
    emit("gesture_ack", {
        "command": command,
        "confidence": confidence,
        "status": "received",
    })

    payload = {
        "command": command,
        "effect": _COMMAND_EFFECTS[command],
        "confidence": confidence,
        "stream_id": stream_id,
        "triggered_by": sid,
    }

    if command in _INSTANT_COMMANDS:
        emit("stream_state_update", payload, to=stream_id)
    else:
        # Buffer entertainment effects so they line up with the delayed HLS video
        def _delayed_broadcast():
            socketio.sleep(EFFECT_BROADCAST_DELAY_SECONDS)
            socketio.emit("stream_state_update", payload, to=stream_id)

        socketio.start_background_task(_delayed_broadcast)

    # Debug: how many sockets are currently in this room?
    room_members = socketio.server.manager.rooms.get("/", {}).get(stream_id, {})
    member_count = len(room_members) if room_members else 0
    logger.info(
        "Gesture '%s' from %s -> broadcast to room %s (%d members): %s",
        command, sid, stream_id, member_count, list(room_members) if room_members else [],
    )
