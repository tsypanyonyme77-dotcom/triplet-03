"""Writes docs/BRAIN-MAPPING.md and docs/brain-mapping.html: what in neurophysiology inspired each region of the Brain,
how the region is implemented, and how it maps to the agents and to the architecture's planes.

    uv run python docs/diagrams/brain_map.py

One source for both files. The neuroscience comes from `../reports/Brain inspired City Brain architecture.md` and
`../reports/Inside the City Brain regions.md` (sources marked "established" there were read, at least as abstracts).
A source marked *to verify* is not in those notes and must be checked before it is quoted in the report. The parameters
are the defaults in `src/brain/config.py` on 4 Nov 2026; measurements are from `docs/STATE.md` and the 4 Nov runs.
"""

from __future__ import annotations

from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]

# One row per region on the canopy, in the order a reading travels. `at` is the region's place in the glass brain
# (POS in canopy3d.js, x towards the front, y up), used to draw the side view.
REGIONS = [
    dict(
        id="senses", name="Senses", at=(-9.4, 10.6), where="back of the cortex", analogue="Sensory input and thalamic gating",
        neuro="The thalamic reticular nucleus works as a searchlight that gates what reaches cortex (Crick 1984; Halassa and Kastner 2017). Input is weighted by how reliable it is (Ernst and Banks 2002), and attention can be read as inferring each input's precision (Feldman and Friston 2010).",
        code="`perception/` checks the contract version, the HMAC signature, the sequence number (replay) and the ranges, drops every field outside an allowlist (demographic fields never enter), and applies renames and units from config after the signature check. The Guardian then judges each reading (`POST /verdicts`, or by sensor and sequence number with contract 1.0; 2 s deadline; no verdict, no action). Trust reaches attention as a damping factor: a trusted verdict counts in full from confidence 0.9 and in proportion below.",
        params="Accepted contract versions; `verdict_deadline_ms` 2000; `trust_full_at` 0.9; stable rejection codes such as `signature_invalid`, `replay_or_out_of_order`.",
        agents="No agent. Agents only ever see typed values that came through here.",
        plane="1 Interop edge and 2 Senses and trust",
        breaks="A thalamus does not check signatures. The analogy is the *gating by reliability*; the reliability judgement itself comes from another team's layer, the Guardian.",
    ),
    dict(
        id="forward", name="Forward models", at=(-6.4, 7.0), where="cerebellum", analogue="Cerebellar internal models; prediction error",
        neuro="The cerebellum predicts the sensory result of an action and the error drives correction (Wolpert, Miall and Kawato 1998). Cortex answers a rare stimulus more than a common one (Ulanovsky, Las and Nelken 2003). The nervous system cancels the expected result of its own movement (Blakemore, Wolpert and Frith 1998; Crapse and Sommer 2008). Learning has a fast and a slow memory (Smith, Ghazizadeh and Shadmehr 2006) and a rate that follows volatility (Nassar et al. 2010; Behrens et al. 2007).",
        code="`mind/forward.py`: per sensor and field, a running mean and variance. A reading many spreads from the prediction is a *surprise*. The first of a run is *doubted* and the reflex that would act on it is held (`brain.action.blocked`, check `surprise`); the next in the same direction confirms; three in a row make a new normal. A surprising reading never moves the baseline, so a spoofed spike cannot teach itself as normal. Only trusted readings teach; a retracted reading is forgotten and the baseline rebuilt; a previous normal is remembered and can be recovered. `mind/effects.py` is the corollary discharge: after an action the gate let through, the declared effect is expected, not doubted. `mind/neighbours.py` follows the difference between two sensors that should move together.",
        params="`alpha` 0.2, `warmup` 5, `z_threshold` 4.0 (the Academy proposed 3.75, not enabled), `adopt_after` 3, a spread floor per field and 2% of the value, `history` 200. Off: `calibration: quantile`, `effects` and `coupled` (both wait for the Twin team to say what its actuators do and which sensors move together).",
        agents="No agent. A doubted reading stops reflexes and lowers nothing an agent sees except the surprise feature.",
        plane="2 Senses and trust. Plan 2 adds a Kalman tracker (level and rate) here.",
        breaks="Surprise is a z-score, not Bayesian surprise (Itti and Baldi 2009). The learning rate is fixed on purpose: an adaptive one would open a route for an attacker to teach the Brain a spike. The 'fast and slow memory' is only the remembered previous normal.",
    ),
    dict(
        id="triage", name="Triage", at=(-3.6, 11.6), where="deep in the middle", analogue="Amygdala 'low road': fast, coarse threat appraisal",
        neuro="A fast subcortical route reacts to threat before slower cortical analysis finishes (LeDoux 2000); the salience network flags what matters (Menon and Uddin 2010).",
        code="`triage/` and the packs' detectors open incidents deterministically: crime from CCTV anomaly types at confidence 0.5 or more, flood from a water level of 1.0 m (cleared at 0.6 m), overload at 95% of capacity, smog at AQI 150, and fire, accident and jam from their detectors. Evidence joins an open incident within 300 s (crime) or 600 s (others).",
        params="Seven incident types; `min_confidence` 0.5; merge windows 300 s and 600 s.",
        agents="No agent. Triage decides what exists to think about; it never calls a model.",
        plane="2 Senses and trust into 3 Understanding",
        breaks="No valence or learning: these are rules written in pack files. The parallel is speed and coarseness, not mechanism.",
    ),
    dict(
        id="workspace", name="Workspace", at=(3.0, 13.0), where="front, top", analogue="Global neuronal workspace; salience network; limited capacity",
        neuro="A content that crosses a threshold 'ignites' and is broadcast to many specialised processors (Mashour, Roelfsema, Changeux and Dehaene 2020). Working memory holds about four chunks (Cowan 2001; Luck and Vogel 1997) or a shared resource (Ma, Husain and Bays 2014). Activity is scarce for energy reasons (Attwell and Laughlin 2001). Urgency grows with waiting (Cisek, Puskas and El-Murr 2009).",
        code="`mind/salience.py` scores each incident: a weighted mean of severity, trust, corroboration, novelty and clustering, multiplied by the share of trusted evidence and by freshness, plus a surprise boost damped the same way, so an incident on untrusted readings scores zero. `mind/workspace.py` holds two slots: an incident ignites at 0.5, releases under 0.3, and a newcomer must beat the weakest by 0.1 (hysteresis). Only incident types an agent team can act on compete for a slot; a flood or a jam is lit and broadcast without one. Ignition, release and deferral are timeline events.",
        params="Weights severity 3, trust 3, corroboration 2, novelty 1, clustering 1; freshness half-life 120 s; surprise boost 0.25; 2 slots; `ignite_at` 0.5, `release_below` 0.3, `margin` 0.1. Off: `aging_per_s` (urgency), cap 0.3.",
        agents="The gatekeeper to the agents: only a lit incident may ask the team to deliberate. Two slots because the free model plan allows 8,000 tokens a minute.",
        plane="Between 2 and 4. In plan 2 an ignition also starts the planning supervisor.",
        breaks="Two slots, not four: the limit is the model budget, not biology. Ignition is a threshold with hysteresis, not attractor dynamics (Wang 2002), which the research advised against coding literally. Divisive normalisation (Reynolds and Heeger 2009) was tried for load shedding and cut: it moved no number.",
    ),
    dict(
        id="packs", name="Packs", at=(8.0, 12.0), where="front", analogue="Specialised modules competing; degeneracy",
        neuro="Many different parts can produce the same output, and that is a feature of complex systems (Edelman and Gally 2001). The workspace recruits specialised processors to a broadcast content (Mashour et al. 2020).",
        code="Six department packs as data (`departments/manifests/`: Police, Fire, Ambulance and medical, Traffic control, Disaster response, Utilities), each with what it subscribes to, detectors, actuators, needs and severity. On ignition each pack bids (`mind/bids.py`): its fit for the incident type, scaled by the share of the actuators it needs that the Twin really offers and by free units. A pack that bids 0.5 or more joins. `brain.pack.uncovered` says when nobody can answer. A new pack is a file in `brain.packs_dir`.",
        params="`recruit_at` 0.5; bids never stop a reflex, the gate checks anyway.",
        agents="A pack names its agent team and its tools in the manifest (Police has its team of three; the other five packs each have a desk of two).",
        plane="4 Decision. Phase 2 adaptability: a partner with a new kind of sensor or service gets a pack file, not code.",
        breaks="Bids are computed, not learned.",
    ),
    dict(
        id="reflex", name="Reflex", at=(0.4, 9.8), where="centre", analogue="Reflex arcs; habits",
        neuro="Fixed fast responses run without deliberation; a habitual system competes with a slower goal-directed one, and the choice between them is a trade-off of time against accuracy (Keramati, Dezfouli and Piray 2011).",
        code="`graph/incident_graph.py`: one LangGraph thread per incident (`enrich, reflex, gate, actuate`), no model on the path; each new piece of evidence re-enters the same checkpointed thread. Thirteen rules over four departments propose actions; suspect scoring is a logistic score of behaviour only. A plan learned in sleep is applied here instead of calling the team (`brain.plan.compiled`): the habit.",
        params="Suspect score: bias -3, co-presence 2, flight 2.5, repeat 1.5, direct 4; person of interest at 0.5, suspect at 0.8; flight settles after 10 s. First action 35 to 58 ms after an incident opens (measured, in process).",
        agents="Not an agent, but it asks the team to deliberate in the background and carries on.",
        plane="4 Decision, the fast path. Plan 2 puts the OR-Tools station chooser inside it.",
        breaks="Rules are authored, not learned by repetition, except the plans sleep promotes, which must pass six checks.",
    ),
    dict(
        id="team", name="Team", at=(7.2, 8.8), where="front, lower", analogue="Prefrontal goal maintenance; anterior cingulate conflict monitoring",
        neuro="Prefrontal cortex holds goals and rules that bias processing elsewhere (Miller and Cohen 2001). The anterior cingulate monitors conflict and signals when control is needed (Botvinick et al. 2001), weighed by its expected value (Shenhav, Botvinick and Cohen 2013). Confidence can be a second-order inference (Fleming and Daw 2017).",
        code="`departments/team.py` and `builder.py`: Analyst (a case file: what the evidence supports and what could be wrong), Tactician (options, every zone from a graph algorithm), Chief (one option, justified from the playbook), then `verify_case` and `verify_plan` check the answer against the tool log and the playbook, with one revision round, before the gate. The roles mirror Planning, Operations and Command of the Incident Command System. Each role is a LangChain agent with read-only tools on Groq, or a scripted stand-in; a role whose model fails falls back to the stand-in.",
        params="Analyst and Chief `gpt-oss-120b`, Tactician `gpt-oss-20b`, temperature 0; scripted by default, `--llm` opts in. Measured: on the earlier `b2` (the crime story now in `t14`), 5 of 5 real-model trials passed, 4 placed a plan before the arrest, plan agreement 0.75. The same prompt gave 5 different answers in 5 calls.",
        agents="**This is where the agents live.** Every other region is code.",
        plane="4 Decision, the slow path. Plan 2's supervisor runs the solver and the team in parallel and keeps the better feasible plan; plan 0 records every model call so a run can be replayed.",
        breaks="The three roles are an organisational analogy (incident command), not three brain areas. The 'cingulate' here is deterministic code. There is no second-order confidence yet.",
    ),
    dict(
        id="gate", name="Gate", at=(0.6, 4.4), where="on the brain stem (the way out)", analogue="Basal ganglia: default inhibition, release of the winner, a brake under conflict",
        neuro="The basal ganglia hold competing actions inhibited and select one by releasing it (Redgrave, Prescott and Gurney 1999; Humphries and Gurney 2021). The subthalamic nucleus raises the threshold when responses conflict, holding a premature response (Frank 2006).",
        code="`gate/` is the only code that calls an actuator. Every proposal passes, in order: schema, capability (the Twin lists the tool), the department's allowlist, the incident is open, a trusted and unexpired verdict covers the evidence, enough independent trusted sources for the impact, human approval for high impact, no repeat (idempotency), cooling gap, the Guardian has not quarantined the actuator, and the action budget. Then it signs the call. A held action is reported with its reason as prominently as a sent one.",
        params="Impact: valve and grid high (2 sources and a person), dispatch medium (2 sources), alert, signal and recall low (1 source); 6 actions per incident, 20 a minute; witnesses counted by sensor. One call site for `call_actuator` in the whole code.",
        agents="Agents cannot reach it except through a proposal; their tools are read-only.",
        plane="5 Safety. Plan 1 turns the human-approval refusal into a signed approval.",
        breaks="A learned gate (O'Reilly and Frank 2006) was rejected on purpose: it would be opaque. The canopy draws it on the brain stem because it is the exit; the basal ganglia are deep forebrain nuclei, not the stem.",
    ),
    dict(
        id="memory", name="Memory", at=(2.4, 7.2), where="low in the temporal lobe", analogue="Hippocampal index of episodes; semantic memory",
        neuro="The hippocampus stores an index of an episode's cortical pattern, so a partial cue can bring it back (Teyler and Rudy 2007). An episodic log replayed in quiet time is the basis of consolidation (Mattar and Daw 2018).",
        code="Episodes (`mind/episodes.py`): each closed incident's readings as typed values, people renamed `p-1`, `p-2`, the verdicts and each tier's decision; no identity, no unit id, and never whether a dispatch worked. The knowledge base: 68 items (31 procedures, 13 rules, 6 actuators, 18 interface chunks), hybrid search filtered before the cut. The city graph in memory, mirrored to Neo4j. Similar past stories without outcome or identity.",
        params="Retrieval recall@3 0.956 with the real embedder on 45 questions; GraphRAG a measured null result, off. Episodes kept only when `brain.episodes_dir` is set.",
        agents="Agents read it through tools (`kb.search`, stories when switched on); they never write to it.",
        plane="3 Understanding and the memory stores. Plan 3 adds Qdrant for vectors and stories.",
        breaks="A brain reconstructs memories and edits them on recall (Nader, Schafe and LeDoux 2000). The Brain's record must not change: the log is hash-chained, and episodes are typed copies.",
    ),
    dict(
        id="sleep", name="Sleep", at=(-2.6, 8.0), where="back, low", analogue="Replay and consolidation; tag and capture; useful forgetting",
        neuro="Experience is replayed in sleep, sometimes in reverse (Foster and Wilson 2006), with priority to what is useful (Mattar and Daw 2018). A weak trace is tagged and captured only if later confirmed (Frey and Morris 1997). Sleep renormalises what waking strengthened (Tononi and Cirelli 2014). Forgetting removes what is out of date (Richards and Frankland 2017). Retrieval makes a memory editable again (Nader, Schafe and LeDoux 2000).",
        code="`brain sleep` (`mind/sleep.py`): mine episodes for plans the team made the same way at least twice, rehearse each candidate in simulation against the real team, and promote it as a reflex only through six checks: provenance (every reading trusted, none retracted), safety (only contain, respond and alert, inside the Police allowlist), a size cap, rehearsal (same decisions, fewer team runs), variants (neighbouring stories stay with the team), and the whole Test Book identical. `mind/lifecycle.py`: a lesson is confirmed only when the team plans its pattern the same way again, retired when it plans it differently, and may fade after sleeps with no recurrence.",
        params="`min_support` 2, at most 10 learned rules, `retire_on_contradiction` on, `fade_after_sleeps` 0 (off). Measured on the earlier `b2` (now `t14`): team runs 1 to 0, time to the last action 123.6 ms to 79.7 ms, identical decisions.",
        agents="Sleep learns *from* the agents: what it compiles is a cache of a verified team plan.",
        plane="6 Learning. Plan 3 adds `brain improve`, one audited cycle.",
        breaks="No reward signal. A brain learns from outcomes (reward prediction error); the Brain is forbidden to, because a learner that reads outcomes can be taught by an attacker who controls the sensors.",
    ),
    dict(
        id="twin", name="Twin", at=(12.8, 3.6), where="outside the brain, beside the city", analogue="The body and the world",
        neuro="Sensors and effectors: the periphery the brain senses through and acts on.",
        code="Another team's layer, stood in by `mocks/twin/` over MCP: readings by `list_readings`, actions by tools named after them.",
        params="The mock pursuit lasts 15 s, so a team can answer within it.",
        agents="None.",
        plane="Outside the Brain, reached through `TwinPort`.",
        breaks="The Brain has never talked to the real Twin yet.",
    ),
]

# Engines the convergence design adds, and what they would be in the same picture.
NEW = [
    ("Kalman tracker (plan 2)", "Forward models", "State estimation as an internal model that combines a prediction with noisy input (Wolpert, Ghahramani and Jordan 1995, *to verify*)", "A two-state filter on level and rate; time to a threshold with an interval", "Close: the cerebellar idea, made explicit"),
    ("Belief (plan 2)", "Senses, workspace", "Evidence accumulated as log-likelihood ratios toward a decision (Gold and Shadlen 2007, *to verify*); reliability-weighted cue combination (Ernst and Banks 2002)", "Log-odds fusion over independent witnesses, advisory", "Close for the arithmetic; no neural claim"),
    ("Corollary discharge (built, off)", "Forward models", "Blakemore, Wolpert and Frith 1998; Crapse and Sommer 2008", "`mind/effects.py`: the Brain's own action explains the change it causes", "Close"),
    ("Urgency (built, off)", "Workspace", "Cisek, Puskas and El-Murr 2009", "`workspace.aging_per_s`: a waiting incident ranks higher with time", "Close"),
    ("OR-Tools engines (plan 2)", "Reflex, team", "None claimed. Nearest: goal-directed planning (Miller and Cohen 2001)", "Min-cost flow and CP-SAT with a certificate", "Engineering, not biology"),
    ("Planning supervisor (plan 2)", "Workspace, reflex, team", "Arbitration between a fast habitual and a slow goal-directed system (Keramati, Dezfouli and Piray 2011; Daw, Niv and Dayan 2005, *to verify*)", "LangGraph: solve and deliberate in parallel, keep the better feasible plan", "Close in shape; the arbiter is a certificate, not a value of information"),
    ("Graph analytics (plan 3)", "Memory", "A cognitive map of relations (Behrens et al. 2018, *to verify*)", "Criticality, communities, N-1 cascade on the city graph", "Loose"),
    ("Signed approval (plan 1)", "Gate", "None: a person outside the system", "A single-use, parameter-bound approval", "Where the metaphor stops on purpose"),
    ("Journal, cassette, replay (plan 0)", "Memory", "None: brains reconstruct, they do not replay bytes", "Every input and model call kept and replayable", "A deliberate departure"),
    ("The Academy and `brain improve`", "Sleep", "Homeostatic plasticity holds activity near a setpoint (Turrigiano 2008)", "Held-out tuning of 13 listed parameters, one step at a time", "Loose: it is validated search"),
]

EXPERIMENTS = [
    ("1", "Measure how consistently the language-model team behaves (pass^k)", "Done on the earlier `b2` (now `t14`): 5 of 5 passed (pass^k 1.0 for k 1 to 5), plan agreement 0.75; 3 distinct plans in 5. Not done on other scenarios"),
    ("2", "Subtract the Brain's own actions (corollary discharge)", "Built as `forward.effects`, off until the Twin says what its actuators do"),
    ("3", "Urgency for a waiting incident", "Built as `workspace.aging_per_s`, off"),
    ("4", "Normalised salience with a self-tuning threshold", "Tried as load shedding by normalising salience; cut, it moved no number"),
    ("5", "Adaptive learning rate, a fast and a slow memory", "Partly: a previous normal is remembered and recovered; the rate stays fixed for safety; quantile calibration built, off"),
    ("6", "Learned plans as tags that must be confirmed, re-checked on use and fade", "Built: confirmation and retirement on contradiction (on), fading (off)"),
    ("7", "Ablate the guards on each model upgrade", "`brain ablate` exists for regions; not run per model"),
]

NOT_TAKEN = [
    ("A bus of global neuromodulator values (dopamine, acetylcholine as broadcast numbers)", "An alert-level scalar was cut: its inputs already shape salience"),
    ("A learned gate in front of the actuators", "Opaque; breaks 'code disposes'"),
    ("Attractor-network ignition coded literally", "The margin already gives the behaviour: amplify the difference, commit, keep the commitment"),
    ("Learning from the outcome of a dispatch", "An attacker who controls a sensor could teach it"),
    ("Any claim of consciousness", "The Brain models functions of a brain: attention, prediction error, sleep, habit"),
]


def md() -> str:
    out = ["# The Brain and the brain: what inspired each region, how it is built, and where it maps", "",
           "Written 4 Nov 2026 from the code, the defaults in `src/brain/config.py`, and the two research reports in `../reports/`. Generated by `docs/diagrams/brain_map.py`; edit that file, not this one.", "",
           "**How to say it.** The Brain is brain-inspired: it models functions of a brain (attention, prediction error, sleep, habit) as engineering. Nothing here claims it is conscious or that it works like a brain. Every 'maps to' below is an analogy; sources marked *to verify* are not in the research notes and must be checked before the report quotes them.", "",
           "## The path of one reading", "",
           "Senses (perception and the Guardian's verdict) feed the forward models, which feed triage; triage opens an incident for the reflex tier at once and for the workspace, which ranks it; an ignited incident recruits packs and may ask the team; reflex and team both propose to the gate, the only way out; the Twin carries out the call; a closed incident becomes an episode in memory, and sleep compiles verified plans back into reflexes. On the canopy each of these is a region inside a glass brain, placed by its analogue: the senses at the back, the forward models in the cerebellum, triage deep in the middle, the workspace, packs and team at the front, memory low in the temporal lobe, the gate on the brain stem, the Twin outside.", "",
           "## Region by region", ""]
    for r in REGIONS:
        out += [f"### {r['name']}: {r['analogue']}", "",
                f"*On the canopy:* {r['where']}.", "",
                f"**What inspired it.** {r['neuro']}", "",
                f"**How it is built.** {r['code']}", "",
                f"**Numbers.** {r['params']}", "",
                f"**Agents.** {r['agents']}", "",
                f"**Architecture.** {r['plane']}", "",
                f"**Where the analogy stops.** {r['breaks']}", ""]
    out += ["## Where the agents are", "",
            "| Region | A language model? | Deterministic? | How agents touch it |", "| --- | --- | --- | --- |"]
    for r in REGIONS:
        llm = "yes, opt-in (`--llm`), scripted by default" if r["id"] == "team" else "no"
        det = "no when the model runs; checked by code" if r["id"] == "team" else "yes"
        out.append(f"| {r['name']} | {llm} | {det} | {r['agents']} |")
    out += ["", "The agentic parts are few and fenced: the Police team (three LangChain roles in a LangGraph graph), and, after the plans, the planning supervisor (LangGraph, deterministic itself) and the Brain's MCP server, which gives other teams' agents the same read-only tools ours use.", "",
            "## The new engines in the same picture", "",
            "| Engine | Region | Neuroscience nearest to it | What it does | How close the analogy is |", "| --- | --- | --- | --- | --- |"]
    out += [f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in NEW]
    out += ["", "## The research shortlist, and where each item stands", "", "| # | Experiment (25 Oct report) | State on 4 Nov |", "| --- | --- | --- |"]
    out += [f"| {a} | {b} | {c} |" for a, b, c in EXPERIMENTS]
    out += ["", "## What the Brain does not take from biology, and why", "", "| Not taken | Why |", "| --- | --- |"]
    out += [f"| {a} | {b} |" for a, b in NOT_TAKEN]
    out += ["", "## Sources", "",
            "Read for the research reports (citations, DOIs and abstracts in `../reports/` and `../research_notes/`): Attwell and Laughlin 2001; Behrens et al. 2007; Blakemore, Wolpert and Frith 1998; Botvinick et al. 2001; Carandini and Heeger 2012; Cisek, Puskas and El-Murr 2009; Cowan 2001; Crapse and Sommer 2008; Crick 1984; Edelman and Gally 2001; Ernst and Banks 2002; Feldman and Friston 2010; Fleming and Daw 2017; Foster and Wilson 2006; Frank 2006; Frey and Morris 1997; Halassa and Kastner 2017; Humphries and Gurney 2021; Itti and Baldi 2009; Keramati, Dezfouli and Piray 2011; Körding and Wolpert 2004; LeDoux 2000; Lewis, Knoblich and Poe 2018; Luck and Vogel 1997; Ma, Husain and Bays 2014; Mashour et al. 2020; Mattar and Daw 2018; Menon and Uddin 2010; Miller and Cohen 2001; Nader, Schafe and LeDoux 2000; Nassar et al. 2010; O'Reilly and Frank 2006; Redgrave, Prescott and Gurney 1999; Reynolds and Heeger 2009; Richards and Frankland 2017; Shenhav, Botvinick and Cohen 2013; Smith, Ghazizadeh and Shadmehr 2006; Teyler and Rudy 2007; Tononi and Cirelli 2014; Turrigiano 2008; Ulanovsky, Las and Nelken 2003; Wang 2002; Wolpert, Miall and Kawato 1998; Yu and Dayan 2005.", "",
            "*To verify before quoting* (not in the research notes): Wolpert, Ghahramani and Jordan 1995; Gold and Shadlen 2007; Daw, Niv and Dayan 2005; Behrens et al. 2018.", ""]
    return "\n".join(out)


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline(text: str) -> str:
    """Markdown `code` and **bold** to HTML, after escaping."""
    import re
    t = esc(text)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    return re.sub(r"\*([^*]+)\*", r"<i>\1</i>", t)


def side_view() -> str:
    """The glass brain from the side, front to the right, with each region at its canopy position and the wiring between them."""
    sx = lambda x: 620 + x * 40
    sy = lambda y: 700 - y * 40
    pos = {r["id"]: (sx(r["at"][0]), sy(r["at"][1])) for r in REGIONS}
    wires = [("senses", "forward"), ("forward", "triage"), ("triage", "workspace"), ("triage", "reflex"), ("workspace", "packs"),
             ("workspace", "team"), ("packs", "team"), ("reflex", "gate"), ("team", "gate"), ("gate", "twin"), ("gate", "memory"),
             ("memory", "reflex"), ("sleep", "memory")]
    parts = []
    # cortex, a little narrower at the front; cerebellum low at the back; the stem below the middle
    parts.append('<path class="cortex" d="M172 300 C172 120 400 30 640 32 C860 34 1068 140 1068 300 C1068 420 980 496 800 500 C640 504 560 470 470 470 C330 470 172 440 172 300 Z"/>')
    parts.append('<ellipse class="cbl" cx="372" cy="440" rx="140" ry="78"/>')
    parts.append('<path class="stem" d="M600 470 L612 640 L660 640 L668 470 Z"/>')
    for a, b in wires:
        (x1, y1), (x2, y2) = pos[a], pos[b]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2 - 26
        cls = "wire out" if (a, b) == ("gate", "twin") else "wire"
        parts.append(f'<path class="{cls}" d="M{x1:.0f} {y1:.0f} Q{mx:.0f} {my:.0f} {x2:.0f} {y2:.0f}" marker-end="url(#tip)"/>')
    offsets = {"senses": (14, -22, "start"), "forward": (-16, 34, "end"), "triage": (-14, -26, "end"), "workspace": (0, -26, "middle"),
               "packs": (18, -20, "start"), "memory": (18, 30, "start"), "sleep": (-18, 34, "end"), "reflex": (18, -14, "start"),
               "team": (20, 26, "start"), "gate": (-22, 8, "end"), "twin": (0, 38, "middle")}
    for r in REGIONS:
        x, y = pos[r["id"]]
        dx, dy, anchor = offsets[r["id"]]
        cls = "dot gate" if r["id"] == "gate" else "dot agent" if r["id"] == "team" else "dot twin" if r["id"] == "twin" else "dot"
        parts.append(f'<circle class="{cls}" cx="{x:.0f}" cy="{y:.0f}" r="{11 if r["id"] == "team" else 9}"/>')
        parts.append(f'<text class="t" x="{x + dx:.0f}" y="{y + dy:.0f}" text-anchor="{anchor}">{esc(r["name"])}</text>')
        parts.append(f'<text class="s" x="{x + dx:.0f}" y="{y + dy + 16:.0f}" text-anchor="{anchor}">{esc(r["where"].split(" (")[0])}</text>')
    parts.append('<text class="k" x="1064" y="70" text-anchor="end">FRONT</text><text class="k" x="176" y="70">BACK</text>')
    parts.append('<text class="k" x="620" y="664" text-anchor="middle">BRAIN STEM</text><text class="k" x="372" y="540" text-anchor="middle">CEREBELLUM</text>')
    defs = '<defs><marker id="tip" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="tipfill"/></marker></defs>'
    return (f'<svg role="img" aria-label="Side view of the glass brain: senses at the back, forward models in the cerebellum, triage in the middle, workspace, packs and team at the front, memory low in the temporal lobe, sleep at the back, the gate on the brain stem, the Twin outside, with the path of a reading drawn between them." '
            f'viewBox="0 0 1240 690" width="1240" height="690">{defs}{"".join(parts)}</svg>')


PAGE_HEAD = """<title>Brain Map</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Familjen+Grotesk:wght@500;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: a reading column with the side view and tables breaking out wider. Steel is the Brain's code, violet marks the one place agents live, amber the gate. */
:root { --bg:#F2F4F5; --panel:#FFFFFF; --fg:#10161C; --muted:#51606D; --line:#C5CED5; --steel:#31597E; --ember:#A8590A; --violet:#6B4FA0; --wash:#E6EBEE; --glass:#E3ECF4;
  --display:'Familjen Grotesk','Helvetica Neue',Arial,sans-serif; --body:'IBM Plex Sans','Helvetica Neue',Arial,sans-serif; --mono:'IBM Plex Mono',ui-monospace,Menlo,monospace; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#0B1118; --panel:#121A23; --fg:#E8E5DA; --muted:#9AA8B5; --line:#2B3947; --steel:#7FA3C4; --ember:#F2B552; --violet:#B59BE8; --wash:#18222D; --glass:#16263A; color-scheme: dark; } }
:root[data-theme="dark"] { --bg:#0B1118; --panel:#121A23; --fg:#E8E5DA; --muted:#9AA8B5; --line:#2B3947; --steel:#7FA3C4; --ember:#F2B552; --violet:#B59BE8; --wash:#18222D; --glass:#16263A; color-scheme: dark; }
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--fg); font: 16px/1.55 var(--body); padding-block: 40px 96px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
main { max-width: 1240px; margin: 0 auto; display: flex; flex-direction: column; gap: 56px; }
header, section > :not(.wide):not(.regions) { max-width: 70ch; }
h1 { font: 700 clamp(2.4rem, 6vw, 3.8rem)/1.02 var(--display); letter-spacing: -.02em; margin: 0 0 14px; text-wrap: balance; }
h2 { font: 700 1.6rem/1.15 var(--display); margin: 0 0 10px; text-wrap: balance; }
h3 { font: 700 1.25rem/1.2 var(--display); margin: 0; text-wrap: balance; }
p { margin: 0 0 10px; } .lead { font-size: 1.12rem; }
.date { font: 500 .85rem var(--mono); color: var(--muted); letter-spacing: .04em; margin-bottom: 12px; }
.wide { max-width: none; overflow-x: auto; border: 1px solid var(--line); background: var(--panel); border-radius: 8px; }
.wide svg { display: block; min-width: 900px; width: 100%; height: auto; }
.cortex { fill: var(--glass); stroke: var(--steel); stroke-width: 1.4; } .cbl { fill: var(--glass); stroke: var(--steel); stroke-width: 1.2; stroke-dasharray: 3 4; } .stem { fill: var(--glass); stroke: var(--steel); stroke-width: 1.2; }
.wire { fill: none; stroke: var(--steel); stroke-width: 1.5; opacity: .7; } .wire.out { stroke: var(--ember); opacity: 1; stroke-width: 2; } .tipfill { fill: var(--steel); }
.dot { fill: var(--steel); } .dot.gate { fill: var(--ember); } .dot.agent { fill: var(--violet); } .dot.twin { fill: var(--muted); }
svg .t { font: 600 15px var(--body); fill: var(--fg); } svg .s { font: 400 12.5px var(--body); fill: var(--muted); } svg .k { font: 500 11px var(--mono); fill: var(--muted); letter-spacing: .1em; }
.regions { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 560px), 1fr)); gap: 16px; }
.region { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 18px 20px; display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.region.agent { border-color: var(--violet); border-width: 2px; } .region.gate { border-color: var(--ember); border-width: 2px; }
.region .an { font: 500 .78rem var(--mono); letter-spacing: .05em; text-transform: uppercase; color: var(--muted); }
.region dl { margin: 0; display: grid; grid-template-columns: 8.5rem 1fr; gap: 8px 14px; font-size: .93rem; }
.region dt { font: 600 .74rem var(--mono); text-transform: uppercase; letter-spacing: .06em; color: var(--muted); padding-top: 3px; }
.region dd { margin: 0; min-width: 0; } .region dd.breaks { color: var(--muted); }
@media (max-width: 560px) { .region dl { grid-template-columns: 1fr; } }
table { border-collapse: collapse; width: 100%; font-size: .9rem; } th, td { text-align: left; vertical-align: top; padding: 10px 14px; border-top: 1px solid var(--line); min-width: 7rem; } th { font: 500 .74rem var(--mono); text-transform: uppercase; letter-spacing: .07em; color: var(--muted); border-top: 0; background: var(--wash); }
td:first-child { font-weight: 600; }
code { font: 500 .86em var(--mono); background: var(--wash); padding: 1px 5px; border-radius: 3px; overflow-wrap: anywhere; }
.legend { display: flex; flex-wrap: wrap; gap: 8px 20px; font-size: .9rem; color: var(--muted); max-width: none; margin-top: 10px; }
.legend span::before { content: ""; display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 7px; vertical-align: -1px; background: var(--steel); }
.legend .a::before { background: var(--violet); } .legend .g::before { background: var(--ember); } .legend .w::before { background: var(--muted); }
footer { color: var(--muted); font-size: .85rem; border-top: 1px solid var(--line); padding-top: 18px; max-width: 72ch; }
</style>
"""


def html() -> str:
    cards = []
    for r in REGIONS:
        cls = "region agent" if r["id"] == "team" else "region gate" if r["id"] == "gate" else "region"
        cards.append(f'<article class="{cls}"><div><h3>{esc(r["name"])}</h3><div class="an">{esc(r["analogue"])}</div></div><dl>'
                     f'<dt>Inspired by</dt><dd>{inline(r["neuro"])}</dd>'
                     f'<dt>Built as</dt><dd>{inline(r["code"])}</dd>'
                     f'<dt>Numbers</dt><dd>{inline(r["params"])}</dd>'
                     f'<dt>Agents</dt><dd>{inline(r["agents"])}</dd>'
                     f'<dt>Architecture</dt><dd>{inline(r["plane"])}</dd>'
                     f'<dt>Analogy stops</dt><dd class="breaks">{inline(r["breaks"])}</dd></dl></article>')
    agents_rows = "".join(
        f'<tr><td>{esc(r["name"])}</td><td>{"yes, opt-in; scripted by default" if r["id"] == "team" else "no"}</td>'
        f'<td>{"no when the model runs; checked by code" if r["id"] == "team" else "yes"}</td><td>{inline(r["agents"])}</td></tr>' for r in REGIONS)
    new_rows = "".join(f"<tr><td>{inline(a)}</td><td>{inline(b)}</td><td>{inline(c)}</td><td>{inline(d)}</td><td>{inline(e)}</td></tr>" for a, b, c, d, e in NEW)
    exp_rows = "".join(f"<tr><td>{a}</td><td>{inline(b)}</td><td>{inline(c)}</td></tr>" for a, b, c in EXPERIMENTS)
    not_rows = "".join(f"<tr><td>{inline(a)}</td><td>{inline(b)}</td></tr>" for a, b in NOT_TAKEN)
    return PAGE_HEAD + f"""<main>
<header>
<p class="date">4 NOVEMBER 2026 · FROM THE CODE AND TWO RESEARCH REPORTS</p>
<h1>Brain Map</h1>
<p class="lead">What in neurophysiology inspired each of the eleven regions of the City Brain, how each one is really built, and where the agents and the architecture's planes fit.</p>
<p>The Brain is brain-inspired: it models functions of a brain, such as attention, prediction error, sleep and habit, as engineering. Every "maps to" here is an analogy, and each region says where the analogy stops. Nothing claims the Brain is conscious.</p>
</header>

<section>
<h2>The glass brain, from the side</h2>
<p>Each region sits where its analogue is on the canopy. The lines follow one reading from the senses to the gate and out to the Twin, and back from memory into reflexes after sleep.</p>
<div class="wide" tabindex="0" role="region" aria-label="Side view diagram, scrolls sideways on a narrow screen">{side_view()}</div>
<p class="legend"><span>code, deterministic</span><span class="a">where the agents live</span><span class="g">the gate, the only way out</span><span class="w">another team's layer</span></p>
</section>

<section>
<h2>Region by region</h2>
<p>In the order a reading travels. Numbers are the defaults in <code>config.py</code> and measurements from the runs.</p>
<div class="regions">{"".join(cards)}</div>
</section>

<section>
<h2>Where the agents are</h2>
<p>One region holds language models; everything around it is code that checks them. After the plans, two more agentic pieces arrive: the planning supervisor and the MCP server that gives other teams' agents our read-only tools.</p>
<div class="wide" tabindex="0" role="region" aria-label="Table of regions and agents"><table><tr><th>Region</th><th>A language model?</th><th>Deterministic?</th><th>How agents touch it</th></tr>{agents_rows}</table></div>
</section>

<section>
<h2>The new engines in the same picture</h2>
<p>Some additions have a close neural parallel, some only a loose one, and some are deliberately not biological at all.</p>
<div class="wide" tabindex="0" role="region" aria-label="Table of new engines"><table><tr><th>Engine</th><th>Region</th><th>Nearest neuroscience</th><th>What it does</th><th>How close</th></tr>{new_rows}</table></div>
</section>

<section>
<h2>The research shortlist, and where each item stands</h2>
<div class="wide" tabindex="0" role="region" aria-label="Table of experiments"><table><tr><th>#</th><th>Experiment from the 25 Oct report</th><th>State on 4 Nov</th></tr>{exp_rows}</table></div>
</section>

<section>
<h2>What the Brain does not take from biology</h2>
<div class="wide" tabindex="0" role="region" aria-label="Table of what is not taken"><table><tr><th>Not taken</th><th>Why</th></tr>{not_rows}</table></div>
</section>

<footer>Sources: the two research reports in <code>reports/</code> with their notes; DOIs and abstracts there. Four sources named here are marked <i>to verify</i> because they are not in those notes: Wolpert, Ghahramani and Jordan 1995; Gold and Shadlen 2007; Daw, Niv and Dayan 2005; Behrens et al. 2018. The same content is in <code>brain/docs/BRAIN-MAPPING.md</code>.</footer>
</main>
"""


def main() -> None:
    (DOCS / "BRAIN-MAPPING.md").write_text(md())
    (DOCS / "brain-mapping.html").write_text(html())
    print("wrote docs/BRAIN-MAPPING.md and docs/brain-mapping.html")


if __name__ == "__main__":
    main()
