"""Periodic memory consolidation pass.

Four phases, all guarded by `execute=True` (default is dry-run):
  1. Snapshot      — copy the DB to backup_dir before any destructive op.
  2. Plan          — identify candidates for cold-marking + orphan rescue.
                     Candidates are NEVER touched if any of these hold:
                       - content contains "[pinned]"
                       - pinned column = 1
                       - confidence >= confidence_floor (default 0.8)
                       - last_accessed within recent_days (default 7)
  3. Cold-mark     — flip duplicate session checkpoints (keep newest per
                     project) and superseded memories ("SUPERSEDES #N" /
                     "superseded by #N") to tier='cold'.
  4. Orphan rescue — for memories with no connections, find one nearest
                     match via FTS and add a low-strength edge so they're
                     reachable on recall.

Same algorithm exposed via:
  - `mycelium maintain` CLI (cron-friendly)
  - `maintain()` MCP tool (Claude-callable)
  - `/maintain` slash skill (paste-prompt UX over the MCP tool)
"""
from __future__ import annotations

import re
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ORPHAN_CONNECTION_STRENGTH = 0.3

ORPHAN_STOPWORDS = frozenset({
    "the", "this", "that", "with", "from", "have", "been", "does", "done",
    "user", "uses", "used", "like", "into", "also", "more", "when", "will",
    "what", "which", "where", "they", "their", "about", "would", "could",
    "should", "some", "other", "most", "just", "very", "then", "than",
    "session", "checkpoint", "working",
})


def _is_protected(memory: tuple, confidence_floor: float, recent_days: int) -> bool:
    """memory tuple shape: (id, content, project, tier, last_accessed, confidence, pinned)."""
    _mid, content, _project, _tier, last_accessed, confidence, pinned = memory
    if "[pinned]" in (content or ""):
        return True
    if pinned == 1:
        return True
    if confidence is not None and confidence >= confidence_floor:
        return True
    if last_accessed:
        try:
            la = datetime.fromisoformat(last_accessed.replace("Z", "+00:00"))
            if la.tzinfo is None:
                la = la.replace(tzinfo=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
            if la >= cutoff:
                return True
        except (ValueError, TypeError):
            pass
    return False


_SELECT_COLS = (
    "id, content, project, tier, last_accessed, confidence, pinned"
)


def _baseline(conn: sqlite3.Connection, confidence_floor: float, recent_days: int) -> dict:
    c = conn.cursor()
    total = c.execute("SELECT count(*) FROM memories").fetchone()[0]
    total_conn = c.execute("SELECT count(*) FROM connections").fetchone()[0]
    tiers = dict(c.execute("SELECT tier, count(*) FROM memories GROUP BY tier").fetchall())
    pinned_text = c.execute(
        "SELECT count(*) FROM memories WHERE content LIKE '%[pinned]%'"
    ).fetchone()[0]
    pinned_col = c.execute(
        "SELECT count(*) FROM memories WHERE pinned = 1"
    ).fetchone()[0]
    high_conf = c.execute(
        "SELECT count(*) FROM memories WHERE confidence >= ?", (confidence_floor,)
    ).fetchone()[0]
    orphans = c.execute(
        "SELECT count(*) FROM memories WHERE id NOT IN "
        "(SELECT source FROM connections UNION SELECT target FROM connections)"
    ).fetchone()[0]
    recent = c.execute(
        "SELECT count(*) FROM memories WHERE last_accessed >= date('now', ?)",
        (f"-{recent_days} days",),
    ).fetchone()[0]
    by_project = c.execute(
        "SELECT project, count(*) FROM memories GROUP BY project ORDER BY count(*) DESC"
    ).fetchall()
    return {
        "total_memories": total,
        "total_connections": total_conn,
        "hot": tiers.get("hot", 0),
        "cold": tiers.get("cold", 0),
        "pinned_tag": pinned_text,
        "pinned_column": pinned_col,
        "high_confidence": high_conf,
        "orphans": orphans,
        "recent": recent,
        "by_project": [{"project": p or "(none)", "count": cnt} for p, cnt in by_project],
    }


def _plan(conn: sqlite3.Connection, confidence_floor: float, recent_days: int) -> dict:
    c = conn.cursor()
    plan = {"session_checkpoints": [], "superseded": [], "orphan_rescues": []}

    # 1) Session-checkpoint duplicates: keep newest per project, cold the rest.
    rows = c.execute(
        f"SELECT {_SELECT_COLS} FROM memories "
        "WHERE (content LIKE '%[session-checkpoint]%' "
        "       OR content LIKE '%Session checkpoint%') "
        "  AND content NOT LIKE '%PROJECT INDEX%' "
        "ORDER BY project, last_accessed DESC"
    ).fetchall()
    by_project = defaultdict(list)
    for r in rows:
        by_project[r[2]].append(r)
    for project, cps in by_project.items():
        if len(cps) <= 1:
            continue
        keep = cps[0]
        cold_ids = []
        for cp in cps:
            if cp[0] == keep[0]:
                continue
            if _is_protected(cp, confidence_floor, recent_days):
                continue
            cold_ids.append(cp[0])
        if cold_ids:
            plan["session_checkpoints"].append({
                "project": project, "keep_id": keep[0], "cold_ids": cold_ids
            })

    # 2) Superseded — explicit "SUPERSEDES #N" or "superseded by #N" markers.
    rows = c.execute(
        f"SELECT {_SELECT_COLS} FROM memories "
        "WHERE content LIKE '%SUPERSEDES%' OR content LIKE '%superseded by%' "
        "ORDER BY last_accessed DESC"
    ).fetchall()
    for row in rows:
        mid, content, *_ = row
        for old_id in (int(m) for m in re.findall(r"SUPERSEDES\s+#(\d+)", content, re.IGNORECASE)):
            old_row = c.execute(
                f"SELECT {_SELECT_COLS} FROM memories WHERE id = ?", (old_id,)
            ).fetchone()
            if not old_row:
                continue
            if _is_protected(old_row, confidence_floor, recent_days):
                continue
            plan["superseded"].append({"newer_id": mid, "old_id": old_id})
        for newer_id in (int(m) for m in re.findall(r"superseded by\s+#(\d+)", content, re.IGNORECASE)):
            if not _is_protected(row, confidence_floor, recent_days):
                plan["superseded"].append({"newer_id": newer_id, "old_id": mid})

    # 3) Orphan rescue — connect each orphan to its FTS-best-match neighbor.
    orphans = c.execute(
        f"SELECT {_SELECT_COLS} FROM memories "
        "WHERE id NOT IN (SELECT source FROM connections UNION SELECT target FROM connections) "
        "ORDER BY id"
    ).fetchall()
    for orphan in orphans:
        oid, content, *_ = orphan
        words = [w.strip("[]().,;:#\"'") for w in (content or "").split()[:20]]
        keywords = [w for w in words if len(w) > 3 and w.lower() not in ORPHAN_STOPWORDS][:5]
        if not keywords:
            continue
        try:
            match = c.execute(
                "SELECT m.id FROM memories_fts "
                "JOIN memories m ON m.id = memories_fts.rowid "
                "WHERE memories_fts MATCH ? AND m.id != ? "
                "ORDER BY memories_fts.rank LIMIT 1",
                (" OR ".join(keywords), oid),
            ).fetchone()
        except sqlite3.OperationalError:
            match = None
        if match:
            plan["orphan_rescues"].append({
                "orphan_id": oid, "connect_to": match[0], "keywords": keywords
            })
    return plan


def _execute(conn: sqlite3.Connection, plan: dict) -> dict:
    c = conn.cursor()
    cold = 0
    for group in plan["session_checkpoints"]:
        for mid in group["cold_ids"]:
            c.execute("UPDATE memories SET tier = 'cold' WHERE id = ? AND tier = 'hot'", (mid,))
            if c.rowcount > 0:
                cold += 1
    for entry in plan["superseded"]:
        c.execute(
            "UPDATE memories SET tier = 'cold' WHERE id = ? AND tier = 'hot'", (entry["old_id"],)
        )
        if c.rowcount > 0:
            cold += 1

    now = datetime.now(timezone.utc).isoformat()
    new_edges = 0
    for rescue in plan["orphan_rescues"]:
        oid, tid = rescue["orphan_id"], rescue["connect_to"]
        existing = c.execute(
            "SELECT 1 FROM connections WHERE (source=? AND target=?) OR (source=? AND target=?)",
            (oid, tid, tid, oid),
        ).fetchone()
        if existing:
            continue
        c.execute(
            "INSERT INTO connections (source, target, strength, last_activated, co_access_count) "
            "VALUES (?, ?, ?, ?, 1)",
            (oid, tid, ORPHAN_CONNECTION_STRENGTH, now),
        )
        new_edges += 1
    conn.commit()
    return {"cold_marked": cold, "new_edges": new_edges}


def run_maintenance(
    db_path: Path,
    *,
    execute: bool = False,
    recent_days: int = 7,
    confidence_floor: float = 0.8,
    backup_dir: Path | None = None,
    no_backup: bool = False,
) -> dict[str, Any]:
    """Run the four-phase consolidation. Default is dry-run (no writes).

    Returns a structured result dict with `mode`, `baseline`, `plan`,
    `executed` (only present when execute=True), and `backup_path` (when a
    backup was made).
    """
    if not db_path.exists():
        return {"error": f"DB not found at {db_path}", "db_path": str(db_path)}

    result: dict[str, Any] = {
        "mode": "execute" if execute else "dry-run",
        "db_path": str(db_path),
        "recent_days": recent_days,
        "confidence_floor": confidence_floor,
    }

    # Snapshot first when executing — never destruct without a rollback path.
    if execute and not no_backup and backup_dir is not None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        target_dir = backup_dir / f"sleep-{ts}"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / db_path.name
        if not target.exists():
            shutil.copy2(db_path, target)
        result["backup_path"] = str(target)

    if execute:
        conn = sqlite3.connect(str(db_path))
    else:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        result["baseline"] = _baseline(conn, confidence_floor, recent_days)
        plan = _plan(conn, confidence_floor, recent_days)
        result["plan"] = {
            "session_checkpoints_to_cold": sum(len(g["cold_ids"]) for g in plan["session_checkpoints"]),
            "superseded_to_cold": len(plan["superseded"]),
            "orphan_rescues_to_create": len(plan["orphan_rescues"]),
            "details": plan,
        }
        if execute:
            result["executed"] = _execute(conn, plan)
    finally:
        conn.close()
    return result


def format_report(result: dict[str, Any]) -> str:
    """Render a run_maintenance() result as a readable report."""
    if "error" in result:
        return f"error: {result['error']}"
    lines = []
    lines.append(f"== mycelium maintain — {result['mode'].upper()} ==")
    lines.append(f"DB: {result['db_path']}")
    lines.append(
        f"Guards: confidence>={result['confidence_floor']}  "
        f"recent<={result['recent_days']}d"
    )
    if "backup_path" in result:
        lines.append(f"Backup: {result['backup_path']}")

    b = result["baseline"]
    lines.append("")
    lines.append("Baseline:")
    lines.append(f"  memories={b['total_memories']}  connections={b['total_connections']}")
    lines.append(f"  hot={b['hot']}  cold={b['cold']}  orphans={b['orphans']}")
    lines.append(
        f"  pinned_tag={b['pinned_tag']}  pinned_col={b['pinned_column']}  "
        f"high_confidence={b['high_confidence']}  recent={b['recent']}"
    )

    p = result["plan"]
    lines.append("")
    lines.append("Plan:")
    lines.append(f"  session checkpoints -> cold:  {p['session_checkpoints_to_cold']}")
    lines.append(f"  superseded          -> cold:  {p['superseded_to_cold']}")
    lines.append(f"  orphan rescues      -> create: {p['orphan_rescues_to_create']}")

    if "executed" in result:
        e = result["executed"]
        lines.append("")
        lines.append("Executed:")
        lines.append(f"  cold-marked: {e['cold_marked']}")
        lines.append(f"  new edges:   {e['new_edges']}")
    else:
        lines.append("")
        lines.append("Dry-run — no changes. Re-run with execute=True to apply.")

    return "\n".join(lines)
