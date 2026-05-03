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
