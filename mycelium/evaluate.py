"""Reproducible recall benchmark: lexical vs hybrid (semantic) recall.

Loads a dataset of memories + labeled paraphrase queries, builds a throwaway DB,
saves the memories, and measures how often each query's target memory shows up in
recall — once with semantic OFF (pure FTS keyword search) and once with it ON.

This is the honest way to answer "is semantic recall worth it for me?": run it on
your own memories. The bundled sample (mycelium/eval_data/sample.json) is just a
demo; pass --dataset to point at your own {memories, queries}.

Semantic numbers require a configured [semantic] embed_url; without one, only the
lexical column is produced (which still shows how much pure keyword search misses
on reworded queries).
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from . import config as _config
from . import server as _server

KS = (1, 3, 5)
_DEFAULT_DATASET = Path(__file__).parent / "eval_data" / "sample.json"


def _ranked_ids(recall_output: str) -> list[int]:
    """Pull memory ids, in order, from recall()'s formatted output."""
    ids: list[int] = []
    for line in recall_output.splitlines():
        if line.startswith("##"):
            continue
        m = re.search(r"#(\d+)", line)
        if m:
            ids.append(int(m.group(1)))
    return ids


def _score(transitions, rank_fn) -> dict:
    hits = {k: 0 for k in KS}
    mrr = 0.0
    n = len(transitions)
    for seeds, target in transitions:
        ids = rank_fn(seeds)
        rank = ids.index(target) + 1 if target in ids else None
        if rank:
            mrr += 1.0 / rank
            for k in KS:
                if rank <= k:
                    hits[k] += 1
    return {"recall": {k: hits[k] / n for k in KS}, "mrr": mrr / n, "n": n}


def run_eval(dataset_path: str | None = None) -> dict:
    """Returns {dataset, n_memories, n_queries, semantic_enabled, lexical, hybrid}.
    `hybrid` is None when no embed_url is configured."""
    path = Path(dataset_path).expanduser() if dataset_path else _DEFAULT_DATASET
    data = json.loads(path.read_text())
    memories = data["memories"]
    queries = data["queries"]

    base = _config.load()
    embed_url = base.semantic.get("embed_url", "")

    tmp = tempfile.mkdtemp(prefix="mycelium-eval-")
    db_path = str(Path(tmp) / "eval.db")

    def cfg(with_semantic: bool):
        d = base.to_dict()
        d["storage"] = dict(d["storage"], db_path=db_path)
        d["semantic"] = dict(d["semantic"],
                             embed_url=(embed_url if with_semantic else ""))
        return _config.Config(
            server=d["server"], storage=d["storage"], memory=d["memory"],
            foundry=d["foundry"], semantic=d["semantic"], source="eval",
        )

    # Build the corpus once, with semantic on if available (so vectors exist).
    _server.set_config(cfg(with_semantic=bool(embed_url)))
    ref_to_id: dict[str, int] = {}
    for mem in memories:
        out = _server.save(mem["content"], force=True)
        ref_to_id[mem["ref"]] = int(re.search(r"#(\d+)", out).group(1))

    transitions = [([q["query"]][0], ref_to_id[q["expect"]]) for q in queries]
    # transitions = (query_string, target_id)

    def lexical_rank(q):
        _server._session_accessed.set(None)
        return _ranked_ids(_server.recall(q, limit=5))

    def hybrid_rank(q):
        _server._session_accessed.set(None)
        return _ranked_ids(_server.recall(q, limit=5))

    # Lexical pass (semantic forced off).
    _server.set_config(cfg(with_semantic=False))
    lexical = _score(transitions, lexical_rank)

    hybrid = None
    if embed_url:
        _server.set_config(cfg(with_semantic=True))
        hybrid = _score(transitions, hybrid_rank)

    return {
        "dataset": str(path),
        "n_memories": len(memories),
        "n_queries": len(queries),
        "semantic_enabled": bool(embed_url),
        "embed_model": base.semantic.get("embed_model", "") if embed_url else "",
        "lexical": lexical,
        "hybrid": hybrid,
    }


def format_report(r: dict) -> str:
    lines = []
    lines.append(f"Recall benchmark — {r['n_queries']} queries over "
                 f"{r['n_memories']} memories")
    lines.append(f"  dataset: {r['dataset']}")
    cols = "".join(f"{'recall@'+str(k):>11}" for k in KS) + f"{'MRR':>9}"
    lines.append(f"  {'method':<10}{cols}")

    def row(label, m):
        body = "".join(f"{m['recall'][k]:>11.0%}" for k in KS)
        return f"  {label:<10}{body}{m['mrr']:>9.3f}"

    lines.append(row("lexical", r["lexical"]))
    if r["hybrid"]:
        lines.append(row("hybrid", r["hybrid"]))
        lift5 = r["hybrid"]["recall"][5] - r["lexical"]["recall"][5]
        lines.append(f"\n  semantic ({r['embed_model']}) recall@5 "
                     f"{'+' if lift5 >= 0 else ''}{lift5:.0%} vs lexical.")
    else:
        lines.append("\n  (semantic disabled — set [semantic] embed_url to compare. "
                     "The lexical column already shows how much keyword search misses "
                     "on reworded queries.)")
    return "\n".join(lines)
