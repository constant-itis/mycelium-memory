# mycelium

Persistent neural-style memory for Claude Code. Single-process MCP server,
SQLite + FTS5, two memory cards in one install:

- **Semantic** — facts and observations. Co-access strengthens connections,
  unused paths decay. Structure emerges from usage, not taxonomy.
- **Behavioral (foundry)** — append-only decision log. Every recorded decision
  becomes a queryable row for later pattern analysis.

Zero external services. One install. One TOML config. Two SQLite files.

## Easiest path: have Claude do it for you

You already have Claude Code installed (it's how you'll use this). Paste the
prompt below into a Claude Code session and it'll detect your OS, pick the
right install method, run the smoke test, and wire up the MCP server. Read
the actions before approving — Claude will tell you everything it's about to
do.

````
Install the mycelium memory MCP server from
https://github.com/constant-itis/mycelium-memory.

Constraints:
- Detect OS (Linux / macOS / Windows) and adapt commands accordingly.
- Require Python 3.11+. If missing, STOP and tell me to install Python first.
  Do not try to install Python yourself.
- Prefer `pipx install ...`. If pipx is unavailable, fall back to
  `pip install --user ...` (or `py -m pip install --user ...` on Windows).
- NEVER use sudo. NEVER use --break-system-packages without confirming with me.
- Use `pip install git+https://github.com/constant-itis/mycelium-memory`
  (or the pipx equivalent) — this isn't on PyPI yet.
- After install, run the smoke test:
  curl -sL https://raw.githubusercontent.com/constant-itis/mycelium-memory/main/scripts/smoke-test.sh | bash
  (Use Git Bash / WSL on Windows, or download + run via bash.)
- If the smoke test passes, register with Claude Code:
  claude mcp add mycelium -- mycelium serve
  Then verify with: claude mcp list
- Optional follow-ups — ASK ME before doing any of these:
  1. Append the CLAUDE.md primer (docs/claude-md-primer.md) to my project's
     CLAUDE.md or my user-level CLAUDE.md.
  2. Install the /checkpoint skill (clone the repo, symlink
     skills/checkpoint into ~/.claude/skills/).
  3. Install the STM hook (clone the repo, run hooks/stm/install.sh —
     requires jq).

Report back: what got installed, where, and which optional steps you'd
recommend based on my environment.
````

If you'd rather do it by hand, the manual instructions below cover the same
steps.

## Quick start (60 seconds)

**Requirements:** Python 3.11+, `pip` or `pipx`. Optional: `jq` (only if
installing the STM hook).

```bash
# 1. Install. Pick one path that fits your environment:
pipx install git+https://github.com/constant-itis/mycelium-memory      # cleanest
# OR:
pip install --user git+https://github.com/constant-itis/mycelium-memory # if no pipx
# OR for development:
git clone https://github.com/constant-itis/mycelium-memory && cd mycelium-memory && pip install -e .

# 2. Verify the install (uses a throwaway temp dir; touches nothing else).
bash scripts/smoke-test.sh                                  # repo clone path
# OR if installed via pipx/pip, fetch and run:
curl -sL https://raw.githubusercontent.com/constant-itis/mycelium-memory/main/scripts/smoke-test.sh | bash

# 3. Wire into Claude Code (stdio — recommended for single-machine use).
claude mcp add mycelium -- mycelium serve

# 4. Open Claude Code. The tools (save, recall, context, log_decision, ...)
#    are now available. Try: "remember that I prefer kebab-case for filenames"
```

**On Debian/Ubuntu 23+ / Fedora 38+** you may hit `error: externally-managed-environment`.
Use `pipx` (preferred) or add `--break-system-packages` to the `pip` command
(safe with `--user`).

**Make sure `~/.local/bin` is on `$PATH`** if you used `pip install --user` —
that's where the `mycelium` script lands.

### Optional: customize the config

```bash
mycelium init                  # copy config.example.toml to ~/.mycelium/config.toml
mycelium config                # print the effective config (defaults + your overrides)
```

You don't need this to get started — sensible defaults are baked in.

### Optional: remote / multi-machine

```bash
mycelium serve --transport http --port 8200 &
claude mcp add mycelium --transport http http://YOUR_HOST:8200/mcp
```

### Optional: seed from existing material

A fresh install starts empty. If you'd rather hit the ground running than
wait for memories to accumulate naturally, [docs/seeding.md](docs/seeding.md)
has paste-ready prompts for seeding from your existing CLAUDE.md, project
trees, curated bullet lists, the current conversation, or shell history.

### Optional but recommended: the CLAUDE.md primer

Drop [docs/claude-md-primer.md](docs/claude-md-primer.md) into your own
`CLAUDE.md` so Claude follows a consistent ritual (when to save, what *not*
to save, project-field convention, consolidate/pin/discover usage, foundry
patterns). The MCP server already sends a basic `instructions=` block, but
the primer is the longer opinionated guide.

### Windows

The Python parts work as-is. Substitute `py -m pip ...` for `pip ...`:

```powershell
py -m pip install --user git+https://github.com/constant-itis/mycelium-memory
# Make sure %APPDATA%\Python\Python311\Scripts is on PATH so `mycelium` resolves.
claude mcp add mycelium -- mycelium serve
```

`scripts/smoke-test.sh` and `hooks/stm/install.sh` are bash + need `jq`.
On Windows run them under **Git Bash** or **WSL**, or skip and verify by
opening Claude Code and calling `context()`.

## Works with any MCP client

Mycelium is an MCP server — any client that speaks MCP can read and write the
same memory store. Run one HTTP server and point all your CLIs at it; lessons
from your morning Claude session are visible to your afternoon Codex session.

### Claude Code (CLI)

```bash
# Stdio — simplest for one CLI on one machine
claude mcp add mycelium -- mycelium serve

# HTTP — required if you want multiple clients sharing this server
mycelium serve --transport http --port 8200 &
claude mcp add mycelium --transport http http://localhost:8200/mcp
```

### Claude Desktop App

Edit the desktop config and add an `mcpServers` entry. Path:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "mycelium": {
      "command": "mycelium",
      "args": ["serve"]
    }
  }
}
```

Restart the desktop app. (For HTTP transport, consult the desktop app's
current MCP docs — the JSON shape is in flux.)

### Codex CLI

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.mycelium]
url = "http://localhost:8200/mcp"

# Optional: gate write tools behind approval prompts
[mcp_servers.mycelium.tools.save]
approval_mode = "approve"
[mcp_servers.mycelium.tools.log_decision]
approval_mode = "approve"
```

Codex uses HTTP transport, so first start the server in HTTP mode:

```bash
mycelium serve --transport http --port 8200 &
```

### Any other MCP client

Two transports are supported:

- **stdio** — client spawns `mycelium serve` as a subprocess
- **streamable-http** — client connects to `http://HOST:PORT/mcp`

Consult your client's MCP docs for its config syntax. The endpoints +
tool surface are standard; only the wrapper config differs.

### Multi-client co-access — how it actually works

- **Same machine, multiple stdio clients** (Claude CLI + Codex CLI both spawning
  `mycelium serve`): each spawns its own server process, but both processes hit
  the same `~/.mycelium/memory.db`. SQLite WAL serializes writers + allows
  concurrent readers. Just works.
- **Multiple machines or multiple clients sharing one server:** use HTTP
  transport. Run one `mycelium serve --transport http` and point each client at
  it. One server, one DB, all clients see the same memories.

> **Security note:** The MCP server has no auth. Don't expose the HTTP
> transport to the public internet — bind to `127.0.0.1` for one-machine use,
> or to a private interface (Tailscale, WireGuard, LAN) for trusted multi-machine.

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

- Quick reference: `config.example.toml` (every knob, line-commented)
- Walkthrough: [docs/configuration.md](docs/configuration.md) (what each knob
  controls, when to change it, tuning by symptom)
- Inspect: `mycelium config` prints the effective config + which file it was
  loaded from. First command to run when something feels off.

## Backups

Your data lives in:

- `~/.mycelium/memory.db` — semantic
- `~/.mycelium/foundry.db` + `~/.mycelium/foundry/logs/*.jsonl` — behavioral

Back these up the same way you back up anything else important. The JSONL files
are the durable source for foundry — if you lose `foundry.db`, re-ingest from
the JSONL with `mycelium foundry ingest`.

## Troubleshooting

| Symptom | What to check |
|---|---|
| `mycelium: command not found` | The `mycelium` script lives wherever your installer put scripts. For `pip install --user` that's `~/.local/bin` (Linux/Mac) or `%APPDATA%\Python\Python311\Scripts` (Windows). Add it to `$PATH`. `pipx` handles this automatically. |
| `ModuleNotFoundError: No module named 'mcp'` | Install didn't complete, or you're running with the wrong Python. `python3 -c "import mcp"` should succeed; if not, reinstall against the right interpreter. |
| `error: externally-managed-environment` (PEP 668) on `pip install` | Modern Debian/Ubuntu/Fedora block global pip. Use `pipx install ...` (preferred) or add `--user --break-system-packages` to the pip command. |
| MCP server doesn't appear in Claude | Restart Claude Code. Run `claude mcp list` to confirm registration. Run `mycelium serve` directly in a terminal to see startup errors. |
| `database is locked` | Rare WAL contention if many writers race. Just retry. If persistent, check that no zombie `mycelium serve` is still running. |
| Config not behaving like the file says | Run `mycelium config` to see what was actually resolved + the source file path. Env vars override file values. |
| `recall()` returns nothing for a memory I know I saved | Check the project field — `recall()` is project-scoped when you pass `project=`. Run `mycelium config` to confirm `db_path` matches what the server is using. |

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
