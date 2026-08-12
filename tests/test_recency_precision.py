"""Recency surfacing (recent() / /wake) + contradicts_prior salience.

Runs against throwaway temp DBs (tmp_path + MYCELIUM_STORAGE_DB_PATH) so recency
boundaries, the max(created, last_accessed) rule, the READ-ONLY invariant, and the
salience ranking are all checked deterministically — no network, no prod data.

Covers:
  - contradicts_prior migration lands the column on a fresh schema
  - recent()/_recent_rows is READ-ONLY (surfacing never mutates the graph)
  - recency window = max(created, last_accessed): an old-but-recently-recalled
    memory surfaces; a stale one is excluded; results are newest-first
  - save(contradicts_prior=True) persists the flag; a generic save leaves it 0
  - a flagged memory OUTRANKS a generic one with equal keyword coverage
  - [OVERRIDES-PRIOR] renders in recall() and the flag rides through recent()
"""
import hashlib
from datetime import datetime, timezone, timedelta

import pytest

from mycelium import config as _config
from mycelium import server as S


@pytest.fixture(autouse=True)
def _reset_session_state():
    # server tracks co-accessed memories in a process-wide contextvar; these
    # tests swap DBs in-process, so reset between tests to avoid ID bridging.
    S._session_accessed.set(None)
    yield


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point the server at a fresh temp DB (created with the current schema)."""
    monkeypatch.setenv("MYCELIUM_STORAGE_DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.delenv("MYCELIUM_SEMANTIC_EMBED_URL", raising=False)
    S.set_config(_config.load())
    return str(tmp_path / "m.db")


def _iso(days_ago=0, hours_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago, hours=hours_ago)).isoformat()


# fixtures: (content, project, created_days_ago, last_accessed_days_ago, pinned, tier)
_FIX = [
    ("Fresh checkpoint today",          "proj-alpha",  0,  0, 0, "hot"),
    ("Old note but RECALLED yesterday", "proj-beta",  40,  1, 0, "hot"),
    ("Beta pinned fact 5d",             "proj-beta",   5,  5, 1, "hot"),
    ("Consolidated cold index 8d",      "proj-beta",   8,  8, 0, "cold"),
    ("Stale 20d excluded at 14d",       "proj-gamma", 20, 20, 0, "hot"),
]


def _seed(db_path):
    conn = S.get_db()  # creates the modern schema incl. contradicts_prior
    for content, proj, cda, lda, pin, tier in _FIX:
        conn.execute(
            "INSERT INTO memories (content, project, tier, created, last_accessed, "
            "access_count, pinned, confidence) VALUES (?,?,?,?,?,3,?,0.3)",
            (content, proj, tier, _iso(cda), _iso(lda), pin),
        )
    conn.commit()
    conn.close()


def _fingerprint():
    # Read through get_db() (same WAL connection the app uses) so we observe
    # committed state; a foreign sqlite3.connect() can miss uncheckpointed WAL.
    # get_db() re-runs CREATE IF NOT EXISTS but never touches last_accessed /
    # access_count, so it's a faithful, side-effect-free snapshot of the invariant.
    conn = S.get_db()
    rows = conn.execute(
        "SELECT id, last_accessed, access_count FROM memories ORDER BY id"
    ).fetchall()
    conn.close()
    h = hashlib.sha256()
    for r in rows:
        h.update(f"{r['id']}|{r['last_accessed']}|{r['access_count']};".encode())
    return h.hexdigest()


def test_migration_adds_contradicts_prior_column(db):
    conn = S.get_db()
    try:
        assert S._column_exists(conn, "memories", "contradicts_prior")
    finally:
        conn.close()


def test_recent_is_read_only(db):
    _seed(db)
    before = _fingerprint()
    conn = S.get_db()
    S._recent_rows(conn, days=14, limit=15)
    conn.close()
    assert _fingerprint() == before


def test_recency_window_and_ordering(db):
    _seed(db)
    conn = S.get_db()
    rows = S._recent_rows(conn, days=14, limit=15)
    conn.close()
    contents = [r["content"] for r in rows]
    # 20d-stale falls outside the 14d window
    assert "Stale 20d excluded at 14d" not in contents
    # max(created, last_accessed): old memory recalled yesterday still surfaces
    assert "Old note but RECALLED yesterday" in contents
    # newest-first
    recencies = [r["recency"] for r in rows]
    assert recencies == sorted(recencies, reverse=True)


def test_salience_boost_config_value(db):
    # The boost is a real, positive knob and (per design) exceeds pinned's 0.1.
    boost = S._cfg().memory["contradicts_prior_boost"]
    assert boost == pytest.approx(0.25)
    assert boost > 0.1


def _saved_id(msg):
    return int(msg.split("#", 1)[1].split()[0].strip("( )"))


def test_flag_persists_and_outranks_generic(db):
    gen = S.save("Zorbex platform general onboarding notes and setup", project="zx", force=True)
    flg = S.save("Zorbex platform Team Edition is still actively shipped 2026",
                 project="zx", contradicts_prior=True, force=True)
    id_gen, id_flg = _saved_id(gen), _saved_id(flg)

    conn = S.get_db()
    f_flag = conn.execute("SELECT contradicts_prior FROM memories WHERE id=?", (id_flg,)).fetchone()[0]
    g_flag = conn.execute("SELECT contradicts_prior FROM memories WHERE id=?", (id_gen,)).fetchone()[0]
    conn.close()
    assert f_flag == 1
    assert g_flag == 0

    out = S.recall("Zorbex platform", limit=5)
    pos_flg, pos_gen = out.find(f"#{id_flg}"), out.find(f"#{id_gen}")
    assert pos_flg >= 0 and pos_gen >= 0, out
    # equal keyword coverage → the salience bump decides: flagged ranks first
    assert pos_flg < pos_gen, out
    assert "[OVERRIDES-PRIOR]" in out


def test_recent_carries_flag(db):
    flg = S.save("Widget daemon runs on port 9999 not the documented 8080",
                 project="zx", contradicts_prior=True, force=True)
    id_flg = _saved_id(flg)
    conn = S.get_db()
    rows = S._recent_rows(conn, days=1, limit=20)
    conn.close()
    assert any(r["id"] == id_flg and r["contradicts_prior"] == 1 for r in rows)
