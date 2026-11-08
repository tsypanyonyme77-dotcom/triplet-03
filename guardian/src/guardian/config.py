"""Loads every YAML in config/ plus .env into validated Pydantic models. Bad config fails at startup, loudly."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    pass


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- guardian.yaml ----------
class ServiceCfg(_M):
    name: str = "guardian"
    version: str = "0.1.0"
    host: str
    port: int


class McpCfg(_M):
    url: str
    readings_tool: str = "get_readings"


class MqttCfg(_M):
    host: str
    port: int
    readings_topic: str = "city/readings/#"
    tools_topic: str = "city/tools"


class TwinCfg(_M):
    transport: Literal["rest", "mcp", "mqtt"] = "rest"
    mode: Literal["push", "pull"] = "push"
    base_url: str
    timeout_s: float = 3.0
    poll_interval_s: float = 2.0
    health_interval_s: float = 5.0
    mcp: McpCfg | None = None
    mqtt: MqttCfg | None = None

    @model_validator(mode="after")
    def _transport_section(self) -> TwinCfg:
        if self.transport != "rest" and getattr(self, self.transport) is None:
            raise ValueError(f"twin.transport={self.transport} needs a twin.{self.transport} section")
        return self


class VerdictCfg(_M):
    ttl_s: float = 30
    lru_size: int = 5000


class StorageCfg(_M):
    db_path: str = "./data/guardian.db"
    history_size: int = 500


class AuditCfg(_M):
    log_dir: str = "./logs"
    file_prefix: str = "t5-guardian"


class BackgroundCfg(_M):
    tick_s: float = 1.0


class MlCfg(_M):
    enabled: bool = False
    min_train: int = 200
    contamination: float = 0.02


class GuardianYaml(_M):
    contract_version: str = "1.0"
    service: ServiceCfg
    twin: TwinCfg
    brain: dict[str, str] = Field(default_factory=dict)
    verdict: VerdictCfg = VerdictCfg()
    storage: StorageCfg = StorageCfg()
    audit: AuditCfg = AuditCfg()
    background: BackgroundCfg = BackgroundCfg()
    ml: MlCfg = MlCfg()


# ---------- sensor_registry.yaml ----------
class FieldSpec(_M):
    type: Literal["int", "float", "bool", "str"]
    unit: str | None = None
    enum: list[str] | None = None


class SensorTypeSpec(_M):
    expected_interval_s: float | None
    fields: dict[str, FieldSpec]
    checks: list[str]


class SensorRegistry(_M):
    sensor_types: dict[str, SensorTypeSpec]


# ---------- thresholds.yaml ----------
class ZCfg(_M):
    limit: float = 4.0
    alpha: float = 0.1
    min_history: int = 20


class BaselineCfg(_M):
    min_samples: int = 200
    sigma: float = 4.0
    drift_window: int = 60
    drift_sigma: float = 1.0
    drift_fraction: float = 0.9


class CallFloodCfg(_M):
    max_calls_per_zone: int = 5
    window_s: float = 60


class RateCfg(_M):
    max_msgs_per_s: float = 5


class FieldLimits(_M):
    min: float | None = None
    max: float | None = None
    max_rate_per_s: float | None = None
    noise_floor: float = 0.0


class Consistency(_M):
    left: str
    op: Literal["<=", "<", ">=", ">"]
    right: str


class Condition(_M):
    field: str
    op: Literal[">", ">=", "<", "<=", "==", "!=", "in", "dev", "jump_pct"]
    value: Any
    center: float | None = None


class Cutoffs(_M):
    trusted: float = 0.8
    suspect: float = 0.4


class Weights(_M):
    plausibility_fail: float = -0.5
    semantic_suspect: float = -0.3
    dynamics_fail: float = -0.3
    corroboration_fail: float = -0.5
    corroboration_pass: float = 0.2
    liveness_fail: float = -0.3
    pattern_fail: float = -0.2


class Tightened(_M):
    trusted_min_score: float = 0.9
    min_corroborating_sources: int = 2


class Scoring(_M):
    cutoffs: Cutoffs = Cutoffs()
    weights: Weights = Weights()
    tightened: Tightened = Tightened()

    @model_validator(mode="after")
    def _order(self) -> Scoring:
        if not 0 <= self.cutoffs.suspect < self.cutoffs.trusted <= 1:
            raise ValueError("scoring.cutoffs must satisfy 0 <= suspect < trusted <= 1")
        return self


class Thresholds(_M):
    max_clock_skew_s: float = 30
    flatline_n: int = 50
    flatline_decimals: int = 6
    zscore: ZCfg = ZCfg()
    baseline: BaselineCfg = BaselineCfg()
    call_flood: CallFloodCfg = CallFloodCfg()
    rate: RateCfg = RateCfg()
    unit_mismatch_factor: float = 100
    fields: dict[str, dict[str, FieldLimits]] = Field(default_factory=dict)
    consistency: dict[str, list[Consistency]] = Field(default_factory=dict)
    events: dict[str, list[Condition]] = Field(default_factory=dict)
    scoring: Scoring = Scoring()


# ---------- crosschecks.yaml ----------
class CrossSource(_M):
    key: str
    sensor_type: str
    presence_only: bool = False


class Crosschecks(_M):
    corroboration_window_s: float = 120
    min_sources: int = 2
    adjacency: dict[str, list[str]] = Field(default_factory=dict)
    rules: dict[str, list[CrossSource]] = Field(default_factory=dict)


# ---------- city_model.yaml ----------
class Zone(_M):
    type: str
    has_water_body: bool = False
    max_water_level_m: float = 0.0
    has_buildings: bool = True
    road_access: bool = True
    fire_possible: bool = True
    hospital: bool = False
    switchable_grid: bool = True
    max_vehicles: int | None = None


class CityModel(_M):
    timezone_offset_h: float = 0
    quiet_hours: list[int] = Field(default_factory=list)
    zones: dict[str, Zone]


# ---------- policies.yaml ----------
class ActuatorSpec(_M):
    type: str
    zone_id: str | None
    verify_sensors: list[str] = Field(default_factory=list)


class Expectation(_M):
    verify_with: list[str]
    expect: str
    within_s: float
    on_fail: str = "actuator_failure"
    check_reverts_at: bool = False


class VerificationCfg(_M):
    partial_min_progress: float = 0.2
    late_window_s: float = 180
    unauthorised_drop_pct: float = 80
    unauthorised_window_s: float = 120
    revert_tolerance_s: float = 5


class SafetyCfg(_M):
    no_grid_disconnect_in_hospital_zone: bool = True
    no_duplicate_dispatch: bool = True


class RateLimits(_M):
    per_caller_per_min: int = 30
    per_actuator_per_min: int = 6


class OddHours(_M):
    hours: list[int] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)


class ContainmentCfg(_M):
    max_isolations_per_zone: int = 3
    release_after_good_readings: int = 10
    cooldown_s: float = 60
    backoff_factor: float = 2


class Policies(_M):
    actuators: dict[str, ActuatorSpec]
    expectations: dict[str, dict[str, Expectation]] = Field(default_factory=dict)
    verification: VerificationCfg = VerificationCfg()
    safety: SafetyCfg = SafetyCfg()
    rate_limits: RateLimits = RateLimits()
    odd_hours: OddHours = OddHours()
    containment_actions: list[str] = Field(default_factory=list)
    containment: ContainmentCfg = ContainmentCfg()

    @model_validator(mode="after")
    def _independent(self) -> Policies:
        for aid, spec in self.actuators.items():
            if aid in spec.verify_sensors:
                raise ValueError(f"actuator {aid} cannot verify itself (verify_sensors must be independent)")
        return self


# ---------- attack_patterns.yaml ----------
class Pattern(_M):
    kind: Literal["generic", "compromised_twin", "attack_during_incident"] = "generic"
    signals: list[str] = Field(default_factory=list)
    group_by: Literal["zone", "device", "source"] = "zone"
    distinct: Literal["device", "source"] | None = None
    threshold: int = 1
    window_s: float = 60
    raises_to: Literal["elevated", "under_attack"] | None = None
    response: str
    min_zones: int = 3
    fraction: float = 0.5


class ThreatLevelsCfg(_M):
    quiet_period_s: float = 120


class AttackPatterns(_M):
    patterns: dict[str, Pattern]
    threat_levels: ThreatLevelsCfg = ThreatLevelsCfg()


# ---------- .env ----------
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    guardian_hmac_key: str = Field(default="", alias="GUARDIAN_HMAC_KEY")
    twin_hmac_key: str = Field(default="", alias="TWIN_HMAC_KEY")
    brain_api_key: str = Field(default="", alias="BRAIN_API_KEY")
    twin_api_key: str = Field(default="", alias="TWIN_API_KEY")
    ops_api_key: str = Field(default="", alias="OPS_API_KEY")
    config_dir: str = Field(default="./config", alias="GUARDIAN_CONFIG_DIR")
    log_dir: str | None = Field(default=None, alias="LOG_DIR")
    db_path: str | None = Field(default=None, alias="GUARDIAN_DB_PATH")
    twin_base_url: str | None = Field(default=None, alias="TWIN_BASE_URL")
    twin_transport: str | None = Field(default=None, alias="TWIN_TRANSPORT")
    twin_mode: str | None = Field(default=None, alias="TWIN_MODE")

    def api_keys(self) -> dict[str, str]:
        """API key -> caller identity."""
        pairs = {"brain": self.brain_api_key, "twin": self.twin_api_key, "ops": self.ops_api_key}
        return {k: who for who, k in pairs.items() if k}


class GuardianConfig(BaseModel):
    guardian: GuardianYaml
    sensors: SensorRegistry
    thresholds: Thresholds
    crosschecks: Crosschecks
    city: CityModel
    policies: Policies
    attacks: AttackPatterns
    config_dir: Path

    @model_validator(mode="after")
    def _cross_refs(self) -> GuardianConfig:
        zones = set(self.city.zones)
        for z, adj in self.crosschecks.adjacency.items():
            unknown = ({z, *adj}) - zones
            if unknown:
                raise ValueError(f"crosschecks.adjacency references unknown zones {sorted(unknown)}")
        for aid, a in self.policies.actuators.items():
            if a.zone_id and a.zone_id not in zones:
                raise ValueError(f"policies.actuators.{aid}.zone_id {a.zone_id!r} is not in city_model")
        for t in [*self.thresholds.fields, *self.thresholds.events]:
            if t not in self.sensors.sensor_types:
                raise ValueError(f"thresholds references unknown sensor_type {t!r}")
        return self


FILES = {
    "guardian": "guardian.yaml",
    "sensors": "sensor_registry.yaml",
    "thresholds": "thresholds.yaml",
    "crosschecks": "crosschecks.yaml",
    "city": "city_model.yaml",
    "policies": "policies.yaml",
    "attacks": "attack_patterns.yaml",
}


def load_config(config_dir: str | Path | None = None, settings: Settings | None = None) -> GuardianConfig:
    """Read and validate every YAML. Raises ConfigError naming the file and field on any problem."""
    settings = settings or Settings()
    cdir = Path(config_dir or settings.config_dir)
    raw: dict[str, Any] = {}
    for key, name in FILES.items():
        path = cdir / name
        try:
            raw[key] = yaml.safe_load(path.read_text()) or {}
        except FileNotFoundError as e:
            raise ConfigError(f"missing config file {path}") from e
        except yaml.YAMLError as e:
            raise ConfigError(f"invalid YAML in {path}: {e}") from e
        if not isinstance(raw[key], dict):
            raise ConfigError(f"{path} must contain a mapping at the top level")
    g = raw["guardian"]
    twin = g.setdefault("twin", {})
    if settings.twin_base_url:
        twin["base_url"] = settings.twin_base_url
    if settings.twin_transport:
        twin["transport"] = settings.twin_transport
    if settings.twin_mode:
        twin["mode"] = settings.twin_mode
    if settings.log_dir:
        g.setdefault("audit", {})["log_dir"] = settings.log_dir
    if settings.db_path:
        g.setdefault("storage", {})["db_path"] = settings.db_path
    try:
        return GuardianConfig(**raw, config_dir=cdir)
    except ValidationError as e:
        lines = []
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"])
            file = FILES.get(str(err["loc"][0]), "config") if err["loc"] else "config"
            lines.append(f"  {file}: {loc}: {err['msg']}")
        raise ConfigError("invalid configuration:\n" + "\n".join(lines)) from e


def require_secrets(settings: Settings) -> None:
    missing = [n for n, v in (("GUARDIAN_HMAC_KEY", settings.guardian_hmac_key),
                              ("TWIN_HMAC_KEY", settings.twin_hmac_key)) if not v]
    if missing:
        raise ConfigError(f"missing secrets in environment/.env: {', '.join(missing)}")
    if not settings.api_keys():
        raise ConfigError("no API keys configured (BRAIN_API_KEY / TWIN_API_KEY / OPS_API_KEY)")
