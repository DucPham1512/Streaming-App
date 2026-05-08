"""End-to-end HTTP tests for /api/v1/media/*.

Backed by moto (via conftest fixtures). Verifies the full request →
service → storage → response cycle, error envelopes, and auth gates.
"""

import io
import json

import pytest


_PNG = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
    "0000000D49444154789C6300010000000500010D0A2DB40000000049454E44AE426082"
)


def _multipart_data(filename="hello.png", visibility="private", title="", description=""):
    return {
        "file": (io.BytesIO(_PNG), filename),
        "title": title,
        "description": description,
        "visibility": visibility,
    }


class TestUploadEndpoint:
    def test_401_without_auth(self, client, fresh_buckets):
        resp = client.post(
            "/api/v1/media/upload",
            data=_multipart_data(),
            content_type="multipart/form-data",
        )
        assert resp.status_code == 401
        assert resp.get_json()["code"] == "UNAUTHORIZED"

    def test_201_with_auth(self, client, auth_headers, fresh_buckets):
        resp = client.post(
            "/api/v1/media/upload",
            data=_multipart_data(visibility="public"),
            headers=auth_headers,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["media"]["mimetype"] == "image/png"
        assert body["media"]["visibility"] == "public"

    def test_415_for_unsupported_mimetype(self, client, auth_headers, fresh_buckets):
        resp = client.post(
            "/api/v1/media/upload",
            data={"file": (io.BytesIO(b"PK\x03\x04garbage"), "x.zip")},
            headers=auth_headers,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 415
        assert resp.get_json()["code"] == "UNSUPPORTED_MEDIA_TYPE"

    def test_400_when_file_missing(self, client, auth_headers, fresh_buckets):
        resp = client.post(
            "/api/v1/media/upload",
            data={"title": "no file"},
            headers=auth_headers,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "INVALID_FIELD"


class TestListEndpoint:
    def _upload(self, client, headers, visibility, filename):
        return client.post(
            "/api/v1/media/upload",
            data=_multipart_data(filename=filename, visibility=visibility),
            headers=headers,
            content_type="multipart/form-data",
        )

    def test_anonymous_lists_only_public_and_unlisted(
        self, client, auth_headers, fresh_buckets
    ):
        self._upload(client, auth_headers, "public", "p.png")
        self._upload(client, auth_headers, "private", "x.png")
        self._upload(client, auth_headers, "unlisted", "u.png")

        resp = client.get("/api/v1/media")
        assert resp.status_code == 200
        body = resp.get_json()
        for it in body["items"]:
            assert it["visibility"] in ("public", "unlisted")

    def test_pagination_envelope(self, client, auth_headers, fresh_buckets):
        for i in range(3):
            self._upload(client, auth_headers, "public", f"{i}.png")
        resp = client.get("/api/v1/media?per_page=2&page=1")
        body = resp.get_json()
        assert body["page"] == 1
        assert body["per_page"] == 2
        assert body["total"] >= 3
        assert "total_pages" in body

    def test_per_page_capped_at_100(self, client, auth_headers, fresh_buckets):
        resp = client.get("/api/v1/media?per_page=999")
        assert resp.status_code == 200
        assert resp.get_json()["per_page"] == 100

    def test_invalid_page_returns_400_envelope(self, client, fresh_buckets):
        resp = client.get("/api/v1/media?page=foo")
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["code"] == "INVALID_REQUEST"

    def test_invalid_per_page_returns_400_envelope(self, client, fresh_buckets):
        resp = client.get("/api/v1/media?per_page=abc")
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["code"] == "INVALID_REQUEST"


class TestGetSingle:
    def _upload(self, client, headers, visibility="public"):
        return client.post(
            "/api/v1/media/upload",
            data=_multipart_data(visibility=visibility),
            headers=headers,
            content_type="multipart/form-data",
        ).get_json()["media"]

    def test_get_public_no_auth(self, client, auth_headers, fresh_buckets):
        item = self._upload(client, auth_headers, "public")
        resp = client.get(f"/api/v1/media/{item['id']}")
        assert resp.status_code == 200

    def test_404_when_missing(self, client, fresh_buckets):
        resp = client.get("/api/v1/media/no-such-id")
        assert resp.status_code == 404
        assert resp.get_json()["code"] == "NOT_FOUND"

    def test_private_requires_auth(self, client, auth_headers, fresh_buckets):
        item = self._upload(client, auth_headers, "private")
        resp_anon = client.get(f"/api/v1/media/{item['id']}")
        assert resp_anon.status_code == 401
        resp_auth = client.get(f"/api/v1/media/{item['id']}", headers=auth_headers)
        assert resp_auth.status_code == 200

    def test_private_403_for_other_user(
        self, client, auth_headers, other_headers, fresh_buckets
    ):
        item = self._upload(client, auth_headers, "private")
        resp = client.get(f"/api/v1/media/{item['id']}", headers=other_headers)
        assert resp.status_code == 403
        assert resp.get_json()["code"] == "FORBIDDEN"


class TestStreamEndpoint:
    def test_stream_returns_bytes(self, client, auth_headers, fresh_buckets):
        item = client.post(
            "/api/v1/media/upload",
            data=_multipart_data(visibility="public"),
            headers=auth_headers,
            content_type="multipart/form-data",
        ).get_json()["media"]
        resp = client.get(f"/api/v1/media/{item['id']}/stream")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"] == "image/png"
        assert resp.data == _PNG

    def test_invalid_range_returns_416(self, client, auth_headers, fresh_buckets):
        item = client.post(
            "/api/v1/media/upload",
            data=_multipart_data(visibility="public"),
            headers=auth_headers,
            content_type="multipart/form-data",
        ).get_json()["media"]
        resp = client.get(
            f"/api/v1/media/{item['id']}/stream",
            headers={"Range": "bytes=9999-10000"},
        )
        assert resp.status_code == 416
        assert resp.get_json()["code"] == "INVALID_RANGE"


class TestPresignedUrlEndpoint:
    def test_url_for_public_item(self, client, auth_headers, fresh_buckets):
        item = client.post(
            "/api/v1/media/upload",
            data=_multipart_data(visibility="public"),
            headers=auth_headers,
            content_type="multipart/form-data",
        ).get_json()["media"]
        resp = client.get(f"/api/v1/media/{item['id']}/url")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "url" in body
        assert body["expires_in_seconds"] > 0

    def test_400_for_private_item(self, client, auth_headers, fresh_buckets):
        item = client.post(
            "/api/v1/media/upload",
            data=_multipart_data(visibility="private"),
            headers=auth_headers,
            content_type="multipart/form-data",
        ).get_json()["media"]
        resp = client.get(f"/api/v1/media/{item['id']}/url")
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "INVALID_FIELD"


class TestPatchEndpoint:
    def _upload(self, client, headers, visibility="private"):
        return client.post(
            "/api/v1/media/upload",
            data=_multipart_data(visibility=visibility),
            headers=headers,
            content_type="multipart/form-data",
        ).get_json()["media"]

    def test_owner_can_update_title(self, client, auth_headers, fresh_buckets):
        item = self._upload(client, auth_headers)
        resp = client.patch(
            f"/api/v1/media/{item['id']}",
            data=json.dumps({"title": "Renamed"}),
            headers={**auth_headers, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["media"]["title"] == "Renamed"

    def test_visibility_change_moves_bucket(self, client, auth_headers, fresh_buckets, app):
        item = self._upload(client, auth_headers, "private")
        resp = client.patch(
            f"/api/v1/media/{item['id']}",
            data=json.dumps({"visibility": "public"}),
            headers={**auth_headers, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        body = resp.get_json()["media"]
        assert body["visibility"] == "public"
        assert body["storage_bucket"] == app.config["MEDIA_PUBLIC_BUCKET"]

    def test_403_for_non_owner(
        self, client, auth_headers, other_headers, fresh_buckets
    ):
        item = self._upload(client, auth_headers, "private")
        resp = client.patch(
            f"/api/v1/media/{item['id']}",
            data=json.dumps({"title": "Hijack"}),
            headers={**other_headers, "Content-Type": "application/json"},
        )
        assert resp.status_code == 403
        after = client.get(f"/api/v1/media/{item['id']}", headers=auth_headers).get_json()[
            "media"
        ]
        assert after["title"] != "Hijack"


class TestDeleteEndpoint:
    def _upload(self, client, headers):
        return client.post(
            "/api/v1/media/upload",
            data=_multipart_data(visibility="public"),
            headers=headers,
            content_type="multipart/form-data",
        ).get_json()["media"]

    def test_owner_can_soft_delete(self, client, auth_headers, fresh_buckets):
        item = self._upload(client, auth_headers)
        resp = client.delete(f"/api/v1/media/{item['id']}", headers=auth_headers)
        assert resp.status_code == 200
        # Subsequent GET 404s.
        resp2 = client.get(f"/api/v1/media/{item['id']}")
        assert resp2.status_code == 404

    def test_403_for_non_owner(self, client, auth_headers, other_headers, fresh_buckets):
        item = self._upload(client, auth_headers)
        resp = client.delete(f"/api/v1/media/{item['id']}", headers=other_headers)
        assert resp.status_code == 403
        # Ensure failed delete attempt does not mutate ownership-visible state.
        still_there = client.get(f"/api/v1/media/{item['id']}", headers=auth_headers)
        assert still_there.status_code == 200
