# 002 — Burn Gesture Effects Into the Broadcaster's Video, Not Overlay Them on Viewers

**Status:** Accepted
**Date:** 2026-05-16

## Context

Today, when a streamer triggers a gesture (e.g., open palm → heart burst), the gesture is detected on the broadcaster's laptop, dispatched as a Socket.IO event to all viewers, and each viewer's app renders the visual effect *as an overlay on top of the video*, anchored to the streamer's hand position (normalized 0–1 coordinates from MediaPipe). See `PROBLEMS_AND_SOLUTIONS.md` #17–18 for the anchor-position fixes.

With HLS this was the only option (you cannot modify video on the server in real time without re-encoding). With WebRTC / LiveKit, we revisit the question: should viewers continue to render effects as overlays, or should the broadcaster composite effects onto frames before publishing?

## Decision

**The broadcaster composites effects onto camera frames before encoding and publishing.** Viewers receive a pre-rendered video stream with effects already burned in. The Socket.IO `stream_state_update` visual-effect fan-out to viewers is removed; effects are dispatched only locally to the broadcaster's compositor.

## Alternatives Considered

| Option | Why not |
|---|---|
| **Keep viewer-side overlays** | Even with sub-second latency, the gesture event and the corresponding video frame are not perfectly aligned at the viewer — some drift remains. Worse, every viewer independently renders effects, so different devices show slight differences. Adds runtime overlay complexity to every client. |
| **Server-side compositing (in LiveKit / SFU)** | LiveKit (and SFUs in general) do not decode/re-encode media. Doing this would require LiveKit Egress + a custom track ingest pipeline; adds 200–500ms latency and significant CPU. Wrong architectural layer. |
| **Hybrid (overlay for visual effect, burn-in for hand landmarks)** | Doubles the complexity. Pick one model. |

## Consequences

**Positive:**
- Pixel-perfect alignment of effect to hand position — no possibility of viewer-side drift.
- Effects look identical on all clients regardless of device, browser, or app version.
- Simpler viewer code: just play a video. No overlay layer, no anchor math, no per-effect React components, no `stream_state_update` handlers for visual events.
- Recording trivializes: LiveKit Egress can record the published track as-is; effects are part of the recording.

**Negative:**
- More CPU on the broadcaster's laptop (drawing on numpy frames before encoding). At 720p30, this is well within budget on a modern laptop using OpenCV's existing draw routines from `effects.py`.
- The broadcaster's local OpenCV preview window and the published frame must use **different drawing passes** (the preview adds landmark skeletons + comment column; the publish path does not). One source of frames, two render targets. See [#003](003-python-broadcaster-not-phone.md) and the plan's Step 6a.
- Effects cannot be turned off / customized per viewer (e.g., "accessibility mode: no flashing effects"). For a 10-person demo, acceptable; revisit if it becomes a requirement.

**Implementation note:** Socket.IO `gesture_command_received` events still flow from the broadcaster to the backend (for chat-side notifications, analytics, and potentially future viewer-side reactions), but the `stream_state_update` → visual-effect path on viewers is removed.
