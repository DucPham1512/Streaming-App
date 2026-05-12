# VSR Livestream — Gesture Demo Setup & Usage

End-to-end guide for running the streaming backend, the React Native viewer app, and the Python gesture-recognition demo together.

---

## Repository Layout

This project lives in **two separate git repositories** that talk to each other over HTTP and Socket.IO:

| Repo | Purpose |
|---|---|
| `Streaming-App/` (this repo) | Flask backend, Socket.IO server, Mux integration, `gesture_demo/` Python streamer client |
| `FE-Streaming-app/` | Expo / React Native app for streamers and viewers |

Clone them side-by-side:

```bash
mkdir streaming && cd streaming
git clone <backend-repo-url> Streaming-App
git clone <frontend-repo-url> FE-Streaming-app
```

---

## Prerequisites

- **Python 3.10+** (the gesture demo uses `str | None` syntax)
- **Node.js 18+** and **npm**
- **Expo CLI** (`npm install -g expo-cli` or use `npx expo` directly)
- **OBS Studio** (for pushing webcam video to Mux)
- **A Mux account** with an environment, plus webhooks pointed at your backend via **ngrok** (or any public tunnel)
- **A webcam** (the demo uses device index 0 by default)
- **The phone and your laptop must be on the same Wi-Fi** so the phone can reach the backend at your LAN IP

---

## 1. Backend Setup (`Streaming-App`)

```bash
cd Streaming-App
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env` in the backend root with at minimum:

```
MUX_TOKEN_ID=your_mux_token_id
MUX_TOKEN_SECRET=your_mux_token_secret
MUX_WEBHOOK_SECRET=your_mux_webhook_secret
DATABASE_URL=sqlite:///dev.db   # or your Postgres URL
```

Initialize the database and run the server:

```bash
flask --app run db upgrade        # apply migrations
python run.py                     # listens on http://0.0.0.0:5001
```

Expose port 5001 publicly for Mux webhooks:

```bash
ngrok http 5001
```

Then in the Mux dashboard, set the webhook URL to `<your-ngrok-url>/api/v1/webhooks/mux`.

---

## 2. Frontend Setup (`FE-Streaming-app`)

```bash
cd FE-Streaming-app
npm install
```

Find your laptop's LAN IP:

```bash
ip addr show | grep "inet "       # Linux
ipconfig getifaddr en0            # macOS
```

Create `.env.local`:

```
EXPO_PUBLIC_API_URL=http://<your-lan-ip>:5001
API_BASE=http://<your-lan-ip>:5001
SOCKET_URL=http://<your-lan-ip>:5001
```

Start Expo:

```bash
npx expo start --clear
```

Open **Expo Go** on your phone and scan the QR code.

---

## 3. Gesture Demo Setup (`Streaming-App/gesture_demo/`)

This is a standalone Python tool that watches your webcam, classifies hand gestures with MediaPipe, and emits commands to the backend over Socket.IO.

```bash
cd Streaming-App/gesture_demo
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `gesture_demo/.env`:

```
SOCKET_URL=http://localhost:5001
API_BASE=http://localhost:5001
API_KEY=blank_api_demo_only
```

(If you're running the demo from a different machine than the backend, use the LAN IP instead of `localhost`.)

The first run downloads MediaPipe's hand landmark model (~1 MB) into the folder automatically.

---

## 4. OBS Setup

Add **one** scene with **one** source — your **webcam, full-frame**. The gesture system assumes OBS captures the same image MediaPipe sees; positional effects rely on this.

Set the streaming output to **Custom RTMP**:

- Server: `rtmp://global-live.mux.com:5222/app`
- Stream Key: copied from the `stream_key` returned when you create a stream in the app (see step 5).

---

## 5. End-to-End Workflow

### A. Start everything

In separate terminals:

```bash
# Terminal 1: backend
cd Streaming-App && python run.py

# Terminal 2: ngrok
ngrok http 5001

# Terminal 3: Expo dev server
cd FE-Streaming-app && npx expo start
```

### B. Go live

1. Open the Expo app on your **streamer phone**, log in.
2. Go to the **Go Live** tab → enter a title → **Create Stream**. The app shows your RTMP stream key.
3. Paste the stream key into OBS, click **Start Streaming**.
4. Wait until Mux fires the `video.live_stream.active` webhook (backend log shows `Stream <uuid> marked active`).

### C. Open as a viewer

5. On a **second phone** (or the same phone in viewer mode), open the stream from the feed. The video appears with ~5–22 s delay (HLS buffering).

### D. Run the gesture demo

```bash
cd Streaming-App/gesture_demo
python demo.py
```

`--stream-id` is **optional** — the demo auto-discovers the most recent active stream via `GET /api/v1/streams`. Override with `--stream-id <uuid>` if you need a specific one. Use `--camera 2` if your webcam is on a non-default device.

The OpenCV window shows your webcam with a hand skeleton overlay. The HUD top-right shows a green **LIVE** dot when Socket.IO is connected.

---

## 6. Gesture Reference

| Gesture | What to do | Command | Viewer effect |
|---|---|---|---|
| 🤚 Open Palm | All five fingers extended | `mute_toggle` | Mute icon overlay; mutes audio locally |
| ✊ Fist | Curl all five fingers tight, **hold ~3 s** | `end_stream` | Ends the stream in the database |
| 👍 Thumbs Up | Only thumb extended, others curled | `like_stream` | Yellow 👍 badge pops at the streamer's thumb position |
| ✌️ Peace | Index + middle extended, others curled | `entertainment_confetti` | Confetti bursts from the fingertips |
| ❤️ Finger Heart | Thumb tip touches a bent index | `entertainment_heart` | Hearts float up from the fingertips |
| 🤙 ILY / Shaka | Thumb + index + pinky extended | `entertainment_fireworks` | Fireworks burst around the hand |

**Timing notes**

- Each gesture must be **held ~0.5 s** (15 frames) before it fires (stabilizer).
- Control commands (`mute_toggle`, `end_stream`) broadcast **immediately**.
- Entertainment effects are buffered server-side by `EFFECT_BROADCAST_DELAY_SECONDS` (default 22 s) so they line up with the delayed HLS video on the viewer's phone. Tune this in `app/sockets/media_events.py` if your actual Mux delay differs.

---

## 7. Testing

### Manual end-to-end test

After Go Live, on the viewer phone:

1. **Mute / Open palm** — viewer's audio cuts and a mute badge appears.
2. **Thumbs up at the left edge of the camera** — wait the delay, then a yellow LIKE badge appears at the left side of the viewer's video (not centered).
3. **Finger heart at the top of the frame** — hearts emerge near the top and float up.
4. **Peace sign in different corners** — confetti spawns from the matching corner.
5. **Fist held 3 s** — countdown completes, REST call ends the stream, viewer is dropped.

### Logs to watch when debugging

- **Flask terminal**: `Client X joined room Y` (phone joined room), `Gesture '...' broadcast to room ... (N members)` (N = how many viewers will receive it).
- **Python demo terminal**: `[GestureClient] SENT ... anchor=...` confirms emission with coords.
- **Expo terminal**: `[stream-player] stream_state_update {...}` shows incoming events with anchor data on the phone.

### Backend unit tests

```bash
cd Streaming-App
pytest
```

---

## 8. Common Issues

| Symptom | Likely cause |
|---|---|
| Phone can't load feed; "Network request failed" | `EXPO_PUBLIC_API_URL` points to `localhost` (which means the phone itself) or wrong LAN IP. Edit `.env.local`, run `npx expo start --clear`. |
| Phone reaches `GET /api/v1/streams` but no effects appear | Viewer's `stream-player` didn't join the Socket.IO room. Check the Flask log for `Client X joined room Y` when opening the stream. |
| Python demo says SENT but backend logs nothing | Wrong stream-id. The Python tool uses the **backend UUID** (`stream.id`), not Mux's `live_stream_id`. Omit `--stream-id` to let the demo auto-discover. |
| `mediapipe has no attribute 'solutions'` | Old MediaPipe API. Use `mediapipe==0.10.35` per the requirements file. |
| Effect appears at the wrong place on viewer | The Mux delay constant is mistuned, OR OBS is capturing more than just the webcam. The plan assumes OBS = webcam, full-frame, no other scene elements. |

---

## 9. Repository Map

```
Streaming-App/
├── app/
│   ├── api/                  # REST endpoints (streams, auth, gestures, ...)
│   ├── sockets/              # Socket.IO handlers
│   │   ├── connection_events.py    # join_room / leave_room
│   │   └── media_events.py         # gesture_command_received, audio chunks
│   ├── models/               # SQLAlchemy models
│   └── services/             # stream_manager, stt_engine, mux client
├── gesture_demo/
│   ├── demo.py               # entry point — capture loop + HUD
│   ├── detector.py           # MediaPipe + classification + anchor selection
│   ├── client.py             # Socket.IO client with cooldowns
│   ├── effects.py            # OpenCV overlay effects (origin-aware)
│   └── requirements.txt
├── migrations/
└── run.py

FE-Streaming-app/
├── app/                      # Expo Router pages
├── components/
│   └── stream-player.tsx     # video + overlays + socket listener
├── features/
│   ├── gesture/
│   │   ├── components/       # confetti-effect, heart-burst-effect, like-effect, mute-indicator
│   │   └── lib/cover-coords.ts  # contentFit="cover" coord mapping
│   └── social/               # comments, hearts, follow
└── lib/
    ├── api/                  # client, realtime (socket provider), auth, ...
    └── config.ts             # API_BASE, SOCKET_URL from env
```
