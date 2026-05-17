# Broadcaster — laptop-side streaming process

The broadcaster captures your laptop's camera + microphone, runs MediaPipe
gesture recognition, composites visual effects, and publishes to LiveKit.
It is **not** part of the docker-compose stack — see
[../docs/decisions/003-python-broadcaster-not-phone.md](../docs/decisions/003-python-broadcaster-not-phone.md)
for why (camera + audio + X11 passthrough through Docker is brittle).

There are two ways to run it:

---

## Single-laptop demo (everything on one machine)

```bash
cd Streaming-App
./start.sh
```

That script brings up the docker-compose stack (backend, LiveKit, postgres,
minio) **and** launches the broadcaster on the host. One command — done.

Viewers connect from phones on the same Wi-Fi using the Expo dev client,
or from any browser at `http://<this-laptop-LAN-IP>:8081`.

---

## Two-laptop demo (a second streamer joins)

> Goal: Laptop A hosts the backend stack + its own broadcaster, Laptop B
> runs **only** a second broadcaster. Viewers see both streams in the
> swipe feed and switch with a swipe up/down (TikTok-style).

On **Laptop A** (the host): `./start.sh` as above. Note its LAN IP, e.g.
`192.168.1.42`. Make sure your firewall allows incoming connections on:
- `5001` (Flask backend)
- `7880` / `7881` (LiveKit signaling + TCP fallback)
- `50000–60000/udp` (LiveKit media)
- `5432` and `9000` should stay LAN-only or off the network entirely.

On **Laptop B** (the second streamer):

```bash
git clone <this-repo>
cd Streaming-App
python -m venv .venv
source .venv/bin/activate

# Slim subset of deps — no Flask/SQLAlchemy/MinIO, just the broadcaster's needs.
pip install -r broadcaster/requirements.txt

# Linux runtime: sudo apt install libportaudio2 libgl1 libglib2.0-0
# (libportaudio2 = sounddevice's PortAudio backend; the GL/glib libs are
#  what opencv-python imports for cv2.imshow.)

python -m broadcaster \
    --api-base   http://192.168.1.42:5001 \
    --socket-url http://192.168.1.42:5001 \
    --camera     0
```

That's it. Laptop B creates its own `Stream` row via `POST /api/v1/streams`
on Laptop A's Flask, receives a publisher token for a fresh LiveKit room,
opens its camera + mic, and starts publishing. The two streams appear side
by side in the swipe feed.

---

## CLI flags reference

```text
python -m broadcaster --help
```

| Flag             | Default                          | Notes |
|------------------|----------------------------------|-------|
| `--camera N`     | `BROADCAST_CAMERA_INDEX` env, 0  | `cv2.VideoCapture` device index |
| `--title T`      | "Live now"                       | Initial stream title (editable via PATCH) |
| `--width W`      | 1280                             | Published frame width |
| `--height H`     | 720                              | Published frame height |
| `--no-audio`     | off                              | Skip microphone capture |
| `--no-preview`   | off                              | Headless: no cv2.imshow window |
| `--api-base URL` | `API_BASE` env, `http://localhost:5001` | Backend REST URL |
| `--socket-url U` | `SOCKET_URL` env, falls back to `--api-base` | Backend Socket.IO URL |
| `--api-key K`    | `API_KEY` env                    | Bearer token (optional — for when routes get auth-gated) |
| `--log-level L`  | INFO                             | DEBUG / INFO / WARNING / ERROR |

CLI flags always override env vars. Env vars are loaded from
`broadcaster/.env` (gitignored) if present.

---

## Local controls (OpenCV preview)

When the cv2.imshow window has focus:

| Key | Action |
|-----|--------|
| Q   | Quit (also POSTs `/streams/<id>/end`) |
| M   | Toggle local mute display |
| R   | Clear active visual effects |

Plus the gesture-driven controls (open palm = mute, peace = confetti,
fist-hold 3s = end stream, etc. — see `broadcaster/detector.py`).

---

## Troubleshooting

- **"Cannot open camera N"** → try a different `--camera` index. On Linux,
  `ls /dev/video*` lists what's available.
- **"Failed to create stream: Connection refused"** → backend isn't up yet,
  or `--api-base` points at the wrong host/port.
- **No mic, video still works** → expected. If `sounddevice` / PortAudio
  fails to open the mic, the publisher logs a warning and continues
  video-only.
- **"Error 28: No space" or libGL missing** → on a fresh Linux laptop install
  `libgl1 libglib2.0-0 libportaudio2` (opencv + sounddevice deps).
- **Two broadcasters publishing but I only see one in the feed** → check
  `GET /api/v1/streams` on Laptop A; both should appear with `status="active"`.
  If one is stuck on `status="idle"`, its LiveKit `track_published` webhook
  didn't reach the backend (firewall on Laptop A blocking inbound from
  LiveKit container? Confirm `livekit.yaml` webhook URL is reachable from
  inside the `livekit` container — it points at `http://backend:5001`).
