"""WebSocket media event handlers.

Events: stream_audio_chunk, gesture_frame
"""

import logging
from datetime import datetime, timezone

from flask import request as flask_request
from flask_socketio import emit

from app.extensions import db, socketio
from app.models.gesture_log import GestureLog
from app.services.gesture_service import get_effect_name, is_effect, resolve_gesture
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


@socketio.on("gesture_frame")
def handle_gesture_frame(data):
    """Receive a recognized gesture from the broadcaster, resolve it to an action, and broadcast.

    Expected payload:
        {
            "gesture": "heart_gesture",
            "confidence": 0.95,
            "stream_id": "<uuid>",
            "user_id": "default",           // optional
            "hand_position": {"x": 0.42, "y": 0.61}  // optional, for effect rendering
        }

    Emits to sender:
        gesture_ack: {"gesture", "action", "status": "mapped"|"unmapped"}

    Emits to room (mapped control gesture):
        stream_action: {"action", "gesture", "stream_id", "triggered_by"}

    Emits to room (mapped effect gesture):
        stream_effect: {"effect", "hand_position", "stream_id", "triggered_by"}
    """
    sid = flask_request.sid

    if not isinstance(data, dict):
        emit("error", {"message": "Gesture payload must be a JSON object"})
        return

    gesture = data.get("gesture")
    confidence = data.get("confidence")
    stream_id = data.get("stream_id")
    user_id = data.get("user_id", "default")
    hand_position = data.get("hand_position")

    if not gesture:
        emit("error", {"message": "'gesture' field is required"})
        return

    if not stream_id or not stream_manager.is_active(stream_id):
        emit("error", {"message": "No active stream for gesture"})
        return

    action = resolve_gesture(gesture, user_id)

    db.session.add(GestureLog(
        stream_id=stream_id,
        user_id=user_id,
        gesture=gesture,
        action=action,
        confidence=confidence,
        timestamp=datetime.now(timezone.utc),
    ))
    db.session.commit()

    status = "mapped" if action else "unmapped"
    emit("gesture_ack", {"gesture": gesture, "action": action, "status": status})

    if not action:
        logger.info("Unmapped gesture '%s' from %s in stream %s", gesture, sid, stream_id)
        return

    if is_effect(action):
        emit(
            "stream_effect",
            {
                "effect": get_effect_name(action),
                "hand_position": hand_position,
                "stream_id": stream_id,
                "triggered_by": sid,
            },
            to=stream_id,
        )
        logger.info("Effect '%s' triggered by gesture '%s' from %s in stream %s",
                    get_effect_name(action), gesture, sid, stream_id)
    else:
        emit(
            "stream_action",
            {
                "action": action,
                "gesture": gesture,
                "stream_id": stream_id,
                "triggered_by": sid,
            },
            to=stream_id,
        )
        logger.info("Action '%s' triggered by gesture '%s' from %s in stream %s",
                    action, gesture, sid, stream_id)
