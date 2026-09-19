# AGENTS.md

Operational guide for coding agents working in this repository. Read this first,
then load `agent-index.json`.

## Orient before you crawl

This repo ships a machine-readable map so you do not have to reconstruct it by
grepping. Use it:

1. **`agent-index.json`** (repo root, ~5k tokens) is the bootstrap map. It lists
   the `concepts`, `components`, and the 12 MCP `tools` with exact file paths and
   line spans, plus how components depend on each other. To answer "where is X"
   or "which component owns Y" or "what does the semantic layer touch", read this
   and jump straight to the span. Do not read whole files to find things.
2. **`agent-graph.json`** (repo root) is the full structural graph (every symbol,
   import edge, and call edge). Use it for exact call-edge questions the index
   does not carry ("what does `recall` call").
3. **`docs/concepts.md`** is the human mental model; **`docs/everyday-use.md`** is
   non-developer usage. The index's `read_order` field names the intended path.

A benchmark of this surface (why it exists, how much context it saves) is in
`benchmarks/agent-index/STUDY.md`.

## The map is generated, not hand-maintained

- `agent-graph.json` and `agent-index.json` are produced by `scripts/`. Do not
  hand-edit their structural fields.
- The **semantic overlay** (component names, summaries, concept groupings) lives
  in `scripts/generate_agent_index.py`. Edit it there, then regenerate.
- After changing code that moves symbols, regenerate and verify:

```
python3 scripts/build_agent_graph.py
python3 scripts/generate_agent_index.py
python3 scripts/verify_agent_index.py
```

CI runs the verifier and fails if the committed map drifts from the code, so keep
it regenerated in the same change.

## Build and test

```
pip install -e .
pytest -q
```

Python >= 3.11. Core is stdlib + SQLite; the optional semantic layer needs an
OpenAI-compatible embeddings endpoint (see `docs/configuration.md`).

## Conventions

- Single-process MCP server (FastMCP). All 12 tools live in `mycelium/server.py`.
- Additive changes to the memory schema only; do not rewrite existing tables.
- No secrets or private values in the repo.
