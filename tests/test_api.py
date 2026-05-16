"""REST API endpoint tests."""

import json


class TestStreamRoutes:
    """Tests for /api/v1/streams endpoints."""

    def test_create_stream_default(self, client):
        """POST /api/v1/streams with no body creates a stream with defaults."""
        resp = client.post("/api/v1/streams", content_type="application/json")
        assert resp.status_code == 201
        data = resp.get_json()
        assert "stream" in data
        assert data["stream"]["title"] == "Untitled Stream"
        # Newly created streams start idle; webhook 'track_published' flips
        # them to active. See app/api/webhook_routes.py (Commit 4).
        assert data["stream"]["status"] == "idle"
        # Publisher JWT for the broadcaster to publish to the LiveKit room.
        assert "publisher_token" in data
        assert "livekit_url" in data

    def test_create_stream_with_metadata(self, client):
        """POST /api/v1/streams with custom metadata."""
        resp = client.post(
            "/api/v1/streams",
            data=json.dumps({
                "title": "My Stream",
                "description": "Test desc",
                "privacy": "private",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201
        stream = resp.get_json()["stream"]
        assert stream["title"] == "My Stream"
        assert stream["description"] == "Test desc"
        assert stream["privacy"] == "private"

    def test_create_stream_invalid_privacy(self, client):
        """POST /api/v1/streams with invalid privacy returns 400."""
        resp = client.post(
            "/api/v1/streams",
            data=json.dumps({"privacy": "invalid"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_get_stream(self, client):
        """GET /api/v1/streams/<id> returns the stream."""
        create_resp = client.post("/api/v1/streams", content_type="application/json")
        stream_id = create_resp.get_json()["stream"]["id"]

        resp = client.get(f"/api/v1/streams/{stream_id}")
        assert resp.status_code == 200
        assert resp.get_json()["stream"]["id"] == stream_id

    def test_get_stream_not_found(self, client):
        """GET /api/v1/streams/<bad_id> returns 404."""
        resp = client.get("/api/v1/streams/nonexistent")
        assert resp.status_code == 404

    def test_update_stream(self, client):
        """PATCH /api/v1/streams/<id> updates metadata."""
        create_resp = client.post("/api/v1/streams", content_type="application/json")
        stream_id = create_resp.get_json()["stream"]["id"]

        resp = client.patch(
            f"/api/v1/streams/{stream_id}",
            data=json.dumps({"title": "Updated Title"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["stream"]["title"] == "Updated Title"

    def test_update_stream_no_fields(self, client):
        """PATCH with empty body returns 400."""
        create_resp = client.post("/api/v1/streams", content_type="application/json")
        stream_id = create_resp.get_json()["stream"]["id"]

        resp = client.patch(
            f"/api/v1/streams/{stream_id}",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_end_stream(self, client):
        """POST /api/v1/streams/<id>/end terminates the stream."""
        create_resp = client.post("/api/v1/streams", content_type="application/json")
        stream_id = create_resp.get_json()["stream"]["id"]

        resp = client.post(f"/api/v1/streams/{stream_id}/end")
        assert resp.status_code == 200
        assert resp.get_json()["stream"]["status"] == "ended"

    def test_end_stream_twice(self, client):
        """Ending an already-ended stream returns 404."""
        create_resp = client.post("/api/v1/streams", content_type="application/json")
        stream_id = create_resp.get_json()["stream"]["id"]

        client.post(f"/api/v1/streams/{stream_id}/end")
        resp = client.post(f"/api/v1/streams/{stream_id}/end")
        assert resp.status_code == 404

    def test_list_streams(self, client):
        """GET /api/v1/streams lists active streams."""
        from app.services.stream_manager import stream_manager
        r1 = client.post("/api/v1/streams", content_type="application/json")
        r2 = client.post("/api/v1/streams", content_type="application/json")
        # Flip both to 'active' as if the LiveKit webhook had fired.
        stream_manager.mark_active(r1.get_json()["stream"]["id"])
        stream_manager.mark_active(r2.get_json()["stream"]["id"])

        resp = client.get("/api/v1/streams")
        assert resp.status_code == 200
        assert resp.get_json()["count"] == 2

    def test_ended_stream_not_in_list(self, client):
        """Ended streams are removed from the active list."""
        from app.services.stream_manager import stream_manager
        r1 = client.post("/api/v1/streams", content_type="application/json")
        r2 = client.post("/api/v1/streams", content_type="application/json")
        s1 = r1.get_json()["stream"]["id"]
        s2 = r2.get_json()["stream"]["id"]
        stream_manager.mark_active(s1)
        stream_manager.mark_active(s2)

        client.post(f"/api/v1/streams/{s1}/end")

        resp = client.get("/api/v1/streams")
        assert resp.get_json()["count"] == 1


class TestGestureConfigRoutes:
    """Tests for /api/v1/settings/gestures endpoints."""

    def test_get_default_gestures(self, client):
        """GET /api/v1/settings/gestures returns seeded defaults."""
        resp = client.get("/api/v1/settings/gestures")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "gestures" in data
        assert data["gestures"]["open_palm"] == "start_stream"
        assert data["gestures"]["peace_sign"] == "mute_mic"

    def test_update_gestures(self, client):
        """PUT /api/v1/settings/gestures updates mappings."""
        resp = client.put(
            "/api/v1/settings/gestures",
            data=json.dumps({
                "gestures": {"open_palm": "mute_mic", "wave": "say_hello"}
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        gestures = resp.get_json()["gestures"]
        assert gestures["open_palm"] == "mute_mic"
        assert gestures["wave"] == "say_hello"

    def test_update_gestures_invalid(self, client):
        """PUT with no gestures dict returns 400."""
        resp = client.put(
            "/api/v1/settings/gestures",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_health_check(self, client):
        """GET / returns health status."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"
