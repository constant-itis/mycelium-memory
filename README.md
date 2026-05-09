# mycelium

Persistent neural-style memory for Claude Code. Single-process MCP server,
SQLite + FTS5, two memory cards in one install:

- **Semantic** — facts and observations. Co-access strengthens connections,
  unused paths decay. Structure emerges from usage, not taxonomy.
- **Behavioral (foundry)** — append-only decision log. Every recorded decision
  becomes a queryable row for later pattern analysis.

Zero external services. One pip install. One TOML config. Two SQLite files.

## Install

```bash
pip install mycelium-memory
mycelium init                                                  # writes ~/.mycelium/config.toml
claude mcp add mycelium -- mycelium serve                      # stdio (default)
# OR for remote:
# mycelium serve --transport http --port 8200 &
# claude mcp add mycelium --transport http http://HOST:8200/mcp
```

That's it. Open a Claude Code session and the `save`, `recall`, `context`,
`log_decision`, `query_decisions` (and friends) tools are available.

## Smoke test

After install, verify the round-trip works:

```bash
bash scripts/smoke-test.sh
```

Uses a throwaway temp dir — touches no user state.

## Tools

### Semantic card

| Tool | What |
|---|---|
| `save(content, project="", ...)` | Store a memory. Auto-connects to similar existing memories. |
| `recall(query, project="", limit=5)` | FTS-search and propagate through connections. |
| `context(project="")` | Load hub memories — call at session start. |
| `connections(memory_id)` | Show neighbors of a specific memory. |
| `consolidate(project="")` | Show hot memories ready to merge into a cold summary. |
| `forget(memory_id)` | Delete a memory and its connections. |
| `pin(memory_id)` | Pinned memories' connections never decay below the configured floor. |
| `resolve(term, meanings)` | Disambiguate an ambiguous term — returned ahead of recall results. |
| `discover()` | Find hidden connections (semantic, keyword-cluster, project-hub, orphan). |
| `review()` | Network health: stale, dense, orphaned. |

### Behavioral card (foundry)

| Tool | What |
|---|---|
| `log_decision(decision_point, agent, decision_made, ...)` | Append-only, fail-soft. Writes JSONL. |
| `query_decisions(agent, decision_point, failure_class, since_iso, limit)` | Read back from SQLite. Drains JSONL first. |

CLI equivalents:

```bash
mycelium foundry ingest                       # drain JSONL -> SQLite
mycelium foundry query --agent X --limit 10   # query back
```

## Configuration

Everything is config-driven. Built-in defaults exist only so zero-config works.

Resolution order: **CLI args > env vars > config file > defaults.**

Search paths for the config file:

1. `--config <path>` flag, or `$MYCELIUM_CONFIG`
2. `$XDG_CONFIG_HOME/mycelium/config.toml`
3. `~/.config/mycelium/config.toml`
4. `~/.mycelium/config.toml`

Env vars: `MYCELIUM_<SECTION>_<KEY>` — e.g. `MYCELIUM_SERVER_PORT=9000`.

See `config.example.toml` for every knob and what it does.

## Companion bits in this repo

| Path | What |
|---|---|
| `skills/checkpoint/` | `/checkpoint` slash-skill — save a session checkpoint to mycelium before `/clear` |
| `hooks/stm/` | Short-Term Memory — paired Claude Code hooks that inject operational lessons before matching tool runs (separate concern from mycelium proper; lives outside SQLite) |
| `docs/claude-md-primer.md` | Paste-ready primer for your CLAUDE.md so Claude follows a consistent ritual when using these tools |

## How the semantic memory works

In short:

```
save(content)          -> insert; auto-connect to top-N FTS-similar; project-index update
                          (duplicate-detection nudges you to update instead, unless force=True)

recall(query)          -> FTS5 + BM25 entry points; propagate one hop through connections;
                          score = (token coverage) + (connection strength) + (recency) + (access)
                          touch every result; co-accessed-in-session pairs get a strength boost

context()              -> rank by (access_count * (connection_count + 1)); return top hub_limit
                          per-agent ranking when an agent has access history

decay (every recall)   -> connection strength *= exp(-days / decay_tau_days)
                          drop below prune_threshold; pinned memories floored at pinned_decay_floor
```

The compounding behavior — frequently-co-accessed memories stay strong,
rarely-touched paths fade — is the whole point. Don't curate by hand; let
usage shape the network.

## How foundry works

```
publisher.publish(...) -> append one JSON line to today's foundry-YYYYMMDD.jsonl
                          fail-soft: never raises, never blocks the caller

ingest.drain_all(...)  -> read each JSONL from last-known offset; insert into SQLite;
                          remember new offset (idempotent, safe to run on a timer)

ingest.query(...)      -> filter + ORDER BY ts DESC + LIMIT
```

Two-stage (JSONL -> SQLite) so the hot path stays tiny and disposable. Lose
the SQLite, re-ingest from JSONL.

## License

MIT. See [LICENSE](LICENSE).
