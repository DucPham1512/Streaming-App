# Content Library Implementation Review

## Verdict

**CHANGES REQUESTED**

The implementation is close and test-rich (`91 passed`), but there are architecture-level compliance gaps and edge-case correctness issues that should be fixed before merge.

## Scope and Method

- Applied BMad review layers: **Blind Hunter**, **Edge Case Hunter**, **Acceptance Auditor**
- Reviewed implementation files listed in the request (Story A + Story B)
- Checked architecture compliance against D1-D8, Step 5 patterns, Step 6 boundary checklist
- Ran baseline tests at end:
  - `cd /Users/nangsontay/Streaming-App && .venv/bin/pytest -q`
  - Result: `91 passed in 0.51s`

## Triage Table

| ID | Severity | Category | Finding | Evidence |
|---|---|---|---|---|
| F1 | Blocking | Eventlet | D2 eventlet strategy is not implemented; boto3 network calls run inline with no `socketio.start_background_task` wrapping | `app/services/storage_service.py:128`, `app/services/storage_service.py:150`, `app/services/storage_service.py:180`, `app/services/storage_service.py:195` |
| F2 | High | Correctness | Non-integer pagination params raise `ValueError` and leak to default 500 HTML instead of canonical error envelope | `app/api/media_routes.py:94`, `app/api/media_routes.py:95`, `app/__init__.py:69` |
| F3 | High | Correctness | Invalid `Range` past EOF is translated to `503 STORAGE_UNAVAILABLE` instead of a client error (`416`/`400`) | `app/services/storage_service.py:151`, `app/services/storage_service.py:158` |
| F4 | Medium | Correctness | Story A model-level FK expectation not met: `User.avatar_media_id` is plain `String` (no ORM FK declaration) | `app/models/user.py:31` |
| F5 | Medium | Style | Boundary checklist requires `@require_owner` on PATCH/DELETE; routes use manual ownership checks instead | `app/api/media_routes.py:211`, `app/api/media_routes.py:233`, `app/api/media_routes.py:217`, `app/api/media_routes.py:239` |
| F6 | Medium | Correctness | Quota check is race-prone under concurrent uploads (check-then-upload without lock/atomic reservation) | `app/services/media_service.py:240`, `app/services/media_service.py:265` |
| F7 | Medium | Correctness | D7 visibility-move partial-failure behavior differs from architecture decision; copy succeeds + delete fails currently raises and leaves DB unchanged | `app/services/storage_service.py:200`, `app/services/media_service.py:354`, `app/services/media_service.py:357` |
| F8 | Low | Style | Socket event payload shape does not follow Step 5 convention (`event/data/timestamp`) | `app/services/media_service.py:320` |
| F9 | Nit | Style | Boundary checklist says "No print()"; modified `seed.py` still prints | `seed.py:145`, `seed.py:149`, `seed.py:151` |

## Detailed Findings (Blocking/High)

### F1 — D2 eventlet wrapping missing (Blocking)

**Argument:** Architecture D2 explicitly requires wrapping network-bound S3 calls with `socketio.start_background_task` + wait primitive. Current implementation calls boto3 inline directly in request path.

**Why this matters:** Under eventlet async mode, blocking boto3 I/O can stall greenlets and hurt socket/http responsiveness under upload/download load.

**Suggested fix:**

1. Implement private `_await_io(...)` helper in `storage_service` per architecture Step 5 pseudocode.
2. Route `upload_fileobj`, `get_object`, `delete_object`, `copy_object` through it.
3. Add tests that monkeypatch `_await_io` and assert these methods call the wrapper.
4. Ensure runtime import/boot path satisfies monkey-patch ordering requirement documented in D2.

### F2 — Invalid pagination params crash into 500 HTML (High)

**Reproduction:**

- Request: `GET /api/v1/media?page=foo`
- Runtime result observed: `ValueError` at `int(...)` in route, response becomes default 500 HTML.

**Why this matters:** Violates D8 canonical API error envelope and creates non-deterministic client behavior.

**Suggested fix:**

1. Guard int parsing in `list_media` with validation (`try/except ValueError`).
2. Return `400` with canonical envelope (`{"error": "...", "code": "INVALID_REQUEST"}`).
3. Add global `@application.errorhandler(Exception)` fallback in `app/__init__.py` for unexpected errors, returning `INTERNAL_ERROR` and logging `exc_info=True`.

### F3 — Invalid range mapped to storage outage (High)

**Reproduction:**

- Upload a valid item, then request `GET /api/v1/media/<id>/stream` with `Range: bytes=9999-10000` (past EOF).
- Observed status: `503`, because `InvalidRange` from S3 is mapped to `StorageUnavailable`.

**Why this matters:** Client input error is misreported as infrastructure outage; this can trigger wrong retries/alerts and violates error taxonomy intent.

**Suggested fix:**

1. In `storage_service.get_object_stream`, branch on `ClientError` code:
   - `NoSuchKey` -> `NotFound`
   - `InvalidRange` -> typed 416/400 domain exception
   - true backend failures -> `StorageUnavailable`
2. Add API tests for malformed/past-end/multi-range behaviors.

## Acceptance Auditor Notes (Stories A/B AC)

- **Story A ACs**
  - Existing suite still green: ✅ (verified by final `pytest -q`)
  - `create-user` command prints API key: ✅ (code path present)
  - `flask shell` import path for `current_user`: ✅ (module exports correctly)
  - Canary `@require_auth` 401/200: ✅ (`tests/test_auth_service.py`)

- **Story B ACs**
  - Upload returns 201 with bearer token: ✅ (`tests/test_media_api.py`)
  - Vietnamese filename round-trip upload->list->download without corruption: 🟡 partially covered (upload filename covered; full list+stream round-trip assertion missing)
  - Soft-delete hides item while object remains until purge: 🟡 partially covered (list exclusion covered; object-still-exists check missing)
  - Visibility flip private->public moves object and URL available: ✅ (covered across patch + url tests)
  - All adversarial #1-#28 resolved or tracked: 🟡 mostly, but D2 and edge-case error mapping gaps remain
  - Full suite green with regression parity: ✅

## Compliance Matrix

| Area | Status | One-line justification |
|---|---|---|
| D1 Auth & ownership boundary | 🟡 | Auth boundary works, but PATCH/DELETE did not use required `@require_owner` pattern |
| D2 Eventlet ⇄ boto3 strategy | ❌ | Required background-task wrapping is documented but not implemented in code |
| D3 Multi-layer size enforcement | ✅ | `MAX_CONTENT_LENGTH`, header check, and streaming counter all present |
| D4 Key/filename/mimetype strategy | ✅ | NFKC sanitize, 261-byte sniff, allowlist, generated key scheme implemented |
| D5 Soft-delete semantics | ✅ | `deleted_at` source-of-truth and purge path implemented |
| D6 Bucket/visibility enforcement | ✅ | Two-bucket split, visibility routing, stream proxy, presigned public-only present |
| D7 Transactional safety | 🟡 | Upload-first + commit-compensate implemented, but visibility partial-failure handling differs from decision text |
| D8 Operational concerns batch | 🟡 | Most implemented; notable error-taxonomy gaps on invalid pagination/range handling |
| Boundary checklist | 🟡 | Major items pass, but `@require_owner` checklist item fails and `print()` remains in modified `seed.py` |
| Step 5 pattern consistency | 🟡 | Naming/envelopes mostly consistent; socket payload convention and some error-path contracts drift |

## Boundary Checklist Verification

- No `flask.request` import in `app/services/*` except `auth_service`: ✅
- No `boto3` import outside `storage_service` + `tests/conftest.py`: ✅
- No hardcoded bucket literals outside `config.py`: ✅
- Every `media_items` query filters `deleted_at IS NULL` except `purge_deleted_media`: 🟡 (`get_media` enforces post-fetch rather than SQL filter)
- Every mutating media route has `@require_auth`; PATCH/DELETE has `@require_owner`: ❌ (`@require_auth` yes, `@require_owner` no)
- No `print()` calls; only `logger`: ❌ (`seed.py` prints)

## Pattern Consistency Samples (Step 5)

1. Datetime JSON serialization via `.isoformat()`: ✅ (`MediaItem.to_dict`, `User.to_dict`)
2. List envelope shape `{"items": ...}`: ✅ (`GET /api/v1/media`)
3. Canonical typed service exceptions for business errors: ✅ (`app/services/exceptions.py`, service raises)
4. Error envelope on unhandled exceptions: ❌ (no global `Exception` handler)
5. Socket payload shape (`event/data/timestamp`): ❌ (`media_uploaded` emits `{"media": ...}`)

## Test Coverage Assessment (Required Before Merge)

1. **Pagination parse hardening** in `tests/test_media_api.py`:
   - `?page=foo`, `?per_page=abc`, negatives/zero behavior
   - Expect canonical 400 where invalid type is provided
2. **Range edge cases** in `tests/test_media_api.py` + `tests/test_storage_service.py`:
   - malformed (`bytes=foo-bar`), past EOF, and multi-range semantics
   - assert correct status taxonomy (not `503` for client mistakes)
3. **Eventlet wrapping contract** in `tests/test_storage_service.py`:
   - assert S3 network ops route through `_await_io` wrapper required by D2
4. **Quota race** in `tests/test_media_service.py`:
   - concurrent uploads by same owner near quota boundary
   - define and test deterministic conflict behavior
5. **AC-specific round-trip assertions** in `tests/test_media_api.py`:
   - Vietnamese filename survives upload -> list -> stream response headers
   - soft-delete keeps object accessible in storage until purge path runs

