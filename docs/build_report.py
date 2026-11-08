"""The triplet's report as docs/report.pdf: one document, one page style, pages numbered 1 to 20.

    uv run --project brain --with pypdf python docs/build_report.py

Part 0 and Part 4 are written for all three teams. Part 1 is the Twin team's PDF (docs/parts/part1-twin.pdf), already in the house style;
only its page numbers are re-stamped. Part 2 is the Brain's part from brain/docs/report/build.py. Part 3 is the Guardian team's text
(docs/parts/part3-guardian.pdf) re-set in the house style, with their ASCII architecture redrawn and these corrections, to be confirmed by
the Guardian team: 113 tests and 95% coverage (measured, not 97%); the Brain routes valve, grid, signal and dispatch calls through
the Guardian (not every call); an unreliable actuator is refused rather than the Brain picking a backup; a repeated dispatch is the same
incident, station, unit, mode and zone (on main since 06e9a3b, configurable since b537f8d); compromised_twin raises an alert advising safe mode.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

DOCS = Path(__file__).resolve().parent
ROOT = DOCS.parent
sys.path.insert(0, str(ROOT / "brain" / "docs" / "report"))
import build as B  # noqa: E402  the Brain report's page style, figures and fonts

TWIN_PDF = DOCS / "parts" / "part1-twin.pdf"
OUT = DOCS / "report.pdf"
TEAMS = "Triplet 03 · all three teams"


def fig_triplet() -> str:
    """The three layers and every link between them, as INTEGRATION.md and the three Interface Cards agree."""
    b = []
    b.append(B.NODE(0, 70, 210, 214, "Twin", ["What is really happening?", "", "the city engine at 10 Hz,", "the only ground truth;", "signs every reading", "(HMAC-SHA256, sequence no);",
                                               "checks every call (key,", "contract, trust_ref)", "", "Part 1"], "city", B.INK, ("python", "fastapi")))
    b.append(B.NODE(570, 0, 210, 160, "Guardian", ["Is this data telling the truth?", "", "seven trust checks, signed", "verdicts, threat correlation,", "containment; audits calls", "", "Part 3"],
                    "shield", B.GOOD, ("python", "fastapi")))
    b.append(B.NODE(570, 230, 210, 160, "City Brain", ["What should we do?", "", "rules, agent teams, solvers;", "one safety gate; a trust_ref", "on every call", "", "Part 2"],
                    "brain", B.BLUE, ("python", "langgraph")))
    b.append(B.ARROW([(210, 95), (570, 95)], B.INK, "signed readings · HTTP POST, one per second", 390, 89, size=9.5))
    b.append(B.ARROW([(570, 130), (210, 130)], B.GOOD, "containment; the audited calls, forwarded", 390, 124, size=9.5))
    b.append(B.ARROW([(210, 252), (570, 252)], B.INK, "signed readings · HTTP, MCP or MQTT", 390, 246, size=9.5))
    b.append(B.ARROW([(570, 274), (210, 274)], B.BLUE, "alert, recall and pump calls", 390, 268, size=9.5))
    b.append(B.ARROW([(612, 230), (612, 160)], B.BLUE) + B.T(620, 186, "verdict request;", 9, 400, B.BLUE) + B.T(620, 198, "audited calls", 9, 400, B.BLUE))
    b.append(B.ARROW([(745, 160), (745, 230)], B.GOOD) + B.T(738, 214, "signed verdict", 9, 400, B.GOOD, "end"))
    b.append(B.R(0, 412, 780, 40, B.WASH[B.MUTED], B.MUTED, 1, 8) + B.T(14, 430, "Timeline (R3) and logs (R2)", 10, 700)
             + B.T(14, 444, "Twin viewer (SSE) · Guardian /timeline (WebSocket) · City Brain screen (SSE, CloudEvents) · one log per scenario run in logs/", 9.3, 400, B.INK2))
    return B.SVG(780, 456, "".join(b), "The triplet: Twin, Guardian and City Brain, and the messages between them")


def part0() -> list[str]:
    p = []
    p.append(B.page(1, "Part 0 · Triplet overview and integration", f"""
<h1>0. Triplet overview and integration</h1>
<p class='meta'>Written by the Twin, City Brain and Guardian teams of Triplet 03 · shared data dictionary <code>2026-09-17</code> and the Guardian&rsquo;s contract 1.0 · <code>INTEGRATION.md</code></p>
<h2>0.1 Architecture and how the layers talk</h2>
<p>Three teams build one city. The <b>Twin</b> simulates it and is the only layer that knows what really happens. The <b>Guardian</b> judges every reading and audits every actuator call. The <b>City Brain</b> detects incidents and decides, acting only on readings the Guardian has trusted. Each layer runs alone with mocks of the other two (R1), starts every scenario from one trigger and logs it (R2), and shows its events live (R3).</p>
{fig_triplet()}
<p class='cap'><b>Figure 0.1.</b> The triplet as <code>INTEGRATION.md</code> and the three Interface Cards define it. Grey: readings; blue: the Brain&rsquo;s calls; green: the Guardian&rsquo;s answers and containment. Every address is configuration (<code>TWIN_URL</code>, <code>BRAIN_URL</code>, <code>GUARDIAN_URL</code>).</p>
<table><tr><th style='width:15%'>Link</th><th style='width:27%'>Message</th><th style='width:30%'>Transport</th><th>Protection</th></tr>
<tr><td>Twin &rarr; Guardian</td><td>every signed reading</td><td>HTTP POST, one reading per request, every second</td><td>HMAC-SHA256 over canonical JSON; a rising sequence number per sensor</td></tr>
<tr><td>Twin &rarr; Brain</td><td>every signed reading; the city layout</td><td>the Brain pulls them: MCP <code>list_readings</code>, or HTTP</td><td>the same signature and sequence checks, in the Brain</td></tr>
<tr><td>Brain &rarr; Guardian</td><td>a verdict request by sensor and sequence number</td><td>REST <code>POST /v1/verdicts/request</code>, 2 s deadline</td><td>an API key per layer; the verdict is HMAC-signed</td></tr>
<tr><td>Brain &rarr; Twin</td><td>a signed actuator call with its <code>trust_ref</code></td><td>dispatch through the Guardian&rsquo;s audit; alert, recall and pump straight to the Twin&rsquo;s MCP tools</td><td>the Brain&rsquo;s gate, the Guardian&rsquo;s auditor, the Twin&rsquo;s key and <code>trust_ref</code> checks</td></tr>
<tr><td>Guardian &rarr; Twin</td><td>isolate, quarantine, clear</td><td>a call with <code>requesting_layer: guardian</code></td><td>containment is Guardian-only on the Twin; caps and release paths</td></tr></table>
""", TEAMS))
    p.append(B.page(2, "Part 0 · One scenario end to end", f"""
<h2>0.2 One scenario end to end: a robbery and a pursuit</h2>
<p>A robbery is caught on camera (scenario T14). The trace is the committed run <code>logs/t14-20261108T153858Z.jsonl</code> at normal speed, with times measured from the robbery report. The Twin and the Guardian in this run are the Brain&rsquo;s stand-ins, which speak the shared contract; the three teams&rsquo; real layers have also run together (0.3).</p>
{B.fig_trace()}
<p class='cap'><b>Figure 0.2.</b> T14 across the layers. Every reading is judged before it counts; the reflex dispatches one unit 15 ms after the reading that completes the evidence, and the team&rsquo;s solver-checked perimeter follows about 120 ms later through the same gate.</p>
<table><tr><th style='width:15%'>Layer</th><th>What it does in this scenario</th></tr>
<tr><td>Twin</td><td>streams the signed camera reading and a citizen running away at 18 km/h; answers each dispatch with a unit id; reports the units on their way and the arrest</td></tr>
<tr><td>Guardian</td><td>judges every reading within about 5 ms; a call to a station it had quarantined would be refused (T6, T16)</td></tr>
<tr><td>City Brain</td><td>opens the incident, scores the suspect 0.82, dispatches one unit by reflex, adds two perimeter units and an alert, and recalls every unit at the arrest</td></tr></table>
<p>Each part also traces a scenario of its own team: an accident from the truth to its log (Figure 1.5), one reading through the Brain&rsquo;s eighteen steps (Figure 2.2), and a fake flood at the port (3.2.1).</p>
<h3>Where to find each of the jury&rsquo;s criteria</h3>
<table><tr><th style='width:40%'>Criterion (points)</th><th>Sections</th></tr>
<tr><td>Individual prototype functionality (10)</td><td>1.2, 2.2, 3.2; the scenarios of Part 4</td></tr>
<tr><td>Technical implementation and features (5)</td><td>1.3, 2.3, 3.3</td></tr>
<tr><td>Interoperability between the three teams (15)</td><td>0.1, 0.3; 1.4, 2.4, 3.4; each layer&rsquo;s <code>INTERFACE.md</code></td></tr>
<tr><td>Security and trust mechanisms (10)</td><td>1.5, 2.5, 3.5; the gate (Table 2.1) and the trust checks (3.2.1)</td></tr>
<tr><td>Documentation and code quality (5)</td><td>1.6, 2.6, 3.6; each layer&rsquo;s <code>README.md</code></td></tr>
<tr><td>Demonstration and presence (5)</td><td>0.2; the triggers and logs of Part 4; the three timeline screens</td></tr></table>
""", TEAMS))
    p.append(B.page(3, "Part 0 · Shared decisions", """
<h2>0.3 Shared decisions</h2>
<ul class='items'>
<li><b>One data dictionary</b>, contract <code>2026-09-17</code>, with an example of every message in each layer&rsquo;s Interface Card.</li>
<li><b>Signed readings.</b> The Twin signs each reading with HMAC-SHA256 over canonical JSON (sorted keys, no spaces) and a sequence number per sensor; the Guardian and the Brain both check it.</li>
<li><b>No verdict, no action.</b> Every Brain call carries a <code>trust_ref</code> to a trusted, unexpired Guardian verdict, checked by the Brain&rsquo;s gate, the Guardian&rsquo;s auditor and the Twin.</li>
<li><b>Containment belongs to the Guardian</b>, and valve, grid, signal and dispatch calls pass its audit before they reach the Twin.</li>
<li><b>Configuration, not code.</b> Addresses and keys come from configuration and the environment.</li>
<li><b>One numbering, one log.</b> T1 to T20 across the three teams, one trigger and one log per run (Part 4).</li>
</ul>
<h3>When a layer fails</h3>
<table><tr><th style='width:27%'>Failure</th><th>What happens</th><th style='width:18%'>Shown by</th></tr>
<tr><td>The Guardian stops answering</td><td>the Brain acts on nothing the Guardian has not judged; the Twin keeps running</td><td>T15</td></tr>
<tr><td>The Twin goes silent</td><td>the Guardian marks every sensor unknown; the Brain reports it and keeps its state</td><td>T7; Brain tests</td></tr>
<tr><td>A partner is unreachable for the Twin</td><td>the delivery fails and is logged; the city keeps running</td><td>Part 1, 1.4</td></tr>
<tr><td>A forged or replayed reading</td><td>the Guardian marks it untrusted; the Brain refuses it with a code</td><td>T3; Brain red team</td></tr>
<tr><td>A device is quarantined</td><td>the Guardian refuses calls to it; the Brain picks another station</td><td>T6, T16</td></tr></table>
<h3>Integration status</h3>
<p>On 8 November the three teams&rsquo; real layers ran together as local processes, with no mock and no person deciding. A pedestrian hit, a car crash and a building fire went end to end, each unit dispatched through the Guardian&rsquo;s audit and each incident closed; a flood opened once, with a public alert (<code>twin/docs/joint-run-2026-11-08.md</code>). Every link now follows the shared contract:</p>
<table><tr><th style='width:22%'>Link</th><th>Agreed and built</th></tr>
<tr><td>Readings to the Brain</td><td>the Brain pulls them from the Twin: MCP <code>list_readings</code>, or <code>GET /readings</code></td></tr>
<tr><td>Readings to the Guardian</td><td>the Twin pushes each signed reading to <code>POST /v1/readings</code></td></tr>
<tr><td>Verdicts</td><td>the Brain asks <code>POST /v1/verdicts/request</code>; the Guardian answers with a signed verdict</td></tr>
<tr><td>Actions</td><td>dispatches pass the Guardian&rsquo;s audit and reach the Twin at <code>POST /tools/{action}</code>; alerts, recalls and the pump go straight to the Twin&rsquo;s MCP tools</td></tr>
<tr><td>Still to do</td><td>the same runs through the root <code>docker-compose.yml</code>, with the Brain&rsquo;s agent teams (the run used its rules), and the pump call, added after the run, played with all three</td></tr></table>
""", TEAMS))
    return p


def fig_guardian() -> str:
    """The Guardian's four blocks (their ASCII figure, redrawn): adapters outside, the reading path, the actuator watch, the state store, the audit."""
    b = []
    b.append(B.R(0, 0, 200, 44, B.STRIP, B.MUTED, 1.2, 8, "5 3") + B.BADGE("city", 24, 22, 26, B.MUTED) + B.T(44, 20, "Twin", 11, 700) + B.T(44, 34, "partner", 9, 400, B.MUTED))
    b.append(B.R(580, 0, 200, 44, B.STRIP, B.MUTED, 1.2, 8, "5 3") + B.BADGE("brain", 604, 22, 26, B.MUTED) + B.T(624, 20, "City Brain", 11, 700) + B.T(624, 34, "partner", 9, 400, B.MUTED))
    b.append(B.ARROW([(60, 44), (60, 80)], B.INK) + B.T(66, 63, "readings", 8.8, 400, B.INK2))
    b.append(B.ARROW([(160, 80), (160, 44)], B.GOOD) + B.T(166, 63, "audited calls, containment", 8.8, 400, B.GOOD))
    b.append(B.ARROW([(610, 44), (610, 80)], B.BLUE) + B.T(604, 63, "verdict request, actuator call", 8.8, 400, B.BLUE, "end"))
    b.append(B.ARROW([(730, 80), (730, 44)], B.GOOD) + B.T(724, 63, "verdicts, alerts", 8.8, 400, B.GOOD, "end"))
    b.append(B.NODE(0, 80, 780, 50, "Adapters: the only code that knows partner formats",
                    ["twin_client: REST, MCP or MQTT  ·  brain_api: REST and WebSocket  ·  schemas: Pydantic"], "plug", B.BLUE, ("fastapi", "pydantic")))
    y1 = 160
    b.append(B.NODE(0, y1, 140, 58, "Ingest", ["validate, normalise"], "file", B.INK))
    b.append(B.NODE(160, y1, 150, 58, "A · Detection", ["L1 to L6 on every", "reading"], "shield", B.GOOD, accent=True))
    b.append(B.NODE(330, y1, 140, 58, "Verdict engine", ["score, reasons,", "HMAC signature"], "stamp", B.GOOD))
    b.append(B.NODE(490, y1, 290, 58, "B · Actuator watch", ["call auditor: trust_ref, policies, rate limits;", "effect verifier: did it happen?"], "eye", B.BLUE, accent=True))
    b.append(B.ARROW([(70, 130), (70, y1)], B.INK) + B.ARROW([(140, y1 + 29), (160, y1 + 29)], B.INK) + B.ARROW([(310, y1 + 29), (330, y1 + 29)], B.INK))
    b.append(B.ARROW([(400, y1), (400, 130)], B.GOOD) + B.ARROW([(635, 130), (635, y1)], B.BLUE))
    y2 = 250
    b.append(B.NODE(0, y2, 225, 58, "C · Threat correlation", ["9 attack patterns: zone threat", "level and security alerts"], "chart", B.WARN, accent=True))
    b.append(B.NODE(245, y2, 225, 58, "D · Containment", ["isolate, quarantine, roll back,", "release; sent to the Twin"], "lock", B.BAD, accent=True))
    b.append(B.NODE(490, y2, 290, 58, "State store", ["history, baselines, last-known-good;", "in memory and SQLite, read by A and B"], "db", B.MUTED))
    b.append(B.ARROW([(400, y1 + 58), (400, 234), (112, 234), (112, y2)], B.GOOD) + B.T(260, 229, "every verdict", 8.8, 400, B.GOOD, "middle"))
    b.append(B.ARROW([(225, y2 + 29), (245, y2 + 29)], B.WARN) + B.ARROW([(635, y1 + 58), (635, y2)], B.BLUE))
    b.append(B.R(0, 336, 780, 36, B.WASH[B.MUTED], B.MUTED, 1, 8) + B.ICON("chain", 20, 354, 18, B.MUTED, 2.4)
             + B.T(38, 358, "Audit: every reading, verdict, call and containment goes to a JSONL log (R2) and to the timeline (R3)", 9.8, 400, B.INK2))
    return B.SVG(780, 376, "".join(b), "The Guardian's architecture: adapters, detection, verdict engine, actuator watch, threat correlation, containment, state store and audit")


def logo_cell(names: tuple[str, ...]) -> str:
    imgs = "".join(f"<img src='{B.logo_uri(n)[0]}' alt='' style='height:3.6mm;width:{3.6 * min(B.logo_uri(n)[1], 3.2):.1f}mm'>" for n in names)
    return f"<span class='logos'>{imgs}</span>"


def part3(n: int) -> list[str]:
    """The Guardian team's Part 3, re-set in the report's style. Their text and structure, with the corrections listed in the docstring of main()."""
    team = "Guardian team"
    head = "Part 3 · The Guardian"
    p = []
    p.append(B.page(n, head, f"""
<h1>3. The Guardian</h1>
<p class='meta'>Written by the Guardian team · repository folder <code>triplet-03/guardian/</code> · contract 1.0 · key question: &ldquo;Is this data telling the truth?&rdquo;</p>
<h2>3.1 Role and goals</h2>
<p>The Guardian is the trust layer of the triplet. It judges what the city reports (the Twin&rsquo;s sensors and actuators) before the City Brain acts on it. The Brain cannot act safely on raw readings: data can be faked (a flood that is not there), replayed, frozen by a dead sensor, or drowned in a flood of emergency calls. The Guardian judges every reading and every actuator order, and contains what it finds.</p>
<p>Every reading meets seven checks (L1 to L6, with L3 split in two), and nine attack patterns are correlated across readings. The eleven Guardian scenarios of the Test Book (T1 to T11) pass, with their logs committed; the suite has 113 tests with 95% line coverage.</p>
<h3>Threats covered</h3>
<table><tr><th style='width:27%'>Threat</th><th style='width:38%'>Detected by</th><th>Response</th></tr>
<tr><td>Sensor fault (stuck, dead, out of range, wrong unit)</td><td>L3a range and unit, L4 flatline, L6 heartbeat</td><td><i>suspect</i> or <i>unknown</i>; isolate if persistent</td></tr>
<tr><td>Spoofed or false data (a fake flood, an impossible event)</td><td>L3b city model, L4 dynamics, L5 corroboration</td><td><i>untrusted</i>, isolate, roll back</td></tr>
<tr><td>Replay and tampering</td><td>L1 HMAC and schema, L2 sequence numbers</td><td><i>untrusted</i>; tampering or replay alert</td></tr>
<tr><td>Flooding (calls, messages)</td><td>L6 arrival rate, duplicate ids</td><td>throttle, corroborate, never drop</td></tr>
<tr><td>Actuator failure (ordered but not done)</td><td>effect verifier with an independent sensor</td><td><code>actuator_failure</code>; mark it unreliable</td></tr>
<tr><td>Cyber-attacks across readings</td><td>threat correlator, nine patterns (3.2.3)</td><td>zone threat level, alert, quarantine</td></tr>
<tr><td>Unsafe or injected commands</td><td>call auditor: <code>trust_ref</code>, policies, rate limits</td><td>block; quarantine the caller</td></tr></table>
<p><b>Design principle.</b> Simple, explainable detectors that visibly catch the attack beat a black-box model. Every verdict names its reasons, so the Brain, the jury and the timeline can see why a reading was rejected. Optional machine learning can only lower trust, never raise it, and stays off the critical path.</p>
<h2>3.2 Architecture</h2>
<p>Four functional blocks share one state store, wrapped by adapters on the outside and an audit trail at the bottom.</p>
<div style='width:94%;margin:0 auto'>{fig_guardian()}</div>
<p class='cap'><b>Figure 3.1.</b> The Guardian&rsquo;s blocks. Readings flow all the time, from ingest through L1 to L6 to a verdict that threat correlation also reads. The Brain&rsquo;s verdict requests and actuator calls arrive on demand and pass the auditor, then the effect verifier.</p>
""", team))
    p.append(B.page(n + 1, head, f"""
<h3>3.2.1 Block A: the trust checks on every reading</h3>
<p>Cheap, definitive checks run first; statistical and cross-sensor checks run last. Failing L1 or L2 makes a reading untrusted at once (a hard gate). L3 to L6 adjust a score that starts at 1.0.</p>
<table><tr><th style='width:15%'>Layer</th><th style='width:17%'>Question</th><th>How it checks</th><th style='width:20%'>Catches</th></tr>
<tr><td>L1 Authenticity</td><td>genuine and well formed?</td><td>Pydantic schema, <code>contract_version</code>, HMAC-SHA256 over a canonical body, constant-time compare</td><td>tampering, injection, malformed data</td></tr>
<tr><td>L2 Freshness</td><td>is it new?</td><td><code>sequence_no</code> strictly rising per sensor, timestamp skew; an agreed <code>sequence_reset</code> flag after a Twin restart</td><td>replay attacks</td></tr>
<tr><td>L3a Range and unit</td><td>physically possible?</td><td>per-type ranges, internal consistency (load &le; capacity), a unit heuristic (a value about 100&times; over range that fits after &divide;100 is cm sent as m)</td><td>faulty values, unit mix-ups</td></tr>
<tr><td>L3b Semantic</td><td>possible here?</td><td>the city model in <code>city_model.yaml</code>: a fire in the open sea, a flood above a zone&rsquo;s maximum level, a sensor in a zone without that feature</td><td>impossible context, crude spoofing</td></tr>
<tr><td>L4 Dynamics</td><td>does the change make sense?</td><td>rate of change, flatline (N identical readings), EWMA and z-score, a per-hour baseline, slow same-sign drift</td><td>fake spikes, frozen sensors, drift</td></tr>
<tr><td>L5 Corroboration</td><td>does the city agree?</td><td>independent sources from <code>crosschecks.yaml</code> (rain, flow and the upstream level for water; neighbouring zones), a minimum source count</td><td>single-sensor and subtle spoofing</td></tr>
<tr><td>L6 Liveness and rate</td><td>alive, at a normal pace?</td><td>no reading within twice the expected interval is stale; more than 5 emergency calls per zone per minute is a flood; a duplicate <code>call_id</code></td><td>dead devices, call floods</td></tr></table>
<p><b>Scoring</b> (<code>thresholds.yaml</code>): plausibility fail &minus;0.5, semantic suspect &minus;0.3, dynamics fail &minus;0.3, corroboration fail &minus;0.5, corroboration pass +0.2, liveness fail &minus;0.3, pattern fail &minus;0.2. A score of 0.8 or more is <i>trusted</i>, 0.4 to 0.8 <i>suspect</i>, below 0.4 <i>untrusted</i>; stale or missing data is <i>unknown</i>. In a zone whose threat level is raised, <i>trusted</i> needs 0.9 and two independent corroborating sources, and a reading with a big move needs corroboration to reach <i>trusted</i>.</p>
<p><b>Example</b> (T1, from the committed log). The port sensor <code>wl-port-03</code> reports 1.80 m while the real level is 0.40 m and there is no rain. Within 10 s the verdict is <i>untrusted</i> with the reasons <code>rate_of_change</code>, <code>no_rainfall_corroboration</code>, <code>no_flow_corroboration</code> and <code>no_upstream_level_corroboration</code>; the sensor is isolated; <code>/v1/readings/wl-port-03/latest</code> serves the rolled-back 0.41 m; and the Brain mock ignores the reading and leaves the valve alone.</p>
""", team))
    p.append(B.page(n + 2, head, """
<h3>3.2.2 Block B: actuator watch, ordered against happened</h3>
<p>The Brain sends its valve, grid, signal and dispatch calls through the Guardian (<code>POST /v1/actuator-calls</code>). A Twin reply of <code>status: ok</code> only means the call was accepted: a stuck valve or a lying controller can answer ok and do nothing.</p>
<table><tr><th style='width:25%'>Check</th><th>Detail</th></tr>
<tr><td>1. Authorisation</td><td>the call carries a <code>trust_ref</code> to a verdict that is trusted and not expired (30 s); no <code>trust_ref</code>, or a quarantined target, is blocked</td></tr>
<tr><td>2. Policy and safety invariants</td><td>from <code>policies.yaml</code>: no grid disconnect in the hospital zone, no repeated dispatch (same incident, station, unit, mode and zone), rate limits per caller and per actuator</td></tr>
<tr><td>3. Effect verification</td><td>an expectation with a deadline and a tolerance, watched by an independent sensor: valve closed, flow drops at least 80% within 30 s; grid disconnected, the zone&rsquo;s load near 0; signal green, traffic changes. No effect raises <code>actuator_failure</code> and marks the actuator unreliable, so further calls to it are refused</td></tr>
<tr><td>4. Audit</td><td>every call, decision and justification is logged and shown on the timeline</td></tr></table>
<p>If the verifying sensor is itself not trusted, the result is <i>unknown</i>: the Guardian never accuses an actuator on bad evidence (T5).</p>
<h3>3.2.3 Block C: threat correlation</h3>
<p>Checks on single readings cannot see an attack spread over many. The correlator groups verdicts and calls by zone, device, source and time window against the catalogue in <code>attack_patterns.yaml</code>. It raises a zone&rsquo;s threat level from <i>normal</i> to <i>elevated</i> to <i>under_attack</i>, which tightens the trust bar, and emits a security alert with its type, evidence and suggested response. Levels decay with hysteresis after 120 s of quiet.</p>
<table><tr><th style='width:24%'>Pattern</th><th>Signal</th><th style='width:30%'>Response</th></tr>
<tr><td><code>replay</code></td><td>a repeated <code>sequence_no</code> with a valid HMAC</td><td>untrusted; flag the source</td></tr>
<tr><td><code>spoofing</code></td><td>failed corroboration or impossible dynamics</td><td>isolate, roll back</td></tr>
<tr><td><code>coordinated_spoofing</code></td><td>several sensors in one zone fail within a window</td><td>zone <i>under_attack</i>, stricter trust</td></tr>
<tr><td><code>flood_dos</code></td><td>a message-rate spike, an emergency-call flood</td><td>throttle; mark for corroboration, never drop</td></tr>
<tr><td><code>tampering</code></td><td>HMAC failures, schema violations</td><td>reject; possible key compromise alert</td></tr>
<tr><td><code>command_injection</code></td><td>calls without <code>trust_ref</code>, bursts</td><td>block; quarantine the caller after 3</td></tr>
<tr><td><code>slow_drift</code></td><td>a small same-sign deviation over a long window</td><td>alert; freeze the baseline</td></tr>
<tr><td><code>compromised_twin</code></td><td>signatures valid, but corroboration collapses city-wide</td><td>alert advising safe mode</td></tr>
<tr><td><code>attack_during_incident</code></td><td>a real corroborated event and a fake alarm elsewhere</td><td>keep acting on trusted data only</td></tr></table>
<h3>3.2.4 Block D: containment</h3>
<table><tr><th style='width:22%'>Action</th><th>Effect</th><th style='width:38%'>Guardrail</th></tr>
<tr><td><code>isolate_sensor</code></td><td>its readings can no longer be used by the Brain</td><td>a cap per zone; evidence logged</td></tr>
<tr><td><code>quarantine_device</code></td><td>a sensor, actuator or caller is blocked</td><td>reversible; a reason is required</td></tr>
<tr><td><code>rollback</code></td><td>serves the last known good value, marked <code>rolled_back: true</code></td><td>visible in the log and the API</td></tr>
<tr><td><code>clear_quarantine</code></td><td>release after clean readings</td><td>hysteresis, a growing cool-down, a manual release endpoint</td></tr></table>
<p>Containment goes to the Twin as calls with <code>requesting_layer: guardian</code>; the Guardian authorises its own containment. Caps and release paths stop an attacker from turning quarantine against healthy sensors.</p>
""", team))
    stack = [(("python",), "Language", "Python 3.11+, asyncio", "fast to write detection logic; a non-blocking pipeline"),
             (("fastapi",), "Brain-facing API", "FastAPI (REST and WebSocket), OpenAPI at <code>/docs</code>", "standard, self-documenting, validated input"),
             (("modelcontextprotocol", "mqtt"), "Twin transport", "REST push or pull by default; MCP and MQTT adapters", "the Twin may expose MCP-style tools or a stream; switched by configuration"),
             (("pydantic",), "Validation", "Pydantic v2", "strict schemas and precise error messages"),
             ((), "Crypto", "standard-library <code>hmac</code> and <code>hashlib</code> (SHA-256)", "no custom crypto; constant-time compare"),
             (("sqlite",), "State", "in-memory ring buffers and SQLite", "no external infrastructure; survives a restart"),
             (("numpy",), "Statistics", "NumPy; scikit-learn Isolation Forest, off by default", "light and explainable; the model can only lower trust"),
             ((), "Config, logs", "7 YAML files and <code>.env</code>; structlog JSONL, WebSocket, an HTML screen", "nothing partner-specific in code; machine-checkable logs (R2), a live view (R3)"),
             (("pytest", "docker"), "Quality, packaging", "pytest, hypothesis, ruff, mypy; Docker Compose with both mocks", "unit, integration, fuzz and scenario tests; one command, nothing installed on stage, runs offline")]
    stack_rows = "".join(f"<tr><td>{logo_cell(l)}</td><td><b>{c}</b><br>{ch}</td><td>{why}</td></tr>" for l, c, ch, why in stack)
    p.append(B.page(n + 3, head, f"""
<h2>3.3 Tech stack and why</h2>
<p class='cap' style='margin:0'><b>Table 3.1.</b> The Guardian&rsquo;s stack. Each logo belongs to its owner.</p>
<table class='stack'><tr><th style='width:11%'></th><th style='width:36%'>Concern and choice</th><th>Why</th></tr>{stack_rows}</table>
<p>Left out on purpose: Kafka, Kubernetes, deep learning and external databases, which add demo risk without improving a trust decision.</p>
<h2>3.4 Interfaces in/out</h2>
<table><tr><th style='width:19%'>Direction</th><th style='width:43%'>Message and transport</th><th>Purpose</th></tr>
<tr><td>Twin &rarr; Guardian</td><td>the signed sensor envelope: <code>POST /v1/readings</code> (push), or pull over HTTP, MCP <code>get_readings</code> or MQTT <code>city/readings/#</code></td><td>the evidence to judge</td></tr>
<tr><td>Brain &rarr; Guardian</td><td><code>POST /v1/verdicts/request</code></td><td>the check before acting</td></tr>
<tr><td>Guardian &rarr; Brain</td><td>the signed verdict in reply; verdicts and alerts also on <code>WS /v1/ws/verdicts</code></td><td>safe decisions</td></tr>
<tr><td>Brain &rarr; Guardian &rarr; Twin</td><td><code>POST /v1/actuator-calls</code> with a <code>trust_ref</code>, forwarded to <code>POST {{twin}}/tools/{{action}}</code></td><td>the audited actuator gateway</td></tr>
<tr><td>Guardian &rarr; Twin</td><td>containment calls (isolate, quarantine, clear)</td><td>the city really changes</td></tr>
<tr><td>Guardian &rarr; everyone</td><td><code>WS /v1/ws/timeline</code>, the <code>/timeline</code> screen, JSONL logs</td><td>cause and effect (R2, R3)</td></tr></table>
<p class='cap' style='margin:2mm 0 0'><b>Listing 3.1.</b> A verdict, from the Guardian to the Brain (abridged). Every message has an example in the Interface Card, <code>guardian/INTERFACE.md</code>.</p>
<pre class='log'>{{ "verdict_id": "verdict-88213",
  "reading_ref": {{"sensor_id": "wl-port-03", "sequence_no": 4821}},
  "status": "untrusted", "trust_score": 0.2,
  "reasons": ["rate_of_change", "no_rainfall_corroboration", "no_flow_corroboration"],
  "layer_results": [ {{"layer": "L1_authenticity", "passed": true, ...}}, ... ],
  "action_taken": "isolate_sensor", "threat_level": "normal",
  "ts": "...", "expires_at": "...", "signature": "&lt;HMAC-SHA256&gt;" }}</pre>
<p><b>Other endpoints:</b> <code>/health</code>, <code>/v1/readings/{{id}}/latest</code> (the rolled-back value when contained), <code>/v1/sensors/{{id}}/status</code>, <code>/v1/threat</code>, <code>/v1/alerts</code>, <code>/v1/containment</code> (with <code>/clear</code> and <code>/quarantine</code>), <code>/v1/verify/signature</code>.</p>
""", team))
    p.append(B.page(n + 4, head, """
<p><b>Repointing to another partner</b> (Phase 2) means changing <code>twin.base_url</code>, <code>twin.transport</code> (rest, mcp or mqtt) and <code>twin.mode</code> (push or pull) in <code>config/guardian.yaml</code> or the environment, and the shared keys in <code>.env</code>. In the triplet&rsquo;s Compose file the Guardian also accepts the shared names <code>GUARDIAN_URL</code> (port 8003), <code>TWIN_URL</code> and <code>TWIN_HMAC_SECRET</code>. No code changes.</p>
<p><b>Input validation and errors.</b> Every endpoint answers malformed input with a 4xx and one body shape, <code>{"error", "message", "field"}</code>; the codes include <code>schema_invalid</code>, <code>contract_version_mismatch</code>, <code>hmac_invalid</code>, <code>auth_required</code>, <code>trust_ref_missing</code> and <code>verdict_not_found</code>. A well-formed reading with a bad HMAC is not an error but an untrusted verdict. A bad configuration file stops start-up and names the file and the field.</p>
<h2>3.5 Security measures</h2>
<ul class='items'>
<li><b>Authenticated API.</b> One API key per partner (<code>X-API-Key</code>; <code>?api_key=</code> for browser WebSockets, closed with 4401 on a bad key). The key decides the caller identity used in audit and quarantine.</li>
<li><b>Signed data both ways.</b> Sensor envelopes are checked with the Twin&rsquo;s HMAC key, and verdicts are signed with the Guardian&rsquo;s key, so the Brain can detect a forged verdict. Both use the same canonical form, and an endpoint checks it.</li>
<li><b>Replay protection.</b> Strict sequence numbers per sensor and a timestamp skew limit; an explicit, signed <code>sequence_reset</code> for a legitimate restart.</li>
<li><b>A gate on actions.</b> Every actuator call needs a fresh trusted verdict and passes the safety invariants and rate limits; a caller that injects commands is quarantined.</li>
<li><b>Fail-safe.</b> If the Guardian is unreachable or a verdict is missing, expired or not trusted, the Brain treats the data as unknown and does not act. An internal error gives <i>unknown</i>, never <i>trusted</i>. A silent Twin turns every sensor unknown after twice its interval (T7).</li>
<li><b>Proportionate response.</b> Isolation caps per zone, hysteresis, a growing cool-down and a manual release path, so the defence cannot be turned against healthy sensors.</li>
<li><b>Secrets out of code.</b> Keys live only in <code>.env</code> (git-ignored), and the service refuses to start without them.</li>
</ul>
<h3>Handling of false alarms</h3>
<table><tr><th style='width:31%'>Risk</th><th>How the Guardian avoids it</th></tr>
<tr><td>A real event looks abrupt (a burst pipe, a real flood)</td><td>dynamics alone only gives <i>suspect</i>; corroboration decides. The real flood in T11 stays trusted</td></tr>
<tr><td>An incomplete city map</td><td>semantic failures are <i>suspect</i> unless physically impossible (a fire in the open sea)</td></tr>
<tr><td>A real disaster brings many calls</td><td>call floods are throttled and marked for corroboration, never dropped</td></tr>
<tr><td>Its own order changes a sensor (valve closed, flow drops)</td><td>a change explained by a call the Guardian forwarded is not flagged during the expectation window</td></tr>
<tr><td>A bad verification sensor; a Twin restart</td><td>an untrusted verify sensor gives <i>unknown</i>; a signed <code>sequence_reset</code> is accepted instead of raising replay</td></tr>
<tr><td>Flapping isolation</td><td>release after clean readings, hysteresis, a growing cool-down, caps per zone</td></tr></table>
<h2>3.6 Known limitations</h2>
<div class='cols'><div><ul class='items'>
<li><b>A compromised Twin.</b> If the Twin itself lies, HMAC does not help. Corroboration is the defence and weakens as more sensors are spoofed together; a city-wide collapse raises <code>compromised_twin</code> but cannot say which value is true.</li>
<li><b>HMAC proves origin, not truth.</b> A compromised sensor signs lies perfectly; that is why L3 to L6 exist.</li>
<li><b>Two sources for trusted.</b> A notable reading needs two independent sources; a sensor with no corroboration path can only be <i>suspect</i>.</li>
<li><b>Thresholds.</b> They trade false alarms against missed attacks; the defaults suit the mock city and need tuning on the real Twin.</li>
</ul></div><div><ul class='items'>
<li><b>Baselines learn online</b> from trusted readings only (at least 200 samples per hour bucket); an attack present from the very start is caught only by the other layers. A recorded normal day from the Twin would help.</li>
<li><b>A stolen Brain key</b> could be used to get a caller quarantined.</li>
<li><b>One process.</b> State is in memory and SQLite; several replicas would need shared state. Effect windows are fixed per action.</li>
</ul></div></div>
""", team))
    return p


GUARDIAN = [("T1", "Fake flood at the port (1.80 m vs 0.40 m, no rain)", "untrusted within 10 s, sensor isolated, rollback serves 0.40 m; the Brain does not move the valve"),
            ("T2", "Stuck or dead sensor", "flatline gives suspect; silence gives stale, then unknown"),
            ("T3", "Replayed readings", "a repeated sequence_no with a valid HMAC is untrusted (replay); a signed sequence_reset is accepted"),
            ("T4", "Emergency-call flood", "over 5 calls per zone per minute: call_flood, suspect, throttled, none dropped"),
            ("T5", "Valve closed, no effect", "actuator_failure alert; with an untrusted flow sensor the result is unknown instead"),
            ("T6", "The Brain uses a quarantined device", "call blocked, reason device_quarantined"),
            ("T7", "Twin goes silent", "every sensor unknown, /health degraded"),
            ("T8", "Fire in the open sea", "untrusted (impossible_location), dispatch blocked"),
            ("T9", "Coordinated spoofing in a zone", "zone under_attack: trusted needs 0.9 and 2 sources; back to normal with hysteresis"),
            ("T10", "Command injection without trust_ref", "blocked; the caller quarantined after 3; command_injection alert"),
            ("T11", "Real flood and an attack elsewhere", "the corroborated flood trusted, the valve call forwarded and verified; the fake alarm untrusted")]
BRAIN = [("T12", "A calm day", "no incident and no actuator call: the Brain does not overreact"),
         ("T13", "A fake flood", "the gauge is untrusted; the gate refuses the warning and the valve; nothing reaches the city"),
         ("T14", "A crime and a pursuit", "reflex dispatch with a trust_ref, a solver-checked perimeter, every unit recalled at the arrest"),
         ("T15", "A flood, an attack and a layer down", "warning sent, valve held, no police for the forged report; once the Guardian is silent, no action on unjudged readings"),
         ("T16", "A quarantined police station", "every call to the quarantined station refused (quarantine); the pursuit unit leaves another station")]
TWIN = [("T17", "A car hits a walker (Part 1: T1)", "a witness calls, the signed emergency_call is trusted, the Brain dispatches an ambulance and police with a trust_ref, the street closes and reopens; 10 of 10 expected events, PASS at 245 s"),
        ("T18", "Part 1: T2, at junction 2", "10 of 10 expected events of the three layers, PASS at 287 s"),
        ("T19", "Part 1: T3, at a building in block A", "9 of 9 expected events, PASS at 146 s"),
        ("T20", "A street floods at its low point (Part 1: T4)", "12 of 12 expected events, PASS at 340 s")]


def part4() -> list[str]:
    def rows(team, items):
        return "".join(f"<tr><td>{i}</td><td>{team}</td><td>{B.esc(name)}</td><td>{B.esc(exp)}</td></tr>" for i, name, exp in items)
    head = "<table class='gate'><tr><th style='width:5%'>ID</th><th style='width:9%'>Team</th><th style='width:27%'>Scenario</th><th>Expected, observable</th></tr>"
    p = []
    p.append(B.page(19, "Part 4 · Test Book", f"""
<h1>4. Test Book</h1>
<p class='meta'>All three teams · one numbering: T1 to T11 the Guardian team&rsquo;s, T12 to T16 the City Brain team&rsquo;s, T17 to T20 the Twin team&rsquo;s · every field (description, trigger, expected output per layer, how to verify) in <code>TESTBOOK.md</code></p>
<p>Taken together the scenarios test all three layers and every interaction between them. Each starts from one trigger and leaves one log, so the jury can check a run after the event.</p>
<table><tr><th style='width:17%'>Interaction</th><th style='width:40%'>What it shows</th><th>Scenarios</th></tr>
<tr><td>Twin &rarr; Brain</td><td>the city runs normally and the Brain reacts correctly to real events</td><td>T12, T14, T17 to T20</td></tr>
<tr><td>Twin &rarr; Guardian</td><td>the Guardian recognises healthy and unhealthy data</td><td>T1 to T4, T7 to T9, T13</td></tr>
<tr><td>Brain &rarr; Guardian</td><td>trust verdicts change decisions, and decisions stay safe</td><td>T5, T6, T10, T13, T14, T16</td></tr>
<tr><td>All three</td><td>the city works as one system, including when something goes wrong</td><td>T11, T15</td></tr></table>
<table><tr><th style='width:12%'>Team</th><th style='width:44%'>Trigger</th><th>Log</th></tr>
<tr><td>Guardian</td><td><code>make scenario T=T1</code> in <code>guardian/</code></td><td><code>logs/t1-guardian-*.log</code></td></tr>
<tr><td>City Brain</td><td><code>brain/scenarios/triggers/t12.sh</code>, or a number key on the screen</td><td><code>logs/t12-*.jsonl</code>, hash-chained</td></tr>
<tr><td>Twin</td><td><code>docker compose run --rm scenario t1</code>, or a button in the viewer</td><td><code>logs/t1-*.log</code>, ending in PASS or FAIL</td></tr></table>
{head}{rows("Guardian", GUARDIAN)}</table>
""", TEAMS))
    p.append(B.page(20, "Part 4 · Test Book", f"""
{head}{rows("City Brain", BRAIN)}{rows("Twin", TWIN)}</table>
<p class='cap'>The Guardian&rsquo;s scenarios run against its own Twin and Brain mocks, the Brain&rsquo;s against its mocks of the Twin and the Guardian, and the Twin&rsquo;s against its mocks of the other two. The Twin team numbers its scenarios T1 to T4 in Part 1; T18 and T19 are described here only as far as Part 1 describes them.</p>
""", TEAMS))
    return p


def twin_numbers(first: int, count: int) -> str:
    """Pages that cover the Twin PDF's own page number (bottom right, as in every part) and print the report's number in its place."""
    box = ("<svg style='position:absolute;right:36pt;top:811pt;width:36pt;height:19pt;margin:0' viewBox='0 0 36 19'>"
           "<rect width='36' height='19' fill='#fff'/></svg>")
    return "".join(f"<section style='width:210mm;height:297mm;position:relative;break-after:page'>{box}"
                   f"<span style='position:absolute;right:42.4pt;top:816.4pt;font:400 7.4pt/10pt Inter,sans-serif;color:#4A5156'>{first + k}</span></section>"
                   for k in range(count))


def main() -> int:
    if not TWIN_PDF.exists():
        print(f"error: missing {TWIN_PDF.relative_to(ROOT)}", file=sys.stderr)
        return 1
    twin = PdfReader(TWIN_PDF)
    with tempfile.TemporaryDirectory() as work:
        w_ = Path(work)
        jobs = {"p0": part0(), "p2": B.part2(9), "p3": part3(14), "p4": part4()}
        printed = [(w_ / f"{k}.pdf", B.document(False, v, k)) for k, v in jobs.items()]
        overlay = B.document(False, [twin_numbers(4, len(twin.pages))], "numbers").replace("html,body{margin:0;background:#fff;", "html,body{margin:0;background:transparent;")
        if not B.print_pdfs(printed + [(w_ / "numbers.pdf", overlay)]):
            return 1
        numbers = PdfReader(w_ / "numbers.pdf")
        w = PdfWriter()
        sections = [("Part 0 · Triplet overview and integration", list(PdfReader(w_ / "p0.pdf").pages)), ("Part 1 · The City (Twin)", list(twin.pages)),
                    ("Part 2 · The City Brain", list(PdfReader(w_ / "p2.pdf").pages)), ("Part 3 · The Guardian", list(PdfReader(w_ / "p3.pdf").pages)),
                    ("Part 4 · Test Book", list(PdfReader(w_ / "p4.pdf").pages))]
        for title, pages in sections:
            start = len(w.pages)
            for k, pg in enumerate(pages):
                added = w.add_page(pg)
                if title.startswith("Part 1"):
                    added.merge_page(numbers.pages[k])  # the report's page number over the Twin PDF's own
            w.add_outline_item(title, start)
        w.add_metadata({"/Title": "Triplet 03 · TSYP14 City Brain Convergence, Phase 1 report", "/Author": "Triplet 03: Twin, City Brain and Guardian teams"})
        w.page_mode = "/UseOutlines"
        with OUT.open("wb") as f:
            w.write(f)
    sizes = [len(p) for _, p in sections]
    print(f"wrote {OUT.relative_to(ROOT)} ({len(w.pages)} pages: {' + '.join(map(str, sizes))})")
    return 0 if sizes == [3, 5, 5, 5, 2] else 2


if __name__ == "__main__":
    sys.exit(main())
