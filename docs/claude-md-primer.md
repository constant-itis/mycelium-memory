# CLAUDE.md primer for mycelium

Drop this into your own `CLAUDE.md` (or any project-level `CLAUDE.md`) so Claude
follows a consistent ritual when using mycelium. Trim sections you don't need.

The MCP server already sends a short `instructions=` block to Claude on init —
this primer is the longer, opinionated guide that shapes *how* Claude uses the
tools day-to-day.

---

## Mycelium — persistent memory

You have a persistent memory system via MCP. It's a neural-style network:
memories connect through co-access, paths strengthen with use, decay without it.
Structure emerges from usage, not taxonomy.

### Startup ritual

At the start of every conversation:

1. Call `context()` (optionally with `project="..."` if the work is scoped) to
   load the hub memories — most-connected, most-accessed.
2. If the user references prior work, call `recall("query")` before guessing.

### Saving memories

Call `save(content, project="...")` whenever you learn something the next
session would benefit from knowing. Examples worth saving:

- Project structure, key file paths, service ports, command runbooks
- Bugs you debugged and the root cause / fix pattern
- User preferences and conventions you confirmed
- Decisions and their rationale
- "I tried X, it failed because Y, Z works" workarounds

Examples NOT worth saving (these belong elsewhere or nowhere):

- Secrets, API keys, passwords, tokens — never
- Anything fully derivable from `git log`, `git blame`, or reading the file
- Ephemeral session state ("currently editing line 42") — that's not memory
- Anything you'd be embarrassed to read back to the user verbatim

Keep memories **short and dense — one idea per memory.** Mycelium auto-detects
near-duplicates on save and asks you to update instead of adding noise; trust
that signal.

Use a stable `project` string per logical project (`"acme-website"`, not
`"the new acme thing"`) so context() and recall() can scope cleanly.

### Recalling

Call `recall("query")` when you need something. The system propagates one hop
through connections, so a partial cue returns the whole cluster. Don't over-narrow
the query — short noun phrases work better than long sentences.

If a term is ambiguous, call `resolve("TERM", "1. meaning A\n2. meaning B")` once
to seed a disambiguation memory. Future recalls of that term surface the resolver
ahead of results.

### Maintenance

- `consolidate(project="...")` shows hot memories ready to merge. Synthesize a
  cold summary, `save()` it, then `forget()` the originals you've absorbed.
- `pin(memory_id)` for facts the user has confirmed manually — pinned memories'
  connections never decay below the configured floor.
- `discover()` periodically (idle moments, end-of-session) finds hidden links
  and rescues orphans. Cheap to run.
- `review()` shows network health: stale memories, dense clusters, orphans.

### Session checkpoints (with the /checkpoint skill)

Before `/clear`, `/compact`, or ending a long session, save your working state
as a single memory tagged `[session-checkpoint]`:

```
[session-checkpoint] Working on <X>. Done: <Y>. Blocked: <Z>. Next: <W>.
```

If the `checkpoint` skill is installed, just type `/checkpoint`.

---

## Foundry — behavioral memory (decisions log)

When you make a non-obvious decision (which model tier, how to route a task,
which strategy to try), call `log_decision(...)`. It's append-only and fail-soft
— never blocks you, never raises.

```
log_decision(
    decision_point="model_routing",
    agent="<your-agent-name>",
    decision_made="cheaper_tier",
    input_features={"prompt_tokens": 412, "task_type": "summarize"},
    outcome={"latency_ms": 320, "qc_passed": True},
)
```

Read decisions back with `query_decisions(agent="...", failure_class="...", limit=20)`.

When NOT to log: every routine read or trivial choice. Foundry is a substrate
for pattern analysis later — keep signal-to-noise high.

---

## Short-Term Memory (STM) — optional

If the STM hook is installed, you have a 6-entry buffer at
`~/.claude/short-term-memory/stm.json` that gets injected as additionalContext
before matching tool runs.

Self-maintenance:

- When you hit a wall and find a workaround, write the lesson to `stm.json`.
  Format: `{domain, keywords[], lesson, added, last_hit, hits}`.
- New entry in same `domain` REPLACES the old one (interference-based displacement).
- Max 6 entries — drop the lowest-`hits` one if full and a new domain is needed.
- Lessons are operational (how to do X), not secrets (no IPs, keys, passwords).
- Promote stable lessons to mycelium with `save()` and remove from STM.
