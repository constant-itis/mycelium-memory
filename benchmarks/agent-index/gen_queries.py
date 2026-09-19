#!/usr/bin/env python3
"""Tier 1 setup: generate a ground-truth query set from agent-graph.json.
The graph is the answer key, so every query has a deterministic expected answer.
Archetypes mirror what a coding agent actually asks about an unfamiliar repo.
Run from anywhere: python3 benchmarks/agent-index/gen_queries.py"""
import json
from pathlib import Path

def find_root(start):
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").is_file() and (p / "mycelium").is_dir():
            return p
    raise SystemExit("could not locate repo root")

HERE = Path(__file__).resolve().parent
ROOT = find_root(HERE)
g = json.loads((ROOT / "agent-graph.json").read_text())
idx = json.loads((ROOT / "agent-index.json").read_text())
sym = {s["id"]: s for s in g["symbols"]}

_src = {}
def file_text(path):
    if path not in _src:
        _src[path] = (ROOT / path).read_text()
    return _src[path]
def toks(chars):
    return max(1, chars // 4)
def span_tokens(path, l0, l1):
    ls = file_text(path).splitlines()
    return toks(sum(len(x) + 1 for x in ls[l0 - 1:l1]))
def file_tokens(path):
    return toks(len(file_text(path)))

queries = []
def add(archetype, question, gt, resolvable_from, needs_code_read, answer_path=None, answer_span=(0, 0)):
    q = {"id": f"q{len(queries)+1:03d}", "archetype": archetype, "question": question,
         "ground_truth": gt, "resolvable_from": resolvable_from, "needs_code_read": needs_code_read}
    if answer_path:
        q["answer_path"] = answer_path
        q["answer_span_tokens"] = span_tokens(answer_path, *answer_span)
        q["crawl_file"] = answer_path
        q["crawl_file_tokens"] = file_tokens(answer_path)
    queries.append(q)

tools = [s for s in g["symbols"] if s.get("mcp_tool")]
for t in tools:
    add("LOCATE", f"Where is the `{t['name']}` MCP tool implemented?",
        {"path": t["path"], "span": [t["line_start"], t["line_end"]]},
        ["index"], True, answer_path=t["path"], answer_span=(t["line_start"], t["line_end"]))

callees = {}
for e in g["call_edges"]:
    callees.setdefault(e["from"], []).append(e["to"])
for t in tools:
    add("DEPS", f"What intra-repo helpers does `{t['name']}` call?",
        {"helpers": sorted(sym[c]["name"] for c in callees.get(t["id"], []))}, ["graph"], False)

owner = {}
for c in idx["components"]:
    for sid in c["symbols"]:
        owner[sid] = c["id"]
for hn in ["_apply_decay", "_semantic_sims", "_check_duplicates", "_get_neighbors",
           "_recent_rows", "_fts_search", "embed_query", "_protection_reason"]:
    cands = [s for s in g["symbols"] if s["name"] == hn]
    if cands:
        add("OWNERSHIP", f"Which component owns `{hn}`?",
            {"component": owner.get(cands[0]["id"], "UNMAPPED")}, ["index"], False)

add("SURFACE", "List the MCP tools mycelium exposes.",
    {"tools": sorted(t["name"] for t in tools)}, ["index"], False)
sem_deps = {c["id"] for c in idx["components"] if "comp.semantic" in c.get("depends_on", [])}
add("SURFACE", "Which MCP tools depend on the semantic/embeddings component?",
    {"tools": sorted(t["name"] for t in idx["mcp_tools"] if t["implemented_by"] in sem_deps)},
    ["index"], False)

comp_by_id = {c["id"]: c for c in idx["components"]}
for cid, comp in {"decay": "comp.graph_dynamics", "semantic-recall": "comp.semantic",
                  "recency": "comp.episodic", "consolidation": "comp.maintenance"}.items():
    c = comp_by_id[comp]
    first = sym[c["symbols"][0]] if c["symbols"] else None
    add("CONCEPT", f"Where is `{cid}` implemented?",
        {"component": comp, "paths": c["paths"][:3]}, ["index"], True,
        answer_path=first["path"] if first else None,
        answer_span=(first["line_start"], first["line_end"]) if first else (0, 0))

(HERE / "queries.json").write_text(json.dumps(queries, indent=2) + "\n")
from collections import Counter
print("wrote queries.json (%d queries): %s" % (len(queries), dict(Counter(q["archetype"] for q in queries))))
