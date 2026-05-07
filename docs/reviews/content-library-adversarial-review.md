# Adversarial Review — Content Library Backend Plan

**Reviewed artifact:** `.cursor/plans/content_library_backend_c86809f5.plan.md`
**Review date:** 2026-05-07
**Method:** Cynical adversarial review — assumes problems exist, finds at least ten issues

---

## Summary

The plan correctly identifies the *files* to create, but treats every dangerous topic — auth, ownership, transactions, eventlet compatibility, streaming, key naming, ACL drift, error semantics, testing, bucket strategy, malware — as someone else's problem. It is a scaffolding outline, not an implementation plan. Roughly two-thirds of the findings below must be resolved (or explicitly deferred with a written rationale) before this is safe to build.

---

## Findings

### 1. No ownership model
The plan adds `visibility: public/private` but never adds an `owner_id` / `user_id` column or references a `User` model (which does not exist in this repo). Without ownership, "private" is meaningless, and `PATCH`/`DELETE` are wide open to anyone who knows a media id. The whole feature presumes a user system that the codebase does not have.

### 2. Zero authentication, zero authorization
Six new endpoints, including upload and delete, with no mention of auth tokens, sessions, API keys, or even a placeholder middleware. The existing `stream_routes.py` is also unauthenticated, but a media library is a far higher-value target — the plan should at minimum stub out an auth boundary instead of pretending the problem doesn't exist.

### 3. `python-magic` is a hidden-install footgun
It requires the `libmagic` C library (`brew install libmagic` on macOS, `apk add file` on Alpine). Adding it to `requirements.txt` will work on the dev's machine and silently fail in CI / Docker / prod. The plan never mentions `libmagic`, `python-magic-bin`, or pure-Python alternatives like `filetype`.

### 4. Eventlet + boto3 is a known compatibility minefield
The app already uses `async_mode="eventlet"` in `app/__init__.py:40`. boto3/botocore + eventlet monkey-patching has documented issues with connection pooling, SSL, and DNS. The plan does not specify import order, monkey-patch timing, or whether S3 calls should be wrapped in `socketio.start_background_task`. This will bite at runtime, not at code-review.

### 5. Uploads will block the SocketIO event loop
A single eventlet worker handling a 100 MB synchronous upload to MinIO blocks all WebSocket events (audio chunks, gestures) and HTTP requests for the duration. The plan never mentions chunked transfer, multipart upload, background offload, or worker-pool sizing.

### 6. `MEDIA_MAX_SIZE_MB` is enforced nowhere real
Without setting Werkzeug's `MAX_CONTENT_LENGTH`, Flask will happily buffer a multi-GB upload into memory before the route handler can check size. The plan says "validation done in `media_routes.py` before hitting storage" — that's *after* the body is already buffered. Three layers are needed (Werkzeug limit, `Content-Length` header check, streaming size check) and the plan describes one.

### 7. No streaming upload to MinIO
`upload_file(file_obj, bucket, key, mimetype)` implies reading the whole file then PUT'ing. For a 100 MB cap that's 100 MB of RAM per concurrent upload. boto3 supports `upload_fileobj` and `TransferConfig` for multipart streaming — the plan ignores this entirely.

### 8. Storage-key naming scheme is undefined
The model has a `storage_key` column but the plan never specifies how keys are generated. Two users uploading `photo.jpg` collide. The plan needs an explicit scheme (e.g., `{yyyy}/{mm}/{uuid}{ext}` or `{owner_id}/{uuid}{ext}`) and rules for re-uploads.

### 9. Filename sanitization is hand-waved
"Sanitized name used in storage" with no algorithm. `werkzeug.utils.secure_filename` strips non-ASCII (the project already contains Vietnamese strings like `Sao đen thui zậy` in the Figma — those filenames become empty strings). No mention of unicode policy, length cap, extension preservation, or path-traversal handling.

### 10. Soft-delete logic is self-contradictory
The plan says `delete_media` "soft-deletes the row + removes the object from MinIO." If the object is gone, the row is unrecoverable — that's a hard delete dressed in soft-delete clothing. Pick one: keep the object and mark deleted, or hard-delete both. As written, the soft-delete buys nothing.

### 11. Presigned URLs survive visibility changes
A user uploads a public file, gets a 1-hour presigned URL, then flips visibility to private. The URL still works for the remaining TTL because MinIO signed it directly — Flask is no longer in the loop. Either TTLs must be very short, downloads must be proxied, or bucket policies must enforce ACLs. The plan addresses none of these.

### 12. Single-bucket strategy hurts both performance and security
Putting public and private content in one bucket forces presigned URLs for everything, prevents CDN fronting of public assets, and makes lifecycle policies coarser. No bucket split, no CDN strategy, no `Cache-Control`, no `Content-Disposition` discussion.

### 13. Test coverage is "manual curl"
The repo already has `tests/test_api.py` and `tests/test_sockets.py`, so a testing pattern exists. The plan adds six endpoints and adds zero tests. No `moto` for boto3 mocking, no MinIO testcontainer, no error-path coverage. "Verify with manual curl" is not a test plan.

### 14. Pagination contract is missing
`list_media` returns `(items, total)` but the response JSON shape is undefined. No max `per_page` cap (client requests `per_page=999999` and OOMs you), no default sort order, no cursor-vs-offset decision, no behavior for soft-deleted items.

### 15. Error-response taxonomy is undefined
What status code for: file too large (413 vs 400), unsupported mimetype (415 vs 400), bucket unreachable (503 vs 500), DB row exists but object missing (404 vs 500), storage write succeeds but DB commit fails? Plan covers happy paths only.

### 16. Two-resource transactional safety is ignored
Classic dual-write problem: insert DB row → upload object fails → phantom row. Or upload first → DB insert fails → orphaned object. Plan specifies neither operation order, nor compensating actions, nor a cleanup job.

### 17. No rate limiting or quota
Unauthenticated upload endpoint + no rate limit = a one-line `curl` loop fills your disk and your MinIO bucket. No `flask-limiter`, no per-IP throttle, no per-user storage quota.

### 18. No malware / virus scanning
Accepting arbitrary uploads from the internet with no scanning is below table stakes for any media platform. The plan does not even acknowledge the gap (ClamAV sidecar, scan-on-upload lambda, etc.).

### 19. Mimetype source-of-truth is ambiguous
`python-magic` detects from bytes, the model stores a `mimetype` column, and the request carries a `Content-Type` header. The plan never says which one wins, what happens on mismatch (`.jpg` extension but `application/x-msdownload` bytes), or whether the stored value can be trusted by clients later.

### 20. No thumbnail / metadata extraction
A "Content Library" without image dimensions, video duration, or thumbnail derivation will force the future media-library UI to download full-resolution originals to render a grid. Missing Pillow/ffmpeg discussion is a planning omission, not an implementation detail.

### 21. `MINIO_SECURE = False` default is a production footgun
Anyone copying `.env.example` to prod ships plaintext credentials over the wire. The plan should default secure-on and require explicit opt-out for local dev, or at minimum document the risk loudly.

### 22. SQLite + eventlet + heavy writes is fragile
The existing app uses SQLite. Adding a media table that takes concurrent writes from multiple eventlet greenlets invites `database is locked` errors. Plan should at least note when Postgres becomes mandatory.

### 23. Alembic migration is described as a one-step task
No mention of downgrade, no rollback strategy, no separation of schema migration vs MinIO bucket initialization, no production rollout plan.

### 24. MinIO bucket CORS is unaddressed
Frontend will load images/videos from MinIO origin (different from Flask origin). Without bucket-level CORS configuration, browsers will block these loads — especially `<video crossorigin>` and `<canvas drawImage>`. Plan never mentions it.

### 25. `docker-compose.yml` only contains MinIO
This creates two parallel dev workflows: Flask app runs native, MinIO runs in Docker. Either Dockerize everything (including Postgres) or document why the split is intentional. As proposed, the docker file pulls its weight only for one developer on one machine.

### 26. No bucket lifecycle policy
Soft-deleted items, abandoned uploads, and orphaned objects live in MinIO forever. Storage cost is unbounded. No `expiration`, no `noncurrent-version-expiration`, no cleanup cron.

### 27. `status` column name collides with `Stream.status`
The `Stream` model already has `status` with values `active` / `ended`. Adding `MediaItem.status` with values `active` / `deleted` creates two unrelated state machines under the same column name. Future joins and analytics will silently mislead. Use `deleted_at` (NULL = active) or `lifecycle` to disambiguate.

### 28. No `updated_at` automation
The plan lists `updated_at` in the model but never specifies whether it auto-updates on `PATCH`. SQLAlchemy doesn't do this for free — needs `onupdate=datetime.utcnow` on the column or an event hook. Will silently stay at `created_at` value otherwise.

---

## Recommended Next Steps

1. Run `bmad-review-edge-case-hunter` to catch boundary conditions (concurrent uploads of identical files, partial multipart failures, MinIO downtime mid-upload, etc.)
2. Run `bmad-advanced-elicitation` with **pre-mortem** and **first-principles** methods to rebuild the weakest sections (auth model, transactional safety, soft-delete semantics)
3. Use `bmad-create-architecture` in a fresh context to rebuild the plan from scratch incorporating all findings above as constraints
