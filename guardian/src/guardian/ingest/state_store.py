"""Per-sensor state: ring buffers in memory; durable facts (verdicts, containment, sequences, last-known-good,
baselines) in SQLite so a restart recovers."""

from __future__ import annotations

import json
import sqlite3
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from guardian.models import ContainmentRecord, Reading, Status, Verdict


@dataclass
class HistEntry:
    ts: datetime
    value: dict[str, Any]
    status: Status | None = None


@dataclass
class SensorState:
    sensor_id: str
    sensor_type: str
    zone_id: str
    history: deque[HistEntry]
    last_seq: int | None = None
    last_ts: datetime | None = None
    last_seen: datetime | None = None
    latest_reading: Reading | None = None
    latest_verdict: Verdict | None = None
    lkg: Reading | None = None
    ewma: dict[str, tuple[float, float, int]] = field(default_factory=dict)
    arrivals: deque[datetime] = field(default_factory=lambda: deque(maxlen=64))
    stale: bool = False
    flags: set[str] = field(default_factory=set)


class SqliteStore:
    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS verdicts(verdict_id TEXT PRIMARY KEY, sensor_id TEXT,
                sequence_no INTEGER, ts TEXT, body TEXT);
            CREATE INDEX IF NOT EXISTS verdicts_sensor ON verdicts(sensor_id, ts);
            CREATE TABLE IF NOT EXISTS containment(device_id TEXT, kind TEXT, active INTEGER, body TEXT,
                PRIMARY KEY(device_id, kind));
            CREATE TABLE IF NOT EXISTS sensors(sensor_id TEXT PRIMARY KEY, sensor_type TEXT, zone_id TEXT,
                last_seq INTEGER, last_ts TEXT);
            CREATE TABLE IF NOT EXISTS lkg(sensor_id TEXT PRIMARY KEY, body TEXT);
            CREATE TABLE IF NOT EXISTS baselines(sensor_id TEXT, field TEXT, hour INTEGER, n INTEGER,
                mean REAL, m2 REAL, PRIMARY KEY(sensor_id, field, hour));
            CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
            """
        )

    def put_verdict(self, v: Verdict) -> None:
        self.db.execute("INSERT OR REPLACE INTO verdicts VALUES (?,?,?,?,?)",
                        (v.verdict_id, v.sensor_id, v.sequence_no, v.ts.isoformat(), v.model_dump_json()))

    def get_verdict(self, verdict_id: str) -> Verdict | None:
        row = self.db.execute("SELECT body FROM verdicts WHERE verdict_id=?", (verdict_id,)).fetchone()
        return Verdict.model_validate_json(row[0]) if row else None

    def find_verdict(self, sensor_id: str, sequence_no: int) -> Verdict | None:
        row = self.db.execute(
            "SELECT body FROM verdicts WHERE sensor_id=? AND sequence_no=? ORDER BY ts DESC LIMIT 1",
            (sensor_id, sequence_no)).fetchone()
        return Verdict.model_validate_json(row[0]) if row else None

    def latest_verdicts(self) -> list[Verdict]:
        rows = self.db.execute(
            "SELECT body FROM verdicts v WHERE ts = (SELECT MAX(ts) FROM verdicts w WHERE w.sensor_id=v.sensor_id)"
        ).fetchall()
        return [Verdict.model_validate_json(r[0]) for r in rows]

    def put_containment(self, r: ContainmentRecord) -> None:
        self.db.execute("INSERT OR REPLACE INTO containment VALUES (?,?,?,?)",
                        (r.device_id, r.kind, int(r.active), r.model_dump_json()))

    def active_containment(self) -> list[ContainmentRecord]:
        rows = self.db.execute("SELECT body FROM containment WHERE active=1").fetchall()
        return [ContainmentRecord.model_validate_json(r[0]) for r in rows]

    def put_sensor(self, s: SensorState) -> None:
        self.db.execute("INSERT OR REPLACE INTO sensors VALUES (?,?,?,?,?)",
                        (s.sensor_id, s.sensor_type, s.zone_id, s.last_seq,
                         s.last_ts.isoformat() if s.last_ts else None))

    def sensors(self) -> list[tuple[str, str, str, int | None, str | None]]:
        return self.db.execute("SELECT * FROM sensors").fetchall()

    def put_lkg(self, r: Reading) -> None:
        self.db.execute("INSERT OR REPLACE INTO lkg VALUES (?,?)", (r.sensor_id, r.model_dump_json()))

    def all_lkg(self) -> list[Reading]:
        return [Reading.model_validate_json(r[0]) for r in self.db.execute("SELECT body FROM lkg")]

    def put_baseline(self, sensor_id: str, field_: str, hour: int, n: int, mean: float, m2: float) -> None:
        self.db.execute("INSERT OR REPLACE INTO baselines VALUES (?,?,?,?,?,?)",
                        (sensor_id, field_, hour, n, mean, m2))

    def baselines(self) -> list[tuple[str, str, int, int, float, float]]:
        return self.db.execute("SELECT * FROM baselines").fetchall()

    def put_kv(self, k: str, v: Any) -> None:
        self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(v)))

    def get_kv(self, k: str, default: Any = None) -> Any:
        row = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(row[0]) if row else default

    def close(self) -> None:
        self.db.close()


class StateStore:
    def __init__(self, db: SqliteStore, history_size: int = 500, lru_size: int = 5000) -> None:
        self.db = db
        self.history_size = history_size
        self.sensors: dict[str, SensorState] = {}
        self._verdicts: OrderedDict[str, Verdict] = OrderedDict()
        self._lru_size = lru_size
        self.call_ids: OrderedDict[str, datetime] = OrderedDict()
        self.zone_calls: dict[str, deque[tuple[datetime, str, str, str]]] = {}  # ts, call_id, caller, type
        self._recover()

    def _recover(self) -> None:
        for sid, stype, zone, seq, ts in self.db.sensors():
            s = self.sensor(sid, stype, zone)
            s.last_seq = seq
            s.last_ts = datetime.fromisoformat(ts) if ts else None
        for r in self.db.all_lkg():
            if r.sensor_id in self.sensors:
                self.sensors[r.sensor_id].lkg = r
        for v in self.db.latest_verdicts():
            if v.sensor_id in self.sensors:
                self.sensors[v.sensor_id].latest_verdict = v
            self._remember(v)

    def sensor(self, sensor_id: str, sensor_type: str, zone_id: str) -> SensorState:
        s = self.sensors.get(sensor_id)
        if s is None:
            s = SensorState(sensor_id, sensor_type, zone_id, deque(maxlen=self.history_size))
            self.sensors[sensor_id] = s
        return s

    def get(self, sensor_id: str) -> SensorState | None:
        return self.sensors.get(sensor_id)

    def in_zones(self, zones: set[str], sensor_type: str | None = None) -> list[SensorState]:
        return [s for s in self.sensors.values()
                if s.zone_id in zones and (sensor_type is None or s.sensor_type == sensor_type)]

    # ---- verdicts
    def _remember(self, v: Verdict) -> None:
        self._verdicts[v.verdict_id] = v
        self._verdicts.move_to_end(v.verdict_id)
        while len(self._verdicts) > self._lru_size:
            self._verdicts.popitem(last=False)

    def put_verdict(self, v: Verdict) -> None:
        self._remember(v)
        self.db.put_verdict(v)

    def get_verdict(self, verdict_id: str) -> Verdict | None:
        return self._verdicts.get(verdict_id) or self.db.get_verdict(verdict_id)

    def find_verdict(self, sensor_id: str, sequence_no: int) -> Verdict | None:
        s = self.sensors.get(sensor_id)
        if s and s.latest_verdict and s.latest_verdict.sequence_no == sequence_no:
            return s.latest_verdict
        return self.db.find_verdict(sensor_id, sequence_no)

    # ---- sequences + last-known-good
    def accept(self, r: Reading, now: datetime) -> SensorState:
        s = self.sensor(r.sensor_id, r.sensor_type, r.zone_id)
        s.zone_id = r.zone_id
        s.last_seq, s.last_ts, s.last_seen = r.sequence_no, r.ts, now
        s.latest_reading = r
        s.arrivals.append(now)
        s.stale = False
        self.db.put_sensor(s)
        return s

    def set_lkg(self, r: Reading) -> None:
        self.sensors[r.sensor_id].lkg = r
        self.db.put_lkg(r)

    # ---- emergency calls
    def remember_call(self, call_id: str, now: datetime, max_ids: int = 100_000) -> None:
        self.call_ids[call_id] = now
        while len(self.call_ids) > max_ids:
            self.call_ids.popitem(last=False)
