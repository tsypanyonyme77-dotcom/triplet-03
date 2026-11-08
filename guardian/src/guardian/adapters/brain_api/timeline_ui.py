"""R3 timeline screen: a dependency-free HTML/JS page served by the Guardian that subscribes to
`WS /v1/ws/timeline` and shows reading -> verdict -> decision -> action as they happen (cause and effect).

The page itself is open (like /health and /docs); the WebSocket still authenticates with ?api_key=.
Open it at /timeline (or /timeline?api_key=<key> to connect straight away)."""
# ruff: noqa: E501  -- embedded CSS/JS template; column wrapping hurts readability

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter(tags=["timeline"])


@router.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/timeline")


@router.get("/timeline", include_in_schema=False)
async def timeline() -> HTMLResponse:
    return HTMLResponse(PAGE)


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Guardian · Live Timeline</title>
<style>
  :root {
    --navy:#0f2238; --navy-2:#16314d; --ink:#0b1a2c; --line:#24405f;
    --gold:#d8a53a; --text:#e8eef5; --muted:#8ba3bd; --panel:#13273e;
    --trusted:#2fb574; --suspect:#d8a53a; --untrusted:#e5564b; --unknown:#7f93a8;
    --reading:#4a90c2; --decision:#9b7bd6; --action:#3fb6a8; --alert:#e5564b;
    --containment:#e08a3c; --error:#e5564b; --system:#6b7f96;
  }
  * { box-sizing:border-box; }
  body {
    margin:0; background:var(--navy); color:var(--text);
    font:14px/1.45 ui-sans-serif,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
  }
  header {
    display:flex; align-items:center; gap:16px; flex-wrap:wrap;
    padding:12px 18px; background:var(--ink); border-bottom:1px solid var(--line);
    position:sticky; top:0; z-index:10;
  }
  .brand { display:flex; align-items:baseline; gap:10px; }
  .brand h1 { margin:0; font-size:17px; font-weight:700; letter-spacing:.2px; }
  .brand .tag { color:var(--muted); font-size:12px; }
  .brand .bar { width:34px; height:3px; background:var(--gold); border-radius:2px; margin-right:4px; }
  .spacer { flex:1; }
  .status { display:flex; align-items:center; gap:8px; font-size:13px; color:var(--muted); }
  .dot { width:10px; height:10px; border-radius:50%; background:var(--unknown); box-shadow:0 0 0 0 rgba(0,0,0,0); }
  .dot.live { background:var(--trusted); animation:pulse 2s infinite; }
  .dot.down { background:var(--untrusted); }
  @keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(47,181,116,.5);} 70%{box-shadow:0 0 0 7px rgba(47,181,116,0);} 100%{box-shadow:0 0 0 0 rgba(47,181,116,0);} }
  input, select, button {
    background:var(--panel); color:var(--text); border:1px solid var(--line);
    border-radius:7px; padding:7px 10px; font:inherit; outline:none;
  }
  input:focus, select:focus { border-color:var(--gold); }
  button { cursor:pointer; }
  button:hover { border-color:var(--gold); }
  button.primary { background:var(--gold); color:#20160a; border-color:var(--gold); font-weight:600; }
  input[type=password] { width:180px; }

  .stats { display:flex; gap:10px; flex-wrap:wrap; padding:12px 18px; background:var(--navy-2); border-bottom:1px solid var(--line); }
  .stat { background:var(--panel); border:1px solid var(--line); border-radius:9px; padding:8px 12px; min-width:84px; }
  .stat .n { font-size:20px; font-weight:700; }
  .stat .l { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.4px; }
  .stat.trusted .n{color:var(--trusted);} .stat.suspect .n{color:var(--suspect);}
  .stat.untrusted .n{color:var(--untrusted);} .stat.unknown .n{color:var(--unknown);}
  .stat.alerts .n{color:var(--alert);} .stat.cont .n{color:var(--containment);}
  .zones { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-left:auto; }
  .zchip { font-size:12px; padding:5px 10px; border-radius:20px; border:1px solid var(--line); background:var(--panel); }
  .zchip.elevated { border-color:var(--suspect); color:var(--suspect); }
  .zchip.under_attack { border-color:var(--untrusted); color:var(--untrusted); font-weight:700; animation:pulse 2s infinite; }

  .feed { max-width:1100px; margin:0 auto; padding:14px 18px 60px; }
  .hint { color:var(--muted); text-align:center; padding:40px 20px; }
  .ev {
    display:grid; grid-template-columns:72px 120px 1fr; gap:12px; align-items:start;
    padding:10px 12px; border-left:3px solid var(--system); border-radius:0 8px 8px 0;
    background:var(--navy-2); margin-bottom:7px; cursor:pointer; transition:background .12s, opacity .12s;
  }
  .ev:hover { background:#1b355a; }
  .ev.dim { opacity:.28; }
  .ev.hl { outline:1px solid var(--gold); }
  .ev .time { color:var(--muted); font-variant-numeric:tabular-nums; font-size:12px; padding-top:2px; }
  .ev .time .sid { display:block; color:var(--gold); font-size:10px; margin-top:2px; }
  .ev .badge {
    display:inline-flex; align-items:center; gap:6px; font-size:11px; font-weight:700;
    text-transform:uppercase; letter-spacing:.4px; padding:3px 8px; border-radius:6px;
    background:rgba(255,255,255,.06); white-space:nowrap;
  }
  .ev .badge::before { content:""; width:8px; height:8px; border-radius:50%; background:currentColor; }
  .ev .summary { word-break:break-word; }
  .ev .scope { color:var(--muted); font-size:12px; margin-top:3px; }
  .ev .scope b { color:var(--text); font-weight:600; }
  .reasons { margin-top:6px; display:flex; gap:6px; flex-wrap:wrap; }
  .reason { font-size:11px; padding:2px 7px; border-radius:5px; background:rgba(229,86,75,.14); color:#f0a59e; border:1px solid rgba(229,86,75,.3); }
  .detail { display:none; margin-top:8px; }
  .ev.open .detail { display:block; }
  .detail pre { margin:0; padding:10px; background:var(--ink); border:1px solid var(--line); border-radius:7px; overflow:auto; font-size:12px; color:#cfe0f0; }

  /* type + status accents */
  .t-reading{border-left-color:var(--reading);} .t-reading .badge{color:var(--reading);}
  .t-decision{border-left-color:var(--decision);} .t-decision .badge{color:var(--decision);}
  .t-action{border-left-color:var(--action);} .t-action .badge{color:var(--action);}
  .t-alert{border-left-color:var(--alert); background:#2a1d26;} .t-alert .badge{color:var(--alert);}
  .t-containment{border-left-color:var(--containment);} .t-containment .badge{color:var(--containment);}
  .t-error{border-left-color:var(--error);} .t-error .badge{color:var(--error);}
  .t-system{border-left-color:var(--system);} .t-system .badge{color:var(--system);}
  .v-trusted{border-left-color:var(--trusted);} .v-trusted .badge{color:var(--trusted);}
  .v-suspect{border-left-color:var(--suspect);} .v-suspect .badge{color:var(--suspect);}
  .v-untrusted{border-left-color:var(--untrusted);} .v-untrusted .badge{color:var(--untrusted);}
  .v-unknown{border-left-color:var(--unknown);} .v-unknown .badge{color:var(--unknown);}
  @media (max-width:640px){ .ev{grid-template-columns:60px 1fr;} .ev .badge{grid-column:2;} .ev .time{grid-row:span 2;} }
</style>
</head>
<body>
<header>
  <div class="brand"><span class="bar"></span><h1>Guardian</h1><span class="tag">Live Timeline · R3</span></div>
  <div class="spacer"></div>
  <label class="status"><span class="dot" id="dot"></span><span id="conn">disconnected</span></label>
  <input type="password" id="key" placeholder="API key" autocomplete="off">
  <select id="filter"><option value="">all tracks</option></select>
  <button id="pause">Pause</button>
  <button id="clear">Clear</button>
  <button class="primary" id="connect">Connect</button>
</header>

<div class="stats" id="stats">
  <div class="stat trusted"><div class="n" id="s-trusted">0</div><div class="l">trusted</div></div>
  <div class="stat suspect"><div class="n" id="s-suspect">0</div><div class="l">suspect</div></div>
  <div class="stat untrusted"><div class="n" id="s-untrusted">0</div><div class="l">untrusted</div></div>
  <div class="stat unknown"><div class="n" id="s-unknown">0</div><div class="l">unknown</div></div>
  <div class="stat alerts"><div class="n" id="s-alerts">0</div><div class="l">alerts</div></div>
  <div class="stat cont"><div class="n" id="s-cont">0</div><div class="l">containment</div></div>
  <div class="zones" id="zones"></div>
</div>

<div class="feed" id="feed">
  <div class="hint" id="hint">Enter the API key and press <b>Connect</b> to watch readings become verdicts, decisions and actions in real time.</div>
</div>

<script>
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const MAX = 600;
  const counts = { trusted:0, suspect:0, untrusted:0, unknown:0, alerts:0, cont:0 };
  const zones = {};
  const tracks = new Set();
  let ws = null, paused = false, selected = null, reconnectT = null, want = false;

  const params = new URLSearchParams(location.search);
  $("key").value = params.get("api_key") || localStorage.getItem("guardian_key") || "";

  function wsURL() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return proto + "//" + location.host + "/v1/ws/timeline?api_key=" + encodeURIComponent($("key").value.trim());
  }
  function setConn(state, text) {
    $("dot").className = "dot" + (state ? " " + state : "");
    $("conn").textContent = text;
  }
  async function connect() {
    want = true;
    if (reconnectT) { clearTimeout(reconnectT); reconnectT = null; }
    if (ws) { try { ws.close(); } catch (e) {} }
    const key = $("key").value.trim();
    localStorage.setItem("guardian_key", key);
    setConn("", "connecting…");
    // Browsers hide the WS close code (a 4401 often surfaces as 1006), so check the key over HTTP first.
    try {
      const r = await fetch("/v1/threat", { headers: { "X-API-Key": key } });
      if (r.status === 401) { setConn("down", "auth failed — check the API key"); want = false; return; }
    } catch (e) { /* offline: fall through and let the WS retry */ }
    if (!want) return;
    ws = new WebSocket(wsURL());
    ws.onopen = () => setConn("live", "live");
    ws.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch (e) {} };
    ws.onclose = (e) => {
      if (e.code === 4401) { setConn("down", "auth failed — check the API key"); want = false; return; }
      setConn("down", "disconnected");
      if (want) reconnectT = setTimeout(connect, 2000);
    };
    ws.onerror = () => { try { ws.close(); } catch (e) {} };
  }
  function disconnect() { want = false; if (ws) { try { ws.close(); } catch (e) {} } setConn("", "disconnected"); }

  const TYPE_META = {
    reading:"reading", verdict:"verdict", decision:"decision", action:"action",
    alert:"alert", containment:"containment", error:"error", system:"system"
  };
  function trackOf(ev) { return ev.sensor_id || ev.actuator_id || ev.zone_id || "system"; }

  function addTrack(t) {
    if (tracks.has(t)) return;
    tracks.add(t);
    const o = document.createElement("option"); o.value = t; o.textContent = t;
    $("filter").appendChild(o);
  }
  function renderZones() {
    const el = $("zones"); el.innerHTML = "";
    Object.keys(zones).sort().forEach((z) => {
      const lvl = zones[z];
      const c = document.createElement("span");
      c.className = "zchip " + lvl;
      c.textContent = z + " · " + lvl.replace("_", " ");
      el.appendChild(c);
    });
  }
  function updateStats() {
    $("s-trusted").textContent = counts.trusted;
    $("s-suspect").textContent = counts.suspect;
    $("s-untrusted").textContent = counts.untrusted;
    $("s-unknown").textContent = counts.unknown;
    $("s-alerts").textContent = counts.alerts;
    $("s-cont").textContent = counts.cont;
  }

  function onEvent(ev) {
    const d = ev.data || {};
    // tally
    if (ev.type === "verdict" && counts.hasOwnProperty(d.status)) counts[d.status]++;
    if (ev.type === "alert") counts.alerts++;
    if (ev.type === "containment") counts.cont++;
    // threat levels: from explicit threat_level events or any event carrying one
    const z = ev.zone_id;
    if (z && (d.kind === "threat_level") && d.threat_level) { zones[z] = d.threat_level; renderZones(); }
    else if (z && d.threat_level && d.threat_level !== "normal") { if (zones[z] !== d.threat_level) { zones[z] = d.threat_level; renderZones(); } }
    updateStats();
    if (!paused) renderEvent(ev);
  }

  function renderEvent(ev) {
    const hint = $("hint"); if (hint) hint.remove();
    const d = ev.data || {};
    const track = trackOf(ev); addTrack(track);

    const row = document.createElement("div");
    let cls = "ev t-" + (TYPE_META[ev.type] || "system");
    if (ev.type === "verdict" && d.status) cls += " v-" + d.status;
    row.className = cls;
    row.dataset.track = track;

    const t = new Date(ev.ts);
    const hhmmss = isNaN(t) ? ev.ts : t.toLocaleTimeString("en-GB", { hour12:false });
    const badgeLabel = ev.type === "verdict" && d.status ? d.status : ev.type;
    const kind = d.kind ? ("<span class='scope'>" + esc(d.kind) + "</span>") : "";

    const scopeBits = [];
    if (ev.sensor_id) scopeBits.push("sensor <b>" + esc(ev.sensor_id) + "</b>");
    if (ev.actuator_id) scopeBits.push("actuator <b>" + esc(ev.actuator_id) + "</b>");
    if (ev.zone_id) scopeBits.push("zone <b>" + esc(ev.zone_id) + "</b>");
    if (ev.scenario_id) scopeBits.push("<b>" + esc(ev.scenario_id) + "</b>");

    const reasons = Array.isArray(d.reasons) && d.reasons.length
      ? "<div class='reasons'>" + d.reasons.map((r) => "<span class='reason'>" + esc(r) + "</span>").join("") + "</div>" : "";

    row.innerHTML =
      "<div class='time'>" + hhmmss + "<span class='sid'>" + esc(track) + "</span></div>" +
      "<div><span class='badge'>" + esc(badgeLabel) + "</span></div>" +
      "<div><div class='summary'>" + esc(ev.summary || "") + "</div>" +
        (scopeBits.length ? "<div class='scope'>" + scopeBits.join(" · ") + "</div>" : "") +
        reasons +
        "<div class='detail'><pre>" + esc(JSON.stringify(ev, null, 2)) + "</pre></div>" +
      "</div>";

    row.addEventListener("click", (e) => {
      if (e.detail === 2) { row.classList.toggle("open"); return; }
      selectTrack(selected === track ? null : track);
    });

    const feed = $("feed");
    feed.insertBefore(row, feed.firstChild);
    // honour active filter
    const f = $("filter").value;
    if (f && f !== track) row.style.display = "none";
    if (selected) applySelect();
    while (feed.children.length > MAX) feed.removeChild(feed.lastChild);
  }

  function selectTrack(track) { selected = track; applySelect(); }
  function applySelect() {
    document.querySelectorAll(".ev").forEach((el) => {
      el.classList.toggle("dim", selected && el.dataset.track !== selected);
      el.classList.toggle("hl", selected && el.dataset.track === selected);
    });
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
  }

  $("connect").addEventListener("click", () => { if (want && ws && ws.readyState === 1) disconnect(); else connect(); updateBtn(); });
  function updateBtn() { $("connect").textContent = (want && ws && ws.readyState <= 1) ? "Disconnect" : "Connect"; }
  $("pause").addEventListener("click", () => { paused = !paused; $("pause").textContent = paused ? "Resume" : "Pause"; });
  $("clear").addEventListener("click", () => {
    const feed = $("feed"); feed.innerHTML = "";
    for (const k in counts) counts[k] = 0; updateStats();
  });
  $("filter").addEventListener("change", () => {
    const f = $("filter").value;
    document.querySelectorAll(".ev").forEach((el) => { el.style.display = (!f || el.dataset.track === f) ? "" : "none"; });
  });
  $("key").addEventListener("keydown", (e) => { if (e.key === "Enter") { connect(); updateBtn(); } });

  setInterval(updateBtn, 500);
  if ($("key").value) { connect(); updateBtn(); }
})();
</script>
</body>
</html>
"""
