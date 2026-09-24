"""Hybrid RRF candidate gathering + semantic-unit index tests.

No live model required: an in-process HTTP stub returns vectors proportional
to topic word counts, so a LONG memory about one topic with a single buried
sentence about another gets a whole-document vector dominated by the majority
topic. That reproduces the failure the unit index exists to fix: the buried
fact is unreachable by whole-memory cosine, reachable by its own window.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mycelium import config as _config
from mycelium import embeddings as E
from mycelium import server as S

OCEAN = ("ocean", "marine", "reef", "trench")
MOUNTAIN = ("mountain", "alpine", "ridge", "summit")


def _vec_for(text: str):
    t = text.lower()
    o = sum(t.count(w) for w in OCEAN)
    m = sum(t.count(w) for w in MOUNTAIN)
    return E._normalize([float(o), float(m), 0.1])


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        data = [{"index": i, "embedding": _vec_for(t)}
                for i, t in enumerate(body.get("input", []))]
        out = json.dumps({"data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture(autouse=True)
def _reset_session_state():
    S._session_accessed.set(None)
    yield


@pytest.fixture
def stub():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1/embeddings"
    srv.shutdown()


def _long_mountain_memory_with_buried_fact() -> str:
    filler = [
        f"Alpine ridge segment {i} was surveyed and the mountain summit "
        f"elevation was recorded in the ledger."
        for i in range(30)
    ]
    # One buried sentence about a different topic, mid-document.
    filler.insert(15, "The reef monitoring buoy reports through gateway node forty-two.")
    return " ".join(filler)


# ---- windowing (pure function) ----
def test_windows_overlap_and_short_text():
    text = "One. Two. Three. Four. Five."
    ws = S._extractive_windows(text, win=3, stride=2)
    assert ws[0] == "One. Two. Three."
    assert ws[1] == "Three. Four. Five."   # stride 2 overlaps by one sentence
    assert S._extractive_windows("", 3, 2) == []
    assert S._extractive_windows("Single sentence only.", 3, 2) == ["Single sentence only."]


# ---- config ----
def test_hybrid_defaults():
    cfg = _config.load()
    assert cfg.memory["hybrid_rrf"] is True
    assert cfg.memory["conn_boost_scale"] == 0.0
    assert cfg.semantic["units"] is True
    assert cfg.semantic["unit_min_chars"] == 1200


# ---- hybrid gather without any embedder: deep BM25 only ----
def test_hybrid_lexical_only(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_STORAGE_DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.delenv("MYCELIUM_SEMANTIC_EMBED_URL", raising=False)
    S.set_config(_config.load())
    S.save("postgres connection pooling notes", force=True)
    S.save("nginx reverse proxy config", force=True)
    out = S.recall("postgres pooling", limit=5)
    assert "postgres" in out


def test_hybrid_kill_switch_uses_legacy_path(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_STORAGE_DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("MYCELIUM_MEMORY_HYBRID_RRF", "false")
    monkeypatch.delenv("MYCELIUM_SEMANTIC_EMBED_URL", raising=False)
    S.set_config(_config.load())
    assert S._cfg().memory["hybrid_rrf"] is False
    S.save("postgres connection pooling notes", force=True)
    assert "postgres" in S.recall("postgres", limit=5)


# ---- unit index: save-time indexing + buried-fact rescue ----
def test_units_indexed_on_save_and_rescue_buried_fact(tmp_path, stub, monkeypatch):
    monkeypatch.setenv("MYCELIUM_STORAGE_DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("MYCELIUM_SEMANTIC_EMBED_URL", stub)
    monkeypatch.setenv("MYCELIUM_SEMANTIC_EMBED_MODEL", "test")
    S.set_config(_config.load())

    long_content = _long_mountain_memory_with_buried_fact()
    assert len(long_content) >= S._cfg().semantic["unit_min_chars"]
    S.save(long_content, force=True)
    S.save("tall alpine mountain ridge trail notes", force=True)  # short: no units

    conn = S.get_db()
    long_id = conn.execute(
        "SELECT id FROM memories WHERE content LIKE '%buoy%'").fetchone()["id"]
    n_units = conn.execute(
        "SELECT COUNT(*) FROM memory_units WHERE memory_id=?", (long_id,)).fetchone()[0]
    assert n_units >= 2, "long memory should be unit-indexed at save time"
    short_units = conn.execute(
        "SELECT COUNT(*) FROM memory_units WHERE memory_id != ?", (long_id,)).fetchone()[0]
    assert short_units == 0, "short memories must not be unit-indexed"

    # The buried window outscores the whole-document vector for its own topic.
    qvec = E.embed_query("marine reef status", url=stub, model="test")
    whole = S._semantic_sims(conn, qvec).get(long_id, 0.0)
    unit = S._unit_parent_sims(conn, qvec).get(long_id, 0.0)
    assert unit > whole, (unit, whole)
    conn.close()

    # End to end: the query shares no keywords with the memory except inside
    # the buried sentence's topic; the unit arm must surface the long memory.
    out = S.recall("marine reef status", limit=5)
    assert "buoy" in out, out


def test_backfill_units(tmp_path, stub, monkeypatch):
    monkeypatch.setenv("MYCELIUM_STORAGE_DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.delenv("MYCELIUM_SEMANTIC_EMBED_URL", raising=False)
    S.set_config(_config.load())
    S.save(_long_mountain_memory_with_buried_fact(), force=True)  # no embedder yet

    # Enable the embedder afterwards, as an operator would, then backfill.
    monkeypatch.setenv("MYCELIUM_SEMANTIC_EMBED_URL", stub)
    monkeypatch.setenv("MYCELIUM_SEMANTIC_EMBED_MODEL", "test")
    S.set_config(_config.load())
    r = S.backfill_units()
    assert r["indexed"] == 1 and r["failed"] == 0 and r["units_written"] >= 2
    # Idempotent: second run indexes nothing new.
    r2 = S.backfill_units()
    assert r2["indexed"] == 0 and r2["total_units"] == r["total_units"]
