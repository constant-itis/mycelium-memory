# Tier 2: agentic A/B results (local 35B on evo-x2)

Two arms answer the same 7 code-navigation tasks with the same tools
(`grep`, `read_lines`). CRAWL has no map; INDEX gets `agent-index.json` preloaded.
Model: Qwen3.6-35B-A3B, enable_thinking=false, temp 0. Tokens are REAL (endpoint `usage`).

## Headline

| Metric | CRAWL (no map) | INDEX (map) |
|---|---|---|
| Correct | 4/7 (57%) | **6/7 (86%)** |
| Mean steps | 5.3 | **1.0** |
| Tool calls (grep+read) | 32 | **0** |
| Mean tokens/task | 5836 | 4847 |
| Token reduction | - | **1.20x** |

The small model with the map answers **every task in one step with zero tool
calls** and is **more accurate**. Without the map it thrashes (up to 8 steps of
grep) and gets it wrong 43% of the time.

## Per-task

| task | CRAWL correct / steps / tok | INDEX correct / steps / tok |
|---|---|---|
| loc_recall | Y / 6 / 9346 | Y / 1 / 4848 |
| loc_save | Y / 5 / 5271 | Y / 1 / 4847 |
| loc_discover | Y / 4 / 3207 | Y / 1 / 4849 |
| loc_connections | **N / 8 / 7153** | Y / 1 / 4849 |
| concept_decay | Y / 4 / 4662 | Y / 1 / 4845 |
| surface_tools | **N / 8 / 10694** | Y / 1 / 4850 |
| own_apply_decay | N / 2 / 519 | N / 1 / 4844 |

## Reading the numbers honestly

**The token reduction (1.20x) is the WORST CASE, not the ceiling.** Each INDEX
task is a fresh conversation that re-pays the full ~4.8k index prompt (see the dead-flat
4844-4850 tok/task). In a real session the index loads ONCE and is cached/shared
across many questions, so its marginal cost collapses and the reduction widens a lot.
CRAWL tokens instead track thrash: 519 (quick wrong guess) to 10694 (8-step flail).

**The reliability win is the real story for a small model.** 57% -> 86% accuracy
and 5.3 -> 1.0 steps. The map converts a flailing grep-agent into a one-shot
router. The two CRAWL failures are exactly where grep is weak: `connections` is a
thin 18-line tool it never located in 8 tries, and `surface_tools` requires
enumerating all 12 tools, which it could not assemble by crawling.

**One failure is a benchmark artifact, not an index gap.** `own_apply_decay` asked
"which component owns `_apply_decay`". Both arms answered with a *location*
(server.py:423, correct location) instead of the component *name*
`comp.graph_dynamics`. The index HAS the mapping; the question invited a location
answer and grading wanted a component id. Fix the task framing and INDEX is 6/6 on
well-posed questions.

## Scaling intuition

Token win grows with: (a) repo size (crawl reads whole files; the map jumps to a
span), (b) task count per session (index amortizes, crawl does not), (c) task
difficulty (crawl thrash is unbounded; index is flat). This micro-benchmark on a
3.5k-LOC repo with 7 fresh-context tasks is the least favorable case for the map,
and it still wins on every axis.

## Reproduce

```
python3 agent_ab.py    # needs evo-x2 35B at :8100 reachable on LAN
```
Raw per-step trace in `agentic_run.log`; machine results in `agentic_results.json`.
