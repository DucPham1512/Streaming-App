# Setup guide — get the VSR Streaming App running on a fresh machine

This walks a new teammate through every step to demo the app on
**Ubuntu** or **Windows**, on their own laptop, with their own phone
as a viewer. It assumes you have the laptop's camera + microphone.

If you only want to **watch** an existing stream someone else is hosting,
skip to the [Viewer-only setup](#viewer-only-setup) section near the end.

---

## TL;DR

```
1.  Clone both repos                (Streaming-App + FE-Streaming-app)
2.  Install prerequisites           (Docker, Node, Python, apt libs)
3.  Configure .env files            (one in each repo)
4.  Backend:    cd Streaming-App && ./start.sh
5.  Frontend:   cd FE-Streaming-app && npm install && npx expo start --web
6.  Open browser to localhost:8081 (viewer) and the dashboard URL the
    broadcaster auto-opens.
```

The rest of this file is the long version.

---

## 0. Prerequisites at a glance

| Tool | Min version | Used by |
|---|---|---|
| Git | any | Cloning |
| Docker Engine + Docker Compose v2 | 20.10+ | Backend stack |
| Python | 3.11+ | Broadcaster |
| Node.js | **20 LTS** (NOT 18) | Frontend |
| npm | 10+ | Frontend |

Plus a few **OS-level libraries** for the broadcaster:
- Ubuntu/Debian: `libportaudio2 libgl1 libglib2.0-0`
- Windows: the broadcaster needs a different setup — see the
  Windows section below.

---

## 1. Clone both repos

These are **two separate repos** sitting side by side. Set up a parent
folder and clone both into it:

```bash
mkdir streaming-app && cd streaming-app
git clone <Streaming-App git URL> Streaming-App
git clone <FE-Streaming-app git URL> FE-Streaming-app
```

End state:

```
streaming-app/
├── Streaming-App/         (backend + broadcaster — this repo)
└── FE-Streaming-app/      (Expo viewer app)
```

The README and code in both repos use relative paths assuming this
layout (e.g. `../FE-Streaming-app/`). Keep them as siblings.

---

## 2. Install prerequisites

### 2A. Ubuntu (24.04 tested)

```bash
# Native Docker Engine (NOT Docker Desktop — Desktop's VM breaks LiveKit's
# host networking on Linux; see PROBLEMS_AND_SOLUTIONS.md #26).
sudo apt update
sudo apt install -y docker.io docker-compose-plugin

# Allow your user to run docker without sudo.
sudo usermod -aG docker $USER
# IMPORTANT: log out and back in (or reboot) for the new group to take effect.
# `newgrp docker` works as a one-shell workaround but doesn't persist.

# Python + system libs the broadcaster needs.
sudo apt install -y python3 python3-pip python3-venv \
                    libportaudio2 libgl1 libglib2.0-0

# Node 20 via nvm (Ubuntu's apt nodejs is too old).
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
# Reload shell (or open a new terminal):
exec $SHELL
nvm install 20
nvm alias default 20
```

**Verify**:
```bash
docker info | grep "Operating System"   # should say Ubuntu, NOT Docker Desktop
node --version                          # should print v20.x
python3 --version                       # 3.11+
```

If `docker info` says `Operating System: Docker Desktop`, switch contexts:
```bash
docker context use default
```

### 2B. Windows 10/11

> Windows is harder because the broadcaster needs camera + microphone +
> X11-style preview window access, plus low-level audio (PortAudio).
> Two paths:
> - **Easy path:** WSL2 with Ubuntu — works for the backend stack and
>   web viewer, but the broadcaster's camera access from WSL2 is unreliable.
>   Use this if you only want to view streams or run the backend for a
>   teammate to stream against.
> - **Full path:** native Windows — needed if you'll stream from this
>   machine.

#### 2B-i. Common (both paths)

Install:
- **[Docker Desktop for Windows](https://www.docker.com/products/docker-desktop)**
  — required on Windows. (On Linux we avoid Desktop, but on Windows it's
  the only sane way to get Docker.) Enable WSL2 integration during setup.
- **[Node.js 20 LTS](https://nodejs.org/)** — Windows installer.
- **[Git for Windows](https://git-scm.com/download/win)**.
- **[Python 3.11+](https://www.python.org/downloads/windows/)** — during
  install, check "Add python.exe to PATH".

#### 2B-ii. Easy path — backend + viewer in WSL2

```powershell
# Open PowerShell as Administrator (one-time)
wsl --install -d Ubuntu-24.04
```

Restart, finish the Ubuntu user setup, then **inside the Ubuntu shell**
follow [Section 2A](#2a-ubuntu-2404-tested) above. You can `git clone`
into `~/streaming-app` inside WSL.

For viewing, just open a Windows browser at `http://localhost:8081`
once Expo is running — Windows can reach WSL2's localhost.

#### 2B-iii. Full path — native Windows broadcaster

On native Windows the broadcaster needs:
- **OpenCV** — `pip install opencv-python` (bundles its own libs).
- **Microphone access** — `sounddevice` works on Windows via PortAudio
  (`pip install sounddevice` includes a Windows wheel — no apt install
  needed).
- **MediaPipe** — `pip install mediapipe` works on Python 3.11 Windows.

The `start.sh` script is Bash; on native Windows use **Git Bash**
(installed with Git for Windows) and run `bash start.sh`. Or run the
two halves manually:

```powershell
# Terminal 1: backend stack
cd Streaming-App
docker compose up -d --build

# Terminal 2 (Git Bash or PowerShell): broadcaster
cd Streaming-App
python -m venv .venv
.venv\Scripts\activate
pip install -r broadcaster/requirements.txt
python -m broadcaster
```

Things that won't work on native Windows out of the box:
- The `start.sh` preflight check uses `ldconfig` (Linux-only); skip it.
- File paths in some logs assume forward slashes; cosmetic only.

---

## 3. Configure `.env` files

### 3A. Backend `.env` (`Streaming-App/.env`)

```bash
cd Streaming-App
cp .env.example .env
```

Open `.env` and set:

- `LIVEKIT_API_SECRET` — generate a random 32+ character string. For
  example:
  ```bash
  openssl rand -hex 32        # Linux / Mac / WSL / Git Bash
  ```
- `LIVEKIT_URL` — set to your laptop's **LAN IP**, not `localhost`.
  Phones on Wi-Fi can't reach `localhost`. Find it:
  ```bash
  hostname -I | awk '{print $1}'   # Linux / WSL  → e.g. 192.168.1.42
  ipconfig | findstr IPv4          # Windows native → look for your Wi-Fi adapter
  ```
  Then set `LIVEKIT_URL=ws://192.168.1.42:7880` (substituting your IP).

Everything else can stay at the defaults for a demo.

### 3B. Frontend `.env` (`FE-Streaming-app/.env`)

```bash
cd ../FE-Streaming-app
cp .env.example .env
```

Open `.env` and set:

- `API_BASE` — the **same LAN IP** as above, port `5001`:
  ```
  API_BASE=http://192.168.1.42:5001
  ```
- `SOCKET_URL` — leave as `${API_BASE}` (or paste the same value).

> **If you change Wi-Fi networks**, your LAN IP probably changes. Update
> both `.env` files when this happens.

---

## 4. Start the backend

```bash
cd Streaming-App
./start.sh
```

What `start.sh` does:
1. Preflight checks for system libs.
2. `docker compose up -d --build` brings up the backend container,
   LiveKit, Postgres, and MinIO.
3. Waits for the backend to accept HTTP connections on `:5001`.
4. Launches the broadcaster (`python -m broadcaster`) on the host.
5. The broadcaster creates a stream record, connects to LiveKit, starts
   publishing your camera, and **auto-opens the streamer dashboard** in
   your default browser.

First run will take ~2 minutes (Docker has to pull and build images).
Subsequent runs are ~10s.

**Expected output near the end:**

```
2026-05-21 12:34:56,789 [INFO] broadcaster: Stream created: id=<uuid>
2026-05-21 12:34:56,789 [INFO] broadcaster: LiveKit URL: ws://192.168.1.42:7880
2026-05-21 12:34:56,789 [INFO] broadcaster: Streamer dashboard: http://localhost:5001/streamer/<uuid>
2026-05-21 12:34:57,012 [INFO] broadcaster: LiveKit publisher ready; entering capture loop
```

The dashboard opens in your browser. Sign up (or log in) in the modal
— this single sign-in tells the broadcaster who you are and loads
your custom gestures.

> **If `./start.sh` exits with "Missing host libraries:"** install
> what it asks for: `sudo apt install -y libportaudio2 libgl1 libglib2.0-0`.

> **If the dashboard doesn't open**, just paste the URL from the log
> (`http://localhost:5001/streamer/<uuid>`) into your browser.

---

## 5. Start the frontend (viewer)

In a **separate terminal** (leave `start.sh` running):

```bash
cd FE-Streaming-app
npm install
npx expo start
```

Pick a target from the terminal menu:
- **`w`** — opens `http://localhost:8081` in your browser. **Easiest path.**
- **`a` / `i`** — needs a custom dev client installed on the phone
  first (see [FE README](../FE-Streaming-app/README.md#building-the-dev-client-once-per-platform)).

Sign up / log in as a different user than the streamer, click the
Streams tab, watch yourself.

---

## 6. Add another viewer (phone, optional)

For the phone viewer to work, the phone needs:
1. To be on the **same Wi-Fi** as the laptop.
2. **Either** Expo Go installed (web-only paths) **or** a custom dev
   client built via EAS for LiveKit-backed playback.

Web: open `http://<laptop-LAN-IP>:8081` in the phone's browser.

Native: see [FE README → Building the dev client](../FE-Streaming-app/README.md#building-the-dev-client-once-per-platform).

---

## Streamer workflow once everything's up

- **Dashboard** auto-opens — sign in.
- See your own video (~1s LiveKit latency), live comments, viewer
  count, hearts.
- **"Manage gestures ↗"** opens the gestures page in a new tab.
  - Remap built-ins (peace → confetti, fist → end stream, etc.).
  - **● Record new** — name it, hold the pose; the broadcaster
    counts down 3s and captures 10 frames. Assign an action via the
    pill that appears.
- Gestures fire actions immediately; viewers see them as composited
  effects on the video.

---

## Stopping

- **Streamer:** Ctrl-C in the terminal running `start.sh`. The
  broadcaster exits, Docker containers keep running. To stop those:
  ```bash
  docker compose -f Streaming-App/docker-compose.yml down
  ```
- **Frontend dev server:** Ctrl-C in the terminal running `npx expo start`.

---

## Common gotchas

| Symptom | Cause | Fix |
|---|---|---|
| `Connection refused` from broadcaster to backend | Backend container exited during boot | `docker compose logs backend --tail 50` to see why |
| `Cannot connect to host livekit:7880 ... ('192.168.65.2', 7880)` | Docker Desktop on Linux | Switch to native Docker (see [Section 2A](#2a-ubuntu-2404-tested)) |
| `WebRTC native module not found` (Expo Go) | Expo Go can't load LiveKit native code | Build a dev client via EAS |
| Phone can't reach backend | Stale LAN IP in FE `.env` | Update `API_BASE` to your current IP and restart `npx expo start --clear` |
| `permission denied while trying to connect to the docker API` | User not in `docker` group OR session predates `usermod` | `sudo usermod -aG docker $USER`, then **log out and back in** |
| `source .venv/bin/activate` fails in fish | Wrong activate script for shell | `source .venv/bin/activate.fish` |
| Preview window tiny | OpenCV default | Already fixed; window is resizable. Drag the edge. |

For more detail on any of these, see
[../PROBLEMS_AND_SOLUTIONS.md](../PROBLEMS_AND_SOLUTIONS.md).

---

## Viewer-only setup

If a teammate is hosting and you just want to watch:

1. Get their **LAN IP** (or LAN domain). They run `hostname -I` on
   their laptop and tell you the IP, e.g. `192.168.1.42`.
2. Make sure you're on the **same Wi-Fi** as them.
3. Open `http://192.168.1.42:8081` in your browser.

That's it — no Docker, no Node, no Python needed.

---

## Updating

```bash
# Backend
cd Streaming-App && git pull
./start.sh                    # picks up any code changes via --build

# Frontend
cd ../FE-Streaming-app && git pull
npm install                   # in case package.json changed
npx expo start --clear        # --clear flushes Metro cache
```
