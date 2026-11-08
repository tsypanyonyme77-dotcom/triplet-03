"""Configuration models. Defaults here equal the shipped YAML files in `config/`."""

from __future__ import annotations

import hashlib
import os
from datetime import date
from pathlib import Path
from typing import Any, Literal, TypeVar
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field

from brain.contracts import CONTRACT_VERSION
from brain.contracts.signing import canonical_json

T = TypeVar("T", bound=BaseModel)


class FieldProfile(BaseModel):
    """How to build a field the Brain expects from one the Twin sends: `canonical = twin_field * scale + offset`."""

    model_config = ConfigDict(populate_by_name=True)

    from_field: str = Field(alias="from")
    scale: float = 1.0
    offset: float = 0.0


class TlsConfig(BaseModel):
    """Files for TLS. As a client: `ca` is the authority to trust, `cert` and `key` what we present for mutual TLS. As a server: `cert` and
    `key` are ours, and `ca` (if set) is the authority a client's certificate must come from."""

    ca: str | None = None
    cert: str | None = None
    key: str | None = None


class MqttConfig(BaseModel):
    """The broker a Twin publishes readings to (adapter `mqtt`). Actions, topology and capabilities still go to `twin.url` over HTTP."""

    url: str = "mqtt://127.0.0.1:1883"  # mqtt:// plain, mqtts:// with TLS
    topic_prefix: str = "city"  # readings arrive on {prefix}/{zone_id}/{type}/{sensor_id}
    qos: Literal[0, 1] = 1
    client_id: str = "city-brain"
    username_env: str | None = None  # the name of an environment variable, never the value
    password_env: str | None = None
    reorder_ms: int = Field(default=200, ge=0, le=5000)  # how long a reading waits for an earlier one from the same sensor
    tls: TlsConfig | None = None


class TwinConfig(BaseModel):
    adapter: Literal["mcp", "http", "mqtt"] = "mcp"  # http: GET /readings, POST /actuators/{action} (adapters/twin_http.py); mqtt: readings by broker, the rest as http (adapters/twin_mqtt.py)
    url: str = "http://127.0.0.1:8765/mcp"
    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    hmac_secret_env: str = "TWIN_HMAC_SECRET"
    require_signature: bool = True
    # A signed reading whose timestamp is more than this many seconds from the Brain's clock is refused (`reading_stale`). None: off, because
    # scenarios replay readings stamped in the past; set it on a live Twin, a few times its reporting interval.
    max_age_s: float | None = Field(default=None, gt=0)
    poll_interval_ms: int = 200
    # A Twin that cannot be reached is reported once (`brain.degraded`), asked again this often, and the stream resumes where it stopped
    # (`brain.recovered`). 0 gives up at the first failure, as before.
    retry_s: float = Field(default=2.0, ge=0)
    tls: TlsConfig | None = None  # for an https Twin URL
    # When the Twin names things differently from the shared contract, say so here instead of changing code.
    # `type_aliases`: the Twin's sensor type to the contract's. `profiles`: per contract type, a field the Twin
    # does not send, built from one it does (never overriding a field the Twin really sent).
    type_aliases: dict[str, str] = Field(default_factory=dict)
    profiles: dict[str, dict[str, FieldProfile]] = Field(default_factory=dict)


class GuardianConfig(BaseModel):
    adapter: Literal["rest"] = "rest"
    url: str = "http://127.0.0.1:8766"
    # sidecar: the Brain asks for a verdict per reading. inline: readings arrive carrying `trust`.
    mode: Literal["sidecar", "inline"] = "sidecar"
    verdict_deadline_ms: int = 2000
    tls: TlsConfig | None = None  # for an https Guardian URL


class BrainConfig(BaseModel):
    signing_secret_env: str = "BRAIN_HMAC_SECRET"
    log_dir: str = "logs"
    # Where `brain run` and `brain serve --live` keep their working memory between restarts ("" to keep none).
    state_file: str = "state/brain.sqlite"
    # State older than this is from another session and is discarded, not restored.
    state_max_age_s: float = 900.0
    accepted_contract_versions: list[str] = Field(default_factory=lambda: [CONTRACT_VERSION])
    # A folder of pack files (and `rules/` beside them) added to the built-in packs; a pack with the same code replaces one.
    packs_dir: str | None = None
    # Where closed incidents are kept as episodes for `brain sleep`, and where sleep keeps what it promoted.
    episodes_dir: str | None = None
    learned_dir: str | None = None
    # Where the Academy keeps the parameters it tuned (an overlay over the policy) and the history of how it got there.
    tuned_dir: str | None = None
    # Which screen opens first: the Strip Board (the live timeline) or the canopy (the brain above the city). Both always work.
    default_view: Literal["strip", "canopy"] = "strip"
    # Documents (relative to the Brain's folder) cut into reference chunks that the knowledge base can retrieve and cite.
    reference_docs: list[str] = Field(default_factory=lambda: ["docs/INTEGRATION-brain.md"])


class GraphConfig(BaseModel):
    # neo4j (default): the City Graph is mirrored to Neo4j (durable, explorable) and the knowledge vectors live in Qdrant (embedded in `qdrant_location`,
    # or a server at `qdrant_url`). Either that cannot be reached is reported once and the Brain carries on from memory. memory: everything in process.
    backend: Literal["memory", "neo4j", "qdrant"] = "neo4j"  # qdrant: the graph stays in memory, the knowledge vectors live in Qdrant
    qdrant_location: str | None = "state/qdrant"  # a folder (embedded, no server) or ":memory:"; None with no qdrant_url: knowledge served by Neo4j instead
    qdrant_url: str | None = None  # or a Qdrant server
    qdrant_api_key_env: str | None = None  # the name of the variable holding the server's API key, never the key
    qdrant_fusion: Literal["client", "server"] = "client"  # server: one hybrid query (dense + keyword, fused by Qdrant); see knowledge/qdrant.py
    uri: str = "bolt://127.0.0.1:7687"
    user: str = "neo4j"
    password_env: str = "NEO4J_PASSWORD"
    database: str = "neo4j"


class SecurityConfig(BaseModel):
    """Who may call the API. `auto` requires tokens only when the server listens off loopback (`brain serve` decides)."""

    require: Literal["auto", "always", "never"] = "auto"
    # scope -> the environment variable that holds that scope's token
    token_envs: dict[str, str] = Field(default_factory=lambda: {
        "read": "BRAIN_TOKEN_READ", "analyse": "BRAIN_TOKEN_ANALYSE", "approve": "BRAIN_TOKEN_APPROVE", "admin": "BRAIN_TOKEN_ADMIN"})
    # partner -> the environment variable holding that partner's push token (an event it pushes takes its source from this)
    push_tokens: dict[str, str] = Field(default_factory=lambda: {"twin": "TWIN_PUSH_TOKEN", "guardian": "GUARDIAN_PUSH_TOKEN"})
    max_body_bytes: int = 262144
    rate_per_minute: int = 600
    cookie_name: str = "brain_session"
    keys: dict[str, list[KeyConfig]] = Field(default_factory=dict)  # peer (twin, guardian, brain) -> keys; empty: the shared secrets named in TwinConfig and BrainConfig
    tls: TlsConfig | None = None  # our own listener (`brain serve --tls-cert ...` overrides)
    token_key_env: str = "BRAIN_TOKEN_KEY"  # the key that signs short-lived tokens (`brain token`)
    revocations_path: str = "state/revoked_tokens.txt"  # token ids (`brain token --revoke`), one per line
    clock_skew_s: int = 30  # a signed actuator call older or newer than this is refused by the receiver


class KeyConfig(BaseModel):
    """One signing key of a peer. The first key listed for a peer is its current one."""

    kid: str
    alg: Literal["HS256", "EdDSA"] = "HS256"
    secret_env: str | None = None       # HS256: the environment variable holding the shared secret
    public_key: str | None = None       # EdDSA: base64url of the 32-byte public key, or the path of a file holding it
    private_key_env: str | None = None  # EdDSA, our own key: the environment variable holding the base64url 32-byte seed
    not_before: date | None = None
    not_after: date | None = None       # the key is refused after the end of this day


class McpConfig(BaseModel):
    """The Brain's own MCP server (read-only tools for other teams' agents), mounted at `/mcp` on the API port."""

    enabled: bool = True
    allowed_hosts: list[str] = Field(default_factory=list)  # extra Host headers to accept, e.g. ["brain:8080"] in a container


class ApprovalConfig(BaseModel):
    """High-impact calls (a valve, the grid). `off`: the gate holds them. `human`: they wait for a signed approval from a person."""

    mode: Literal["off", "human"] = "off"
    ttl_s: int = 120
    secret_env: str = "BRAIN_APPROVAL_SECRET"
    path: str = "state/approvals.sqlite"


class ObservabilityConfig(BaseModel):
    """Where the Brain sends its spans. Metrics at `/metrics` need no setting; spans need a collector and the optional packages (`uv sync --extra otel`)."""

    otlp_endpoint: str | None = None  # an OTLP/HTTP collector, e.g. http://jaeger:4318; null sends nothing
    dashboard_url: str | None = None  # where the screen's "Observe" button goes (the Grafana dashboard); null hides the button
    service_name: str = "city-brain"


class PartnersConfig(BaseModel):
    twin: TwinConfig = Field(default_factory=TwinConfig)
    guardian: GuardianConfig = Field(default_factory=GuardianConfig)
    brain: BrainConfig = Field(default_factory=BrainConfig)
    graph: GraphConfig = Field(default_factory=GraphConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)


class Window(BaseModel):
    before: float = 120.0
    after: float = 60.0


class ScoringPolicy(BaseModel):
    bias: float = -3.0
    weights: dict[str, float] = Field(
        default_factory=lambda: {"copresence": 2.0, "flight": 2.5, "repeat": 1.5, "direct": 4.0}
    )
    trust_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "trusted": 1.0,
            "suspicious": 0.3,
            "untrusted": 0.0,
            "unavailable": 0.0,
        }
    )
    poi_threshold: float = 0.5
    suspect_threshold: float = 0.8
    copresence_window_s: Window = Field(default_factory=Window)
    flight_window_s: float = 300.0
    flight_speed_kmh: float = 12.0
    flight_activities: list[str] = Field(default_factory=lambda: ["running", "fleeing"])
    flight_radius_hops: int = 2
    # Flight singles one person out only once everyone else who was at the scene has been seen
    # again. After this long, people who have not been seen stop holding the decision up.
    settle_s: float = 10.0


class TriagePolicy(BaseModel):
    crime_anomaly_types: list[str] = Field(
        default_factory=lambda: ["robbery", "assault", "burglary", "theft", "vandalism", "shooting"]
    )
    min_confidence: float = 0.5
    incident_merge_window_s: float = 300.0
    # Non-crime incidents (flood, jam, fire...) come from the packs' detectors; this is how long evidence joins one.
    condition_merge_window_s: float = 600.0
    # An open incident that has had no new evidence for this long (on the readings' own clock) says a person may be needed. 0 off.
    stall_s: float = Field(default=0.0, ge=0.0)


class GatePolicy(BaseModel):
    impact: dict[str, Literal["low", "medium", "high"]] = Field(
        default_factory=lambda: {
            "dispatch_unit": "medium",
            "recall_unit": "low",
            "set_signal_phase": "low",
            "broadcast_alert": "low",
            "set_valve_state": "high",
            "set_grid_connection": "high",
        }
    )
    min_trusted_sources: dict[str, int] = Field(
        default_factory=lambda: {"low": 1, "medium": 2, "high": 2}
    )
    # Minimum seconds, on the readings' own clock, between two calls of one action to one actuator (a signal that flaps).
    # Empty means no gap. Recall and stand-down are never held.
    min_gap_s: dict[str, float] = Field(default_factory=dict)
    independence: Literal["sensor", "cause"] = "sensor"  # a witness is one sensor, or one (type, zone): two cameras in a zone count once
    retry_unreached: bool = True  # a call the Twin never answered frees its idempotency key, so the same call may be tried again
    max_actions_per_incident: int = 6
    max_actions_per_minute: int = 20
    # Actions that only withdraw. They stay allowed once an incident is closed and are not
    # counted against the budget: each is bounded by a unit that was really dispatched.
    standdown_actions: list[str] = Field(default_factory=lambda: ["recall_unit"])


class TacticsPolicy(BaseModel):
    reserve_units: int = 1  # units that must stay uncommitted city-wide
    max_perimeter_units: int = 3
    # When a named suspect's pursuit is refused for lack of units, recall one perimeter unit of another incident that
    # still has its own pursuit unit out and send it. Never a pursuit unit, never from the incident that is asking.
    preempt_perimeter: bool = False
    alert_anomaly_types: list[str] = Field(default_factory=lambda: ["robbery", "assault", "shooting"])
    alert_channel: Literal["sms", "siren", "app"] = "app"
    alert_message: str = "Police activity in {zone}. Please avoid the area."


class WorkspacePolicy(BaseModel):
    """Scarce attention: how many incidents may ask the agent team for deliberation at once, and how they are ranked."""

    enabled: bool = True
    slots: int = 2
    # An incident with at least this salience may take a free slot. A lit incident gives its slot up
    # when it falls under `release_below`, and a better candidate must beat it by `margin` to displace it.
    # `all`: every incident type competes for the slots. `team`: only the types in `team_types` do (an agent team can act on
    # them); the others are lit and broadcast without a slot, so a flood never makes a robbery wait for the team.
    slots_for: Literal["all", "team"] = "team"
    team_types: list[str] = Field(default_factory=lambda: ["crime"])
    ignite_at: float = 0.5
    margin: float = 0.1
    # Waiting counts: an incident that has been deferred for a while is ranked as if its salience were higher by
    # `aging_per_s` for each second it has waited (on the readings' own clock), up to `aging_cap`. 0 switches it off.
    aging_per_s: float = 0.0
    aging_cap: float = 0.3
    release_below: float = 0.3
    recruit_at: float = 0.5  # a pack bidding at least this joins the response to an ignited incident
    bids: bool = True  # packs bid when an incident ignites (switched off, only the explanation is lost)
    severity: dict[str, float] = Field(
        default_factory=lambda: {"crime": 0.7, "fire": 0.9, "flood": 0.8, "accident": 0.7, "jam": 0.3, "overload": 0.8, "smog": 0.4}
    )
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "severity": 3.0, "trust": 3.0, "corroboration": 2.0, "novelty": 1.0, "clustering": 1.0,
        }
    )
    freshness_halflife_s: float = 120.0
    trust_full_at: float = 0.9  # a trusted verdict at or above this confidence counts in full; below it, in proportion
    corroboration_by: Literal["sensor", "cause"] = "sensor"  # sources counted by sensor, or by (type, zone) as one witness
    cluster_radius_hops: int = 2
    surprise_boost: float = 0.25  # added to the score at full surprise (and damped like the rest by trust and freshness)
    # A flood that is still rising is worth more attention than one that has levelled off. Added at full urgency (damped like surprise); full urgency is
    # a rise of `urgency_full_rate_m_per_min` or more, from the level forecast. 0 switches it off.
    urgency_boost: float = 0.2
    urgency_full_rate_m_per_min: float = 0.5


class Effect(BaseModel):
    """What one of the Brain's own actions is known to do to what a sensor reads, so the change is not a surprise."""

    sensor_type: str
    changes: dict[str, Literal[-1, 1]]  # field -> the direction it moves (a queue clearing: congestion -1, speed +1)
    delay_s: float = 0.0  # seconds after the reading that triggered the action before the effect may show
    window_s: float = 60.0  # how long the effect may show for


class ForwardPolicy(BaseModel):
    """How the Brain predicts a numeric sensor from its own history, and how far off a reading must be to count as a surprise."""

    enabled: bool = True
    alpha: float = 0.2          # weight of the newest ordinary reading in the running mean and variance
    warmup: int = 5             # readings a sensor must have sent before it can surprise anyone
    z_threshold: float = 4.0    # spreads from the expected value
    adopt_after: int = 3        # surprises in a row, one direction, that make a new normal
    # The spread is never smaller than this, so a flat sensor does not turn every wobble into a surprise.
    min_spread: dict[str, float] = Field(
        default_factory=lambda: {
            "congestion_score": 0.05, "avg_speed_kmh": 4.0, "vehicle_count": 5.0, "level_m": 0.03, "flow_rate_m3s": 0.2,
            "load_kw": 10.0, "voltage_v": 5.0, "aqi": 5.0, "pm25_ugm3": 3.0, "pm10_ugm3": 5.0,
        }
    )
    relative_spread: float = 0.02  # ... nor smaller than this share of the expected value
    freeze_spread: bool = False  # stop updating the spread once warmed up (used by the models of coupled differences)
    history: int = 200  # readings each baseline remembers having learned, so a retracted one can be forgotten
    # `fixed`: z_threshold for every sensor. `quantile`: z_threshold scaled up by how heavy this sensor's own tail is
    # (never below z_threshold, never above max_z), read from the readings that were not surprising.
    calibration: Literal["fixed", "quantile"] = "fixed"
    calibration_window: int = 500
    calibration_min: int = 100
    max_z: float = 5.0
    # Remember the normal a sensor had before the last one it accepted, for `calibration_window` readings: a trusted
    # return to it is recognised at once (reported as `recovered`, not doubted), and the level it leaves is remembered too.
    recover: bool = True
    # Effects of the Brain's own actions, by action name (empty until the Twin team says what its actuators do).
    effects: dict[str, Effect] = Field(default_factory=dict)
    # Groups of sensor ids that measure one physical thing and should move together (two gauges on one channel). One that
    # drifts alone is *disputed*: held like a doubted reading until the group agrees again or another kind of source
    # corroborates. Declared, never guessed from the map: a real local event next to an unaffected sensor must not be held.
    coupled: list[list[str]] = Field(default_factory=list)
    coupled_alpha: float = 0.005  # the difference between two coupled sensors is followed slowly, so a creep cannot hide in it
    coupled_window_s: float = 30.0  # a partner's reading older than this is not compared


class LearningPolicy(BaseModel):
    """Sleep: what may be compiled from episodes into reflexes, and how much."""

    use_learned: bool = True  # load the rules sleep promoted (from `brain.learned_dir`)
    min_support: int = 2  # episodes that must agree before a plan is a lesson
    max_learned_rules: int = 10
    # A learned rule is a cache of what the team planned once; it must not outlive the city it was learned in. It fades after
    # this many sleeps in which its pattern did not recur (0: never). It is retired when the team later plans the same
    # pattern differently more often than it plans it the same way. Using a rule never counts as proof that it is right.
    fade_after_sleeps: int = 0
    retire_on_contradiction: bool = True


class OptimiserConfig(BaseModel):
    """Solvers that return their answer with a certificate. All on (6 Nov); `brain baseline --plain` and the `--set` flags measure the Brain with them off."""

    dispatch: Literal["off", "on"] = "on"  # which station sends a unit, all open incidents solved together (min-cost flow)
    time_limit_ms: int = 200
    unmet_penalty: int = 1000  # the cost of an incident no unit can reach, in severity-weighted hops
    shed: Literal["off", "on"] = "on"  # which zones to disconnect on an overload: the least impact that removes the excess (CP-SAT)
    shed_target_ratio: float = 0.85  # shed down to this share of the feeder's capacity
    perimeter: Literal["off", "on"] = "on"  # check each verified perimeter against the fewest units that would do, and say how likely it holds
    perimeter_sigma: float = 0.3  # spread of travel times in that estimate
    perimeter_slack: int = 1  # a plan that uses more than this many units above the fewest that would hold is sent back to the team once


class MathConfig(BaseModel):
    """Estimators that look ahead of a threshold."""

    kalman: Literal["off", "on"] = "on"  # track water level and rate; say when it will cross the line, with an interval
    kalman_threshold_m: float = 1.0       # the flood line the time is measured to (the water pack's own detector threshold)
    kalman_measurement_var: float = 0.0004  # (0.02 m) squared: the noise of a level reading
    kalman_horizon_s: float = 3600.0      # only a crossing inside this horizon is reported
    # A trusted forecast of a crossing this close sends one low-impact alert to the sensor's zone through the gate, before the line is crossed. 0 off.
    prewarn_s: float = Field(default=600.0, ge=0.0)


class OrchestrationConfig(BaseModel):
    """The planning supervisor (a LangGraph graph with checkpoints). On: it opens the emergency corridor after a fire or ambulance dispatch."""

    planner: Literal["off", "on"] = "on"
    corridor_units: list[str] = Field(default_factory=lambda: ["ambulance", "fire"])  # a dispatch of these opens a corridor
    checkpoint_db: str = ":memory:"  # a file path (state/plan.sqlite) keeps the checkpoints across a restart
    max_checkpoints: int = 2000


class DesksPolicy(BaseModel):
    """What the department desks (Fire, Ambulance and medical, Traffic control, Disaster response, Utilities) may tell the public: the words are fixed here, never written by a model."""

    # An incident type the playbook has no procedure for is first read against the department's other procedures; with none at all the
    # desk does nothing and says a person is needed (`brain.human.needed`), so a new kind of incident from the Twin is never met with silence.
    escalate_to_person: bool = True
    # The forecast's early alert: fixed wording, with the zone's name and the time to the line ("1 minute", "5 minutes").
    prewarning: str = "Water is rising near {zone} and may reach the flood line in about {when}. Keep clear of low-lying roads and be ready to move."
    messages: dict[str, str] = Field(default_factory=lambda: {
        "fire": "A fire has been reported near {zone}. Avoid the area and follow the instructions of the emergency services.",
        "accident": "A serious accident has been reported near {zone}. Avoid the area; emergency services are on their way.",
        "flood": "Flooding has been reported near {zone}. Stay away from the water and move to higher ground if you are close.",
        "jam": "Heavy traffic near {zone}. Consider another route.",
        "overload": "Power demand is very high near {zone}. Please use less if you can.",
        "smog": "Air quality is poor near {zone}. Limit time outdoors."})


class Policy(BaseModel):
    scoring: ScoringPolicy = Field(default_factory=ScoringPolicy)
    triage: TriagePolicy = Field(default_factory=TriagePolicy)
    gate: GatePolicy = Field(default_factory=GatePolicy)
    tactics: TacticsPolicy = Field(default_factory=TacticsPolicy)
    workspace: WorkspacePolicy = Field(default_factory=WorkspacePolicy)
    forward: ForwardPolicy = Field(default_factory=ForwardPolicy)
    learning: LearningPolicy = Field(default_factory=LearningPolicy)
    optimiser: OptimiserConfig = Field(default_factory=OptimiserConfig)
    desks: DesksPolicy = Field(default_factory=DesksPolicy)
    math: MathConfig = Field(default_factory=MathConfig)
    orchestration: OrchestrationConfig = Field(default_factory=OrchestrationConfig)


class TeamConfig(BaseModel):
    enabled: bool = True
    # on: Fire, Ambulance and medical, Traffic control, Disaster response and Utilities also get an agent desk (analyst and chief) that may advise neighbouring zones. Off: they are rules only.
    departments: Literal["off", "on"] = "off"
    # false: scripted stand-ins follow the playbook. true: LLM agents, falling back to the stand-ins on failure.
    llm: bool = False
    budget_s: float = 30.0
    # With a hosted model, seconds between one-token calls that check the key and the quota while no deliberation is running. 0 off.
    probe_s: float = Field(default=60.0, ge=0.0)
    # After asking the team to deliberate, the reading loop gives it this long before taking the next
    # reading. A fast team (the scripted one) finishes inside it, so its plan is made on the picture
    # that triggered it; a slow one simply carries on in the background. 0 disables the wait.
    head_start_s: float = 1.0
    max_revisions: int = 1
    structured_output: Literal["auto", "provider", "tool"] = "auto"
    # A brief carries the seconds since the incident and never a calendar time, so a rerun of one input gives the agents the same prompt.
    relative_times: bool = False
    # Every call to a language model, kept (`record`), played back with no model (`replay`), or both (`auto`: replay what it has,
    # record what it lacks). A hosted model does not repeat itself even at temperature 0, so a run is made repeatable by recording it.
    cassette: Literal["off", "record", "replay", "auto"] = "off"
    cassette_path: str | None = None


class EmbeddingsConfig(BaseModel):
    provider: Literal["auto", "fastembed", "hashing"] = "auto"
    model: str = "BAAI/bge-small-en-v1.5"


class KnowledgeConfig(BaseModel):
    """How retrieval ranks. Both switches are off (0) by default, so the ranking is the plain fusion of the two searches."""

    mmr: float = Field(default=0.0, ge=0.0, le=1.0)  # 0 off; else how much a near-duplicate of a better item is held against it
    utility_weight: float = Field(default=0.0, ge=0.0)  # 0 off; else items that helped more than they harmed rank higher
    # off: the fused search alone. local: also walk the links the playbooks state, from the search's hits, at most `hops` steps,
    # each step worth `decay` of the one before; a hit then says which links brought it.
    graphrag: Literal["off", "local"] = "off"
    hops: int = Field(default=2, ge=1, le=4)
    # off: the Analyst has the tools its pack names. on: it also gets `graph.context` (the city around the incident), `episodes.similar`
    # (past stories, no outcomes) and `kb.graph_search` (the playbooks' links, with the path to each hit). All read-only.
    team_tools: bool = True
    # Two candidates that advise against each other (`conflicts_with`): the weaker one's score is cut by this share. 0 off. On the
    # design questions a cut of one half cost recall in both embedders, so it is off.
    conflict_penalty: float = Field(default=0.0, ge=0.0, lt=1.0)
    seeds: int = Field(default=3, ge=1, le=10)  # the walk starts from this many of the best hits of each search signal, not from all of them
    decay: float = Field(default=0.5, gt=0.0, lt=1.0)


class ExplainConfig(BaseModel):
    # off: the one-line explanation is made by code. llm: a model rephrases it, and its text is discarded if it adds a figure or a name.
    narrate: Literal["off", "llm"] = "off"
    role: str = "fast"


# A local model's default context (4k tokens) is too small for a brief plus tool results, and
# "thinking" output multiplies latency on a laptop GPU. The cap stops a runaway generation.
OLLAMA_DEFAULTS = {"num_ctx": 8192, "num_predict": 1024, "reasoning": False, "temperature": 0}
# A hosted call that stalls must not spend the whole deliberation budget; when it gives up, the
# role's scripted stand-in takes over. One retry only: on Groq's free plan a rate-limit wait can
# be 5 to 12 s, and two of them outlast the budget.
GROQ_DEFAULTS = {"temperature": 0, "timeout": 20, "max_retries": 1}
# gpt-oss reasons before it answers; at low effort it spends far fewer tokens, which is what
# the free plan's per-minute allowance runs out of, and the tasks here do not need more.
GPT_OSS_DEFAULTS = {"reasoning_effort": "low"}


class ModelsConfig(BaseModel):
    # `provider:model` strings understood by langchain's init_chat_model.
    roles: dict[str, str] = Field(
        default_factory=lambda: {
            "fast": "groq:openai/gpt-oss-20b",
            "strong": "groq:openai/gpt-oss-120b",
        }
    )
    # Extra keyword arguments for init_chat_model, per role (e.g. {"fast": {"num_ctx": 8192}}).
    role_options: dict[str, dict[str, Any]] = Field(default_factory=dict)
    team: TeamConfig = Field(default_factory=TeamConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    explain: ExplainConfig = Field(default_factory=ExplainConfig)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)

    def options_for(self, role: str) -> dict[str, Any]:
        """Explicit options win; otherwise each provider gets the settings that suit it."""
        if role in self.role_options:
            return self.role_options[role]
        spec = self.roles.get(role, "")
        if spec.startswith("ollama:"):
            return dict(OLLAMA_DEFAULTS)
        if spec.startswith("groq:openai/gpt-oss"):
            return {**GROQ_DEFAULTS, **GPT_OSS_DEFAULTS}
        if spec.startswith("groq:"):
            return dict(GROQ_DEFAULTS)
        return {}


def home() -> Path:
    """Project root: where `config/`, `scenarios/`, `mocks/` and `logs/` live."""
    return Path(os.environ.get("BRAIN_HOME", Path.cwd()))


def load(cls: type[T], name: str, path: str | Path | None = None) -> T:
    """Load `config/<name>.yaml` (or an explicit path); fall back to built-in defaults."""
    file = Path(path) if path else home() / "config" / f"{name}.yaml"
    if not file.exists():
        if path:
            raise FileNotFoundError(f"config file not found: {file}")
        loaded = cls()
    else:
        loaded = cls.model_validate(yaml.safe_load(file.read_text()) or {})
    return _with_partner_addresses(loaded) if isinstance(loaded, PartnersConfig) else loaded


def _with_partner_addresses(partners: PartnersConfig) -> PartnersConfig:
    """`TWIN_URL` and `GUARDIAN_URL` (the triplet's root `.env`) override the addresses in the file, so one stack-wide variable points the Brain at a partner.
    A bare `http://host:port` for an MCP Twin means the MCP endpoint at `/mcp`."""
    if twin := os.environ.get("TWIN_URL"):
        partners.twin.url = twin.rstrip("/") + "/mcp" if partners.twin.adapter == "mcp" and not urlparse(twin).path.strip("/") else twin
    if guardian := os.environ.get("GUARDIAN_URL"):
        partners.guardian.url = guardian
    return partners


def secret(env_name: str) -> str | None:
    return os.environ.get(env_name) or None


def fingerprint(*models: BaseModel | dict | list) -> str:
    """Short stable hash of the behaviour-defining config, stamped on every decision."""
    dumped = [m.model_dump(mode="json") if isinstance(m, BaseModel) else m for m in models]
    return hashlib.sha256(canonical_json(dumped)).hexdigest()[:12]
