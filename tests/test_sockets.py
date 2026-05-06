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
    """Tests for audio chunk and gesture frame socket events."""

    def _create_stream(self, client):
        resp = client.post("/api/v1/streams", content_type="application/json")
        return resp.get_json()["stream"]["id"]

    def _join_stream(self, socketio_test_client, stream_id):
        socketio_test_client.emit("join_room", {"stream_id": stream_id})
        socketio_test_client.get_received()  # clear join events

    # --- gesture_frame: validation ---

    def test_gesture_frame_requires_gesture(self, client, socketio_test_client):
        """gesture_frame without 'gesture' emits error."""
        stream_id = self._create_stream(client)
        socketio_test_client.get_received()
        self._join_stream(socketio_test_client, stream_id)

        socketio_test_client.emit("gesture_frame", {"stream_id": stream_id})
        received = socketio_test_client.get_received()
        errors = [r for r in received if r["name"] == "error"]
        assert len(errors) > 0

    def test_gesture_frame_inactive_stream(self, socketio_test_client):
        """gesture_frame with inactive stream emits error."""
        socketio_test_client.get_received()
        socketio_test_client.emit(
            "gesture_frame",
            {"gesture": "thumbs_up", "stream_id": "fake"},
        )
        received = socketio_test_client.get_received()
        errors = [r for r in received if r["name"] == "error"]
        assert len(errors) > 0

    def test_gesture_frame_invalid_payload_type(self, socketio_test_client):
        """gesture_frame with non-dict payload emits error."""
        socketio_test_client.get_received()
        socketio_test_client.emit("gesture_frame", "not-a-dict")
        received = socketio_test_client.get_received()
        errors = [r for r in received if r["name"] == "error"]
        assert len(errors) > 0

    # --- gesture_frame: control action ---

    def test_gesture_frame_mapped_control_action(self, client, socketio_test_client):
        """Known control gesture resolves to action and emits stream_action to room."""
        stream_id = self._create_stream(client)
        # seed gesture mappings
        client.get("/api/v1/settings/gestures")

        socketio_test_client.get_received()
        self._join_stream(socketio_test_client, stream_id)

        socketio_test_client.emit(
            "gesture_frame",
            {"gesture": "thumbs_up", "confidence": 0.9, "stream_id": stream_id},
        )
        received = socketio_test_client.get_received()
        event_names = [r["name"] for r in received]

        assert "gesture_ack" in event_names
        ack = next(r for r in received if r["name"] == "gesture_ack")
        assert ack["args"][0]["gesture"] == "thumbs_up"
        assert ack["args"][0]["action"] == "switch_camera"
        assert ack["args"][0]["status"] == "mapped"

        assert "stream_action" in event_names
        action_event = next(r for r in received if r["name"] == "stream_action")
        assert action_event["args"][0]["action"] == "switch_camera"
        assert action_event["args"][0]["gesture"] == "thumbs_up"

    # --- gesture_frame: entertainment effect ---

    def test_gesture_frame_mapped_effect(self, client, socketio_test_client):
        """Effect gesture resolves to effect:heart and emits stream_effect to room."""
        stream_id = self._create_stream(client)
        client.get("/api/v1/settings/gestures")  # seed defaults

        socketio_test_client.get_received()
        self._join_stream(socketio_test_client, stream_id)

        socketio_test_client.emit(
            "gesture_frame",
            {
                "gesture": "heart_gesture",
                "confidence": 0.88,
                "stream_id": stream_id,
                "hand_position": {"x": 0.4, "y": 0.6},
            },
        )
        received = socketio_test_client.get_received()
        event_names = [r["name"] for r in received]

        assert "gesture_ack" in event_names
        ack = next(r for r in received if r["name"] == "gesture_ack")
        assert ack["args"][0]["action"] == "effect:heart"
        assert ack["args"][0]["status"] == "mapped"

        assert "stream_effect" in event_names
        effect_event = next(r for r in received if r["name"] == "stream_effect")
        assert effect_event["args"][0]["effect"] == "heart"
        assert effect_event["args"][0]["hand_position"] == {"x": 0.4, "y": 0.6}

    # --- gesture_frame: unmapped gesture ---

    def test_gesture_frame_unmapped_gesture(self, client, socketio_test_client):
        """Unknown gesture returns status=unmapped and no room broadcast."""
        stream_id = self._create_stream(client)
        client.get("/api/v1/settings/gestures")  # seed defaults

        socketio_test_client.get_received()
        self._join_stream(socketio_test_client, stream_id)

        socketio_test_client.emit(
            "gesture_frame",
            {"gesture": "unknown_wave", "confidence": 0.5, "stream_id": stream_id},
        )
        received = socketio_test_client.get_received()
        event_names = [r["name"] for r in received]

        assert "gesture_ack" in event_names
        ack = next(r for r in received if r["name"] == "gesture_ack")
        assert ack["args"][0]["status"] == "unmapped"
        assert ack["args"][0]["action"] is None

        assert "stream_action" not in event_names
        assert "stream_effect" not in event_names

    # --- audio chunk ---

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
