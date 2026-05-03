"""WebSocket event tests."""

import json


class TestConnectionEvents:
    """Tests for connect/disconnect/join_room socket events."""

    def test_connect(self, socketio_test_client):
        """Client receives connection_ack on connect."""
        assert socketio_test_client.is_connected()
        received = socketio_test_client.get_received()
        events = [r["name"] for r in received]
        assert "connection_ack" in events

    def test_join_room_requires_stream_id(self, socketio_test_client):
        """join_room without stream_id emits an error."""
        socketio_test_client.get_received()  # clear buffer
        socketio_test_client.emit("join_room", {})
        received = socketio_test_client.get_received()
        errors = [r for r in received if r["name"] == "error"]
        assert len(errors) > 0

    def test_join_room_inactive_stream(self, socketio_test_client):
        """join_room with a non-active stream_id emits an error."""
        socketio_test_client.get_received()  # clear buffer
        socketio_test_client.emit("join_room", {"stream_id": "fake-id"})
        received = socketio_test_client.get_received()
        errors = [r for r in received if r["name"] == "error"]
        assert len(errors) > 0

    def test_join_room_active_stream(self, client, socketio_test_client):
        """join_room with an active stream succeeds."""
        # Create a stream via REST
        create_resp = client.post(
            "/api/v1/streams", content_type="application/json"
        )
        stream_id = create_resp.get_json()["stream"]["id"]

        socketio_test_client.get_received()  # clear buffer
        socketio_test_client.emit("join_room", {"stream_id": stream_id})
        received = socketio_test_client.get_received()
        events = [r["name"] for r in received]
        assert "room_joined" in events


class TestMediaEvents:
    """Tests for audio chunk and gesture command socket events."""

    def test_gesture_command_requires_command(self, socketio_test_client):
        """gesture_command_received without 'command' emits error."""
        socketio_test_client.get_received()  # clear buffer
        socketio_test_client.emit("gesture_command_received", {"stream_id": "x"})
        received = socketio_test_client.get_received()
        errors = [r for r in received if r["name"] == "error"]
        assert len(errors) > 0

    def test_gesture_command_inactive_stream(self, socketio_test_client):
        """gesture_command_received with inactive stream emits error."""
        socketio_test_client.get_received()
        socketio_test_client.emit(
            "gesture_command_received",
            {"command": "mute_mic", "stream_id": "fake"},
        )
        received = socketio_test_client.get_received()
        errors = [r for r in received if r["name"] == "error"]
        assert len(errors) > 0

    def test_gesture_command_success(self, client, socketio_test_client):
        """gesture_command_received with valid stream broadcasts update."""
        create_resp = client.post(
            "/api/v1/streams", content_type="application/json"
        )
        stream_id = create_resp.get_json()["stream"]["id"]

        socketio_test_client.get_received()
        socketio_test_client.emit("join_room", {"stream_id": stream_id})
        socketio_test_client.get_received()  # clear join events

        socketio_test_client.emit(
            "gesture_command_received",
            {
                "command": "switch_camera",
                "confidence": 0.95,
                "stream_id": stream_id,
            },
        )
        received = socketio_test_client.get_received()
        events = [r["name"] for r in received]
        assert "gesture_ack" in events

    def test_audio_chunk_inactive_stream(self, socketio_test_client):
        """stream_audio_chunk with no active stream emits error."""
        socketio_test_client.get_received()
        socketio_test_client.emit(
            "stream_audio_chunk",
            {"stream_id": "fake", "audio": ""},
        )
        received = socketio_test_client.get_received()
        errors = [r for r in received if r["name"] == "error"]
        assert len(errors) > 0

    def test_audio_chunk_success(self, client, socketio_test_client):
        """stream_audio_chunk with valid stream processes and emits subtitle."""
        create_resp = client.post(
            "/api/v1/streams", content_type="application/json"
        )
        stream_id = create_resp.get_json()["stream"]["id"]

        socketio_test_client.get_received()
        socketio_test_client.emit("join_room", {"stream_id": stream_id})
        socketio_test_client.get_received()  # clear join events

        import base64
        audio_b64 = base64.b64encode(b"fake audio data").decode()
        socketio_test_client.emit(
            "stream_audio_chunk",
            {"stream_id": stream_id, "audio": audio_b64},
        )
        received = socketio_test_client.get_received()
        events = [r["name"] for r in received]
        assert "broadcast_subtitle" in events
