/* The story the screen tells: one plain sentence per timeline event that matters, tagged with the layer that acts and its step on the relay.
   Both views read this table, so the canopy and the strip cannot disagree. An event with no entry returns null and belongs to the Details drawer.
   A plain script, loaded by index.html; Node loads it too (tests/test_story_js.py). */
(function (root) {
  "use strict";
  const STEPS = ["Twin", "Guardian", "Brain", "Safety gate", "City"];
  /* What each element is for, in the words the presenter uses: one short line for the bar, one longer for the tooltip and the walkthrough. */
  const ROLES = [
    { name: "Twin", job: "Senses the city", long: "The partner's simulated city. Its sensors report what happens, and it carries out what the Brain orders. It decides nothing." },
    { name: "Guardian", job: "Judges each reading", long: "The partner's trust layer. It says whether each reading is trusted, doubted or not trusted. It never acts." },
    { name: "Brain", job: "Decides what to do", long: "Our layer. It works out what is happening and what to do: a written rule for a clear case, a team of agents for a hard one." },
    { name: "Safety gate", job: "Checks and signs", long: "The only way out of the Brain. Code, never a model, checks every order and signs it, or holds it and says why." },
    { name: "City", job: "Does it", long: "The Twin carrying out a signed order: a unit moves, a warning goes out. It answers that it did." },
  ];
  const zone = (s, id) => (s && s.zones && s.zones.get && (s.zones.get(id) || {}).name) || String(id || "the city").replace(/^zone-0?/, "zone ");
  const sensorWord = { water_level: "water gauge", traffic_camera: "traffic camera", cctv_anomaly: "security camera", citizen_activity: "citizen sensor",
    power_load: "power meter", air_quality: "air sensor", unit_status: "unit report", emergency_call: "emergency call" };
  const incidentWord = { crime: "crime", flood: "flood", fire: "fire", accident: "accident", jam: "traffic jam", overload: "power overload", smog: "smog" };
  const unitWord = { police: "police unit", fire: "fire engine", ambulance: "ambulance" };
  const unitState = { en_route: "is on its way", in_position: "is in position", pursuing: "is pursuing the suspect", apprehended: "has caught the suspect", returning: "is heading home", idle: "is free" };
  const ago = n => `${n} minute${n === 1 ? "" : "s"}`;

  function phrase(action, params, s) {
    const where = zone(s, params.zone_id);
    if (action === "dispatch_unit" && params.mode === "pursuit") return `send a police unit after the suspect from ${where}`;
    if (action === "dispatch_unit" && params.mode === "contain") return `post a police unit in ${where}`;
    if (action === "dispatch_unit") return `send a ${unitWord[params.unit_type] || "unit"} to ${where}`;
    if (action === "broadcast_alert") return `warn ${where}`;
    if (action === "set_valve_state") return `${params.state === "closed" ? "close" : "open"} the valve`;
    if (action === "set_grid_connection") return `${params.state === "disconnected" ? "cut" : "reconnect"} the power in ${where}`;
    if (action === "set_signal_phase") return "hold a traffic signal";
    if (action === "recall_unit") return "send a unit home";
    return String(action || "act").replace(/_/g, " ");
  }
  const heldWhy = d => d.check === "trust_ref" ? "no trusted Guardian verdict stands behind it"
    : d.check === "evidence" ? "it needs two independent trusted sources and only one agrees"
    : d.check === "human_approval" ? "a person must approve it first"
    : String(d.reason || "a safety check failed").replace(/\.$/, "");

  const unitName = id => String(id || "A unit").replace(/^unit-/, "Unit ");
  const TABLE = {
    "brain.reading.received": (e, s, d) => ({ layer: "TWIN", step: 0, tone: "go", quiet: true,
      say: `The ${sensorWord[d.type] || "sensor"} in ${zone(s, d.zone_id)} reports${d.summary ? `: ${d.summary}` : ""}.`,
      why: "Every reading enters here, signed, and is checked before anything depends on it." }),
    "brain.verdict.received": (e, s, d) => d.status === "trusted"
      ? { layer: "GUARDIAN", step: 1, tone: "go", quiet: true, say: "The Guardian says the reading is trusted.",
          why: "The Brain never acts on a reading the Guardian has not vouched for." }
      : d.status === "untrusted" || d.status === "suspicious"
        ? { layer: "GUARDIAN", step: 1, tone: "hold", say: `The Guardian ${d.status === "untrusted" ? "does not trust" : "doubts"} that reading.`,
            why: "The Brain will still look at it, but it cannot be the reason for any order." }
        : null,  /* no verdict at all is said once, by brain.guardian.unavailable */
    "brain.guardian.unavailable": () => ({ layer: "GUARDIAN", step: 1, tone: "hold",
      say: "The Guardian has stopped answering, so the Brain keeps watching but acts on nothing new until it returns.",
      why: "Every action needs a trusted verdict: no verdict, no action, which is also the Guardian's own fail-safe rule." }),
    "brain.incident.opened": (e, s, d) => ({ layer: "BRAIN", step: 2, tone: "now",
      say: `The Brain opens a ${incidentWord[d.type] || d.type} incident in ${zone(s, d.zone_id)}${d.evidence_verdict === "untrusted" ? ", though its evidence is not trusted" : ""}.`,
      why: "An incident is the Brain's file on one event: it collects every reading about it and tracks it until it closes." }),
    "brain.workspace.ignited": (e, s, d) => ({ layer: "BRAIN", step: 2, tone: "now",
      say: `The Brain gives the ${incidentWord[d.type] || d.type} in ${zone(s, d.zone_id)} its full attention${d.slot === false ? ", without needing a team of agents" : ", with a seat for the team of agents"}.`,
      why: "Attention is limited on purpose: only the most urgent incidents get the team, so a flood of alerts cannot swamp it." }),
    "brain.pack.bid": (e, s, d) => { const won = (d.recruited || []).map(x => String(x).toLowerCase()); return won.length ? ({ layer: "BRAIN", step: 2, tone: "now",
      say: `The departments say how well they can answer; the ${won.join(" and ")} team takes it.`,
      why: "Each department (police, fire, medical, traffic, disaster, utilities) bids for the incidents it knows how to handle." }) : null; },
    "brain.suspect.assessed": (e, s, d) => ({ layer: "BRAIN", step: 2, tone: "now",
      say: `The Brain rates ${d.entity_id} a ${d.level === "suspect" ? "suspect" : "person of interest"} (score ${Number(d.score).toFixed(2)}).`,
      why: "The score adds up evidence: who was at the scene, who ran, and how far each source is trusted. Nobody is named on one clue." }),
    "brain.suspect.tracked": (e, s, d) => ({ layer: "BRAIN", step: 2, tone: "go",
      say: `The suspect (${d.entity_id}) is seen again, now in ${zone(s, d.zone_id)}.`,
      why: "The Brain follows the suspect so the units can be placed where they are going, not where they were." }),
    "brain.forecast.warned": (e, s, d) => ({ layer: "BRAIN", step: 2, tone: "now",
      say: `The water in ${zone(s, d.zone_id)} is rising fast and would pass the flood line in about ${ago(Math.max(1, Math.round(d.seconds_to_threshold / 60)))}, so the Brain warns people early.`,
      why: "A filter estimates how fast the level is rising from the trusted readings, so people are warned before the line, not after." }),
    "brain.deliberation.started": (e, s, d) => ({ layer: "BRAIN", step: 2, tone: "now",
      say: d.reason === "plan" ? "The police team starts planning how to catch the suspect." : "The responsible team starts reviewing the incident.",
      why: "A rule has already acted. The team (an Analyst, a Tactician and a Chief) now works on the harder part, in the background." }),
    "brain.case.reviewed": (e, s, d) => ({ layer: "BRAIN", step: 2, tone: "now",
      say: `The Analyst reviews the evidence and recommends to ${String(d.recommendation || "wait")}${d.confidence ? ` (${d.confidence} confidence)` : ""}.`,
      why: "The Analyst may only read and cite: it cannot act, and every claim must point to a reading." }),
    "brain.options.prepared": (e, s, d) => ({ layer: "BRAIN", step: 2, tone: "now",
      say: `The Tactician prepares ${(d.options || []).length || "several"} ways to respond, from a tight perimeter to sealing the exits.`,
      why: "The Tactician proposes options with their costs and risks; it does not choose." }),
    "brain.perimeter.checked": (e, s, d) => ({ layer: "BRAIN", step: 2, tone: "go",
      say: `Code checks the perimeter: the team holds ${d.team_units} zones and a calculation says ${d.optimal_units} would be enough.`,
      why: "A calculation gives the best possible answer as a yardstick, so the team's plan is measured, not just trusted." }),
    "brain.plan.verified": (e, s, d) => ({ layer: "BRAIN", step: 2, tone: "go",
      say: `The Chief picks ${String(d.option || "a plan").replace(/-/g, " ")}, and code checks it before it goes anywhere near the city.`,
      why: "A model proposes; code verifies. A plan that breaks a rule is thrown out before it becomes an order." }),
    "brain.deliberation.finished": (e, s, d) => ({ layer: "BRAIN", step: 2, tone: d.status === "completed" ? "go" : "hold",
      say: d.status === "completed" ? `The team is done: ${d.actions} order${d.actions === 1 ? "" : "s"} for the Safety gate.` : "The team stops: the incident closed before it finished.",
      why: "Nothing the team decided has any effect until the Safety gate lets it through." }),
    "brain.decision.made": (e, s, d) => ({ layer: "BRAIN", step: 2, tone: "now", say: `The Brain decides to ${phrase(d.action, d.params || {}, s)}.`,
      why: d.tier === "reflex" ? "A written rule fits this case exactly, so it answers at once, without waiting for the team." : "This order comes from the team's verified plan." }),
    "brain.action.requested": (e, s, d) => ({ layer: "GATE", step: 3, tone: "now", say: `The Safety gate checks the order to ${phrase(d.action, d.params || {}, s)} and signs it.`,
      why: "The gate checks the order's trust, evidence, limits and who may approve it, then signs it. Only a signed order reaches the city." }),
    "brain.action.blocked": (e, s, d) => ({ layer: "GATE", step: 3, tone: "hold",
      say: `The Safety gate holds the order to ${phrase(d.would_have, d.params || {}, s)}: ${heldWhy(d)}.`,
      why: "Holding back is the gate doing its job: a wrong action in a real city costs more than a late one." }),
    "brain.action.result": (e, s, d) => ({ layer: "CITY", step: 4, tone: "go",
      say: d.status === "dispatched" ? `${unitName(d.unit_id)} is on its way${d.eta_minutes ? `, arriving in ${ago(d.eta_minutes)}` : ""}.`
        : d.status === "broadcast" ? `The warning reaches ${zone(s, d.zone_id)}.`
        : d.status === "recalled" ? "The unit goes home."
        : `The city answers: ${String(d.status || "done").replace(/_/g, " ")}.`,
      why: "The Twin carries out the signed order and answers that it did, so the Brain knows it happened." }),
    "brain.unit.status": (e, s, d) => ({ layer: "CITY", step: 4, tone: "go", say: `${unitName(d.unit_id)} ${unitState[d.state] || String(d.state || "reports").replace(/_/g, " ")}.`,
      why: "The Twin reports back, and the Guardian vouches for the report, so the Brain sees the result of its own order." }),
    "brain.units.released": () => ({ layer: "CITY", step: 4, tone: "go", say: "The incident is over, so the units on the perimeter go home.",
      why: "The Brain brings back every unit it sent, so none is left posted after the danger has passed." }),
    "brain.incident.closed": (e, s, d) => ({ layer: "BRAIN", step: 2, tone: "go",
      say: `The incident closes: ${d.outcome === "cleared" ? "the danger has passed" : d.outcome === "apprehended" ? "the suspect was caught" : String(d.outcome || "finished").replace(/_/g, " ")}.`,
      why: "A closed incident is kept as a story, so the Brain can learn from it while the city is quiet." }),
    "brain.human.needed": (e, s, d) => ({ layer: "GATE", step: 3, tone: "hold", say: `A person is needed: ${String(d.message || d.why || "the Brain cannot decide this alone").replace(/_/g, " ").replace(/\.$/, "")}.`,
      why: "When no rule or plan fits, the Brain asks instead of guessing." }),
    "brain.reading.rejected": (e, s, d) => ({ layer: "TWIN", step: 0, tone: "hold", say: `A message was refused: ${String(d.message || d.code || "it was not valid").replace(/\.$/, "")}.`,
      why: "Every message is validated at the door and refused with a named reason, never silently." }),
    "brain.degraded": () => ({ layer: "TWIN", step: 0, tone: "hold", say: "The Twin has stopped answering. The Brain keeps what it holds and tries again.",
      why: "A partner can fail. The Brain says so once, keeps its state and sends nothing twice." }),
    "brain.recovered": () => ({ layer: "TWIN", step: 0, tone: "go", say: "The Twin answers again and the Brain reads on from where it stopped.",
      why: "Nothing was lost while it was away." }),
    "brain.scenario.finished": (e, s, d) => ({ layer: "BRAIN", step: 2, tone: d.passed ? "go" : "hold",
      say: d.passed ? "The scenario is over and every expectation was met." : "The scenario is over, but an expectation was not met.",
      why: "Each scenario states in advance what each layer must do; this is the check against it." }),
  };

  function storyOf(e, s) {
    const make = TABLE[e && e.type];
    if (!make) return null;
    try { return make(e, s, e.data || {}); } catch (error) { return null; }
  }

  const api = { storyOf, STEPS, ROLES, TABLE };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.STORY = api;
})(typeof window !== "undefined" ? window : globalThis);
