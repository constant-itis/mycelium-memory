"""Drain JSONL decision logs into SQLite foundry_decisions.

Idempotent: tracks per-file byte offset in foundry_ingest_state. Safe to run on
a timer; stops at the last newline if a writer is mid-write.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .schema import connect, init_schema


INSERT_SQL = """
INSERT INTO foundry_decisions (
    ts, decision_point, agent, tier, client_id, trace_id,
    input_features, decision_made, alternatives_considered, outcome,
    elapsed_ms, cost, qc_status,
    failure_class, failure_detail, trap_pattern_ref,
    source_file, source_line
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def _to_row(rec: dict) -> tuple:
    """Convert a JSON record to the parameter tuple for INSERT_SQL.

    JSON columns (input_features, alternatives_considered, outcome) are stored
    as TEXT — we serialize here so SQLite gets strings, not Python objects.
    """
    def _j(v):
        return json.dumps(v) if v is not None else None
    return (
        rec.get("ts"),
        rec.get("decision_point") or "",
        rec.get("agent") or "",
        rec.get("tier"),
        rec.get("client_id"),
        rec.get("trace_id"),
        json.dumps(rec.get("input_features") or {}),
        rec.get("decision_made") or "",
        _j(rec.get("alternatives_considered")),
        _j(rec.get("outcome")),
        rec.get("elapsed_ms"),
        rec.get("cost"),
        rec.get("qc_status"),
        rec.get("failure_class"),
        rec.get("failure_detail"),
        rec.get("trap_pattern_ref"),
        rec.get("source_file"),
        rec.get("source_line"),
    )


def drain_file(conn: sqlite3.Connection, path: Path) -> int:
    """Drain one JSONL file. Returns count of rows ingested this call."""
    cur = conn.execute(
        "SELECT last_offset FROM foundry_ingest_state WHERE source_file = ?",
        (str(path),),
    )
    row = cur.fetchone()
    offset = row[0] if row else 0

    size = path.stat().st_size
    if size <= offset:
        return 0

    with path.open("rb") as f:
        f.seek(offset)
        chunk = f.read()
    text = chunk.decode("utf-8", errors="replace")
    last_nl = text.rfind("\n")
    if last_nl < 0:
        return 0  # no complete line yet
    consumable = text[: last_nl + 1]
    new_offset = offset + len(consumable.encode("utf-8"))

    rows = []
    for line in consumable.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows.append(_to_row(rec))

    if rows:
        conn.executemany(INSERT_SQL, rows)
    conn.execute(
        """INSERT INTO foundry_ingest_state (source_file, last_offset, last_run)
           VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
           ON CONFLICT (source_file) DO UPDATE SET
             last_offset = excluded.last_offset,
             last_run = excluded.last_run""",
        (str(path), new_offset),
    )
    conn.commit()
    return len(rows)


def drain_all(db_path: Path, log_dir: Path) -> int:
    """Drain every *.jsonl in log_dir into the foundry DB. Returns total rows."""
    if not log_dir.exists():
        return 0
    init_schema(db_path)
    conn = connect(db_path)
    try:
        total = 0
        for path in sorted(log_dir.glob("*.jsonl")):
            total += drain_file(conn, path)
        return total
    finally:
        conn.close()


def query(
    db_path: Path,
    *,
    agent: str | None = None,
    decision_point: str | None = None,
    failure_class: str | None = None,
    since_iso: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Read decisions back. Filter on any combination of fields."""
    init_schema(db_path)
    conn = connect(db_path)
    try:
        clauses, params = [], []
        if agent:
            clauses.append("agent = ?")
            params.append(agent)
        if decision_point:
            clauses.append("decision_point = ?")
            params.append(decision_point)
        if failure_class:
            clauses.append("failure_class = ?")
            params.append(failure_class)
        if since_iso:
            clauses.append("ts >= ?")
            params.append(since_iso)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        sql = f"""
            SELECT id, ts, decision_point, agent, tier, client_id, trace_id,
                   input_features, decision_made, alternatives_considered,
                   outcome, elapsed_ms, cost, qc_status, failure_class,
                   failure_detail, trap_pattern_ref, source_file, source_line
            FROM foundry_decisions
            {where}
            ORDER BY ts DESC
            LIMIT ?
        """
        rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            # decode JSON columns back for the caller
            for k in ("input_features", "alternatives_considered", "outcome"):
                if d.get(k):
                    try:
                        d[k] = json.loads(d[k])
                    except (json.JSONDecodeError, TypeError):
                        pass
            out.append(d)
        return out
    finally:
        conn.close()
