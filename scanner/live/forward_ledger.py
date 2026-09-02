from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any

from .models import (
    Direction,
    FeedHealth,
    FeatureSnapshot,
    LifecycleState,
    LiveSignalEvent,
    ProductionStatus,
    StrategyDescriptor,
    StrategyIntent,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_events (
    event_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    event_timestamp TEXT NOT NULL,
    setup_anchor TEXT NOT NULL,
    effective_state TEXT NOT NULL,
    action_label TEXT NOT NULL,
    production_status TEXT NOT NULL,
    production_eligible INTEGER NOT NULL,
    reference_price REAL NOT NULL,
    entry_trigger REAL,
    stop_reference REAL,
    target_1 REAL,
    target_2 REAL,
    setup_score REAL NOT NULL,
    evidence_score REAL NOT NULL,
    execution_score REAL NOT NULL,
    feed_health TEXT NOT NULL,
    feature_json TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    inserted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scanner_health (
    health_id TEXT PRIMARY KEY,
    event_timestamp TEXT NOT NULL,
    state TEXT NOT NULL,
    details_json TEXT NOT NULL
);
"""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class ForwardLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ForwardLedger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def append_event(self, event: LiveSignalEvent, features: FeatureSnapshot) -> bool:
        descriptor = event.intent.descriptor
        intent = event.intent
        envelope = {
            "strategy_family": descriptor.strategy_family,
            "correlation_group": descriptor.correlation_group,
            "required_features": list(descriptor.required_features),
            "explanation": intent.explanation,
            "management_policy": intent.management_policy,
            "intent_metadata": intent.metadata,
            "source_timestamp": event.source_timestamp.isoformat(),
        }
        feature_payload = asdict(features)
        before = self._conn.total_changes
        self._conn.execute(
            """
            INSERT OR IGNORE INTO signal_events (
                event_id, signal_id, strategy_id, variant_id, strategy_version,
                symbol, direction, event_timestamp, setup_anchor, effective_state,
                action_label, production_status, production_eligible, reference_price,
                entry_trigger, stop_reference, target_1, target_2, setup_score,
                evidence_score, execution_score, feed_health, feature_json,
                reason_codes_json, metadata_json, inserted_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event.event_id,
                event.signal_id,
                descriptor.strategy_id,
                descriptor.variant_id,
                descriptor.strategy_version,
                intent.symbol.upper(),
                descriptor.direction.value,
                intent.event_timestamp.isoformat(),
                intent.setup_anchor.isoformat(),
                event.effective_state.value,
                event.action_label,
                descriptor.production_status.value,
                int(descriptor.production_eligible),
                float(intent.reference_price),
                intent.entry_trigger,
                intent.stop_reference,
                intent.target_1,
                intent.target_2,
                float(intent.setup_score),
                float(descriptor.evidence_score),
                float(intent.execution_score),
                event.feed_health.value,
                _json(feature_payload),
                _json(list(intent.reason_codes)),
                _json(envelope),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()
        return self._conn.total_changes > before

    def append_health(
        self,
        timestamp: datetime,
        state: FeedHealth | str,
        details: dict[str, Any],
    ) -> bool:
        state_value = state.value if isinstance(state, FeedHealth) else str(state)
        details_json = _json(details)
        raw = "|".join((timestamp.isoformat(), state_value, details_json))
        health_id = sha256(raw.encode("utf-8")).hexdigest()[:24]
        before = self._conn.total_changes
        self._conn.execute(
            "INSERT OR IGNORE INTO scanner_health (health_id, event_timestamp, state, details_json) VALUES (?,?,?,?)",
            (health_id, timestamp.isoformat(), state_value, details_json),
        )
        self._conn.commit()
        return self._conn.total_changes > before

    def event_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM signal_events").fetchone()
        return int(row["n"])

    def latest_events(self, session_date: date) -> list[LiveSignalEvent]:
        start = datetime.combine(session_date, datetime.min.time()).isoformat()
        end = datetime.combine(session_date + timedelta(days=1), datetime.min.time()).isoformat()
        rows = self._conn.execute(
            """
            SELECT * FROM signal_events
            WHERE event_timestamp >= ? AND event_timestamp < ?
            ORDER BY event_timestamp, inserted_at
            """,
            (start, end),
        ).fetchall()
        if not rows:
            # ISO timestamps may carry UTC offsets; fall back to their date prefix.
            rows = self._conn.execute(
                "SELECT * FROM signal_events WHERE substr(event_timestamp, 1, 10) = ? ORDER BY event_timestamp, inserted_at",
                (session_date.isoformat(),),
            ).fetchall()
        return [self._restore_event(row) for row in rows]

    @staticmethod
    def _restore_event(row: sqlite3.Row) -> LiveSignalEvent:
        envelope = json.loads(row["metadata_json"])
        descriptor = StrategyDescriptor(
            strategy_id=row["strategy_id"],
            strategy_family=envelope.get("strategy_family", row["strategy_id"]),
            variant_id=row["variant_id"],
            direction=Direction(row["direction"]),
            strategy_version=row["strategy_version"],
            production_status=ProductionStatus(row["production_status"]),
            production_eligible=bool(row["production_eligible"]),
            correlation_group=envelope.get("correlation_group", row["strategy_id"]),
            evidence_score=float(row["evidence_score"]),
            required_features=tuple(envelope.get("required_features", ())),
        )
        intent = StrategyIntent(
            descriptor=descriptor,
            symbol=row["symbol"],
            state=LifecycleState(row["effective_state"]),
            event_timestamp=_parse_dt(row["event_timestamp"]),
            setup_anchor=_parse_dt(row["setup_anchor"]),
            reference_price=float(row["reference_price"]),
            setup_score=float(row["setup_score"]),
            execution_score=float(row["execution_score"]),
            reason_codes=tuple(json.loads(row["reason_codes_json"])),
            explanation=envelope.get("explanation", "restored from forward ledger"),
            entry_trigger=row["entry_trigger"],
            stop_reference=row["stop_reference"],
            target_1=row["target_1"],
            target_2=row["target_2"],
            management_policy=envelope.get("management_policy"),
            metadata=envelope.get("intent_metadata", {}),
        )
        source_value = envelope.get("source_timestamp", row["event_timestamp"])
        return LiveSignalEvent(
            event_id=row["event_id"],
            signal_id=row["signal_id"],
            intent=intent,
            effective_state=LifecycleState(row["effective_state"]),
            action_label=row["action_label"],
            feed_health=FeedHealth(row["feed_health"]),
            source_timestamp=_parse_dt(source_value),
        )
