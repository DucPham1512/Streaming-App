# VSR Streaming App — backend

A livestreaming platform with **hand-gesture-controlled streaming
effects**. The streamer raises a hand, a gesture fires, viewers see a
heart burst / confetti / mute toggle / etc. Custom gestures can be
recorded and remapped per-user from a browser dashboard.

This repo holds the backend stack (Flask + SocketIO + LiveKit +
Postgres + MinIO) and the **broadcaster** — a Python process that runs
on the streamer's laptop, captures the camera with OpenCV, detects
gestures with MediaPipe, and publishes video to LiveKit.

The viewer-facing mobile/web app lives in a separate repo:
[FE-Streaming-app](../FE-Streaming-app/).

> **Setting up to run the demo? See [SETUP.md](SETUP.md).** This README
> is the overview; SETUP.md is the step-by-step.

---

## What it is, in one diagram

```
  Streamer laptop                                    Viewers
  ──────────────────                                 ───────
                                       ┌──────────┐
   ┌────────────────┐                  │  Mobile  │   (React Native, custom
   │  broadcaster   │   WebRTC video   │   app    │    dev client — Expo Go
   │  (Python exe)  │ ───────────────► │          │    can't load WebRTC)
   │                │                  └──────────┘
   │  • OpenCV cam  │       ┌──────────┐
   │  • MediaPipe   │       │ LiveKit  │   ┌──────────┐
   │  • gestures    │ ────► │  Server  │ ─►│   Web    │    (any browser,
   │  • LiveKit pub │       │  (SFU)   │   │  viewer  │     no install)
   └───────┬────────┘       └──────────┘   └──────────┘
           │
           │  Socket.IO (gestures, recording requests, auth)
           │  REST     (auth, /api/v1/gestures/*, /api/v1/streams/*)
           ▼
   ┌──────────────────┐        ┌──────────┐
   │  Flask backend   │ ─────► │ Postgres │
   │                  │        └──────────┘
   │ • REST API       │        ┌──────────┐
   │ • Socket.IO hub  │ ─────► │  MinIO   │    (S3-compatible blob
   │ • streamer dash  │        └──────────┘     store for media uploads)
   │   at /streamer/  │
   └──────────────────┘
```

Everything except the broadcaster runs in Docker. The broadcaster runs
on the host because it needs direct access to the camera, microphone,
and display for the preview window.

---

## What the streamer experiences

1. Launch `Broadcaster.exe` (Windows) or `./Broadcaster` (macOS/Linux).
2. A login dialog appears. Enter username + password, or click
   **Continue as Guest** to stream without an account.
3. A browser tab auto-opens to the **streamer dashboard** — their own
   stream's video on the left, comments/viewer count/hearts on the right.
   The dashboard is automatically signed in as the same account used in
   the login dialog (the API key is passed via URL hash and stored in
   `localStorage`). Guest mode shows the modal for optional sign-in.
4. Click "Manage gestures ↗" to remap built-in gestures or record
   custom ones (3-second countdown → 10 frames of landmarks → k-NN
   template stored per-user).
5. Gesture detection runs locally in the broadcaster. **Open palm** →
   mute/unmute (stops audio at the WebRTC track level and notifies
   viewers). **Fist hold (3 s)** → end stream.

---

## What viewers experience

- Open the FE app (iOS/Android dev client, or a browser) and watch.
- Chat in the comment panel; tap the heart button.
- See the streamer's profile picture and display name in the stream
  overlay. If the streamer is authenticated, their avatar is fetched
  live.
- See a 🔇 badge and have their audio muted when the streamer uses the
  mute gesture.

---

## Authentication model

- Each user has a per-account **API key** (`secrets.token_hex(32)`).
- The broadcaster obtains the key via the login dialog at startup and
  keeps it **in RAM only** — it is never written to disk.
- The key is passed to the streamer dashboard via `#api_key=…` in the
  URL (hash fragment — never sent to the server, removed from the
  browser URL bar after use).
- Viewers do not need an API key to watch; they do need one to chat
  (standard bearer-token auth on comment routes).

---

## Repo layout

```
Streaming-App/
├── app/                        Flask backend
│   ├── api/                    REST blueprints
│   │   ├── auth_routes.py             register / login / logout / GET+PATCH me
│   │   │                              (display_name, avatar, password change)
│   │   ├── user_routes.py             GET /api/v1/users/<id>  (public profile)
│   │   ├── stream_routes.py           create/list/end streams; mint viewer tokens
│   │   ├── comment_routes.py          comment REST
│   │   ├── follow_routes.py
│   │   ├── gesture_routes.py          per-user gesture overrides + custom templates
│   │   ├── media_routes.py            content library (uploads, streaming)
│   │   ├── config_routes.py
│   │   ├── webhook_routes.py          LiveKit webhooks
│   │   ├── streamer_dashboard_routes.py    /streamer/<id>          (live dashboard HTML)
│   │   └── streamer_gestures_routes.py     /streamer/<id>/gestures (manage gestures HTML)
│   ├── sockets/                Socket.IO event handlers
│   │   ├── connection_events.py    connect / disconnect / join_room (kind-aware)
│   │   ├── social_events.py        comment_send / emote_send
│   │   ├── media_events.py         gesture_command_received (mute, end_stream, effects)
│   │   ├── streamer_events.py      streamer_authenticated → persists owner_identity
│   │   └── session.py              per-sid auth stash
│   ├── services/               LiveKit, stream lifecycle, storage, auth, exceptions
│   └── models/                 SQLAlchemy models
│       ├── user.py             User (api_key, display_name, avatar_media_id)
│       ├── stream.py           Stream (owner_identity stores user UUID, owner_display_name)
│       └── media.py            MediaItem (S3-backed uploads)
├── broadcaster/                Python worker, runs on host (or as .exe)
│   ├── __main__.py             entry point — tkinter login dialog, wires everything
│   ├── loop.py                 capture → detect → composite → publish loop
│   ├── publisher.py            LiveKit SDK wrapper (video + audio; mute via track.mute())
│   ├── client.py               Socket.IO client (gestures, recording, auth)
│   ├── detector.py             MediaPipe hand-landmarker + rule-based gesture mapping
│   ├── custom_classifier.py    k-NN matcher for recorded templates
│   ├── recording.py            recording session state machine
│   ├── tray.py                 system tray entry point (used by PyInstaller)
│   ├── api_client.py           REST client
│   ├── local_view.py           OpenCV preview overlays (comment scroll, HUD)
│   ├── effects.py              compositing effects burned into the published frame
│   └── broadcaster.spec        PyInstaller spec (platform-aware: win/mac/linux)
├── migrations/versions/        Alembic (PostgreSQL) migrations
├── docs/decisions/             Architecture decision records
├── docker-compose.yml          backend + LiveKit + Postgres + MinIO
├── livekit.yaml                LiveKit Server config
├── Dockerfile                  backend image
├── requirements.txt            backend Python deps
├── start.sh                    one-command launcher (compose up + broadcaster)
├── .env / .env.example         configuration (no API_KEY — obtained at runtime)
├── SETUP.md                    setup instructions (Windows + Ubuntu)
└── README.md                   this file
```

---

## Key API endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/auth/register` | — | Create account |
| POST | `/api/v1/auth/login` | — | Get API key |
| GET | `/api/v1/auth/me` | Bearer | Own profile + avatar_url |
| PATCH | `/api/v1/auth/me` | Bearer | Update display_name, avatar, password |
| GET | `/api/v1/users/<id>` | — | Public profile |
| POST | `/api/v1/streams` | Bearer (optional) | Create stream |
| POST | `/api/v1/streams/<id>/viewer-token` | — | Mint viewer token |
| GET | `/streamer/<id>` | — | Streamer dashboard HTML |

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Video transport | LiveKit (self-hosted WebRTC SFU) | Sub-second latency; full control. See [decision-001](docs/decisions/001-livekit-over-mux.md). |
| Backend | Flask + Flask-SocketIO (eventlet) | Same process serves REST and Socket.IO. |
| Database | PostgreSQL 16 | Alembic-managed migrations. |
| Object store | MinIO (S3-compatible) | For media uploads; runs in Docker. |
| Broadcaster | Python (OpenCV, MediaPipe, LiveKit SDK) | Runs on the host; packaged with PyInstaller. See [decision-003](docs/decisions/003-python-broadcaster-not-phone.md). |
| Gesture detection | MediaPipe Hands → rule-based + k-NN for custom | See [decision-004](docs/decisions/004-knn-gesture-templates.md). |
| Effects compositing | OpenCV burn-in on broadcaster | All viewers see identical effects. See [decision-002](docs/decisions/002-broadcaster-burn-in-compositing.md). |

---

## Building the broadcaster

PyInstaller must be run on the target platform (no cross-compilation).

**Windows**
```powershell
cd broadcaster
pyinstaller broadcaster.spec
# output: dist/Broadcaster.exe
```

**Ubuntu**
```bash
sudo apt-get install -y python3-tk portaudio19-dev libportaudio2
cd broadcaster
pyinstaller broadcaster.spec
# output: dist/Broadcaster
```

**macOS**
```bash
brew install portaudio
cd broadcaster
pyinstaller broadcaster.spec
# output: dist/Broadcaster
```

---

## How the two repos connect

- **Backend ↔ FE**: REST on `:5001` (`/api/v1/…`) + Socket.IO on the
  same port. FE reads `API_BASE` from its `.env` at build time.
- **Backend ↔ Broadcaster**: same Flask process. Broadcaster is a
  Socket.IO client + REST consumer; authenticates via API key in RAM.
- **Streamer dashboard**: HTML served by the backend at
  `/streamer/<stream_id>`. Auto-opened by the broadcaster with the
  API key pre-loaded via URL hash so no second login is needed.

---

## Useful files for newcomers

- **[SETUP.md](SETUP.md)** — get a working demo on a fresh machine.
- **[docs/decisions/](docs/decisions/)** — why the architecture is shaped this way.
- **[../PROBLEMS_AND_SOLUTIONS.md](../PROBLEMS_AND_SOLUTIONS.md)** — every gotcha we hit, with root cause + fix.
