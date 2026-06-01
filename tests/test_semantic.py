"""Semantic recall tests — no live model required.

A tiny in-process HTTP stub stands in for an OpenAI-compatible /v1/embeddings
endpoint, returning deterministic vectors keyed on topic words so we can assert
meaning-based behavior (e.g. "marine" bridging to an "ocean" memory that shares
no keywords).
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mycelium import config as _config
from mycelium import embeddings as E
from mycelium import server as S


def _vec_for(text: str):
    t = text.lower()
    if any(k in t for k in ("ocean", "sea", "marine", "water")):
        return [1.0, 0.0, 0.0]
    if any(k in t for k in ("mountain", "alpine", "rock", "peak")):
        return [0.0, 1.0, 0.0]
    return [0.0, 0.0, 1.0]


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

    def log_message(self, *a):  # silence
        pass


@pytest.fixture(autouse=True)
def _reset_session_state():
    # The server tracks co-accessed memories in a process-wide contextvar. These
    # tests swap DBs in-process (which production never does), so reset it between
    # tests to avoid bridging IDs from one tmp DB into another.
    S._session_accessed.set(None)
    yield


@pytest.fixture
def stub():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1/embeddings"
    srv.shutdown()


# ---- unit (no server) ----
def test_blob_roundtrip():
    v = [0.1, -0.2, 0.3, 0.0]
    assert E.from_blob(E.to_blob(v)) == pytest.approx(v, abs=1e-6)


def test_cosine_sims_pure_python():
    q = E._normalize([1.0, 0.0])
    rows = [(1, E.to_blob(E._normalize([1.0, 0.0]))),
            (2, E.to_blob(E._normalize([0.0, 1.0])))]
    sims = E.cosine_sims(q, rows)
    assert sims[1] == pytest.approx(1.0, abs=1e-5)
    assert sims[1] > sims[2]


def test_prefixes_dispatch():
    assert E._prefixes("nomic-embed-text")[1].startswith("search_query")
    assert E._prefixes("embeddinggemma")[0].startswith("title:")
    assert E._prefixes("text-embedding-3-small") == ("", "")


# ---- config ----
def test_semantic_off_by_default():
    cfg = _config.load()
    assert cfg.semantic["embed_url"] == ""
    assert cfg.semantic_enabled is False


def test_semantic_env_override(monkeypatch):
    monkeypatch.setenv("MYCELIUM_SEMANTIC_EMBED_URL", "http://x/v1/embeddings")
    monkeypatch.setenv("MYCELIUM_SEMANTIC_WEIGHT", "7.5")
    cfg = _config.load()
    assert cfg.semantic_enabled is True
    assert cfg.semantic["weight"] == 7.5


# ---- embed against stub ----
def test_embed_query_and_document(stub):
    qv = E.embed_query("marine life", url=stub, model="test")
    dv = E.embed_document("deep blue ocean", url=stub, model="test")
    assert len(qv) == 3 and len(dv) == 3
    assert E.cosine_sims(qv, [(1, E.to_blob(dv))])[1] == pytest.approx(1.0, abs=1e-5)


# ---- end-to-end recall fusion ----
def test_recall_semantic_bridges_vocabulary(tmp_path, stub, monkeypatch):
    monkeypatch.setenv("MYCELIUM_STORAGE_DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("MYCELIUM_SEMANTIC_EMBED_URL", stub)
    monkeypatch.setenv("MYCELIUM_SEMANTIC_EMBED_MODEL", "test")
    S.set_config(_config.load())

    S.save("deep blue ocean trench biology", force=True)
    S.save("tall alpine mountain ridge", force=True)

    # "marine" shares NO keyword with the ocean memory — only the semantic arm
    # can bridge it. Pure FTS would return nothing for this query.
    out = S.recall("marine ecosystems", limit=5)
    assert "ocean trench" in out, out
    if "alpine mountain" in out:
        assert out.index("ocean") < out.index("alpine")


def test_recall_lexical_unchanged_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_STORAGE_DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.delenv("MYCELIUM_SEMANTIC_EMBED_URL", raising=False)
    S.set_config(_config.load())
    assert S._cfg().semantic_enabled is False
    S.save("postgres connection pooling notes", force=True)
    # keyword hit still works; no embedding endpoint is contacted
    assert "postgres" in S.recall("postgres", limit=5)
