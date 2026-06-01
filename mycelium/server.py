#!/usr/bin/env python3
"""
Mycelium — neural-style memory MCP server.

Memories connect through co-access. Paths strengthen with use, decay without it.
Structure emerges from usage, not taxonomy.

All knobs live in config (see config.example.toml). Run:

    mycelium serve                  # stdio (Claude Code MCP default)
    mycelium serve --transport http # streamable-http
"""
from __future__ import annotations

import contextvars
import json
import math
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import config as _config
from . import embeddings as _embed
from . import maintain as _maintain
from .foundry import publish as foundry_publish
from .foundry import ingest as foundry_ingest
from .foundry.schema import init_schema as _init_foundry_schema


# ----- runtime config (loaded once at startup) -----
_CFG: _config.Config | None = None


def _cfg() -> _config.Config:
    global _CFG
    if _CFG is None:
        _CFG = _config.load()
    return _CFG


def set_config(cfg: _config.Config) -> None:
    """Override the runtime config — useful for tests and the CLI."""
    global _CFG, _schema_initialized
    _CFG = cfg
    _schema_initialized = False  # force re-init against the new DB
    # Pin the foundry publisher's log dir to the config-driven path so writes
    # land where ingest reads from.
    from .foundry import publisher as _publisher
    _publisher.set_log_dir(cfg.foundry_log_dir)


# ----- DB lifecycle -----
_schema_initialized = False
_schema_lock = threading.Lock()


def get_db() -> sqlite3.Connection:
    global _schema_initialized
    db_path = _cfg().db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    if not _schema_initialized:
        with _schema_lock:
            if not _schema_initialized:
                _init_schema(conn)
                _schema_initialized = True
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            project TEXT DEFAULT '',
            tier TEXT DEFAULT 'hot' CHECK(tier IN ('hot', 'cold')),
            created TEXT NOT NULL,
            last_accessed TEXT NOT NULL,
            access_count INTEGER DEFAULT 0,
            pinned INTEGER DEFAULT 0,
            confidence REAL DEFAULT 0.3,
            source_type TEXT DEFAULT 'agent_observation'
        );

        CREATE TABLE IF NOT EXISTS connections (
            source INTEGER NOT NULL,
            target INTEGER NOT NULL,
            strength REAL DEFAULT 1.0,
            last_activated TEXT NOT NULL,
            co_access_count INTEGER DEFAULT 1,
            PRIMARY KEY (source, target),
            FOREIGN KEY (source) REFERENCES memories(id) ON DELETE CASCADE,
            FOREIGN KEY (target) REFERENCES memories(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS recall_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            project TEXT DEFAULT '',
            timestamp TEXT NOT NULL,
            results TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            content,
            content='memories',
            content_rowid='id'
        );

        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
        END;

        CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content)
            VALUES('delete', old.id, old.content);
        END;

        CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE OF content ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content)
            VALUES('delete', old.id, old.content);
            INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
        END;

        CREATE TABLE IF NOT EXISTS agent_access (
            memory_id INTEGER REFERENCES memories(id) ON DELETE CASCADE,
            agent TEXT NOT NULL,
            access_count INTEGER DEFAULT 0,
            last_accessed TEXT NOT NULL,
            PRIMARY KEY (memory_id, agent)
        );

        CREATE TABLE IF NOT EXISTS qc_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            verdict TEXT NOT NULL CHECK(verdict IN ('pass', 'fail')),
            memory_ids TEXT NOT NULL,
            failure_pattern TEXT DEFAULT '',
            timestamp TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS task_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            elapsed_seconds REAL DEFAULT 0,
            cost_estimate REAL DEFAULT 0,
            qc_verdict TEXT DEFAULT 'pending' CHECK(qc_verdict IN ('pass', 'fail', 'pending')),
            model TEXT DEFAULT '',
            timestamp TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS weekly_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            recall_accuracy REAL,
            qc_pass_rate REAL,
            avg_task_time REAL,
            avg_cost REAL,
            memory_utility_rate REAL,
            connection_maturity REAL,
            computed_at TEXT NOT NULL,
            UNIQUE(week_start)
        );

        CREATE TABLE IF NOT EXISTS memory_vectors (
            memory_id INTEGER PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
            dim       INTEGER NOT NULL,
            model     TEXT    NOT NULL,
            vec       BLOB    NOT NULL,
            updated   TEXT    NOT NULL
        );
    """)
    conn.commit()


# ----- helpers -----
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----- semantic recall (optional; active only when [semantic] embed_url set) -----
def _semantic_sims(conn: sqlite3.Connection, qvec) -> dict:
    """{memory_id: cosine} over stored vectors. {} on any failure so recall
    degrades cleanly to pure lexical."""
    try:
        rows = conn.execute("SELECT memory_id, vec FROM memory_vectors").fetchall()
        return _embed.cosine_sims(qvec, [(r["memory_id"], r["vec"]) for r in rows])
    except Exception:
        return {}


def _embed_memory(conn: sqlite3.Connection, memory_id: int, content: str) -> bool:
    """Best-effort: embed one memory and upsert its vector. Never raises."""
    sem = _cfg().semantic
    if not sem.get("embed_url"):
        return False
    try:
        v = _embed.embed_document(
            content or "",
            url=sem["embed_url"],
            model=sem["embed_model"],
            chunk_chars=int(sem["chunk_chars"]),
            timeout=float(sem["timeout_seconds"]),
        )
        conn.execute(
            "INSERT OR REPLACE INTO memory_vectors (memory_id, dim, model, vec, updated) "
            "VALUES (?,?,?,?,?)",
            (memory_id, len(v), sem["embed_model"], _embed.to_blob(v), _now()),
        )
        return True
    except Exception:
        return False  # memory still saved; backfill can fill the vector later


def backfill_vectors(reembed: bool = False) -> dict:
    """Embed all memories into memory_vectors. Idempotent + resumable: skips
    memories already embedded for the current model unless reembed=True."""
    sem = _cfg().semantic
    if not sem.get("embed_url"):
        raise RuntimeError("[semantic] embed_url is not configured")
    conn = get_db()
    rows = conn.execute("SELECT id, content FROM memories").fetchall()
    done: set[int] = set()
    if not reembed:
        done = {
            r[0]
            for r in conn.execute(
                "SELECT memory_id FROM memory_vectors WHERE model=?", (sem["embed_model"],)
            )
        }
    ok = fail = 0
    for r in rows:
        if r["id"] in done:
            continue
        if _embed_memory(conn, r["id"], r["content"]):
            ok += 1
        else:
            fail += 1
        if (ok + fail) % 100 == 0:
            conn.commit()
    conn.commit()
    total = conn.execute(
        "SELECT COUNT(*) FROM memory_vectors WHERE model=?", (sem["embed_model"],)
    ).fetchone()[0]
    conn.close()
    return {"embedded": ok, "failed": fail, "total": total, "memories": len(rows)}


def _decay_strength(strength: float, last_activated: str) -> float:
    try:
        last = datetime.fromisoformat(last_activated)
        days = (datetime.now(timezone.utc) - last).total_seconds() / 86400
        return strength * math.exp(-days / _cfg().memory["decay_tau_days"])
    except (ValueError, TypeError):
        return strength


def _apply_decay(conn: sqlite3.Connection) -> int:
    cfg_mem = _cfg().memory
    prune_threshold = cfg_mem["prune_threshold"]
    pinned_floor = cfg_mem["pinned_decay_floor"]

    pinned_ids = {
        r["id"] for r in conn.execute("SELECT id FROM memories WHERE pinned = 1").fetchall()
    }
    rows = conn.execute(
        "SELECT source, target, strength, last_activated FROM connections"
    ).fetchall()
    to_prune, to_update = [], []
    for r in rows:
        decayed = _decay_strength(r["strength"], r["last_activated"])
        if r["source"] in pinned_ids or r["target"] in pinned_ids:
            decayed = max(decayed, pinned_floor)
        if decayed < prune_threshold:
            to_prune.append((r["source"], r["target"]))
        elif abs(decayed - r["strength"]) > 0.001:
            to_update.append((decayed, r["source"], r["target"]))
    if to_prune:
        conn.executemany("DELETE FROM connections WHERE source=? AND target=?", to_prune)
    if to_update:
        conn.executemany(
            "UPDATE connections SET strength=? WHERE source=? AND target=?", to_update
        )
    conn.commit()
    return len(to_prune)


def _touch_memory(conn: sqlite3.Connection, memory_id: int, agent: str = "") -> None:
    now = _now()
    conn.execute(
        "UPDATE memories SET last_accessed=?, access_count=access_count+1 WHERE id=?",
        (now, memory_id),
    )
    if agent:
        existing = conn.execute(
            "SELECT access_count FROM agent_access WHERE memory_id=? AND agent=?",
            (memory_id, agent),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE agent_access SET access_count=access_count+1, last_accessed=? "
                "WHERE memory_id=? AND agent=?",
                (now, memory_id, agent),
            )
        else:
            conn.execute(
                "INSERT INTO agent_access (memory_id, agent, access_count, last_accessed) "
                "VALUES (?,?,1,?)",
                (memory_id, agent, now),
            )


def _strengthen_connection(
    conn: sqlite3.Connection, id_a: int, id_b: int, boost: float = 1.0
) -> None:
    if id_a == id_b:
        return
    now = _now()
    for s, t in [(id_a, id_b), (id_b, id_a)]:
        existing = conn.execute(
            "SELECT strength, co_access_count FROM connections WHERE source=? AND target=?",
            (s, t),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE connections SET strength=?, co_access_count=co_access_count+1, "
                "last_activated=? WHERE source=? AND target=?",
                (existing["strength"] + boost, now, s, t),
            )
        else:
            conn.execute(
                "INSERT INTO connections (source, target, strength, last_activated, "
                "co_access_count) VALUES (?,?,?,?,1)",
                (s, t, boost, now),
            )


def _get_neighbors(conn: sqlite3.Connection, memory_id: int, limit: int | None = None) -> list[dict]:
    if limit is None:
        limit = _cfg().memory["recall_propagate"]
    rows = conn.execute(
        """
        SELECT m.id, m.content, m.project, m.tier, m.access_count,
               c.strength, c.last_activated, c.co_access_count
        FROM connections c
        JOIN memories m ON m.id = c.target
        WHERE c.source = ?
        ORDER BY c.strength DESC
        LIMIT ?
    """,
        (memory_id, limit),
    ).fetchall()

    prune_threshold = _cfg().memory["prune_threshold"]
    results = []
    for r in rows:
        decayed = _decay_strength(r["strength"], r["last_activated"])
        if decayed >= prune_threshold:
            results.append({
                "id": r["id"],
                "content": r["content"],
                "project": r["project"],
                "tier": r["tier"],
                "connection_strength": round(decayed, 3),
                "co_access_count": r["co_access_count"],
            })
    return results


_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could",
    "i", "me", "my", "we", "our", "you", "your", "he", "him", "his",
    "she", "her", "it", "its", "they", "them", "their",
    "what", "which", "who", "whom", "this", "that", "these", "those",
    "am", "if", "or", "but", "and", "not", "no", "nor", "so", "too",
    "very", "just", "how", "why", "when", "where", "much", "many",
    "of", "in", "to", "for", "with", "on", "at", "from", "by", "about",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "up", "down", "over", "under", "again",
    "then", "here", "there", "all", "any", "both", "each", "more",
    "other", "some", "such", "than", "also",
})


def _sanitize_fts_query(query: str) -> str:
    cleaned = re.sub(r'["\'^*:(){}]', "", query).replace("-", " ")
    tokens = [t.strip() for t in cleaned.split() if t.strip()]
    meaningful = [t for t in tokens if t.lower() not in _STOPWORDS]
    if meaningful:
        tokens = meaningful
    if not tokens:
        return query
    return " OR ".join(f'"{t}"' for t in tokens)


def _fts_search(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict]:
    raw_tokens = [
        t.strip().lower()
        for t in re.sub(r'["\'^*:(){}]', "", query).replace("-", " ").split()
        if t.strip()
    ]
    meaningful_tokens = [t for t in raw_tokens if t not in _STOPWORDS]
    score_tokens = meaningful_tokens if meaningful_tokens else raw_tokens

    results: list[dict] = []
    try:
        rows = conn.execute(
            """
            SELECT m.id, m.content, m.project, m.tier, m.access_count,
                   m.created, m.last_accessed
            FROM memories_fts f
            JOIN memories m ON m.id = f.rowid
            WHERE memories_fts MATCH ?
            ORDER BY f.rank
            LIMIT ?
        """,
            (_sanitize_fts_query(query), limit * 3),
        ).fetchall()
        results = [dict(r) for r in rows]
    except Exception:
        pass

    if not results and raw_tokens:
        clauses = " OR ".join(["LOWER(m.content) LIKE ?"] * len(raw_tokens))
        params = [f"%{t}%" for t in raw_tokens] + [limit * 3]
        rows = conn.execute(
            f"""
            SELECT m.id, m.content, m.project, m.tier, m.access_count,
                   m.created, m.last_accessed
            FROM memories m
            WHERE {clauses}
            LIMIT ?
        """,
            params,
        ).fetchall()
        results = [dict(r) for r in rows]

    if not results:
        return []

    def _score(memory: dict) -> float:
        content_lower = memory["content"].lower()
        hits = sum(1 for t in score_tokens if t in content_lower)
        coverage = hits / len(score_tokens) if score_tokens else 0
        access_boost = math.log1p(memory.get("access_count", 0)) * 0.05
        recency_boost = 0.0
        created = memory.get("created", "")
        if created:
            try:
                created_dt = datetime.fromisoformat(created)
                days_old = max(
                    0, (datetime.now(timezone.utc) - created_dt).total_seconds() / 86400
                )
                recency_boost = 0.3 * math.exp(-days_old / 3.0)
            except (ValueError, TypeError):
                pass
        return coverage + access_boost + recency_boost

    results.sort(key=_score, reverse=True)
    return results[:limit]


def _format_memory(m: dict) -> str:
    parts = [f"[#{m['id']}]"]
    if m.get("project"):
        parts.append(f"({m['project']})")
    if m.get("tier") == "cold":
        parts.append("[consolidated]")
    if m.get("pinned"):
        parts.append("[pinned]")
    parts.append(m["content"])
    if m.get("connection_strength"):
        parts.append(f"[strength: {m['connection_strength']}]")
    return " ".join(parts)


# ----- session co-access tracking -----
_session_accessed: contextvars.ContextVar[list[int] | None] = contextvars.ContextVar(
    "session_accessed", default=None
)


def _track_session_access(conn: sqlite3.Connection, memory_id: int, agent: str = "") -> None:
    accessed = _session_accessed.get(None)
    if accessed is None:
        accessed = []
        _session_accessed.set(accessed)
    for prev_id in accessed:
        if prev_id != memory_id:
            _strengthen_connection(conn, prev_id, memory_id, boost=0.5)
    if memory_id not in accessed:
        accessed.append(memory_id)


# ----- MCP server -----
mcp = FastMCP(
    "mycelium",
    instructions=(
        "Mycelium is your persistent memory system. It works like a neural network — "
        "memories connect through co-access, paths strengthen with use, decay without it.\n\n"
        "At the start of every conversation, call `context` to load your core memories.\n"
        "When you learn something worth remembering, call `save`.\n"
        "When you need to find something, call `recall`.\n"
        "Periodically call `review` to maintain the network.\n\n"
        "If foundry is enabled, use `log_decision` to record decisions for later analysis "
        "and `query_decisions` to read them back."
    ),
)


def _check_duplicates(conn, content: str, project: str = "", threshold: float = 0.6) -> list[dict]:
    raw_tokens = {
        t.lower()
        for t in re.sub(r'["\'^*:(){}]', "", content).replace("-", " ").split()
        if len(t.strip()) > 2
    }
    if not raw_tokens:
        return []

    candidates = _fts_search(conn, content, limit=8)
    if project:
        proj_memories = conn.execute(
            "SELECT id, content, project, tier, access_count, created, last_accessed "
            "FROM memories WHERE project = ? ORDER BY last_accessed DESC LIMIT 20",
            (project,),
        ).fetchall()
        seen_ids = {c["id"] for c in candidates}
        for m in proj_memories:
            if m["id"] not in seen_ids:
                candidates.append(dict(m))

    overlaps = []
    for c in candidates:
        c_tokens = {
            t.lower()
            for t in re.sub(r'["\'^*:(){}]', "", c["content"]).replace("-", " ").split()
            if len(t.strip()) > 2
        }
        if not c_tokens:
            continue
        coverage = len(raw_tokens & c_tokens) / len(raw_tokens) if raw_tokens else 0
        if coverage >= threshold:
            overlaps.append({**c, "_overlap": round(coverage, 2)})

    overlaps.sort(key=lambda x: x["_overlap"], reverse=True)
    return overlaps[:3]


@mcp.tool()
def save(
    content: str,
    project: str = "",
    related_to: list[int] | None = None,
    force: bool = False,
    agent: str = "",
    pinned: bool = False,
    confidence: float = 0.3,
    source_type: str = "agent_observation",
) -> str:
    """Save a memory. Keep it short and dense — one idea per memory.

    The system auto-connects it to similar existing memories. If a similar memory
    already exists, suggests updating instead — pass force=True to save anyway.
    Set pinned=True for human-confirmed facts; pinned memories resist decay.
    """
    conn = get_db()
    now = _now()

    if not force:
        dupes = _check_duplicates(conn, content, project)
        if dupes:
            lines = ["Similar memories already exist:"]
            for d in dupes:
                lines.append(f"  [#{d['id']}] ({d['_overlap']:.0%} overlap) {d['content'][:100]}")
            lines.append("\nTo save anyway, call save() with force=True.")
            lines.append("To update, call forget(id) then save() with merged content.")
            conn.close()
            return "\n".join(lines)

    auto_limit = _cfg().memory["auto_connect_limit"]
    similar_pre = []
    try:
        similar_pre = _fts_search(conn, content, limit=auto_limit)
    except Exception:
        pass

    cur = conn.execute(
        "INSERT INTO memories (content, project, tier, created, last_accessed, "
        "access_count, pinned, confidence, source_type) "
        "VALUES (?,?,'hot',?,?,1,?,?,?)",
        (
            content,
            project,
            now,
            now,
            1 if pinned else 0,
            0.8 if pinned else confidence,
            source_type,
        ),
    )
    new_id = cur.lastrowid

    if agent:
        conn.execute(
            "INSERT INTO agent_access (memory_id, agent, access_count, last_accessed) "
            "VALUES (?,?,1,?)",
            (new_id, agent, now),
        )

    neighbors_found = []
    for s in similar_pre:
        if s["id"] != new_id:
            _strengthen_connection(conn, new_id, s["id"], boost=1.0)
            neighbors_found.append(s)

    if related_to:
        for rid in related_to:
            _strengthen_connection(conn, new_id, rid, boost=2.0)
            row = conn.execute(
                "SELECT id, content, project, tier, access_count FROM memories WHERE id=?",
                (rid,),
            ).fetchone()
            if row and not any(n["id"] == rid for n in neighbors_found):
                neighbors_found.append(dict(row))

    conn.commit()

    # Embed-on-save (optional, best-effort) so new memories are immediately
    # reachable by semantic recall. Never blocks meaningfully or fails the save.
    if _cfg().semantic.get("embed_url"):
        if _embed_memory(conn, new_id, content):
            conn.commit()

    lines = [f"Saved #{new_id}"]
    if project:
        lines[0] += f" ({project})"
    if pinned:
        lines[0] += " [pinned]"

    if neighbors_found:
        lines.append(f"\nConnected to {len(neighbors_found)} related memories:")
        for n in neighbors_found:
            lines.append(f"  {_format_memory(n)}")

    if project:
        threshold = _cfg().memory["consolidation_threshold"]
        count = conn.execute(
            "SELECT COUNT(*) as c FROM memories WHERE project=? AND tier='hot'",
            (project,),
        ).fetchone()["c"]
        if count >= threshold:
            lines.append(
                f"\nProject '{project}' has {count} hot memories — consider consolidating."
            )

    conn.close()
    return "\n".join(lines)


@mcp.tool()
def resolve(term: str, meanings: str) -> str:
    """Create a disambiguation memory for an ambiguous term.

    Pass the term and a description of what it can mean. When recall hits a
    resolver, it returns the disambiguation to help pick the right memory.

    Example:
        resolve("MERCURY",
                "1. mercury-api: REST service on staging\\n"
                "2. mercury-stream: WebSocket service on prod")
    """
    conn = get_db()
    now = _now()
    content = f"RESOLVER: {term}\n{meanings}"

    existing = conn.execute(
        "SELECT id FROM memories WHERE content LIKE ?", (f"RESOLVER: {term}%",)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE memories SET content = ?, last_accessed = ? WHERE id = ?",
            (content, now, existing["id"]),
        )
        conn.commit()
        conn.close()
        return f"Updated resolver for '{term}' (#{existing['id']})"

    cur = conn.execute(
        "INSERT INTO memories (content, project, tier, created, last_accessed, access_count) "
        "VALUES (?,'','hot',?,?,1)",
        (content, now, now),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return f"Created resolver for '{term}' (#{new_id})"


@mcp.tool()
def recall(query: str, project: str = "", limit: int = 5, agent: str = "") -> str:
    """Search memories and propagate through connections.

    Returns a unified ranked list where connection strength is a ranking signal.
    Checks resolvers first for disambiguation.
    """
    conn = get_db()
    pruned = _apply_decay(conn)

    resolver = conn.execute(
        "SELECT id, content FROM memories WHERE content LIKE 'RESOLVER: ' || ? || '%'",
        (query.split()[0] if query.split() else query,),
    ).fetchone()
    resolver_note = ""
    if resolver:
        resolver_note = f"\n## Disambiguation\n  {resolver['content']}\n"
        _touch_memory(conn, resolver["id"], agent=agent)

    results = _fts_search(conn, query, limit=limit)

    if not results and project:
        results = conn.execute(
            "SELECT id, content, project, tier, access_count, created, last_accessed "
            "FROM memories WHERE project=? ORDER BY last_accessed DESC LIMIT ?",
            (project, limit),
        ).fetchall()
        results = [dict(r) for r in results]

    # Semantic arm (optional). Merges the top semantically-similar memories into
    # the candidate pool so meaning-based queries reach memories that share no
    # keywords. `sims` (id -> cosine) is reused below as a primary score term.
    # Any failure (endpoint down, etc.) leaves sims empty -> pure lexical.
    sem = _cfg().semantic
    sims: dict = {}
    if sem.get("embed_url"):
        try:
            qvec = _embed.embed_query(
                query, url=sem["embed_url"], model=sem["embed_model"],
                timeout=float(sem["timeout_seconds"]),
            )
            sims = _semantic_sims(conn, qvec)
        except Exception:
            sims = {}
    if sims:
        have = {r["id"] for r in results}
        for mid, _cos in sorted(sims.items(), key=lambda kv: -kv[1])[: int(sem["top_k"])]:
            if mid in have:
                continue
            row = conn.execute(
                "SELECT id, content, project, tier, access_count, created, last_accessed "
                "FROM memories WHERE id=?",
                (mid,),
            ).fetchone()
            if row:
                results.append(dict(row))
                have.add(mid)

    if not results:
        conn.close()
        return "No memories found."

    for r in results:
        _touch_memory(conn, r["id"], agent=agent)
        _track_session_access(conn, r["id"], agent=agent)

    raw_tokens = [
        t.strip().lower()
        for t in re.sub(r'["\'^*:(){}]', "", query).replace("-", " ").split()
        if t.strip()
    ]
    meaningful_tokens = [t for t in raw_tokens if t not in _STOPWORDS]
    score_tokens = meaningful_tokens if meaningful_tokens else raw_tokens

    def _relevance(memory: dict) -> float:
        content_lower = memory["content"].lower()
        hits = sum(1 for t in score_tokens if t in content_lower) if score_tokens else 0
        coverage = hits / len(score_tokens) if score_tokens else 0.5
        access_boost = math.log1p(memory.get("access_count", 0)) * 0.05
        recency_boost = 0.0
        created = memory.get("created", "")
        if created:
            try:
                created_dt = datetime.fromisoformat(created)
                days_old = max(
                    0, (datetime.now(timezone.utc) - created_dt).total_seconds() / 86400
                )
                recency_boost = 0.3 * math.exp(-days_old / 3.0)
            except (ValueError, TypeError):
                pass
        # Semantic similarity as a primary ranking signal (semantic-led). 0 when
        # disabled or the memory has no vector, so lexical behavior is unchanged.
        semantic_boost = float(sem["weight"]) * sims.get(memory["id"], 0.0) if sims else 0.0
        return coverage + access_boost + recency_boost + semantic_boost

    pool: dict[int, tuple[dict, float, str]] = {}
    for r in results:
        pool[r["id"]] = (r, _relevance(r), "direct")

    for r in results:
        for n in _get_neighbors(conn, r["id"]):
            conn_str = n["connection_strength"]
            if n["id"] in pool:
                m, s, label = pool[n["id"]]
                if label == "direct":
                    pool[n["id"]] = (m, s + conn_str * 0.2, label)
            else:
                prop_relevance = _relevance(n)
                prop_score = (
                    prop_relevance * conn_str if prop_relevance > 0 else conn_str * 0.1
                )
                if n["id"] not in pool or pool[n["id"]][1] < prop_score:
                    pool[n["id"]] = (n, prop_score, "connected")

    ranked = sorted(pool.values(), key=lambda x: x[1], reverse=True)
    log_results = [
        {"id": m["id"], "score": round(s, 4), "source": src} for m, s, src in ranked
    ]
    try:
        conn.execute(
            "INSERT INTO recall_log (query, project, timestamp, results) VALUES (?,?,?,?)",
            (query, project, _now(), json.dumps(log_results)),
        )
    except Exception:
        pass

    conn.commit()

    lines = [f"## Recall: {len(ranked)} memories"]
    total_to_show = limit + _cfg().memory["recall_propagate"]
    for m, score, source in ranked[:total_to_show]:
        tag = "↔" if source == "connected" else "●"
        lines.append(f"  {tag} {_format_memory(m)} [score: {score:.2f}]")

    projects = {m["project"] for m, _, _ in ranked if m.get("project")}
    if len(projects) > 1:
        lines.append(f"\n## Spans projects: {', '.join(sorted(projects))}")

    if resolver_note:
        lines.insert(0, resolver_note)
    if pruned:
        lines.append(f"\n({pruned} dead connections pruned)")

    conn.close()
    return "\n".join(lines)


@mcp.tool()
def context(project: str = "", agent: str = "") -> str:
    """Load startup context — the hubs of your memory network.

    Returns the most connected, most accessed memories. Call at session start.
    When agent is provided, ranks by that agent's access patterns.
    """
    conn = get_db()
    _apply_decay(conn)
    hub_limit = _cfg().memory["hub_limit"]

    agent_has_history = False
    if agent:
        agent_count = conn.execute(
            "SELECT COUNT(*) as c FROM agent_access WHERE agent=?", (agent,)
        ).fetchone()["c"]
        agent_has_history = agent_count > 0

    if agent and agent_has_history:
        sql = """
            SELECT m.id, m.content, m.project, m.tier, m.access_count, m.last_accessed,
                   COUNT(c.target) as connection_count,
                   COALESCE(aa.access_count, 0) as agent_access_count
            FROM memories m
            LEFT JOIN connections c ON m.id = c.source
            LEFT JOIN agent_access aa ON m.id = aa.memory_id AND aa.agent = ?
            {where}
            GROUP BY m.id
            ORDER BY (COALESCE(aa.access_count, 0) * (COUNT(c.target) + 1)) DESC,
                     (m.access_count * (COUNT(c.target) + 1)) DESC
            LIMIT ?
        """
        if project:
            rows = conn.execute(
                sql.format(where="WHERE m.project = ?"), (agent, project, hub_limit)
            ).fetchall()
        else:
            rows = conn.execute(sql.format(where=""), (agent, hub_limit)).fetchall()
    else:
        sql = """
            SELECT m.id, m.content, m.project, m.tier, m.access_count, m.last_accessed,
                   COUNT(c.target) as connection_count
            FROM memories m
            LEFT JOIN connections c ON m.id = c.source
            {where}
            GROUP BY m.id
            ORDER BY (m.access_count * (COUNT(c.target) + 1)) DESC
            LIMIT ?
        """
        if project:
            rows = conn.execute(
                sql.format(where="WHERE m.project = ?"), (project, hub_limit)
            ).fetchall()
        else:
            rows = conn.execute(sql.format(where=""), (hub_limit,)).fetchall()

    if not rows:
        conn.close()
        return "No memories yet."

    for r in rows:
        _touch_memory(conn, r["id"], agent=agent)

    total = conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]
    hot = conn.execute("SELECT COUNT(*) as c FROM memories WHERE tier='hot'").fetchone()["c"]
    cold = conn.execute("SELECT COUNT(*) as c FROM memories WHERE tier='cold'").fetchone()["c"]
    conn_count = conn.execute("SELECT COUNT(*) as c FROM connections").fetchone()["c"]
    projects = conn.execute(
        "SELECT project, COUNT(*) as c FROM memories WHERE project != '' "
        "GROUP BY project ORDER BY c DESC"
    ).fetchall()

    conn.commit()

    lines = [
        f"## Mycelium — {total} memories, {conn_count} connections "
        f"(hot: {hot}, cold: {cold})"
    ]
    if projects:
        lines.append("\n## Projects")
        for p in projects:
            lines.append(f"  {p['project']}: {p['c']} memories")
    lines.append("\n## Hubs")
    for r in rows:
        lines.append(
            f"  {_format_memory(dict(r))} "
            f"[connections: {r['connection_count']}, accessed: {r['access_count']}x]"
        )

    conn.close()
    return "\n".join(lines)


@mcp.tool()
def review() -> str:
    """Review the health of the memory network.

    Shows stale memories, dense clusters needing consolidation, and stats.
    """
    conn = get_db()
    pruned = _apply_decay(conn)
    threshold = _cfg().memory["consolidation_threshold"]

    lines = ["## Network Review"]
    total = conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]
    hot = conn.execute("SELECT COUNT(*) as c FROM memories WHERE tier='hot'").fetchone()["c"]
    cold = conn.execute("SELECT COUNT(*) as c FROM memories WHERE tier='cold'").fetchone()["c"]
    conns = conn.execute("SELECT COUNT(*) as c FROM connections").fetchone()["c"]
    lines.append(f"\nTotal: {total} memories ({hot} hot, {cold} cold), {conns} connections")
    if pruned:
        lines.append(f"Pruned {pruned} dead connections this cycle")

    stale = conn.execute(
        "SELECT id, content, project, last_accessed FROM memories "
        "WHERE julianday('now') - julianday(last_accessed) > 90 "
        "ORDER BY last_accessed ASC LIMIT 10"
    ).fetchall()
    if stale:
        lines.append(f"\n## Stale ({len(stale)} memories not accessed in 90+ days)")
        for s in stale:
            lines.append(
                f"  [#{s['id']}] {s['content'][:80]}... (last: {s['last_accessed'][:10]})"
            )

    dense = conn.execute(
        "SELECT project, COUNT(*) as c FROM memories "
        "WHERE tier='hot' AND project != '' GROUP BY project HAVING c >= ? "
        "ORDER BY c DESC",
        (threshold,),
    ).fetchall()
    if dense:
        lines.append("\n## Dense clusters — consider consolidating")
        for d in dense:
            lines.append(f"  {d['project']}: {d['c']} hot memories")

    orphans = conn.execute(
        "SELECT m.id, m.content, m.project FROM memories m "
        "LEFT JOIN connections c ON m.id = c.source OR m.id = c.target "
        "WHERE c.source IS NULL LIMIT 10"
    ).fetchall()
    if orphans:
        lines.append("\n## Orphaned memories (no connections)")
        for o in orphans:
            lines.append(f"  [#{o['id']}] {o['content'][:80]}")

    conn.close()
    return "\n".join(lines)


@mcp.tool()
def consolidate(project: str = "", memory_ids: list[int] | None = None) -> str:
    """Show memories ready for consolidation.

    Pass a project to see all hot memories for that project, or specific ids.
    Synthesize them by calling save() with the summary, then forget() the originals.
    """
    conn = get_db()
    if memory_ids:
        placeholders = ",".join("?" * len(memory_ids))
        rows = conn.execute(
            f"SELECT id, content, project, tier, access_count, created "
            f"FROM memories WHERE id IN ({placeholders}) ORDER BY created ASC",
            memory_ids,
        ).fetchall()
    elif project:
        rows = conn.execute(
            "SELECT id, content, project, tier, access_count, created "
            "FROM memories WHERE project=? AND tier='hot' ORDER BY created ASC",
            (project,),
        ).fetchall()
    else:
        conn.close()
        return "Provide a project name or specific memory_ids to consolidate."

    if not rows:
        conn.close()
        return "No memories found to consolidate."

    lines = [f"## Consolidation candidates ({len(rows)} memories)"]
    lines.append("Review these, then:")
    lines.append("1. Call save() with a synthesized summary (becomes a cold memory)")
    lines.append("2. Call forget() on the originals you've absorbed\n")
    for r in rows:
        lines.append(f"  [#{r['id']}] ({r['created'][:10]}) {r['content']}")
    conn.close()
    return "\n".join(lines)


@mcp.tool()
def discover() -> str:
    """Discover hidden connections in the memory network.

    Three passes:
      1. Semantic bridges — sample hot memories, FTS-link similar ones not yet connected
      2. Keyword clusters — link memories sharing any keyword from
         memory.keyword_clusters in config (skipped when empty)
      3. Project hubs — connect each project's most-accessed memory to the rest
      4. Orphan rescue — give zero-connection memories a starter link

    Creates weak connections (0.3-0.5) that strengthen with co-access or decay
    naturally. Run during idle time or as nightly maintenance.
    """
    conn = get_db()
    discoveries = 0
    report = ["## Discovery Report\n"]

    samples = conn.execute(
        "SELECT id, content, project FROM memories WHERE tier='hot' "
        "ORDER BY RANDOM() LIMIT 40"
    ).fetchall()
    semantic_found = 0
    for mem in samples:
        try:
            similar = _fts_search(conn, mem["content"], limit=5)
        except Exception:
            continue
        for s in similar:
            if s["id"] == mem["id"]:
                continue
            existing = conn.execute(
                "SELECT 1 FROM connections WHERE (source=? AND target=?) "
                "OR (source=? AND target=?)",
                (mem["id"], s["id"], s["id"], mem["id"]),
            ).fetchone()
            if not existing:
                _strengthen_connection(conn, mem["id"], s["id"], boost=0.5)
                semantic_found += 1
                discoveries += 1
    report.append(
        f"**Semantic bridges:** {semantic_found} new connections from content similarity"
    )

    cluster_found = 0
    for keyword in _cfg().memory.get("keyword_clusters") or []:
        keyword = str(keyword).strip()
        if not keyword:
            continue
        rows = conn.execute(
            "SELECT id FROM memories WHERE LOWER(content) LIKE ? AND tier='hot'",
            (f"%{keyword.lower()}%",),
        ).fetchall()
        ids = [r["id"] for r in rows]
        if len(ids) < 2:
            continue
        pairs_done = 0
        for i, a in enumerate(ids):
            if pairs_done >= 10:
                break
            for b in ids[i + 1:]:
                if pairs_done >= 10:
                    break
                existing = conn.execute(
                    "SELECT 1 FROM connections WHERE (source=? AND target=?) "
                    "OR (source=? AND target=?)",
                    (a, b, b, a),
                ).fetchone()
                if not existing:
                    _strengthen_connection(conn, a, b, boost=0.3)
                    cluster_found += 1
                    discoveries += 1
                    pairs_done += 1
    if cluster_found:
        report.append(
            f"**Keyword clusters:** {cluster_found} links from configured keywords"
        )

    project_links = 0
    projects = conn.execute(
        "SELECT DISTINCT project FROM memories WHERE project != '' AND tier='hot'"
    ).fetchall()
    for p in projects:
        proj_mems = conn.execute(
            "SELECT id FROM memories WHERE project=? AND tier='hot' "
            "ORDER BY access_count DESC LIMIT 20",
            (p["project"],),
        ).fetchall()
        if len(proj_mems) < 2:
            continue
        hub_id = proj_mems[0]["id"]
        for m in proj_mems[1:]:
            existing = conn.execute(
                "SELECT 1 FROM connections WHERE (source=? AND target=?) "
                "OR (source=? AND target=?)",
                (hub_id, m["id"], m["id"], hub_id),
            ).fetchone()
            if not existing:
                _strengthen_connection(conn, hub_id, m["id"], boost=0.3)
                project_links += 1
                discoveries += 1
    report.append(f"**Project hubs:** {project_links} hub-spoke links")

    orphans = conn.execute(
        "SELECT m.id, m.content, m.project FROM memories m "
        "LEFT JOIN connections c ON m.id = c.source OR m.id = c.target "
        "WHERE c.source IS NULL AND m.tier='hot'"
    ).fetchall()
    orphan_rescued = 0
    for orphan in orphans:
        try:
            similar = _fts_search(conn, orphan["content"], limit=3)
        except Exception:
            continue
        for s in similar:
            if s["id"] == orphan["id"]:
                continue
            _strengthen_connection(conn, orphan["id"], s["id"], boost=0.5)
            orphan_rescued += 1
            discoveries += 1
            break
    report.append(
        f"**Orphan rescue:** {orphan_rescued} orphans connected (from {len(orphans)} total)"
    )

    conn.commit()
    conn.close()
    report.append(f"\n**Total discoveries: {discoveries} new connections**")
    return "\n".join(report)


@mcp.tool()
def forget(memory_id: int) -> str:
    """Delete a memory and all its connections."""
    conn = get_db()
    row = conn.execute("SELECT content FROM memories WHERE id=?", (memory_id,)).fetchone()
    if not row:
        conn.close()
        return f"Memory #{memory_id} not found."
    conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
    conn.commit()
    conn.close()
    return f"Forgotten #{memory_id}: {row['content'][:60]}..."


@mcp.tool()
def pin(memory_id: int, unpin: bool = False) -> str:
    """Pin or unpin a memory. Pinned memories' connections never decay below the
    configured pinned_decay_floor.
    """
    conn = get_db()
    row = conn.execute(
        "SELECT id, content, pinned FROM memories WHERE id=?", (memory_id,)
    ).fetchone()
    if not row:
        conn.close()
        return f"Memory #{memory_id} not found."
    new_val = 0 if unpin else 1
    conn.execute("UPDATE memories SET pinned=? WHERE id=?", (new_val, memory_id))
    conn.commit()
    conn.close()
    return f"{'Unpinned' if unpin else 'Pinned'} #{memory_id}: {row['content'][:80]}"


@mcp.tool()
def maintain(
    execute: bool = False,
    recent_days: int = 7,
    confidence_floor: float = 0.8,
    no_backup: bool = False,
) -> str:
    """Periodic memory consolidation — snapshot, plan, cold-mark, orphan rescue.

    Default is dry-run: returns the plan without writing. Pass execute=True to
    apply. Snapshots the DB to backup_dir before any destructive op (skip with
    no_backup=True). Skips anything pinned, anything with confidence above
    confidence_floor, or anything accessed within recent_days.

    Cron path: `mycelium maintain --execute` (same algorithm).
    """
    cfg = _cfg()
    backup_dir = Path(cfg.storage["backup_dir"]).expanduser() if cfg.storage.get("backup_dir") else None
    result = _maintain.run_maintenance(
        cfg.db_path,
        execute=execute,
        recent_days=recent_days,
        confidence_floor=confidence_floor,
        backup_dir=backup_dir,
        no_backup=no_backup,
    )
    return _maintain.format_report(result)


@mcp.tool()
def connections(memory_id: int) -> str:
    """Show all connections for a specific memory — the local network topology."""
    conn = get_db()
    row = conn.execute(
        "SELECT id, content, project, tier FROM memories WHERE id=?", (memory_id,)
    ).fetchone()
    if not row:
        conn.close()
        return f"Memory #{memory_id} not found."
    neighbors = _get_neighbors(conn, memory_id, limit=20)
    lines = [f"## Network for #{memory_id}: {row['content'][:80]}"]
    if not neighbors:
        lines.append("  No connections.")
    else:
        for n in neighbors:
            lines.append(f"  {_format_memory(n)} [co-accessed: {n['co_access_count']}x]")
    conn.close()
    return "\n".join(lines)


# ----- foundry MCP tools (only registered if foundry is enabled) -----
if _cfg().foundry.get("enabled", True):

    @mcp.tool()
    def log_decision(
        decision_point: str,
        agent: str,
        decision_made: str,
        input_features: dict | None = None,
        outcome: dict | None = None,
        elapsed_ms: int | None = None,
        cost: float | None = None,
        qc_status: str | None = None,
        failure_class: str | None = None,
        failure_detail: str | None = None,
    ) -> str:
        """Append one decision to the foundry behavioral log.

        Fail-soft — never raises. Returns "ok" or "skipped".
        Run `mycelium foundry ingest` (or set ingest_interval_seconds) to drain
        the JSONL log into the foundry SQLite for queryable history.
        """
        ok = foundry_publish(
            decision_point,
            agent,
            decision_made,
            input_features=input_features,
            outcome=outcome,
            elapsed_ms=elapsed_ms,
            cost=cost,
            qc_status=qc_status,
            failure_class=failure_class,
            failure_detail=failure_detail,
        )
        return "ok" if ok else "skipped"

    @mcp.tool()
    def query_decisions(
        agent: str = "",
        decision_point: str = "",
        failure_class: str = "",
        since_iso: str = "",
        limit: int = 50,
    ) -> str:
        """Read decisions back from the foundry SQLite.

        Filter by agent, decision_point, failure_class, or since_iso (ISO-8601).
        """
        # Drain any pending JSONL first so reads are fresh.
        try:
            foundry_ingest.drain_all(_cfg().foundry_db_path, _cfg().foundry_log_dir)
        except Exception:
            pass
        rows = foundry_ingest.query(
            _cfg().foundry_db_path,
            agent=agent or None,
            decision_point=decision_point or None,
            failure_class=failure_class or None,
            since_iso=since_iso or None,
            limit=limit,
        )
        if not rows:
            return "No decisions match."
        lines = [f"## Decisions ({len(rows)})"]
        for r in rows:
            head = f"  [{r['ts']}] {r['agent']}/{r['decision_point']}: {r['decision_made']}"
            lines.append(head)
            if r.get("failure_class"):
                lines.append(
                    f"      failure: {r['failure_class']} — {r.get('failure_detail') or ''}"
                )
        return "\n".join(lines)


def serve(transport: str | None = None, host: str | None = None, port: int | None = None) -> None:
    """Start the MCP server. Args override config."""
    cfg = _cfg()
    # Pin the publisher's log dir + init both DBs before accepting traffic.
    from .foundry import publisher as _publisher
    _publisher.set_log_dir(cfg.foundry_log_dir)
    get_db().close()
    if cfg.foundry.get("enabled", True):
        _init_foundry_schema(cfg.foundry_db_path)

    t = transport or cfg.server["transport"]
    if t == "http":
        mcp.settings.host = host or cfg.server["host"]
        mcp.settings.port = port or cfg.server["port"]
        mcp.settings.transport_security.enable_dns_rebinding_protection = False
        mcp.settings.transport_security.allowed_hosts = ["*"]
        mcp.settings.transport_security.allowed_origins = ["*"]
        print(
            f"Mycelium server on {mcp.settings.host}:{mcp.settings.port} "
            f"(streamable-http) [config: {cfg.source}]"
        )
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    serve()
