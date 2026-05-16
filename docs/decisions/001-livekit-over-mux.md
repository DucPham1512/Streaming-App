# 001 — Self-Host LiveKit Instead of Mux

**Status:** Accepted
**Date:** 2026-05-16

## Context

The project originally used [Mux](https://mux.com) to host live streams: OBS pushed RTMP to Mux, viewers played HLS via `expo-video`. On the free tier, Mux delivers HLS with **20–25s end-to-end latency**. To keep gesture effects visually in sync with the delayed video, the backend buffered effect broadcasts by 22s (`EFFECT_BROADCAST_DELAY_SECONDS = 22` in `app/sockets/media_events.py`). This was an active workaround documented in `PROBLEMS_AND_SOLUTIONS.md` #12.

For a ~10-person demo with interactive gestures and chat, 20+ seconds of latency makes the experience feel broken: chat reactions arrive seconds before the moment they reacted to, and gestures need elaborate delay compensation.

## Decision

Replace Mux with **self-hosted [LiveKit](https://livekit.io)**, an open-source WebRTC SFU (Selective Forwarding Unit), running on the broadcaster's laptop via Docker. Use LiveKit's official Python SDK (`livekit-rtc`) for the broadcaster, and its React Native + Web SDKs for viewers.

## Alternatives Considered

| Option | Why not |
|---|---|
| **Mux paid tier** | Costs money; latency improves but still seconds, not sub-second. Doesn't solve the workaround. |
| **MediaMTX** | Excellent RTMP→HLS/WebRTC server, but no purpose-built room/participant model and weaker SDK story for React Native. |
| **Raw WebRTC with custom signaling** | Would need to build signaling, ICE handling, room management, reconnect logic ourselves. Weeks of work; fragile. |
| **Mesh P2P** | Doesn't scale past a handful of peers; broadcaster's encoder load grows linearly with viewer count; N² connections. |
| **Janus / Jitsi / Mediasoup** | Janus has weaker Python support. Jitsi is meeting-focused. Mediasoup is a Node library without a Python publisher SDK. |

## Consequences

**Positive:**
- Sub-second latency (<1s on LAN, ~1–2s over Internet with TURN).
- Effect delay constant collapses to 0; problem #12 disappears.
- Battle-tested SDKs in every language we need (Python broadcaster, RN viewer, Web viewer, server token minting).
- Self-hosted = no per-minute costs; LAN demos work offline.
- Architecture scales beyond demo (more streamers, more viewers, recording, TURN) without code rewrites.

**Negative:**
- New infrastructure component to operate (LiveKit Server). Mitigated by running it in docker-compose alongside everything else.
- Browsers require HTTPS for camera access when not on `localhost` — a real domain + TLS is needed if we ever publicly expose this beyond LAN.
- WebRTC carries more CPU + bandwidth implications than HLS for high viewer counts (not a concern at our scale).

**Note on SFU on the broadcaster's own machine (the "same-laptop" question):** the SFU does not save LAN bandwidth when it lives on the same laptop as the broadcaster. Its value is the SDK ecosystem and turnkey signaling, not bandwidth reduction in our setup. See [#003](003-python-broadcaster-not-phone.md) for the laptop-broadcaster rationale.
