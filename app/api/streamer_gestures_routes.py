"""Streamer gestures page — list / remap built-ins, manage custom templates.

Served at GET /streamer/<stream_id>/gestures. Sibling to /streamer/<stream_id>
(the live dashboard). Streamer tool only — kept in the backend so it doesn't
ship in the viewer FE bundle.

The page calls the same REST endpoints the deleted FE Gesture Library used:
  GET    /api/v1/gestures/builtins
  GET    /api/v1/gestures/templates
  GET    /api/v1/gestures/actions
  POST   /api/v1/gestures                       (upsert override)
  DELETE /api/v1/gestures/<mapping_id>          (reset)
  PATCH  /api/v1/gestures/templates/<id>        (assign action)
  DELETE /api/v1/gestures/templates/<id>

All gesture routes require Bearer auth. The page reads the streamer's
api_key from localStorage, which is populated by the live dashboard's
sign-in flow. If the key isn't present, this page shows a hint pointing
back to the dashboard rather than re-prompting — single source of truth.
"""
from flask import Blueprint, Response

streamer_gestures_bp = Blueprint("streamer_gestures", __name__)


_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gestures — {stream_id}</title>
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<style>
  :root {{
    --bg: #0b0d12; --panel: #161a22; --border: #232936;
    --fg: #e6e8ec; --muted: #8a93a3; --accent: #ff4d6d;
    --good: #4ade80; --warn: #ffb800;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; min-height: 100%; background: var(--bg); color: var(--fg);
    font: 14px/1.45 system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }}

  header {{ display: flex; align-items: center; gap: 12px; padding: 12px 20px;
    border-bottom: 1px solid var(--border); }}
  header h1 {{ font-size: 14px; font-weight: 600; margin: 0; }}
  header .stream-id {{ color: var(--muted); font-family: ui-monospace, monospace; font-size: 12px; }}
  header .links {{ margin-left: auto; display: flex; gap: 14px; }}
  header a {{ color: var(--muted); text-decoration: none; font-size: 12px; }}
  header a:hover {{ color: var(--fg); }}

  main {{ max-width: 880px; margin: 0 auto; padding: 24px 20px 60px; }}

  .auth-banner {{ background: #2a1e10; border: 1px solid #5a3a14;
    border-radius: 8px; padding: 12px 16px; margin-bottom: 24px;
    display: flex; gap: 10px; align-items: center; }}
  .auth-banner input {{ flex: 1; background: #0b0d12; color: var(--fg);
    border: 1px solid var(--border); border-radius: 6px; padding: 8px 10px;
    font: inherit; }}
  .auth-banner button {{ background: var(--accent); color: #fff; border: 0;
    border-radius: 6px; padding: 8px 14px; font: inherit; font-weight: 600;
    cursor: pointer; }}
  .auth-banner.ok {{ background: #11221a; border-color: #2a553f; color: var(--good); }}
  .auth-banner.ok button {{ background: #2a3a32; }}

  h2 {{ font-size: 16px; font-weight: 700; margin: 28px 0 4px; }}
  h2:first-of-type {{ margin-top: 0; }}
  .hint {{ color: var(--muted); font-size: 12px; margin: 0 0 12px; }}

  .row {{ display: flex; align-items: center; gap: 10px;
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 10px 14px; margin-bottom: 8px; }}
  .row .name {{ flex: 1; min-width: 0; }}
  .row .name .label {{ color: var(--fg); }}
  .row .name .meta {{ color: var(--muted); font-size: 11px; margin-top: 2px; }}

  .pill {{ background: #1f2530; color: var(--fg); border: 1px solid var(--border);
    border-radius: 999px; padding: 6px 12px; font-size: 12px; cursor: pointer;
    display: inline-flex; align-items: center; gap: 6px; }}
  .pill:hover {{ background: #262d3a; }}
  .pill.unmapped {{ color: var(--warn); font-style: italic; }}
  .pill .override-dot {{ width: 6px; height: 6px; border-radius: 50%; background: #4dd4ff; }}

  .link-btn {{ background: none; border: 0; color: var(--accent); cursor: pointer;
    font: inherit; font-size: 12px; padding: 6px 4px; }}
  .link-btn:hover {{ text-decoration: underline; }}

  .record-btn {{ background: var(--accent); color: #fff; border: 0; border-radius: 6px;
    padding: 6px 14px; font: inherit; font-size: 13px; font-weight: 600; cursor: pointer; }}
  .record-btn:hover {{ filter: brightness(1.1); }}
  .record-btn:disabled {{ background: #3a2730; cursor: not-allowed; }}
  .record-btn.recording {{ background: #3a2730; color: var(--accent); }}

  .muted {{ color: var(--muted); font-size: 13px; padding: 8px 4px; }}

  .toast {{ position: fixed; bottom: 24px; right: 24px; background: #1a2030;
    border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px;
    color: var(--fg); font-size: 13px; max-width: 320px; opacity: 0;
    transform: translateY(8px); transition: all 0.2s ease; pointer-events: none; }}
  .toast.show {{ opacity: 1; transform: translateY(0); }}
  .toast.err {{ border-color: #5a2a2a; background: #2a1414; color: #ffb3b3; }}

  /* Modal */
  .modal-bg {{ position: fixed; inset: 0; background: rgba(0,0,0,0.7);
    display: none; align-items: center; justify-content: center; padding: 24px; z-index: 10; }}
  .modal-bg.show {{ display: flex; }}
  .modal {{ background: #1a1e26; border: 1px solid var(--border); border-radius: 14px;
    padding: 18px; width: 100%; max-width: 380px; }}
  .modal h3 {{ margin: 0 0 12px; font-size: 14px; font-weight: 700; }}
  .modal .picker {{ max-height: 320px; overflow-y: auto; }}
  .modal .picker-item {{ display: flex; justify-content: space-between; align-items: center;
    padding: 12px 8px; border-bottom: 1px solid var(--border); cursor: pointer; }}
  .modal .picker-item:last-child {{ border-bottom: none; }}
  .modal .picker-item:hover {{ background: #232936; }}
  .modal .picker-item .cat {{ color: var(--muted); font-size: 11px; text-transform: uppercase; }}
  .modal .cancel {{ width: 100%; background: none; border: 0; color: var(--muted);
    padding: 12px; margin-top: 6px; cursor: pointer; font: inherit; }}
</style>
</head>
<body>
<header>
  <h1>Gestures</h1>
  <span class="stream-id">{stream_id}</span>
  <span class="links">
    <a href="/streamer/{stream_id}">← Live dashboard</a>
  </span>
</header>

<main>
  <div id="auth" class="auth-banner" style="display:none">
    <span>Not signed in. Sign in on the <a href="/streamer/{stream_id}" style="color:var(--accent)">live dashboard</a>, then reload this page.</span>
  </div>

  <h2>Built-in gestures</h2>
  <p class="hint">Tap an action pill to remap. Reset returns a built-in to its default.</p>
  <div id="builtins"><div class="muted">Sign in to load…</div></div>

  <div style="display:flex;align-items:center;gap:12px;margin-top:28px">
    <h2 style="margin:0">Your custom gestures</h2>
    <button id="record-btn" class="record-btn">● Record new</button>
  </div>
  <p class="hint">Click Record to capture a new gesture. The broadcaster will count down 3 seconds, then grab 10 frames — hold the pose steady.</p>
  <div id="templates"><div class="muted">Sign in to load…</div></div>
</main>

<div id="modal-bg" class="modal-bg">
  <div class="modal">
    <h3>Pick an action</h3>
    <div id="picker" class="picker"></div>
    <button id="picker-cancel" class="cancel">Cancel</button>
  </div>
</div>

<div id="toast" class="toast"></div>

<script>
  const STREAM_ID = "{stream_id}";
  const $ = (id) => document.getElementById(id);

  const PRETTY = {{
    open_palm: "🖐  Open palm", fist: "✊  Fist", thumbs_up: "👍  Thumbs up",
    peace: "✌️  Peace", finger_heart: "🤏  Finger heart", ily: "🤟  ILY",
  }};

  let apiKey = localStorage.getItem("streamer_api_key") || "";
  let actions = [];
  let pickerTarget = null;

  function escape(s) {{
    return String(s ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;")
      .replaceAll('"',"&quot;").replaceAll("'","&#039;");
  }}

  let toastTimer;
  function toast(msg, isErr) {{
    const el = $("toast");
    el.textContent = msg;
    el.className = "toast show" + (isErr ? " err" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.className = "toast", 2500);
  }}

  function actionLabel(key) {{
    if (key === "unmapped") return "Unmapped";
    return actions.find((a) => a.key === key)?.label ?? key;
  }}

  async function api(path, options = {{}}) {{
    const headers = {{ "Content-Type": "application/json", ...(options.headers || {{}}) }};
    if (apiKey) headers.Authorization = `Bearer ${{apiKey}}`;
    const res = await fetch(path, {{ ...options, headers }});
    const text = await res.text();
    const body = text ? (() => {{ try {{ return JSON.parse(text); }} catch {{ return text; }} }})() : null;
    if (!res.ok) {{
      const msg = (body && body.error) || `Request failed (${{res.status}})`;
      throw new Error(msg);
    }}
    return body;
  }}

  function renderAuth() {{
    // Auth is owned by the live dashboard (/streamer/<id>). Here we just
    // show a hint banner when the key isn't present, and let refresh()
    // do its thing once it is.
    const el = $("auth");
    if (apiKey) {{
      el.style.display = "none";
      $("builtins").innerHTML = `<div class="muted">Loading…</div>`;
      $("templates").innerHTML = `<div class="muted">Loading…</div>`;
    }} else {{
      el.style.display = "";
      $("builtins").innerHTML = `<div class="muted">Sign in on the live dashboard to load…</div>`;
      $("templates").innerHTML = `<div class="muted">Sign in on the live dashboard to load…</div>`;
    }}
  }}

  function renderBuiltins(rows) {{
    const el = $("builtins");
    if (!rows.length) {{ el.innerHTML = `<div class="muted">No built-ins (?)</div>`; return; }}
    el.innerHTML = "";
    rows.forEach((row) => {{
      const div = document.createElement("div");
      div.className = "row";
      const dot = row.is_overridden ? `<span class="override-dot"></span>` : "";
      const resetBtn = (row.is_overridden && row.mapping_id != null)
        ? `<button class="link-btn" data-action="reset" data-mapping="${{row.mapping_id}}" data-gesture="${{escape(row.gesture)}}">Reset</button>`
        : "";
      div.innerHTML = `
        <div class="name"><div class="label">${{PRETTY[row.gesture] || row.gesture}}</div></div>
        <button class="pill" data-action="pick-builtin" data-gesture="${{escape(row.gesture)}}">
          ${{dot}}<span>${{escape(actionLabel(row.action))}}</span>
        </button>
        ${{resetBtn}}`;
      el.appendChild(div);
    }});
  }}

  function renderTemplates(rows) {{
    const el = $("templates");
    if (!rows.length) {{
      el.innerHTML = `<div class="muted">No custom gestures yet. Press R in the broadcaster window to record.</div>`;
      return;
    }}
    el.innerHTML = "";
    rows.forEach((row) => {{
      const div = document.createElement("div");
      div.className = "row";
      const pillCls = row.action === "unmapped" ? "pill unmapped" : "pill";
      div.innerHTML = `
        <div class="name">
          <div class="label">${{escape(row.name)}}</div>
          <div class="meta">${{row.sample_count}} samples • ${{escape(row.handedness)}} hand</div>
        </div>
        <button class="${{pillCls}}" data-action="pick-template" data-id="${{row.id}}">
          ${{escape(actionLabel(row.action))}}
        </button>
        <button class="link-btn" data-action="delete-template" data-id="${{row.id}}" data-name="${{escape(row.name)}}">Delete</button>`;
      el.appendChild(div);
    }});
  }}

  function openPicker(target) {{
    pickerTarget = target;
    const picker = $("picker");
    picker.innerHTML = "";
    actions.forEach((a) => {{
      const item = document.createElement("div");
      item.className = "picker-item";
      item.innerHTML = `<span>${{escape(a.label)}}</span><span class="cat">${{escape(a.category)}}</span>`;
      item.onclick = () => onPickAction(a.key);
      picker.appendChild(item);
    }});
    $("modal-bg").classList.add("show");
  }}

  function closePicker() {{
    pickerTarget = null;
    $("modal-bg").classList.remove("show");
  }}

  function notifyGesturesChanged() {{
    // Cross-tab ping. The dashboard listens for storage events on this key
    // and re-propagates streamer_authenticated, which makes the broadcaster
    // refetch builtins+templates. Value is just a timestamp so each write
    // changes it (storage events only fire when the value actually differs).
    try {{ localStorage.setItem("streamer_gestures_changed_at", String(Date.now())); }}
    catch {{}}
  }}

  async function onPickAction(actionKey) {{
    const target = pickerTarget;
    closePicker();
    if (!target) return;
    try {{
      if (target.kind === "builtin") {{
        await api("/api/v1/gestures", {{
          method: "POST",
          body: JSON.stringify({{ gesture: target.gesture, action: actionKey }}),
        }});
      }} else {{
        await api(`/api/v1/gestures/templates/${{target.id}}`, {{
          method: "PATCH",
          body: JSON.stringify({{ action: actionKey }}),
        }});
      }}
      await refresh();
      notifyGesturesChanged();
      toast("Updated");
    }} catch (e) {{
      toast(e.message || "Update failed", true);
    }}
  }}

  async function onResetBuiltin(mappingId, gesture) {{
    if (!confirm(`Reset ${{PRETTY[gesture] || gesture}} to its built-in action?`)) return;
    try {{
      await api(`/api/v1/gestures/${{mappingId}}`, {{ method: "DELETE" }});
      await refresh();
      notifyGesturesChanged();
      toast("Reset");
    }} catch (e) {{
      toast(e.message || "Reset failed", true);
    }}
  }}

  async function onDeleteTemplate(id, name) {{
    if (!confirm(`Delete the recorded gesture "${{name}}"? This cannot be undone.`)) return;
    try {{
      await api(`/api/v1/gestures/templates/${{id}}`, {{ method: "DELETE" }});
      await refresh();
      notifyGesturesChanged();
      toast("Deleted");
    }} catch (e) {{
      toast(e.message || "Delete failed", true);
    }}
  }}

  // Event delegation for the dynamically-rendered rows
  document.addEventListener("click", (e) => {{
    const t = e.target.closest("[data-action]");
    if (!t) return;
    const act = t.dataset.action;
    if (act === "pick-builtin") openPicker({{ kind: "builtin", gesture: t.dataset.gesture }});
    else if (act === "pick-template") openPicker({{ kind: "template", id: Number(t.dataset.id) }});
    else if (act === "reset") onResetBuiltin(Number(t.dataset.mapping), t.dataset.gesture);
    else if (act === "delete-template") onDeleteTemplate(Number(t.dataset.id), t.dataset.name);
  }});

  $("picker-cancel").onclick = closePicker;
  $("modal-bg").onclick = (e) => {{ if (e.target === $("modal-bg")) closePicker(); }};

  async function refresh() {{
    if (!apiKey) return;
    try {{
      const [a, b, t] = await Promise.all([
        api("/api/v1/gestures/actions"),
        api("/api/v1/gestures/builtins"),
        api("/api/v1/gestures/templates"),
      ]);
      actions = a.actions || [];
      renderBuiltins(b.builtins || []);
      renderTemplates(t.templates || []);
    }} catch (e) {{
      toast(e.message || "Load failed", true);
      if (/401|sign/i.test(e.message)) {{
        apiKey = "";
        localStorage.removeItem("streamer_api_key");
        renderAuth();
      }}
    }}
  }}

  // ---- Recording (Socket.IO → broadcaster) ----------------------------
  const socket = io(window.location.origin, {{ transports: ["websocket", "polling"] }});
  socket.on("connect", () => {{
    socket.emit("join_room", {{ stream_id: STREAM_ID, kind: "gestures" }});
  }});
  socket.on("error", (e) => {{
    toast((e && e.message) || "socket error", true);
    resetRecordButton();
  }});

  const recordBtn = $("record-btn");

  function setRecording(on) {{
    if (on) {{
      recordBtn.classList.add("recording");
      recordBtn.disabled = true;
      recordBtn.textContent = "● Recording…";
    }} else {{
      recordBtn.classList.remove("recording");
      recordBtn.disabled = false;
      recordBtn.textContent = "● Record new";
    }}
  }}
  function resetRecordButton() {{ setRecording(false); }}

  recordBtn.onclick = () => {{
    if (!apiKey) {{ toast("Sign in first", true); return; }}
    const name = prompt("Name for the new gesture (e.g. \"wave\")");
    if (!name) return;
    const trimmed = name.trim();
    if (!trimmed) return;
    if (trimmed.length > 50) {{ toast("Name must be 50 characters or fewer", true); return; }}
    setRecording(true);
    socket.emit("recording_start", {{ stream_id: STREAM_ID, name: trimmed }});
  }};

  socket.on("recording_ack", (data) => {{
    toast(`Recording "${{(data && data.name) || ""}}" — hold the pose`);
    // The broadcaster runs a ~3s countdown then captures ~10 frames.
    // Poll the templates list a few times so the new entry shows up.
    // Track length; if it grew, the recording landed → notify the dashboard.
    let tries = 0;
    let initialCount = -1;
    const poll = setInterval(async () => {{
      tries++;
      try {{
        const t = await api("/api/v1/gestures/templates");
        const rows = t.templates || [];
        if (initialCount < 0) initialCount = rows.length;
        renderTemplates(rows);
        if (rows.length > initialCount) {{
          notifyGesturesChanged();
          clearInterval(poll);
          resetRecordButton();
          return;
        }}
      }} catch {{}}
      if (tries >= 10) {{
        clearInterval(poll);
        resetRecordButton();
      }}
    }}, 1200);
  }});

  // Cross-tab sync: if the dashboard signs in/out in another tab, react.
  window.addEventListener("storage", (e) => {{
    if (e.key !== "streamer_api_key") return;
    apiKey = e.newValue || "";
    renderAuth();
    if (apiKey) refresh();
  }});

  renderAuth();
  refresh();
</script>
</body>
</html>
"""


@streamer_gestures_bp.route("/streamer/<stream_id>/gestures")
def streamer_gestures(stream_id: str):
    html = _PAGE.format(stream_id=stream_id)
    return Response(html, mimetype="text/html")
