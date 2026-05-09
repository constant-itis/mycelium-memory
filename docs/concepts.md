# Concepts — what mycelium actually is and how it works

This is the "read this once and you understand the whole system" doc. Other
docs are references; this one is the mental model.

---

## The one-line version

A persistent memory system for LLM CLIs that behaves like a brain instead of
a database: things you use stay strong, things you don't fade, and similar
ideas link themselves through use.

## The two memory cards

Mycelium ships two distinct memory subsystems in one MCP server:

| Card | What it stores | When to use it |
|---|---|---|
| **Semantic** | Facts, observations, decisions you want to recall later. Free-text. | Most of the time. The thing you mean when you say "memory." |
| **Behavioral (foundry)** | Structured rows logging *decisions made* — which model tier was picked, which strategy was tried, what happened. Append-only. | When you want a queryable audit trail / training-data substrate, not natural-language memory. |

You can use either, both, or just semantic. They share nothing — different
SQLite files, different tools, different lifecycles.

---

## Semantic card — the core concepts

### Memories

The atom. One memory = one short, dense statement of something true. Stored
as a row in `memories` with content + project + tier + access metadata.

You write memories with `save("...")`. You don't curate by hand; the system
handles structure.

### Connections

Memories link to other memories through **co-access**. When two memories
appear in the same recall result (or in the same session of recalls), the
edge between them gets stronger. Strong edges propagate during recall —
finding one memory pulls its cluster.

Connections are also auto-created when you `save()` something similar to
existing content (FTS-similarity at write time).

### Decay

Connections lose strength over time:

```
strength_now = strength_when_last_used * exp(-days_since / decay_tau_days)
```

Default `decay_tau_days = 30`. After ~90 days of no use, an edge is roughly
5% of its original strength. Below `prune_threshold` (default 0.05), the
edge is deleted.

This is the whole point. Frequently-co-accessed memories stay strong;
rarely-touched paths fade. The network shape reflects what you actually use.

Decay runs **automatically on every `recall()`** — no maintenance needed.

### Tiers — `hot` vs `cold`

Every memory has a `tier`:

- **hot** — active, surfaces in recalls
- **cold** — consolidated/superseded, kept for history but lower priority

You don't manually set tier on `save()` — everything starts hot. Memories
get cold-marked by:

1. **Maintenance** (`/maintain` or `mycelium maintain --execute`) — duplicate
   session checkpoints (keep newest per project) and memories with
   `SUPERSEDES #N` markers get demoted to cold.
2. **Manual consolidation** — when you `save()` a synthesized summary and
   `forget()` the originals, the summary is hot and the originals are gone.
   Your call.

Cold memories aren't deleted — `recall()` can still find them; they just
aren't surfaced as hubs.

### Pinning — protecting facts from decay

Two ways to mark a memory as protected:

- **`pin(memory_id)`** — sets the `pinned` column to 1. Connections to
  pinned memories never decay below `pinned_decay_floor` (default 0.5).
- **`[pinned]` tag in the content** — also recognized by the maintenance
  pass as a "do not touch" marker.

When to pin: human-confirmed facts that should outlast the natural decay.
"Production DB is at this hostname." "We chose approach X because Y."
"The user prefers kebab-case filenames." Things you'd be annoyed to lose.

When NOT to pin: anything observational that might change. Pin sparingly —
the whole system is about letting the network re-shape with use.

### Confidence

Each memory has a `confidence` score (0.0-1.0). `save()` defaults to 0.3
(an "agent observation, take with a grain of salt"). The user can pass a
higher confidence on save, or `pin()` raises it implicitly to 0.8.

The maintenance pass uses confidence as a guard: anything with
`confidence >= confidence_floor` (default 0.8) is protected.

This lets you tier memories by trust without the manual ceremony of pinning
each one.

### Project field

Every memory has a `project` string (default empty). It's a soft scope —
`recall(project="acme-api")` filters to that project's memories first;
`context(project="acme-api")` returns hubs for just that project.

Use stable project names per logical project. Don't get cute. `"acme-api"`
beats `"the new acme thing"`.

### Resolvers — disambiguation

When a term has multiple meanings ("MERCURY" might be your API and your
data pipeline), seed a resolver once:

```
resolve("MERCURY", "1. mercury-api: REST service on staging\n2. mercury-stream: ...")
```

Future `recall("mercury")` shows the disambiguation ahead of results so the
agent picks the right thing.

---

## Conventions baked into maintenance

### Session checkpoints

When you call `save("[session-checkpoint] working on X. Done: Y. Next: Z.")`
(or use the `/checkpoint` skill, which does this for you), maintenance treats
it as a checkpoint. On the next `mycelium maintain --execute`, duplicate
checkpoints per project get demoted to cold (newest kept hot).

It's a convention, not a special memory type. The `[session-checkpoint]`
prefix is what the maintenance pass scans for.

### Supersedes markers

If a new memory replaces an older one, write it as:

```
save("Use ConfigMap-based deploys (SUPERSEDES #42).")
```

Maintenance reads the `SUPERSEDES #N` marker (or `superseded by #N` on the
old one) and cold-marks `#42` automatically. Same idea: a convention the
janitor recognizes, not a special tool call.

---

## Lifecycle — what happens to a memory over time

```
save()      -> hot tier, confidence 0.3 (or whatever you passed)
                auto-connects to FTS-similar memories at write time

recall()    -> applies decay to all connections, prunes dead ones
                touches accessed memories (raises access_count)
                strengthens co-access edges between session-touched memories

discover()  -> finds connections that should exist but don't
                creates weak edges (0.3-0.5) — they'll either strengthen
                with use or fade naturally

consolidate() -> shows you hot memories ready to merge
                  YOU decide what to synthesize and call save() + forget()

maintain()  -> snapshot the DB, find duplicate checkpoints + superseded,
                cold-mark them, rescue orphans
                guards: skip pinned, high-confidence, recently-accessed

forget()    -> hard delete (with cascading edge cleanup)
```

---

## Foundry — behavioral memory

Different shape, different use case. Two-stage pipeline:

```
log_decision(...)   -> publisher.py appends one JSON line to today's
                       decisions-YYYYMMDD.jsonl. Fail-soft: never raises,
                       never blocks the caller.

mycelium foundry ingest      -> ingest.py drains JSONL into SQLite,
(or implicit on query)          remembering offsets so it's idempotent.

query_decisions(...)        -> reads from SQLite. Drains JSONL first to
                                stay current.
```

When to use foundry instead of `save()`:

- Use `save()` for "the user prefers X" (one fact, will be re-read later).
- Use `log_decision()` for "I picked the cheaper model tier given prompt
  size 412" (one event in a stream, useful in aggregate, queried later for
  patterns).

Foundry is queryable: `query_decisions(agent="X", failure_class="...")` lets
you slice by agent, decision-point, failure type, time. It's the substrate
for "show me every time I made this kind of decision" analysis later.

---

## All the MCP tools — when each is for

| Tool | Use it when |
|---|---|
| `context(project="")` | Start of a session — load the hub memories. |
| `save(content, project=)` | You learned something worth keeping. Short, dense. |
| `recall(query, project=)` | You need to look something up. |
| `connections(memory_id)` | You want to see the local neighborhood of a memory. |
| `pin(memory_id)` | This memory is human-confirmed, protect it. |
| `forget(memory_id)` | This memory is wrong/obsolete, delete it. |
| `resolve(term, meanings)` | A term is ambiguous; seed a disambiguation. |
| `consolidate(project=)` | You want to see what's ready to merge into a summary. |
| `discover()` | Give the network a kick — find hidden links. |
| `maintain(execute=False)` | Periodic janitor pass. Dry-run first, then execute. |
| `review()` | Show me the network's health (stale, dense, orphans). |
| `log_decision(...)` | I made a non-obvious decision worth analyzing later. |
| `query_decisions(...)` | Read decisions back, filtered. |

---

## Slash skills (companion conventions)

Skills are tiny markdown files at `~/.claude/skills/<name>/SKILL.md` that
make a behavior into a slash command.

| Skill | What `/<name>` does |
|---|---|
| `/checkpoint` | Save a `[session-checkpoint]` memory before `/clear` or ending work |
| `/maintain` | Dry-run `maintain()`, show the plan, ask before applying |
| `/discover` | Run `discover()` and show the discovery report |

Skills don't add new capability — they wrap existing tools with a
consistent ritual so it becomes muscle memory. You can write your own;
see `skills/checkpoint/SKILL.md` for the pattern.

---

## STM — short-term memory hook (separate concept)

A pair of Claude Code hooks (`PreToolUse` + `PostToolUseFailure`) that
maintain a 6-entry buffer of **operational lessons** at
`~/.claude/short-term-memory/stm.json`.

When Claude is about to run a Bash command that matches a stored keyword,
the hook injects the lesson as `additionalContext` so Claude reads it
*before* executing. When a tool fails, a different hook prompts Claude
to capture the workaround.

STM is intentionally separate from mycelium:

- STM is ephemeral, JSON, 6 entries max, scoped to "operational gotchas
  for the immediate present"
- Mycelium is durable, SQLite, unbounded, scoped to "facts and decisions
  worth remembering long-term"

Promote useful STM lessons into mycelium with `save()`, then drop them
from STM. See `hooks/stm/README.md` for installation + the CLAUDE.md
primer that tells Claude how to maintain its own STM buffer.

---

## Mental model — the gardener, not the librarian

Old-school knowledge bases are libraries: you put things in folders, you
build taxonomies, you maintain the index, recall is a function of how well
you organized.

Mycelium is a garden: you plant memories, you water by using them, you
prune by ignoring or by `forget()`. The shape emerges from what gets
attention. Maintenance is *occasional weeding* — `discover()` for filling
gaps, `maintain()` for clearing duplicates and rescuing orphans — not
constant curation.

If you find yourself wanting to organize, that's a smell. Just use it.
The network finds its own shape.
