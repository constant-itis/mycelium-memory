# Recency surfacing + prior-override precision

Two small, coupled additions that fix two failures a *fresh* session has: it
doesn't know what was worked on recently, and it will confidently assert
stale facts about your own stack. Both are opt-in-free — they ship on by
default and cost nothing until used.

## The two problems

They share one root cause: the store had a durable, well-connected layer
(`context()` + the connection graph) but **no fast, recency-indexed view**, and
**no way for a stored fact to outrank the model's training prior**.

1. **Session amnesia.** `context()` ranks hubs by centrality —
   `access_count × (connections + 1)`. That is recency-*blind*: a project worked
   hard for three days last week has low centrality, so a new session never sees
   it and never knows to `recall()` it. (Structural, not incidental — see the
   [benchmark](#benchmark-hubs-are-not-recency).)
2. **Confident-wrong assertions.** Asked to stand up a self-hosted service, a
   fresh session says the free edition "was discontinued" — from stale training
   data — when a memory records you actually running it. Retrieval isn't the
   problem (the contradicting memory ranks fine); the session never *checks*,
   because it thinks it already knows.

## 1. `recent()` — the episodic view

A new MCP tool `recent(days, limit, project)` plus a read-only `GET /wake` HTTP
route. Both rank memories by `max(created, last_accessed)` — "written **or**
recently active" — newest first, grouped by project.

```
recent()                     # last 14 days, all projects
recent(days=3, project="x")  # tighter window, one project
```

Call it at the **start of a session, alongside `context()`**:

> `context()` = what you durably know. `recent()` = what just happened.
> Then `recall()` the specific threads you need.

**It is read-only by construction.** `recent()` deliberately does **not** bump
`last_accessed` or strengthen connections. Every normal `recall()` does — and if
the startup digest *touched* what it surfaces, everything shown at session start
would stay "recent" forever, a self-reinforcing loop. Surfacing is passive
priming; only a real, model-initiated `recall()` earns reactivation.
**Priming ≠ recall.** (A test fingerprints the table before/after to enforce it.)

`GET /wake?days=14&limit=15&project=` returns the same digest as JSON for a
`SessionStart` shell hook to `curl` — it never mutates state and degrades to
`{"ok": false, "error": ...}` rather than a 500 that could read as "server down".

## 2. `contradicts_prior` — prior-override salience

A memory can now be saved with a flag that says *this conflicts with what a model
thinks it knows*:

```python
# base knowledge says this edition is EOL — but you actually run it
save("We run the community edition of $TOOL; vendor still ships 2026 releases",
     contradicts_prior=True)
```

Mechanically it's an additive `INTEGER DEFAULT 0` column (migrated in place on
existing DBs). When set, the memory gets a ranking bump (`contradicts_prior_boost`)
in recall scoring and renders an **`[OVERRIDES-PRIOR]`** marker, so a stored truth
outranks generic matches *and* signals the model to trust it over its prior. Set
it at `save()` time, at the "huh, that still exists?" moment.

Reach for it on the memories most likely to be steamrolled by a prior later: an
edition/version base knowledge thinks is gone, a service on a nonstandard port, a
tool used against its documented purpose.

## Tunables

All live in the `[memory]` config section (override via TOML or `MYCELIUM_*` env
— see [configuration.md](configuration.md)):

| Knob | Default | Meaning |
|---|---|---|
| `recent_window_days` | 14 | episodic horizon for `recent()` / `/wake` |
| `recent_limit` | 15 | max memories in a digest (mirrors `hub_limit`) |
| `recent_summary_chars` | 140 | per-line trim in the `recent()` text digest |
| `wake_summary_chars` | 200 | per-item trim in the `/wake` JSON |
| `contradicts_prior_boost` | 0.25 | salience bump; kept `>` pinned's weight so a learned exception beats a confident default |

## Benchmark: hubs are not recency

`benchmarks/hub_vs_recency.py` — stdlib-only, **reproducible** (`--synthetic`,
fixed seed → identical numbers for everyone) and **self-serve** (`--db PATH`, or
it auto-detects your configured store, read-only):

```bash
python benchmarks/hub_vs_recency.py              # seeded synthetic (default)
python benchmarks/hub_vs_recency.py --db ~/.mycelium/memory.db   # your own graph
```

**Why it holds on any graph:** a memory only accumulates access and connections
*after* it's created, so the all-time top hubs are necessarily old, high-traffic
nodes — a just-created memory can't be a hub yet. So `context()`'s top-K and the
top-K by recency are near-disjoint.

Synthetic graph (seed 42):

```
top-15 overlap        = 0/15   Jaccard 0.000   <- context()'s top-K excludes recent work
Spearman(hub,recency) = -0.52                  (diagnostic; SIGN is dataset-dependent)
sensitivity n=200..5000: overlap 1/1/0/0       (stable, not a small-sample artifact)
```

**Overlap is the robust signal** — ~0 on the synthetic graph and on real graphs.
The correlation *sign* is not: on a live graph, active sessions bump access and
recency together, so the bulk can correlate *positively* — yet the top-K you'd
actually surface stay disjoint. That's exactly why hub-rank can't stand in for
recency, and why `recent()` is a **separate route** rather than a recency term
folded into `context()` (which would need a magic weight and would regress the
stable hub view).

## Biomimetic framing — *inspired-by, not literal*

The design mines memory neuroscience but doesn't claim to be a biological model.
The honest ledger:

| Design element | Inspiration | Status |
|---|---|---|
| fast episodic (`recent`) + slow consolidated (graph) | Complementary Learning Systems — McClelland/O'Reilly 1995; Kumaran et al. 2016 | **well-grounded** |
| surfacing is a *view*, never drains the graph | consolidation is copy-and-extract, not move-and-delete (Multiple Trace / Trace Transformation — Nadel & Moscovitch) | grounded; enforced as the no-mutate rule |
| recency raises retrieval score | ACT-R base-level activation — Anderson & Schooler 1991 | grounded math; *not* "neurons firing" |
| `contradicts_prior` bumps conflicting facts | precision-weighting (Rao & Ballard; Friston) + behavioral tagging (Moncada & Viola) | **analogy/extension**, cited as such — not one proven mechanism |
| forgetting = scroll-off + decay, not deletion | prioritized replay is real; "unreplayed decays" is inferred | engineering choice inspired by replay selectivity |

## Wiring it up (harness side)

`recent()` / `/wake` are meant to fire at session start — a `SessionStart` hook
that `curl`s `/wake`, or a directive to run `context()` + `recent()` together. The
prior-override discipline pairs with a client-side rule worth putting in your
`CLAUDE.md` (see [claude-md-primer.md](claude-md-primer.md)): *never assert a
world-fact about your own stack from base knowledge — recall first; a stored fact
overrides the prior.*
