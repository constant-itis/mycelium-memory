# Making a repo agent-native: a benchmark study

A plain-language writeup of why we built an agent-native bootstrap surface for the
mycelium codebase, how we tested whether it helps, and what we found.

## The problem

When a coding agent opens an unfamiliar repository, it reconstructs the project
from scratch every time: it reads the README, walks the docs, greps the source,
opens files, and pieces together where things live and how they relate. That work
burns context (tokens) and, for smaller models, often goes wrong: the agent
thrashes, guesses, or gives up.

The idea we tested: give the repo a tiny, high-information **bootstrap surface** an
agent can read first, so it can jump straight to what it needs instead of crawling
the whole tree. Think of it as a map that ships with the repo.

## What we built

Two machine-readable artifacts, generated from the actual source (not hand-waved):

1. **`agent-graph.json`** (the ground truth, "L2"): a deterministic extraction of
   the codebase from its syntax tree: every module, function, class, import edge,
   and call edge, with exact line ranges. This is the full, honest structural map.

2. **`agent-index.json`** (the bootstrap, "L0"): a small curated overlay on top of
   the graph. It names the *concepts* (recall, decay, semantic search), groups
   functions into *components*, lists the 12 public tools with their locations, and
   records how components depend on each other. Every entry points at real code;
   nothing in it can reference a function that does not exist.

The design principle is **progressive disclosure**: an agent reads the small index
first (~4.8k tokens), and from it knows exactly which ~150-line span to open next,
instead of reading whole files to find out.

## How we tested it

Two tiers, because they answer different questions.

### Tier 1: is the map correct and cheap to route with? (deterministic, no AI)

We generated a set of 38 questions an agent actually asks ("Where is `recall`
implemented?", "Which component owns this helper?", "List the MCP tools"), using
the graph itself as the answer key. Then we measured two things: what fraction of
questions the map can answer without reading source, and how many tokens it takes
to reach real code with the map versus without it.

### Tier 2: does a real agent actually do better with it? (agentic, live model)

We ran a small local model (a 35B on our own hardware, so it cost no cloud quota)
as an agent, twice over the same 7 navigation tasks. Both runs had the same tools
(grep, read-lines). One run had the index preloaded; the other did not. We measured
real tokens, number of steps, tool calls, and whether the final answer was correct.

## What we found

### Tier 1 (deterministic)

- **100% of the questions were answerable from the machine surface** without
  reading any source code.
- There was a clean split: the small index answered 68% on its own (where things
  are, which component owns what, what depends on what); the remaining 32% needed
  the full graph (exact call-edge questions). That split is useful design feedback,
  not a shortfall: it tells us what belongs in the tiny always-loaded layer versus
  the bigger on-demand one.
- To reach real code, the map saved a **median of 33x** the tokens (up to 109x).
  The extreme cases are the payoff in miniature: finding a 150-line function inside
  a 1,817-line file costs almost nothing with a pointer and a lot without one.

### Tier 2 (agentic, live 35B)

| | Without map | With map |
|---|---|---|
| Correct answers | 4 / 7 (57%) | 6 / 7 (86%) |
| Steps per task | 5.3 | 1.0 |
| Tool calls (grep/read) | 32 | 0 |
| Tokens per task | 5,836 | 4,847 (1.2x less) |

The model with the map answered **every task in a single step with no grep or file
reads**, and was **more accurate**. Without the map it thrashed, sometimes for the
full 8-step budget, and got the answer wrong 43% of the time.

## Reading the results honestly

Two things matter for interpreting this fairly.

**The token savings shown (1.2x in Tier 2) is the worst case, not the ceiling.**
In our test, each map-assisted task was a fresh conversation that re-paid the full
cost of loading the index. In real use the index loads once and is reused across
many questions, so its cost is amortized and the savings grow. You can see the
un-amortized penalty in the flat per-task numbers.

**For a small model, reliability is the real win, not raw tokens.** Going from 57%
to 86% correct, and from 5.3 steps to 1, is the headline. The map converts a
flailing grep-agent into a one-shot router. The failures without the map were
exactly where crawling is weakest: a thin 18-line tool the model never located in 8
tries, and a question requiring it to enumerate all 12 tools, which it could not
assemble by searching.

## Limitations

- One shared failure was a flaw in our question, not the map: it asked "which
  component owns X" and both runs answered with a correct *location* instead of the
  component *name*. The map had the answer; the question invited the wrong form.
- This is a small repo (3,586 lines) and a short task list. That is the least
  favorable setting for a map, because crawling a small repo is cheap. The
  advantage grows with repo size, number of questions per session, and task
  difficulty. It still won on every axis here.
- Token counts use a chars/4 estimate, and the "without map" cost assumes the agent
  reads the enclosing file after grep. Both are stated in the harness so they can
  be argued and re-run.

## Conclusion

A small, honest, source-generated map materially helps an agent navigate a
codebase: it makes the answers cheap to reach and, for smaller models, makes the
agent far more reliable. The approach is validated from two independent angles, and
the harness is reproducible. Next steps are a continuous-integration check that
keeps the map from drifting out of sync with the code, and shipping the map into
the repo so any agent that clones it starts oriented instead of lost.

## Reproduce

```
python3 gen_queries.py && python3 bench.py     # Tier 1
python3 agent_ab.py                            # Tier 2 (needs the local 35B)
```
Machine results: `results.json`, `agentic_results.json`.
Terse reports: `RESULTS.md`, `AGENTIC_RESULTS.md`. Raw traces: `agentic_run.log`.
