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
   │  (Python)      │ ───────────────► │          │    can't load WebRTC)
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
   │ • streamer dash  │        └──────────┘     store for VOD uploads)
   │   at /streamer/  │
   └──────────────────┘
```

Everything except the broadcaster runs in Docker. The broadcaster runs
on the host because it needs direct access to the camera, microphone,
and X11 for the preview window — fiddly through Docker.

---

## What the streamer experiences

1. Run `./start.sh` on the laptop.
2. A browser tab auto-opens to the **streamer dashboard** — their own
   stream's video on the left, comments/viewer count/hearts on the right.
3. Sign in or sign up in the dashboard's modal. That **single sign-in
   identifies them everywhere**: the dashboard, the broadcaster (which
   reloads their gesture overrides + custom templates without
   restarting), and the gestures management page.
4. Click "Manage gestures ↗" to open a sibling page where they can
   remap built-in gestures (peace, thumbs-up, fist, etc.) to actions
   (heart burst, confetti, end stream…), or click "● Record new" to
   capture a custom gesture (3s countdown, then 10 frames of hand
   landmarks → k-NN template).
5. Gesture detection runs locally in the broadcaster; viewers receive
   the effect via Socket.IO and see it overlaid on the video.

---

## What viewers experience

- Open the FE app (iOS dev client, Android dev client, or just a web
  browser pointed at the laptop's LAN IP), pick a stream, watch.
- Chat in the comment panel; tap the heart button.
- See streamer-triggered effects (hearts, confetti, mute badge)
  composited live over the video.

---

## Repo layout

```
Streaming-App/
├── app/                        Flask backend
│   ├── api/                    REST blueprints
│   │   ├── auth_routes.py             register/login/logout/me
│   │   ├── stream_routes.py           create/list/end streams; mint viewer tokens
│   │   ├── comment_routes.py          comment REST
│   │   ├── follow_routes.py
│   │   ├── gesture_routes.py          per-user gesture overrides + custom templates
│   │   ├── media_routes.py            content library (uploads)
│   │   ├── config_routes.py
│   │   ├── webhook_routes.py          LiveKit webhooks
│   │   ├── streamer_dashboard_routes.py    /streamer/<id>          (live dashboard HTML)
│   │   └── streamer_gestures_routes.py     /streamer/<id>/gestures (manage gestures HTML)
│   ├── sockets/                Socket.IO event handlers
│   │   ├── connection_events.py    connect / disconnect / join_room (kind-aware)
│   │   ├── social_events.py        comment_send / emote_send
│   │   ├── media_events.py         gesture_command_received
│   │   ├── streamer_events.py      recording_start / streamer_authenticated
│   │   └── session.py              per-sid auth stash
│   ├── services/               LiveKit, stream lifecycle, storage, auth, exceptions
│   └── models/                 SQLAlchemy models
├── broadcaster/                Python worker, runs on host
│   ├── __main__.py             entry point — wires everything together
│   ├── loop.py                 capture → detect → composite → publish loop
│   ├── publisher.py            LiveKit Python SDK wrapper
│   ├── client.py               Socket.IO client (gestures, recording, auth)
│   ├── detector.py             MediaPipe hand-landmarker + rule-based gestures
│   ├── custom_classifier.py    k-NN matcher for recorded templates
│   ├── recording.py            recording session state machine
│   ├── api_client.py           tiny REST client
│   ├── local_view.py           OpenCV preview overlays
│   └── effects.py              compositing effects (burned into video)
├── migrations/versions/        Alembic (PostgreSQL) migrations
├── docs/decisions/             Architecture decision records
├── docker-compose.yml          backend + LiveKit + Postgres + MinIO
├── livekit.yaml                LiveKit Server config (UDP range, etc.)
├── Dockerfile                  backend image
├── requirements.txt            backend Python deps
├── start.sh                    one-command launcher (compose up + broadcaster)
├── .env / .env.example         configuration
├── SETUP.md                    setup instructions for new machines (Windows + Ubuntu)
└── README.md                   this file
```

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Video transport | LiveKit (self-hosted WebRTC SFU) | Sub-second latency; full control. See [decision-001](docs/decisions/001-livekit-over-mux.md). |
| Backend | Flask + Flask-SocketIO (eventlet) | Same process serves REST and Socket.IO. |
| Database | PostgreSQL 16 | Alembic-managed migrations. |
| Object store | MinIO (S3-compatible) | For VOD uploads; runs locally. |
| Broadcaster | Python (OpenCV, MediaPipe, LiveKit SDK) | Runs on the host. See [decision-003](docs/decisions/003-python-broadcaster-not-phone.md). |
| Gesture detection | MediaPipe Hands → rule-based + k-NN for custom | See [decision-004](docs/decisions/004-knn-gesture-templates.md). |
| Effects compositing | OpenCV burn-in on the broadcaster | All viewers see identical effects, no per-client divergence. See [decision-002](docs/decisions/002-broadcaster-burn-in-compositing.md). |

---

## How the two repos connect

- **Backend ↔ FE**: REST on `:5001` (`/api/v1/…`) + Socket.IO on the
  same port. FE reads `API_BASE` / `SOCKET_URL` from its env at build
  time (see FE README).
- **Backend ↔ Broadcaster**: same Flask process. Broadcaster is just
  another Socket.IO client + REST consumer.
- **Streamer dashboard**: HTML served by the backend at
  `/streamer/<stream_id>`. Auto-opened by the broadcaster when a
  stream is created.

The FE has nothing to do with streaming *out* — it's viewer-only. All
streamer tooling lives in the backend.

---

## Useful files for newcomers

- **[SETUP.md](SETUP.md)** — get a working demo on a fresh laptop
  (Windows or Ubuntu).
- **[broadcaster/BROADCASTER.md](broadcaster/BROADCASTER.md)** —
  what the laptop-side process does and how to run a second one for a
  multi-streamer demo.
- **[docs/decisions/](docs/decisions/)** — why the architecture is
  shaped this way.
- **[../PROBLEMS_AND_SOLUTIONS.md](../PROBLEMS_AND_SOLUTIONS.md)** —
  every gotcha we hit while building this, with root cause + fix.
