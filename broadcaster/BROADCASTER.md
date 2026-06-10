# Broadcaster — laptop-side streaming process

The broadcaster captures your laptop's camera + microphone, runs MediaPipe
gesture recognition, composites visual effects into the video, and publishes
to LiveKit. It is **not** part of the docker-compose stack — see
[../docs/decisions/003-python-broadcaster-not-phone.md](../docs/decisions/003-python-broadcaster-not-phone.md)
for why (camera + audio + display access through Docker is brittle).

---

## Running the pre-built binary

The broadcaster is distributed as a single executable built with PyInstaller.
Put `Broadcaster.exe` (Windows) or `Broadcaster` (macOS/Linux) in any folder
alongside a `.env` file (see below), then run it.

On **Windows**: double-click `Broadcaster.exe`, or from a terminal:
```powershell
.\Broadcaster.exe
```

On **macOS / Linux**:
```bash
chmod +x ./Broadcaster
./Broadcaster
```

### Login dialog

On startup, a dialog appears:

- Enter your **username and password** and click **Sign in**, or
- Click **Continue as Guest** to stream without an account.

Signing in loads your personal gesture overrides and custom templates.
Guest mode uses the built-in gesture defaults and streams anonymously.

The API key obtained at login is stored **in RAM only** — it is never
written to disk. Closing the broadcaster clears it.

### Streamer dashboard

After login (or guest skip), the broadcaster creates a stream and
auto-opens the **streamer dashboard** in your default browser. If you
signed in, the dashboard is pre-authenticated as the same account —
no second login required. If you continued as guest, the dashboard shows
an optional sign-in modal.

---

## Single-laptop demo (everything on one machine)

```bash
cd Streaming-App
./start.sh
```

`start.sh` brings up the docker-compose stack (backend, LiveKit, Postgres,
MinIO) **and** launches the broadcaster on the host via `python -m broadcaster`.
One command — done.

---

## Two-laptop demo (a second streamer joins)

> Goal: Laptop A hosts the backend stack + its own broadcaster. Laptop B
> runs **only** a second broadcaster. Viewers see both streams in the
> swipe feed.

On **Laptop A** (the host): run `./start.sh` as above. Note its LAN IP,
e.g. `192.168.1.42`. Ensure the firewall allows inbound on:
- `5001` (Flask backend)
- `7880` / `7881` (LiveKit signaling)
- `50000–60000/udp` (LiveKit media)

On **Laptop B** (second streamer), copy `Broadcaster.exe` / `Broadcaster`
and create a `.env` file next to it:

```env
API_BASE=http://192.168.1.42:5001
SOCKET_URL=http://192.168.1.42:5001
```

Run the binary. The login dialog appears — sign in or continue as guest.
Laptop B creates its own `Stream` row on Laptop A's Flask, receives a
publisher token, opens its camera + mic, and starts publishing. Both
streams appear in the viewer swipe feed.

Alternatively, run from source:

```bash
cd Streaming-App
python -m venv .venv && source .venv/bin/activate
pip install -r broadcaster/requirements.txt
python -m broadcaster \
    --api-base   http://192.168.1.42:5001 \
    --socket-url http://192.168.1.42:5001
```

---

## CLI flags reference

```
python -m broadcaster --help
```

| Flag | Default | Notes |
|---|---|---|
| `--camera N` | `BROADCAST_CAMERA_INDEX` env, `0` | `cv2.VideoCapture` device index |
| `--title T` | `"Live now"` | Initial stream title (editable via PATCH) |
| `--width W` | `1280` | Published frame width |
| `--height H` | `720` | Published frame height |
| `--no-audio` | off | Skip microphone capture |
| `--no-preview` | off | Headless: no cv2.imshow window |
| `--no-dashboard` | off | Don't auto-open browser tab |
| `--api-base URL` | `API_BASE` env, `http://localhost:5001` | Backend REST URL |
| `--socket-url U` | `SOCKET_URL` env, falls back to `--api-base` | Backend Socket.IO URL |
| `--api-key K` | `API_KEY` env | Skip the login dialog (for scripting) |
| `--log-level L` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

CLI flags override env vars. Env vars are loaded from `.env` in the
working directory (or `broadcaster/.env` when running from source).

> **Note:** `API_KEY` is intentionally not set in the distributed `.env`.
> The login dialog is the intended way to authenticate. Set `API_KEY`
> only for automated/CI use where the dialog is not available.

---

## Local controls (OpenCV preview window)

| Key | Action |
|-----|--------|
| `Q` | Quit — ends the stream and exits |
| `M` | Toggle mute (stops sending audio to LiveKit; notifies viewers) |
| `C` | Clear all in-flight visual effects |
| `R` | Start recording a custom gesture (type name in terminal) |
| `E` | Erase the most recently recorded template |
| `L` | List current gesture templates to the terminal |

Gesture-driven controls (no key needed):

| Gesture | Action |
|---|---|
| 🤚 Open palm | `mute_toggle` — mutes/unmutes mic at the WebRTC track level |
| ✊ Fist (hold 3s) | `end_stream` — ends the stream gracefully |
| 👍 Thumbs up | `like_stream` — like effect burned into video |
| ✌️ Peace | `entertainment_confetti` |
| ❤️ Finger heart | `entertainment_heart` |
| 🤙 ILY / Shaka | `entertainment_fireworks` |

---

## Building the binary from source

PyInstaller must run on the target platform (no cross-compilation).

**Windows** (from `broadcaster/` folder):
```powershell
pyinstaller broadcaster.spec
# output: dist/Broadcaster.exe
```

**Ubuntu**:
```bash
sudo apt-get install -y python3-tk portaudio19-dev libportaudio2
pyinstaller broadcaster.spec
# output: dist/Broadcaster
```

**macOS**:
```bash
brew install portaudio
pyinstaller broadcaster.spec
# output: dist/Broadcaster
```

After a code change, close any running `Broadcaster.exe` first (it locks
the `dist/` folder on Windows), then run `pyinstaller broadcaster.spec`.

---

## Troubleshooting

- **"Cannot open camera N"** — try `--camera 0`, `--camera 1`, etc. On
  Linux, `ls /dev/video*` lists available devices.
- **"Failed to create stream: Connection refused"** — backend isn't up, or
  `--api-base` / `API_BASE` points at the wrong host/port.
- **No mic, video still works** — expected. If PortAudio fails to open
  the mic, the publisher logs a warning and continues video-only. Install
  `libportaudio2` (Linux) or `brew install portaudio` (macOS) if you
  need audio.
- **Login failed "login and password are required"** — make sure both
  fields are non-empty before clicking Sign in.
- **Two broadcasters visible but only one in the feed** — check
  `GET /api/v1/streams` on the host; both should show `status="active"`.
  If one is stuck on `"idle"`, the LiveKit `track_published` webhook
  didn't reach the backend — check the firewall on the host laptop.
- **PermissionError on rebuild** — the old `Broadcaster.exe` is still
  running. Close it, then delete `build/` and `dist/` before rebuilding.
