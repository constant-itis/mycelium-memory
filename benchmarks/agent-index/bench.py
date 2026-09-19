#!/usr/bin/env python3
"""Tier 1: deterministic, no-LLM benchmark of the agent-index bootstrap surface.
  (A) COVERAGE  - fraction of agent questions answerable from the machine surface
                  (agent-index.json L0 + agent-graph.json L2) without reading source.
  (B) CONTEXT COST - tokens read WITH the index (jump to the pointed span) vs
                  WITHOUT it (crawl: read the enclosing file to locate it).
Assumptions: token ~= chars/4; without-index = read the enclosing file; index/graph
loaded once per session (amortized in the cold-session model).
Run: python3 benchmarks/agent-index/gen_queries.py && python3 benchmarks/agent-index/bench.py"""
import json
from pathlib import Path
from statistics import median

def find_root(start):
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").is_file() and (p / "mycelium").is_dir():
            return p
    raise SystemExit("could not locate repo root")

HERE = Path(__file__).resolve().parent
ROOT = find_root(HERE)
Q = json.loads((HERE / "queries.json").read_text())
idx_tokens = max(1, len((ROOT / "agent-index.json").read_text()) // 4)
graph_tokens = max(1, len((ROOT / "agent-graph.json").read_text()) // 4)

N = len(Q)
cov_index = sum(1 for q in Q if "index" in q["resolvable_from"])
cov_graph = sum(1 for q in Q if "graph" in q["resolvable_from"])
cov_either = sum(1 for q in Q if q["resolvable_from"])

code_q = [q for q in Q if q.get("needs_code_read") and "answer_span_tokens" in q]
ratios, per = [], []
for q in code_q:
    wi, wo = q["answer_span_tokens"], q["crawl_file_tokens"]
    r = wo / wi if wi else 0
    ratios.append(r)
    per.append((q["id"], q["archetype"], q["answer_path"], wi, wo, r))

distinct_spans = {(q["answer_path"], q["answer_span_tokens"]) for q in code_q}
file_tok = {q["crawl_file"]: q["crawl_file_tokens"] for q in code_q}
bootstrap_total = idx_tokens + sum(t for _, t in distinct_spans)
crawl_total = sum(file_tok.values())

results = {
    "n_queries": N, "index_tokens": idx_tokens, "graph_tokens": graph_tokens,
    "coverage": {
        "index_L0": [cov_index, N, round(cov_index / N, 3)],
        "graph_L2": [cov_graph, N, round(cov_graph / N, 3)],
        "either": [cov_either, N, round(cov_either / N, 3)]},
    "context_cost_per_query": {
        "n_code_reaching": len(code_q),
        "median_reduction_x": round(median(ratios), 1) if ratios else None,
        "mean_reduction_x": round(sum(ratios) / len(ratios), 1) if ratios else None,
        "min_x": round(min(ratios), 1) if ratios else None,
        "max_x": round(max(ratios), 1) if ratios else None},
    "cold_session_model": {
        "with_index_tokens": bootstrap_total, "crawl_tokens_file_cached": crawl_total,
        "reduction_x": round(crawl_total / bootstrap_total, 2) if bootstrap_total else None},
}
(HERE / "results.json").write_text(json.dumps(results, indent=2) + "\n")

def pct(a, b):
    return "%d/%d (%.0f%%)" % (a, b, 100 * a / b)
L = []
L.append("# Agent-index benchmark results (Tier 1, deterministic)\n")
L.append("Answer key = the frozen graph. token ~= chars/4. See bench.py for assumptions.\n")
L.append("## A. Coverage (answerable without reading source)\n")
L.append("| Machine surface | Queries answered |\n|---|---|")
L.append("| agent-index.json (L0, %d tok) | %s |" % (idx_tokens, pct(cov_index, N)))
L.append("| agent-graph.json (L2, %d tok) | %s |" % (graph_tokens, pct(cov_graph, N)))
L.append("| either (full surface) | %s |\n" % pct(cov_either, N))
L.append("## B. Context cost on code-reaching queries (WITH index vs crawl)\n")
L.append("Per-query reduction: median %sx, mean %sx, range %sx-%sx (n=%d)\n" % (
    results["context_cost_per_query"]["median_reduction_x"],
    results["context_cost_per_query"]["mean_reduction_x"],
    results["context_cost_per_query"]["min_x"],
    results["context_cost_per_query"]["max_x"], len(code_q)))
L.append("| query | archetype | file | with-index tok | crawl tok | reduction |")
L.append("|---|---|---|---:|---:|---:|")
for qid, arch, path, wi, wo, r in sorted(per, key=lambda x: -x[5]):
    L.append("| %s | %s | %s | %d | %d | %.1fx |" % (qid, arch, path.replace("mycelium/", ""), wi, wo, r))
L.append("\n## C. Cold-session model (answer all %d code-reaching queries)\n" % len(code_q))
L.append("- WITH index (load once + read pointed spans): %d tok" % bootstrap_total)
L.append("- WITHOUT index (crawl, read each touched file once): %d tok" % crawl_total)
L.append("- Session reduction: %.2fx\n" % (crawl_total / bootstrap_total))
(HERE / "RESULTS.md").write_text("\n".join(L) + "\n")

print("coverage: index %s | graph %s | either %s" % (
    pct(cov_index, N), pct(cov_graph, N), pct(cov_either, N)))
print("per-query reduction: median %sx (range %s-%s)" % (
    results["context_cost_per_query"]["median_reduction_x"],
    results["context_cost_per_query"]["min_x"], results["context_cost_per_query"]["max_x"]))
print("cold session: with-index %d vs crawl %d = %.2fx" % (
    bootstrap_total, crawl_total, crawl_total / bootstrap_total))
