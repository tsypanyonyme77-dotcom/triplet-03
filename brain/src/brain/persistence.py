"""The Brain's working memory on disk, so a restart picks up where it stopped.

One SQLite file. The graph's append-only facts (readings with their verdicts, decisions,
actions) go to a journal as they happen. Everything small and mutable (incidents, units
out, what the gate and the replay check remember, the position in the Twin's stream) is
saved as a snapshot. Both are committed together, once per handled reading, so the file
always describes the Brain as it was after some reading and never half-way through one.

After a crash the reading that was in flight is delivered again. A call already sent for
it comes back from the Twin as `duplicate` and is recorded like a fresh one, so nothing
is dispatched twice and nothing is lost.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS journal (seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS snapshot (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class StateFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(SCHEMA)
        self._db.commit()
        # Saved with every snapshot under `meta`: whatever the caller wants to find again, such as its log file.
        self.note: dict[str, Any] = {}

    def record(self, kind: str, payload: dict[str, Any]) -> None:
        """Append to the journal. Not durable until the next `save`."""
        self._db.execute("INSERT INTO journal (kind, payload) VALUES (?, ?)", (kind, json.dumps(payload, default=str)))

    def save(self, snapshot: dict[str, Any]) -> None:
        """Replace the snapshot and commit it together with everything journalled since the last save."""
        self._db.executemany(
            "INSERT OR REPLACE INTO snapshot (key, value) VALUES (?, ?)",
            [(key, json.dumps(value, default=str)) for key, value in snapshot.items()],
        )
        self._db.commit()

    def meta(self) -> dict[str, Any] | None:
        row = self._db.execute("SELECT value FROM snapshot WHERE key = 'meta'").fetchone()
        return json.loads(row[0]) if row else None

    def load(self) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]] | None:
        """The last saved state as (snapshot, journal in order), or None if nothing was saved."""
        self._db.rollback()  # anything not saved is not part of the state
        snapshot = {key: json.loads(value) for key, value in self._db.execute("SELECT key, value FROM snapshot")}
        if "meta" not in snapshot:
            return None
        journal = [(kind, json.loads(payload)) for kind, payload in self._db.execute("SELECT kind, payload FROM journal ORDER BY seq")]
        return snapshot, journal

    def clear(self) -> None:
        self._db.rollback()
        self._db.execute("DELETE FROM journal")
        self._db.execute("DELETE FROM snapshot")
        self._db.commit()

    def close(self) -> None:
        self._db.close()


def live_session(state_file: str, max_age_s: float, home: Path, log_dir: Path, fresh: bool) -> tuple[StateFile | None, Path, bool]:
    """Open the state file for a live run and choose its log file.

    Returns (state or None when none is kept, log path, whether an earlier session is being
    continued). A continued session keeps writing to the same log, so the audit chain runs
    unbroken across the restart. `fresh` forgets whatever was saved.
    """
    now = datetime.now(UTC)
    new_log = log_dir / f"live-{now.strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    if not state_file:
        return None, new_log, False
    path = Path(state_file)
    state = StateFile(path if path.is_absolute() else home / path)
    if fresh:
        state.clear()
    meta = state.meta()
    log, resumed = new_log, False
    if meta and meta.get("log") and Path(meta["log"]).exists():
        if (now - datetime.fromisoformat(meta["saved_at"])).total_seconds() <= max_age_s:
            log, resumed = Path(meta["log"]), True
    state.note["log"] = str(log)
    return state, log, resumed
