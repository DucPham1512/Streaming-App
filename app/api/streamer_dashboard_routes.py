"""Streamer dashboard — a single self-contained HTML page.

Served at GET /streamer/<stream_id>. The streamer opens this in any browser
on the laptop while ./start.sh is running. Layout:

    +-----------------------------------------+----------------------+
    |                                         |  Stats               |
    |          LiveKit video preview          |  ----                |
    |          (their own stream)             |  Comments            |
    |                                         |  ...                 |
    |                                         |  ...                 |
    +-----------------------------------------+  ----                |
    |           Floating heart ticker         |  Activity            |
    +-----------------------------------------+----------------------+

The page subscribes to LiveKit as a regular viewer (so the streamer sees
their own video the way viewers see it) and joins the Socket.IO room to
receive comments, emotes, viewer joins/leaves.

No auth in v1 — meant for local use during a demo.
"""
from flask import Blueprint, Response

streamer_dashboard_bp = Blueprint("streamer_dashboard", __name__)


_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Streamer — {stream_id}</title>
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/livekit-client@2.5.10/dist/livekit-client.umd.min.js"></script>
<style>
  :root {{
    --bg: #0b0d12; --panel: #161a22; --border: #232936;
    --fg: #e6e8ec; --muted: #8a93a3; --accent: #ff4d6d; --good: #4ade80;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; height: 100%; background: var(--bg); color: var(--fg);
    font: 14px/1.45 system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }}

  header {{ display: flex; align-items: center; gap: 12px; padding: 10px 16px;
    border-bottom: 1px solid var(--border); }}
  header h1 {{ font-size: 14px; font-weight: 600; margin: 0; }}
  header .stream-id {{ color: var(--muted); font-family: ui-monospace, monospace; font-size: 12px; }}
  header .status {{ margin-left: auto; display: flex; align-items: center; gap: 6px;
    color: var(--muted); font-size: 12px; }}
  header .dot {{ width: 8px; height: 8px; border-radius: 50%; background: #555; }}
  header .dot.on {{ background: var(--good); box-shadow: 0 0 8px var(--good); }}

  main {{ display: grid; grid-template-columns: 1fr 340px; gap: 12px; padding: 12px;
    height: calc(100% - 49px); }}

  /* Video area */
  .video-wrap {{ position: relative; background: #000; border: 1px solid var(--border);
    border-radius: 8px; overflow: hidden; display: flex; align-items: center;
    justify-content: center; min-height: 0; }}
  .video-wrap video {{ width: 100%; height: 100%; object-fit: contain; background: #000; }}
  .video-overlay {{ position: absolute; inset: 0; pointer-events: none; }}
  .video-placeholder {{ color: var(--muted); font-style: italic; }}
  .live-badge {{ position: absolute; top: 12px; left: 12px; padding: 4px 10px;
    background: var(--accent); color: #fff; font-size: 11px; font-weight: 700;
    letter-spacing: 0.06em; border-radius: 4px; text-transform: uppercase; }}
  .live-badge::before {{ content: "● "; }}

  /* Heart ticker (overlaid on video, bottom edge) */
  .ticker {{ position: absolute; left: 0; right: 0; bottom: 0; height: 220px;
    pointer-events: none; overflow: hidden; }}
  .heart {{ position: absolute; bottom: -20px; font-size: 28px; opacity: 0;
    animation: float 2.8s ease-out forwards; text-shadow: 0 2px 6px rgba(0,0,0,0.6); }}
  @keyframes float {{
    0%   {{ transform: translateY(0) scale(0.5); opacity: 0; }}
    15%  {{ opacity: 1; }}
    100% {{ transform: translateY(-220px) scale(1.3); opacity: 0; }}
  }}

  /* Side column */
  .side {{ display: flex; flex-direction: column; gap: 12px; min-height: 0; }}
  .panel {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
    display: flex; flex-direction: column; overflow: hidden; }}
  .panel h2 {{ font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--muted); margin: 0; padding: 10px 14px;
    border-bottom: 1px solid var(--border); }}
  .panel-body {{ flex: 1; overflow-y: auto; padding: 6px 14px; }}

  .stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; padding: 12px; }}
  .stat {{ background: #11151c; border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; }}
  .stat .label {{ color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; }}
  .stat .val {{ font-size: 20px; font-weight: 600; margin-top: 2px; }}

  .panel.comments {{ flex: 2; min-height: 0; }}
  .panel.activity {{ flex: 1; min-height: 0; }}

  .comment {{ padding: 6px 0; border-bottom: 1px solid #1d2330; }}
  .comment:last-child {{ border-bottom: none; }}
  .comment .who {{ font-weight: 600; color: #c8d3e2; margin-right: 6px; }}
  .comment .when {{ color: var(--muted); font-size: 11px; margin-left: 6px; }}
  .comment .what {{ display: block; margin-top: 2px; color: var(--fg); word-wrap: break-word; }}

  .act {{ padding: 3px 0; color: var(--muted); font-size: 12px; }}
  .act .when {{ color: #4a5263; font-size: 11px; margin-right: 8px; font-family: ui-monospace, monospace; }}
  .act.comment {{ color: #c8d3e2; }}
  .act.emote {{ color: #ffb4c1; }}
  .act.join {{ color: #93c5fd; }}
  .act.leave {{ color: #fca5a5; }}

  .empty {{ color: var(--muted); padding: 16px; text-align: center; font-style: italic; }}
</style>
</head>
<body>
<header>
  <h1>Streamer</h1>
  <span class="stream-id">{stream_id}</span>
  <span class="status">
    <span id="lk-dot" class="dot"></span><span id="lk-status">video: connecting…</span>
    <span style="width:12px"></span>
    <span id="io-dot" class="dot"></span><span id="io-status">chat: connecting…</span>
  </span>
</header>

<main>
  <section class="video-wrap">
    <span class="live-badge">Live</span>
    <video id="video" autoplay playsinline muted></video>
    <div id="placeholder" class="video-placeholder">Waiting for video…</div>
    <div id="ticker" class="ticker"></div>
  </section>

  <aside class="side">
    <div class="panel">
      <h2>Stats</h2>
      <div class="stats">
        <div class="stat"><div class="label">Viewers</div><div id="viewers" class="val">0</div></div>
        <div class="stat"><div class="label">Comments</div><div id="comment-count" class="val">0</div></div>
        <div class="stat"><div class="label">Hearts</div><div id="emote-count" class="val">0</div></div>
        <div class="stat"><div class="label">Uptime</div><div id="uptime" class="val">0:00</div></div>
      </div>
    </div>

    <div class="panel comments">
      <h2>Comments</h2>
      <div id="comments" class="panel-body"><div class="empty">No comments yet</div></div>
    </div>

    <div class="panel activity">
      <h2>Activity</h2>
      <div id="activity" class="panel-body"><div class="empty">Waiting for activity…</div></div>
    </div>
  </aside>
</main>

<script>
  const STREAM_ID = "{stream_id}";
  const ORIGIN = window.location.origin;

  const $ = (id) => document.getElementById(id);
  const lkStatus = $("lk-status"), lkDot = $("lk-dot");
  const ioStatus = $("io-status"), ioDot = $("io-dot");
  const videoEl = $("video"), placeholderEl = $("placeholder");
  const commentsEl = $("comments"), activityEl = $("activity");
  const viewersEl = $("viewers"), commentCountEl = $("comment-count");
  const emoteCountEl = $("emote-count"), uptimeEl = $("uptime");
  const tickerEl = $("ticker");

  let viewerCount = 0, emoteCount = 0, commentCount = 0;
  const startTime = Date.now();

  function pad(n) {{ return String(n).padStart(2, "0"); }}
  function fmtTime(d) {{ return `${{pad(d.getHours())}}:${{pad(d.getMinutes())}}:${{pad(d.getSeconds())}}`; }}
  function escape(s) {{
    return String(s ?? "")
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }}
  function clearEmpty(el) {{ const e = el.querySelector(".empty"); if (e) e.remove(); }}

  setInterval(() => {{
    const s = Math.floor((Date.now() - startTime) / 1000);
    uptimeEl.textContent = `${{Math.floor(s / 60)}}:${{pad(s % 60)}}`;
  }}, 1000);

  function addComment(c) {{
    clearEmpty(commentsEl);
    const div = document.createElement("div");
    div.className = "comment";
    const who = escape(c.display_name || c.username || "anon");
    const when = fmtTime(c.created_at ? new Date(c.created_at) : new Date());
    div.innerHTML = `<span class="who">${{who}}</span><span class="when">${{when}}</span>
      <span class="what">${{escape(c.content)}}</span>`;
    commentsEl.appendChild(div);
    commentsEl.scrollTop = commentsEl.scrollHeight;
    commentCountEl.textContent = ++commentCount;
  }}

  function addActivity(cls, html) {{
    clearEmpty(activityEl);
    const div = document.createElement("div");
    div.className = "act " + cls;
    div.innerHTML = `<span class="when">${{fmtTime(new Date())}}</span>${{html}}`;
    activityEl.appendChild(div);
    activityEl.scrollTop = activityEl.scrollHeight;
    while (activityEl.children.length > 200) activityEl.removeChild(activityEl.firstChild);
  }}

  const EMOTE_EMOJI = {{ heart: "❤️", fire: "🔥", clap: "👏", laugh: "😂", wow: "😮", sad: "😢" }};
  function floatEmote(emoji) {{
    const span = document.createElement("span");
    span.className = "heart";
    span.textContent = emoji;
    span.style.left = (5 + Math.random() * 90) + "%";
    tickerEl.appendChild(span);
    setTimeout(() => span.remove(), 2900);
  }}

  // ---- LiveKit subscribe (video) ----
  async function connectVideo() {{
    try {{
      const res = await fetch(`/api/v1/streams/${{STREAM_ID}}/viewer-token`, {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ identity: `streamer-dashboard-${{Date.now()}}`, display_name: "Streamer Dashboard" }}),
      }});
      if (!res.ok) throw new Error(`viewer-token ${{res.status}}`);
      const {{ viewer_token, livekit_url }} = await res.json();

      const room = new LivekitClient.Room({{ adaptiveStream: true, dynacast: true }});

      room.on(LivekitClient.RoomEvent.TrackSubscribed, (track, pub, participant) => {{
        if (track.kind === "video") {{
          track.attach(videoEl);
          placeholderEl.style.display = "none";
        }}
      }});
      room.on(LivekitClient.RoomEvent.TrackUnsubscribed, (track) => {{
        track.detach().forEach((el) => el.remove());
      }});
      room.on(LivekitClient.RoomEvent.Disconnected, () => {{
        lkStatus.textContent = "video: disconnected";
        lkDot.classList.remove("on");
      }});

      await room.connect(livekit_url, viewer_token);
      lkStatus.textContent = "video: connected";
      lkDot.classList.add("on");

      // Attach any tracks already published
      room.remoteParticipants.forEach((p) => {{
        p.trackPublications.forEach((pub) => {{
          if (pub.track && pub.track.kind === "video") {{
            pub.track.attach(videoEl);
            placeholderEl.style.display = "none";
          }}
        }});
      }});
    }} catch (e) {{
      lkStatus.textContent = "video: " + (e.message || "error");
      console.error(e);
    }}
  }}
  connectVideo();

  // ---- Socket.IO subscribe (comments / emotes / viewers) ----
  const socket = io(ORIGIN, {{ transports: ["websocket", "polling"] }});

  socket.on("connect", () => {{
    ioStatus.textContent = "chat: connected";
    ioDot.classList.add("on");
    socket.emit("join_room", {{ stream_id: STREAM_ID }});
  }});
  socket.on("disconnect", () => {{
    ioStatus.textContent = "chat: disconnected";
    ioDot.classList.remove("on");
  }});
  socket.on("connect_error", (e) => {{
    ioStatus.textContent = "chat: " + (e?.message || "error");
  }});

  socket.on("comment_received", (c) => {{
    addComment(c);
    addActivity("comment", `<b>${{escape(c.display_name || c.username || "anon")}}</b>: ${{escape(c.content)}}`);
  }});
  socket.on("emote_received", (e) => {{
    emoteCountEl.textContent = ++emoteCount;
    floatEmote(EMOTE_EMOJI[e.emote_type] || "✨");
    addActivity("emote", `emote <b>${{escape(e.emote_type)}}</b>`);
  }});
  socket.on("viewer_joined", () => {{
    viewerCount++; viewersEl.textContent = viewerCount;
    addActivity("join", `viewer joined`);
  }});
  socket.on("viewer_left", () => {{
    viewerCount = Math.max(0, viewerCount - 1);
    viewersEl.textContent = viewerCount;
    addActivity("leave", `viewer left`);
  }});

  // Backfill recent comments
  fetch(`/api/v1/streams/${{STREAM_ID}}/comments?limit=50`)
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {{
      if (!data?.comments?.length) return;
      data.comments.slice().reverse().forEach(addComment);
    }})
    .catch(() => {{}});
</script>
</body>
</html>
"""


@streamer_dashboard_bp.route("/streamer/<stream_id>")
def streamer_dashboard(stream_id: str):
    html = _PAGE.format(stream_id=stream_id)
    return Response(html, mimetype="text/html")
