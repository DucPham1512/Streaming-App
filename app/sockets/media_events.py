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


@socketio.on("gesture_command_received")
def handle_gesture_command(data):
    """Frontend detected a hand gesture and sends the command.

    Expected payload:
        {"command": "switch_camera", "confidence": 0.95, "stream_id": "<uuid>"}
    """
    sid = flask_request.sid

    if not isinstance(data, dict):
        emit("error", {"message": "Gesture command must be a JSON object"})
        return

    command = data.get("command")
    confidence = data.get("confidence", 0.0)
    stream_id = data.get("stream_id")

    if not command:
        emit("error", {"message": "'command' field is required"})
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

    # Broadcast the state change to all viewers in the room
    emit(
        "stream_state_update",
        {
            "command": command,
            "confidence": confidence,
            "stream_id": stream_id,
            "triggered_by": sid,
        },
        to=stream_id,
    )

    logger.info(
        "Gesture command '%s' (confidence=%.2f) from %s in stream %s",
        command, confidence, sid, stream_id,
    )
