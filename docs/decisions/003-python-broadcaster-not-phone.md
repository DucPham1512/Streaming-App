# 003 — Laptop Python Broadcaster, Not Phone-Based Publishing

**Status:** Accepted
**Date:** 2026-05-16

## Context

Replacing Mux with LiveKit opens the question of where the broadcaster runs. Options were:

1. **Phone (React Native publishing):** the streamer's phone runs the LiveKit RN SDK, captures camera, detects gestures on-device, and publishes. Matches a typical "social streaming" mental model.
2. **Laptop (Python publishing):** the streamer's laptop runs a Python process that opens the camera (USB webcam or built-in), detects gestures, composites effects, and publishes via the `livekit-rtc` Python SDK.

Existing code matters: the project already has a working Python broadcaster — built on OpenCV + MediaPipe Hands, fully debugged for landmark anchoring (`PROBLEMS_AND_SOLUTIONS.md` #17–18). Today's dev flow requires two commands (`python run.py` and `python -m broadcaster --camera 2`), which the team finds annoying.

## Decision

The broadcaster is a **Python process running on the streamer's laptop**, distributed as a standalone executable. Specifically:

- The broadcaster lives in `broadcaster/` at the root of this repo (not in `app/`).
- `broadcaster/publisher.py` wraps `livekit-rtc` and publishes composited numpy frames.
- `broadcaster/__main__.py` shows a tkinter login dialog at startup, then creates a stream, connects, and auto-opens the streamer dashboard.
- The backend stack starts with `./start.sh` (Linux/macOS) or `docker compose up` + `Broadcaster.exe` (Windows).
- For a second concurrent streamer on a second laptop, just run `Broadcaster.exe` (or `python -m broadcaster`) pointing at the host's backend URL — no Docker needed on the second laptop.
- The frontend app is **viewer-only**: no "Go Live" screen, no camera publishing in RN, no compositing in RN.

## Alternatives Considered

| Option | Why not |
|---|---|
| **Phone publishing via RN** | Requires porting MediaPipe Hands + Skia/Canvas compositing + `livekit-rtc` track-source plumbing to React Native. Significant native module work (`react-native-mediapipe`, `@shopify/react-native-skia`), fragile, much larger frontend surface area. Abandons the working Python detector+effects code. |
| **Both: phone *and* laptop** | Doubles maintenance for no demo-day benefit. |
| **Keep two separate processes (`run.py` + `demo.py`)** | Doesn't satisfy the "one command" requirement. Coordination between them is implicit (Socket.IO) and fragile. |

## Consequences

**Positive:**
- Reuses ~100% of the existing detector + effects code (the parts the project has spent the most time debugging).
- Single command starts the system — fixes the annoyance the team called out.
- Frontend surface area to change is small (~5% of FE code, per the migration plan). Other team members' UI work is preserved.
- Adding a second streamer is just running the broadcaster CLI on a second laptop — no infrastructure changes.
- Built-in MediaPipe Python performance is well-characterized (30 fps on a modern laptop).

**Negative:**
- Streamers must be on a laptop with a webcam, not a phone. For our demo use case (interactive lecture demo, two streamers), this is fine — and arguably better, since the laptop has a bigger screen for the streamer's local preview.
- Camera index handling in Docker requires Linux device passthrough (`devices: ["/dev/videoN:/dev/videoN"]`). macOS Docker cannot reach the host camera; macOS is explicitly out of scope.
- If we later want true mobile streaming, this design has to be revisited (but the LiveKit foundation supports it — only the publisher swaps).

**Open implication:** the broadcaster's local view (OpenCV preview window) becomes the streamer's primary "studio" UI. We extend it with a scrolling comment column so the streamer can read chat. See plan Step 6a.
