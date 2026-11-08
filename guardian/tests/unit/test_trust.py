"""Scorer (weights, caps, threat tightening), verdict engine (sign, reissue, unknown)."""

from __future__ import annotations

from guardian.adapters.schemas import VerdictOut
from guardian.adapters.schemas.wire import verdict_payload
from guardian.config import Scoring
from guardian.models import Status, ThreatLevel
from guardian.trust.scorer import Scorer
from guardian.trust.signer import Signer
from tests.conftest import GUARDIAN_KEY, Harness
from tests.unit.helpers import lr

S = Scorer(Scoring())
OK = [lr("L1_authenticity"), lr("L2_freshness")]


def test_clean_reading_is_trusted() -> None:
    sc = S.score(OK)
    assert sc.status == Status.trusted and sc.score == 1.0 and sc.reasons == [] and sc.self_consistent


def test_hard_gate_and_impossible() -> None:
    assert S.score([lr("L1_authenticity", False, "hard", "hmac_invalid")]).status == Status.untrusted
    sc = S.score([*OK, lr("L3b_semantic", False, "impossible", "impossible_location")])
    assert sc.status == Status.untrusted and sc.score == 0.0 and sc.reasons == ["impossible_location"]


def test_weights_and_clamp() -> None:
    sc = S.score([*OK, lr("L4_dynamics", False, "medium", "rate_of_change"),
                  lr("L5_corroboration", False, "strong", "no_rainfall_corroboration")])
    assert sc.score == 0.2 and sc.status == Status.untrusted
    assert sc.reasons == ["rate_of_change", "no_rainfall_corroboration"]
    sc = S.score([*OK, lr("L3a_plausibility", False, "strong", "out_of_range"),
                  lr("L3b_semantic", False, "medium", "x"), lr("L4_dynamics", False, "medium", "y")])
    assert sc.score == 0.0
    sc = S.score([*OK, lr("L3a_plausibility", False, "strong", "out_of_range")])
    assert sc.score == 0.5 and sc.status == Status.suspect


def test_caps() -> None:
    # dynamics fail alone: capped at suspect
    sc = S.score([*OK, lr("L4_dynamics", False, "medium", "zscore_outlier")])
    assert sc.status == Status.suspect and sc.score < 0.8
    # ... unless corroboration passes
    sc = S.score([*OK, lr("L4_dynamics", False, "medium", "zscore_outlier"),
                  lr("L5_corroboration", True, reason="corroborated")])
    assert sc.status == Status.trusted and sc.score == 0.9 and sc.corroborated and sc.self_consistent
    # flatline stays capped even when corroborated
    sc = S.score([*OK, lr("L4_dynamics", False, "medium", "flatline"),
                  lr("L5_corroboration", True, reason="corroborated")])
    assert sc.status == Status.suspect and not sc.self_consistent
    for r in (lr("L5_corroboration", False, "low", "insufficient_corroboration"),
              lr("L3b_semantic", False, "medium", "location_sanity"),
              lr("L6_liveness", False, "medium", "call_flood")):
        assert S.score([*OK, r]).status == Status.suspect
    assert S.score([*OK, lr("ML_pattern", False, "low", "ml_anomaly")]).score == 0.8


def test_threat_level_tightening() -> None:
    corroborated = [*OK, lr("L5_corroboration", True, reason="corroborated")]
    assert S.score(corroborated, ThreatLevel.elevated, agreeing_sources=2).status == Status.trusted
    sc = S.score(corroborated, ThreatLevel.under_attack, agreeing_sources=1)
    assert sc.status == Status.suspect and "threat_level_tightened" in sc.reasons
    dyn = [*corroborated, lr("L4_dynamics", False, "medium", "zscore_outlier")]
    assert S.score(dyn, ThreatLevel.normal, 3).status == Status.trusted  # 0.9
    assert S.score(dyn, ThreatLevel.elevated, 3).status == Status.trusted  # 0.9 >= 0.9
    weak = [*corroborated, lr("L6_liveness", False, "medium", "rate_exceeded")]
    assert S.score(weak, ThreatLevel.elevated, 3).status == Status.suspect


def test_verdict_engine_sign_reissue_unknown(harness: Harness) -> None:
    e = harness.g.engine
    v = e.unknown("ghost", "unknown_sensor")
    assert v.status == Status.unknown and e.verify(v)
    assert Signer(GUARDIAN_KEY).verify(verdict_payload(v), v.signature)
    wire = VerdictOut.from_verdict(v).model_dump()
    assert wire["reading_ref"] == {"sensor_id": "ghost", "sequence_no": None}
    tampered = v.model_copy(update={"status": Status.trusted})
    assert not e.verify(tampered)
    r = e.reissue(v, Status.untrusted, "sensor_isolated")
    assert r.verdict_id != v.verdict_id and r.reasons == ["unknown_sensor", "sensor_isolated"]
    assert harness.g.state.get_verdict(r.verdict_id) is not None
