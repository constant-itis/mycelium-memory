# agent-index benchmark

Measures whether the agent-native bootstrap surface (`agent-index.json` +
`agent-graph.json`) actually helps an agent navigate this codebase with less
context. Two tiers.

Read `STUDY.md` for the plain-language writeup. This file is how to run it.

## Tier 1: deterministic (no model)

Generates a ground-truth query set from the graph (the graph is the answer key),
then measures coverage and context cost. No external dependencies.

```
python3 benchmarks/agent-index/gen_queries.py
python3 benchmarks/agent-index/bench.py
```

Outputs `queries.json`, `results.json`, `RESULTS.md`. Latest snapshot: 100% of
questions answerable from the machine surface, median ~33x fewer tokens to reach
code than crawling the enclosing file.

## Tier 2: agentic A/B (needs a local model)

Runs a real agent loop twice over the same tasks, one arm with the index
preloaded and one without, measuring real tokens, steps, tool calls, and
accuracy. Point it at any OpenAI-compatible chat endpoint:

```
MYCELIUM_BENCH_ENDPOINT=http://localhost:8080/v1/chat/completions \
MYCELIUM_BENCH_MODEL=local \
python3 benchmarks/agent-index/agent_ab.py
```

Outputs `agentic_results.json`, `agentic_run.log`. Snapshot (`AGENTIC_RESULTS.md`):
the map took accuracy from 57% to 86% and steps from 5.3 to 1.0 on a small model.

## Reproducibility rule

Keep a result only if it is reproducible from these scripts with no hand-editing.
The harness is the deliverable; committed numbers are a snapshot of one repo state
and are expected to move as the code does.
