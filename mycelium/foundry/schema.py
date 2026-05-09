"""Foundry SQLite schema. Idempotent — safe to call on every connection."""
from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS foundry_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    decision_point TEXT NOT NULL,
    agent TEXT NOT NULL,
    tier TEXT,
    client_id TEXT,
    trace_id TEXT,
    input_features TEXT NOT NULL DEFAULT '{}',           -- JSON
    decision_made TEXT NOT NULL,
    alternatives_considered TEXT,                         -- JSON or NULL
    outcome TEXT,                                         -- JSON or NULL
    elapsed_ms INTEGER,
    cost REAL,
    qc_status TEXT,
    failure_class TEXT,
    failure_detail TEXT,
    trap_pattern_ref TEXT,
    source_file TEXT,
    source_line INTEGER
);

CREATE INDEX IF NOT EXISTS foundry_decisions_agent_ts
    ON foundry_decisions (agent, ts DESC);

CREATE INDEX IF NOT EXISTS foundry_decisions_decision_point_ts
    ON foundry_decisions (decision_point, ts DESC);

CREATE INDEX IF NOT EXISTS foundry_decisions_failure_class
    ON foundry_decisions (failure_class, agent, ts)
    WHERE failure_class IS NOT NULL;

CREATE INDEX IF NOT EXISTS foundry_decisions_trace_id
    ON foundry_decisions (trace_id)
    WHERE trace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS foundry_decisions_client_id_ts
    ON foundry_decisions (client_id, ts DESC)
    WHERE client_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS foundry_decisions_qc_status_ts
    ON foundry_decisions (qc_status, ts DESC)
    WHERE qc_status IS NOT NULL;

CREATE TABLE IF NOT EXISTS foundry_ingest_state (
    source_file TEXT PRIMARY KEY,
    last_offset INTEGER NOT NULL DEFAULT 0,
    last_run TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_schema(db_path: Path) -> None:
    """Apply schema. Idempotent."""
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
