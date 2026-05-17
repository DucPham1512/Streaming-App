# Streaming-App

## 1. Architectural Strategy: Client vs. Server Processing

Before writing any routes, you need to decide where the heavy lifting happens. To keep latency low and avoid overloading your Flask server:

- **Hand Signals (Computer Vision):** Process this client-side. If you are building a React or Next.js frontend, use a library like MediaPipe.JS directly in the browser to detect hands. The browser then sends a lightweight JSON command (e.g., `{"action": "mute_mic"}`) to Flask, rather than streaming raw 60fps video frames to the backend for processing.
- **Automated Subtitles (Speech-to-Text):** This usually requires heavier models (like Whisper or Vosk). The client should capture audio chunks using the MediaStream Recording API and pipe them to Flask via WebSockets. Flask processes the audio and emits the text back to the clients.

---

## 2. API Blueprint

You will need **Flask** for the HTTP routes and **Flask-SocketIO** for the real-time event streams.

### A. WebSocket Events (The Real-Time Core)

WebSockets maintain a persistent connection, which is strictly required for your livestreaming features.

#### `connect` / `join_room`
Authenticates the user and assigns them to a specific livestream room.

#### `stream_audio_chunk`
- **Payload:** Binary audio blob (e.g., PCM or WebM format).
- **Behavior:** The Flask server buffers this chunk, passes it to the Speech-to-Text service, and resolves it to text.

#### `broadcast_subtitle`
- **Payload:** `{"text": "Hello world", "timestamp": "..."}`
- **Behavior:** Emitted by Flask to all connected clients in the room to display the subtitle.

#### `gesture_command_received`
- **Payload:** `{"command": "switch_camera", "confidence": 0.95}`
- **Behavior:** The frontend detects a hand signal and tells the backend. The backend updates the stream state and broadcasts the change to viewers.

### B. RESTful APIs (State & Configuration)

Standard HTTP routes to handle the application's CRUD operations.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/streams` | Initialize a new livestream session. Returns a unique `stream_id` and WebSocket connection tokens. |
| `PATCH` | `/api/v1/streams/<stream_id>` | Update stream metadata (title, description, privacy status). |
| `POST` | `/api/v1/streams/<stream_id>/end` | Terminate the stream and close WebSocket connections. |
| `GET` | `/api/v1/settings/gestures` | Fetch the user's mapped gestures (e.g., Open Palm = Start Stream, Peace Sign = Mute). |
| `PUT` | `/api/v1/settings/gestures` | Update custom key-value mappings for gesture controls. |

---

## 3. Codebase Structure

To keep the application scalable and highly testable, use the **Flask Application Factory** pattern. Separate the real-time socket logic from the REST API routes and business logic.

```text
livestream_app/
├── app/
│   ├── __init__.py           # Application Factory, SocketIO init
│   ├── api/                  # REST API Blueprints
│   │   ├── stream_routes.py
│   │   └── config_routes.py
│   ├── sockets/              # WebSocket event handlers
│   │   ├── connection_events.py
│   │   └── media_events.py   # Handles audio chunks and gesture JSON
│   ├── services/             # Core Business Logic (Keep this decoupled from routing)
│   │   ├── stt_engine.py     # Speech-to-text processing (Whisper/Vosk)
│   │   └── stream_manager.py # State management for active streams
│   └── models/               # Database schemas (SQLAlchemy)
├── tests/                    # Robust test suite
│   ├── test_api.py           # Endpoint validation
│   └── test_sockets.py       # Mocking WebSocket events and STT queues
├── requirements.txt
└── run.py                    # Entry point (runs SocketIO server)
```

---

## 4. Setup and Dependencies

To initialize this environment, you will need a combination of web and ML-oriented packages.

### Core Python Packages

- **`Flask`** & **`Flask-Cors`** — Core backend.
- **`Flask-SocketIO`** — For WebSockets.
- **`eventlet`** or **`gevent`** — Asynchronous workers required by Flask-SocketIO to handle concurrent media streams without blocking.
- **`SpeechRecognition`** or **`faster-whisper`** — For the backend STT engine.
- **`pytest`** & **`pytest-flask`** — To write test cases that validate both REST endpoints and mocked WebSocket emissions.

### Setup Steps

1. Initialize a virtual environment:
   ```bash
   python -m venv venv
   ```
2. Install the asynchronous worker explicitly before SocketIO:
   ```bash
   pip install eventlet Flask-SocketIO
   ```
3. Set up a lightweight database (SQLite/PostgreSQL) to store stream metadata and gesture configurations.

---

> **Open Question:** For the Speech-to-Text component, processing audio chunks continuously can block your Flask server. Are you planning to run the STT model synchronously on the main server thread, or were you considering a task queue (like Celery or Redis) to handle the audio processing asynchronously?

---

## 5. Developer Code Guide

### A. Running the App

```bash
# First time setup
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# Apply database migrations (creates the DB file on first run)
.venv/bin/alembic upgrade head

# Optionally populate mock data
.venv/bin/python seed.py

# Start the dev server
.venv/bin/python run.py
```

The server starts on `http://localhost:5000`. The health check at `/` confirms it is alive.

### B. Running Tests

```bash
.venv/bin/pytest
```

Tests use an in-memory SQLite database (`sqlite:///:memory:`) that is created fresh and dropped for every test function, so they are fully isolated from the development database.

---

### C. Directory Reference

```text
Streaming_app/
│
├── run.py                      # Entry point — starts the Flask-SocketIO server
├── seed.py                     # Populates the dev DB with mock data (safe to re-run)
├── alembic.ini                 # Alembic configuration (points at migrations/)
├── requirements.txt
│
├── app/
│   ├── __init__.py             # Application factory (create_app)
│   │                           # Wires together config, extensions, blueprints, sockets
│   │
│   ├── config.py               # DevelopmentConfig / TestingConfig / ProductionConfig
│   │                           # DB path, SECRET_KEY, CORS origins live here
│   │
│   ├── extensions.py           # Shared singletons: db, socketio, cors
│   │                           # Instantiated here, bound to the app in create_app()
│   │
│   ├── models/
│   │   ├── __init__.py         # Re-exports all models — import from here, not submodules
│   │   ├── stream.py           # Stream — represents a live session
│   │   └── gesture.py          # GestureMapping — maps a gesture to an action per user
│   │
│   ├── api/                    # REST blueprints (HTTP only)
│   │   ├── stream_routes.py    # /api/v1/streams  — CRUD for stream sessions
│   │   └── config_routes.py    # /api/v1/settings — gesture configuration
│   │
│   ├── sockets/                # WebSocket event handlers (SocketIO only)
│   │   ├── connection_events.py  # connect, disconnect, join_room, leave_room
│   │   └── media_events.py       # stream_audio_chunk, gesture_command_received
│   │
│   └── services/               # Business logic decoupled from routing
│       ├── stream_manager.py   # Singleton that owns stream lifecycle + in-memory registry
│       └── stt_engine.py       # Speech-to-text wrapper (faster-whisper / stub fallback)
│
├── migrations/                 # Alembic migration scripts — commit these to git
│   ├── env.py                  # Flask-aware Alembic env (reads DB URL from app config)
│   ├── script.py.mako          # Template used when generating new migration files
│   └── versions/               # Auto-generated migration files, one per schema change
│
└── tests/
    ├── conftest.py             # Pytest fixtures: app, db, client, socketio_test_client
    ├── test_api.py             # REST endpoint tests
    └── test_sockets.py         # WebSocket event tests
```

---

### D. Key Patterns to Know

**Application Factory (`app/__init__.py`)**
`create_app(config_name)` is the single function that builds the Flask app. Nothing is
global — extensions start unbound in `extensions.py` and are wired up inside `create_app`
via `init_app()`. This is what allows tests to spin up a fresh app with a different config.

**Extension Singletons (`app/extensions.py`)**
`db`, `socketio`, and `cors` are created once at import time with no app attached.
Always import them from `app.extensions`, never from a model or route file, to avoid
circular imports.

**Blueprints (`app/api/`)**
Each file registers a `Blueprint` with a `url_prefix`. To add a new group of REST
routes, create a new blueprint file and register it in `create_app`.

**Service Layer (`app/services/`)**
Route handlers and socket handlers should not contain business logic. They delegate to a
service instead. `StreamManager` is a singleton (module-level instance) that is safe to
import directly anywhere.

---

### E. Adding a New Feature — Step by Step

#### 1. Add a model

Create `app/models/your_model.py` inheriting from `db.Model`, then re-export it in
`app/models/__init__.py`:

```python
# app/models/__init__.py
from app.models.your_model import YourModel  # noqa: F401
```

#### 2. Generate and apply the migration

```bash
.venv/bin/alembic revision --autogenerate -m "add_your_model_table"
.venv/bin/alembic upgrade head
```

Review the generated file in `migrations/versions/` before applying — autogenerate is
accurate for simple cases but occasionally needs manual adjustment.

#### 3. Add a service (if needed)

Put business logic in `app/services/your_service.py`. Keep it framework-agnostic: no
`flask.request`, no `emit()`. This makes it trivially testable.

#### 4. Add REST routes or socket handlers

- REST: create `app/api/your_routes.py`, define a `Blueprint`, register it in `create_app`.
- WebSocket: add handlers to an existing file in `app/sockets/` or create a new one and
  import it (side-effect import) in `create_app`.

#### 5. Write tests

Add test functions to `tests/test_api.py` or `tests/test_sockets.py`. Use the fixtures
from `conftest.py` — `client` for REST, `socketio_test_client` for WebSocket events.

---

### F. Database Workflow (Alembic Cheatsheet)

| Task | Command |
|---|---|
| Apply all pending migrations | `.venv/bin/alembic upgrade head` |
| Roll back one migration | `.venv/bin/alembic downgrade -1` |
| Generate migration from model changes | `.venv/bin/alembic revision --autogenerate -m "description"` |
| Show current revision | `.venv/bin/alembic current` |
| Show migration history | `.venv/bin/alembic history` |
| Re-populate mock data | `.venv/bin/python seed.py` |

The development database lives at the platform-appropriate user data directory:

| OS | Path |
|---|---|
| Linux | `~/.local/share/streaming_app/streaming_app.db` |
| macOS | `~/Library/Application Support/streaming_app/streaming_app.db` |
| Windows | `%APPDATA%\streaming_app\streaming_app.db` |

Set `DATABASE_URL` in your environment to override this for any config (e.g. pointing at
a PostgreSQL instance in production).

---

## 6. Full Dev Setup (feat/media and beyond)

This section covers the additional steps required once MinIO-backed media storage is part of the stack.

### Prerequisites

- Docker (for MinIO)
- The `.env` file must not contain inline comments — they are not supported and will be parsed as part of the value. Put comments on their own line:

```bash
# OK
# DATABASE_URL=

# Breaks — the comment becomes the value
DATABASE_URL=  # leave empty for SQLite
```

### First-time setup

```bash
# 1. Install dependencies
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Copy env file and remove any inline comments
cp .env.example .env

# 3. Start MinIO
docker compose up -d

# 4. Apply all database migrations
.venv/bin/alembic upgrade head

# 5. Create MinIO buckets (run once)
.venv/bin/flask init-buckets

# 6. Seed mock data (optional)
.venv/bin/python seed.py

# 7. Start the server
.venv/bin/python run.py
```

The server starts on `http://0.0.0.0:5001`.

### Subsequent runs

```bash
docker compose up -d     # make sure MinIO is running
.venv/bin/python run.py
```

### Switching branches with different migrations

If you switch to a branch with a different migration history and see:
```
FAILED: Can't locate revision identified by '...'
```

Clear the version record and re-apply:

```bash
sqlite3 ~/.local/share/streaming_app/streaming_app.db "DELETE FROM alembic_version;"
.venv/bin/alembic upgrade head
```

If tables already exist from another branch, delete the DB and start fresh:

```bash
rm ~/.local/share/streaming_app/streaming_app.db
.venv/bin/alembic upgrade head
```

