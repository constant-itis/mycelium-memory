"""Connected (propagated) results must not outrank the direct match.

Connection strength grows past 1.0 with co-access. Used raw as a score
multiplier, a hub strongly connected to the direct match outscored it; with
semantic on, every memory has some cosine, so this hit almost every query on a
densely connected graph.
"""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mycelium import config as _config
from mycelium import embeddings as E
from mycelium import evaluate as EV
from mycelium import server as S

TOPICS = (("ocean", "reef", "marine"), ("invoice", "billing", "payment"))


def _vec_for(text: str):
    t = text.lower()
    return E._normalize([float(sum(t.count(w) for w in ws)) + 0.2 for ws in TOPICS])


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        data = [{"index": i, "embedding": _vec_for(t)} for i, t in enumerate(body.get("input", []))]
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


def _id(out: str) -> int:
    return int(re.search(r"#(\d+)", out).group(1))


def _first_result(out: str) -> tuple[str, int]:
    m = re.search(r"^\s+(\S)\s\[#(\d+)\]", out, re.M)
    return m.group(1), int(m.group(2))


def test_strong_connection_does_not_lift_hub_above_direct_match(tmp_path, stub, monkeypatch):
    db = tmp_path / "m.db"
    monkeypatch.setenv("MYCELIUM_STORAGE_DB_PATH", str(db))
    monkeypatch.setenv("MYCELIUM_SEMANTIC_EMBED_URL", stub)
    monkeypatch.setenv("MYCELIUM_SEMANTIC_EMBED_MODEL", "stub")
    # Direct candidates = the fused top rrf_pool. On a real corpus the hub sits
    # outside that pool and only arrives through the connection; pool=1 makes
    # that happen with two memories.
    monkeypatch.setenv("MYCELIUM_MEMORY_RRF_POOL", "1")
    S.set_config(_config.load())
    answer = _id(S.save("The reef sensor on the ocean buoy reports every hour.", force=True))
    hub = _id(S.save("Index: ocean notes, marine notes, invoice notes, billing notes.", force=True))
    # A co-access-strengthened edge from the answer to the hub (strength > 1).
    con = S.get_db()  # the app's own connection (WAL-consistent, right path)
    con.execute("DELETE FROM connections")
    con.execute(
        "INSERT INTO connections (source, target, strength, last_activated, co_access_count) "
        "VALUES (?, ?, 5.0, ?, 40)", (answer, hub, S._now()))
    con.commit()
    con.close()
    tag, first = _first_result(S.recall("reef buoy report", limit=1))
    assert (tag, first) == ("●", answer)


def test_propagate_scale_default():
    assert _config.DEFAULTS["memory"]["propagate_scale"] == 0.5


def test_eval_parser_ignores_ids_inside_content():
    out = "\n".join([
        "## Recall: 2 memories",
        "  ● [#7] (ops) Index of tools",
        "#56 [ops][server] box notes",
        "GotPrint order #30914209",
        "  ↔ [#3] (ops) Another memory [score: 0.40]",
    ])
    assert EV._ranked_ids(out) == [7, 3]
