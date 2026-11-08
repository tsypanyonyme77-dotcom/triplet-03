"""An explanation an auditor can check offline: the explanation, the log lines it was built from, and an HMAC over both, made with the
Brain's own signing code. A line carries its own chain hash, so each one can be checked alone; changing a line or a fact breaks the
signature, and re-signing needs the key."""

from __future__ import annotations

from typing import Any

from brain.contracts.signing import sign, verify
from brain.explain.models import Explanation
from brain.timeline import _chain_hash

SIGNER = "city_brain"


def make_bundle(explanation: Explanation, events: list[dict[str, Any]], secret: str) -> dict[str, Any]:
    """`events` is the log (rows as written to the `.jsonl` file, with their hashes). Only the lines the explanation names go in."""
    used = {step.event_id for step in explanation.steps}
    lines = [row for row in events if row["id"] in used]
    return sign({"explanation": explanation.model_dump(mode="json"), "log_slice": lines, "chain_head": explanation.log_chain_head}, secret, SIGNER)


def verify_bundle(bundle: dict[str, Any], secret: str) -> tuple[bool, str]:
    """(ok, message). Checks the signature, then each line's own hash, then that every step has its line."""
    if not verify(bundle, secret):
        return False, "the signature does not match: the bundle was changed, or signed with another key"
    ids = set()
    for row in bundle["log_slice"]:
        record = {k: v for k, v in row.items() if k != "hash"}
        if "hash" not in row or "prevhash" not in row or _chain_hash(row["prevhash"], record) != row["hash"]:
            return False, f"log line {row.get('id', '?')} does not match its own hash"
        ids.add(row["id"])
    missing = [s["event_id"] for s in bundle["explanation"]["steps"] if s["event_id"] not in ids]
    if missing:
        return False, f"{len(missing)} step{'' if len(missing) == 1 else 's'} have no log line behind them"
    return True, f"signature good, {len(ids)} log lines each match their hash, every step has its line"
