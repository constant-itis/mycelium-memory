"""Eval harness smoke tests — lexical-only path, no network/model needed."""
import pytest

from mycelium import evaluate
from mycelium import server as S


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    # Force defaults (no embed_url) regardless of any local config.toml, so the
    # eval runs lexical-only and contacts nothing.
    monkeypatch.setenv("MYCELIUM_CONFIG", str(tmp_path / "no-such-config.toml"))
    monkeypatch.delenv("MYCELIUM_SEMANTIC_EMBED_URL", raising=False)
    S._session_accessed.set(None)
    yield


def test_eval_runs_lexical_only():
    r = evaluate.run_eval()  # bundled sample
    assert r["n_memories"] == 22
    assert r["n_queries"] == 20
    assert r["semantic_enabled"] is False
    assert r["hybrid"] is None
    lex = r["lexical"]
    assert lex["n"] == 20
    for k in (1, 3, 5):
        assert 0.0 <= lex["recall"][k] <= 1.0
    # recall@5 >= recall@1 by construction
    assert lex["recall"][5] >= lex["recall"][1]


def test_format_report_mentions_disabled():
    out = evaluate.format_report(evaluate.run_eval())
    assert "lexical" in out
    assert "semantic disabled" in out
