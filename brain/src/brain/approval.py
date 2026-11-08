"""A person's approval of a high-impact call: a valve, a grid cut.

Without it the gate holds the call (`human_approval`). With `approval.mode: human` the held call waits as a *pending approval*
(`brain.approval.requested`), a person grants or denies it over the API, and a grant lets the same proposal back through the
gate, which then runs every later check again. An approval is a signed object, not a flag: it is bound to a hash of the call's
action, actuator, parameters and incident (change the parameters and it no longer fits), it expires, it can be used once, and
it is signed with the approval secret, so it cannot be written by hand. Pending requests and grants live in SQLite and survive
a restart.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from brain import clock
from brain.contracts import Approval, ProposedAction, Provenance
from brain.contracts.signing import canonical_json, sign
from brain.contracts.signing import verify as verify_signature


def proposal_hash(proposal: ProposedAction) -> str:
    """What an approval covers: the action, the actuator, the parameters and the incident. The prose of the justification is not part of it."""
    body = {"action": proposal.action, "actuator_id": proposal.actuator_id, "params": proposal.params, "incident_id": proposal.incident_id}
    return hashlib.sha256(canonical_json(body)).hexdigest()[:32]


def verify(approval: Approval, proposal: ProposedAction, secret: str) -> str | None:
    """None when the approval is good for this proposal now; otherwise why not."""
    if not verify_signature(approval.model_dump(mode="json"), secret):
        return "signature_invalid"
    if approval.proposal_hash != proposal_hash(proposal) or approval.incident_id != proposal.incident_id:
        return "hash_mismatch"
    if approval.expires_at <= clock.current().now():
        return "expired"
    return None


class ApprovalStore:
    def __init__(self, path: str | Path, secret: str, ttl_s: int = 120) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("""CREATE TABLE IF NOT EXISTS approvals (
            pending_id TEXT PRIMARY KEY, hash TEXT, proposal TEXT, trace_id TEXT, requested_at TEXT,
            state TEXT, approver TEXT, reason TEXT, approval TEXT, used INTEGER DEFAULT 0)""")
        self._secret, self._ttl = secret, ttl_s
        self.on_request: Callable[[dict[str, Any]], Any] | None = None  # called for each new pending request (the screen, a test)
        self.emit: Callable[..., Any] | None = None  # (type, subject, data, trace_id): the timeline

    def _say(self, type: str, subject: str | None, data: dict[str, Any], trace_id: str | None) -> None:
        if self.emit is not None:
            self.emit(type, subject, data, trace_id)

    def _row(self, where: str, *args: Any) -> sqlite3.Row | None:
        self._db.row_factory = sqlite3.Row
        return self._db.execute(f"SELECT * FROM approvals WHERE {where}", args).fetchone()  # nosec B608: `where` is one of five literals in this file; values are bound

    def hold(self, proposal: ProposedAction, trace_id: str | None) -> str:
        """Ask for an approval of this call. The same call asked twice is one pending entry."""
        key = proposal_hash(proposal)
        existing = self._row("hash = ? AND used = 0", key)
        if existing is not None:
            return existing["pending_id"]
        pending_id = clock.current().new_id("pending")
        self._db.execute("INSERT INTO approvals (pending_id, hash, proposal, trace_id, requested_at, state) VALUES (?,?,?,?,?,'pending')",
                         (pending_id, key, proposal.model_dump_json(), trace_id, clock.current().now().isoformat()))
        self._db.commit()
        request = {"pending_id": pending_id, "proposal_hash": key, "action": proposal.action, "actuator_id": proposal.actuator_id,
                   "params": proposal.params, "incident_id": proposal.incident_id, "justification": proposal.justification,
                   "evidence": proposal.evidence_reading_ids, "ttl_s": self._ttl}
        self._say("brain.approval.requested", proposal.incident_id, request, trace_id)
        if self.on_request is not None:
            self.on_request(request)
        return pending_id

    def pending(self) -> list[dict[str, Any]]:
        self._db.row_factory = sqlite3.Row
        rows = self._db.execute("SELECT * FROM approvals WHERE state = 'pending' ORDER BY requested_at").fetchall()
        return [{"pending_id": r["pending_id"], "proposal": json.loads(r["proposal"]), "requested_at": r["requested_at"]} for r in rows]

    def status(self, pending_id: str) -> dict[str, Any]:
        row = self._row("pending_id = ?", pending_id)
        if row is None:
            raise KeyError(pending_id)
        return {"pending_id": pending_id, "state": row["state"], "approver": row["approver"], "reason": row["reason"]}

    def proposal(self, pending_id: str) -> tuple[ProposedAction, str | None]:
        row = self._row("pending_id = ?", pending_id)
        if row is None:
            raise KeyError(pending_id)
        return ProposedAction.model_validate_json(row["proposal"]), row["trace_id"]

    def grant(self, pending_id: str, approver: str) -> Approval:
        if not self._secret:
            raise ValueError("no approval secret is set: an approval cannot be signed")
        proposal, trace_id = self.proposal(pending_id)
        now = clock.current().now()
        unsigned = Approval(approval_id=clock.current().new_id("grant"), proposal_hash=proposal_hash(proposal), incident_id=proposal.incident_id,
                            approver=approver, issued_at=now, expires_at=now + timedelta(seconds=self._ttl),
                            provenance=Provenance(signed_by="city_brain", hmac=""))
        body = {k: v for k, v in unsigned.model_dump(mode="json").items() if k != "provenance"}  # signed in the form it is verified in
        approval = Approval.model_validate(sign(body, self._secret, signed_by="city_brain"))
        self._db.execute("UPDATE approvals SET state = 'granted', approver = ?, approval = ? WHERE pending_id = ?",
                         (approver, approval.model_dump_json(), pending_id))
        self._db.commit()
        self._say("brain.approval.granted", proposal.incident_id, {"pending_id": pending_id, "approval_id": approval.approval_id,
                                                                   "approver": approver, "expires_at": approval.expires_at.isoformat()}, trace_id)
        return approval

    def deny(self, pending_id: str, approver: str, reason: str) -> None:
        proposal, trace_id = self.proposal(pending_id)
        self._db.execute("UPDATE approvals SET state = 'denied', approver = ?, reason = ? WHERE pending_id = ?", (approver, reason, pending_id))
        self._db.commit()
        self._say("brain.approval.denied", proposal.incident_id, {"pending_id": pending_id, "approver": approver, "reason": reason}, trace_id)

    def find(self, proposal: ProposedAction) -> tuple[Approval | None, str | None]:
        """A good, unused approval for exactly this call, or why there is none."""
        row = self._row("hash = ? AND state = 'granted' AND used = 0", proposal_hash(proposal))
        if row is None:
            return None, None
        approval = Approval.model_validate_json(row["approval"])
        reason = verify(approval, proposal, self._secret)
        return (None, reason) if reason else (approval, None)

    def consume(self, approval_id: str) -> None:
        """An approval is used once."""
        self._db.row_factory = sqlite3.Row
        for row in self._db.execute("SELECT pending_id, approval FROM approvals WHERE state = 'granted' AND used = 0").fetchall():
            if json.loads(row["approval"])["approval_id"] == approval_id:
                self._db.execute("UPDATE approvals SET used = 1 WHERE pending_id = ?", (row["pending_id"],))
        self._db.commit()
