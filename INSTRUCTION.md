# VSR Livestream — Setup & Usage

End-to-end guide for running the streaming backend (this repo) together
with the React Native viewer app ([../FE-Streaming-app/](../FE-Streaming-app/)).

---

## Repository layout

Two side-by-side repos:

| Repo | Purpose |
|---|---|
| `Streaming-App/` (this one) | Flask backend, Socket.IO, LiveKit-publishing broadcaster |
| `FE-Streaming-app/`         | Expo / React Native app for viewers |

Clone them side-by-side:

```bash
mkdir streaming && cd streaming
git clone <backend-repo-url>  Streaming-App
git clone <frontend-repo-url> FE-Streaming-app
```

---

## Prerequisites

- **Docker** and **Docker Compose** (for the backend stack)
- **Python 3.10+** and a venv (for the host-side broadcaster)
- **Node.js 18+** and **npm** (for the FE)
- A **webcam** and **microphone** on the broadcaster laptop
- All phones / viewer laptops on the **same Wi-Fi** as the host laptop

System packages on Linux for the broadcaster:

```bash
sudo apt install libportaudio2 libgl1 libglib2.0-0
```

---

## 1. Backend stack

```bash
cd Streaming-App
cp .env.example .env                    # then fill in LIVEKIT_API_SECRET
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r broadcaster/requirements.txt
./start.sh
```

`start.sh` brings up `postgres + livekit + backend + minio` via
docker-compose, waits for the backend's `/api/v1/streams` to respond,
and execs `python -m broadcaster` on the host so the camera, mic, and
preview window all work natively.

Quit with `q` in the OpenCV preview window (cleanly ends the stream),
or Ctrl-C in the terminal.

---

## 2. Frontend

```bash
cd FE-Streaming-app
cp .env.example .env                    # set API_BASE to your laptop's LAN IP
npm install
npx expo start
```

Three platform paths from one codebase:

- **Web** — `npx expo start --web` opens `http://<laptop-ip>:8081`. No
  install. Easiest viewer path.
- **iOS / Android dev client** — build once with `eas build --profile
  development --platform android|ios`, install the resulting APK / IPA,
  then daily workflow is `npx expo start` + scan QR. See
  [../FE-Streaming-app/README.md](../FE-Streaming-app/README.md).

The FE is viewer-only: there is no "Go Live" button that captures
the phone's camera. Streaming is initiated from the broadcaster
laptop (Step 1).

---

## 3. End-to-end demo flow

1. **Host laptop:** `./start.sh` in `Streaming-App/`. Camera light
   comes on, OpenCV preview opens.
2. **Viewer phones / laptops:** open `http://<host-laptop-ip>:8081`
   (or the dev-client app). The stream appears in the swipe feed.
3. **Comments** typed in the FE pop up on the right edge of the
   broadcaster's OpenCV window in real time.
4. **Gestures:** open palm = mute, peace = confetti, fist (hold 3s) =
   end stream, etc. Effects are baked into the published video so all
   viewers see them simultaneously.

For **two streamers at once** (the second laptop sets up as a remote
broadcaster pointing at the first), see
[broadcaster/BROADCASTER.md](broadcaster/BROADCASTER.md).

---

## 4. Gesture customization

Each user can:

- **Remap a built-in gesture** to a different action (e.g. peace →
  fireworks instead of confetti). Pick from the action picker in the
  **Gesture Library** screen in the FE.
- **Record a new custom gesture** by pressing `R` in the broadcaster's
  OpenCV preview window: type a name, hold the pose for the on-screen
  countdown, captures 10 frames. Then open the Gesture Library and
  assign an action to the new "Unmapped" entry.

Other broadcaster hotkeys: `E` erases the most recently recorded
template, `L` prints the user's current templates to the terminal,
`C` clears in-flight visual effects, `M` toggles mute, `Q` quits.

---

## 5. Tests

```bash
source .venv/bin/activate
pytest -q
```

Currently 118 tests across REST routes, sockets, auth, media uploads,
the custom-gesture classifier, and the recording session state machine.

---

## 6. Common issues

- **"Cannot open camera N"** — try a different `--camera` index
  (`python -m broadcaster --camera 0`). On Linux `ls /dev/video*` lists
  the device files.
- **"Failed to create stream: Connection refused"** — backend isn't up
  yet. `start.sh` waits for it, but if you ran `python -m broadcaster`
  by hand, check `curl http://localhost:5001/api/v1/streams` first.
- **No sound** — broadcaster logs "Audio setup failed; continuing with
  video-only stream" when PortAudio isn't installed. Install
  `libportaudio2` (Linux) and re-run.
- **Phone can't reach backend** — your phone's `API_BASE` must be the
  laptop's LAN IP (not `localhost`). Confirm both are on the same Wi-Fi
  and the firewall allows inbound on `5001`, `7880`, `7881`, `50000–60000/udp`.
- **Gesture not firing** — press `L` in the broadcaster window to list
  current templates; check that the action isn't `unmapped`. If it is,
  open the FE Gesture Library and assign one.

---

## 7. Where to read more

- **Why LiveKit, why burn-in compositing, why laptop broadcaster, why
  k-NN gestures:** [docs/decisions/](docs/decisions/) (four ~1-page
  ADRs).
- **Two-laptop broadcaster setup + CLI reference + per-key shortcut
  table:** [broadcaster/BROADCASTER.md](broadcaster/BROADCASTER.md).
- **Backend architecture (routes, models, services):** [README.md](README.md).
- **Frontend setup + dev-client build + web export:**
  [../FE-Streaming-app/README.md](../FE-Streaming-app/README.md).
- **Edge cases and bugs you hit so the next person doesn't:**
  `../PROBLEMS_AND_SOLUTIONS.md` (top-level of the streaming workspace).
