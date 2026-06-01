# Does semantic recall help? Benchmark it.

Recall is lexical (SQLite FTS5) by default — it matches on **shared words**.
Optional [semantic recall](configuration.md#semantic) adds matching by **meaning**,
so a query can find a memory it shares no keywords with. Whether that's worth
wiring up depends entirely on *your* memories and *how you search*, so mycelium
ships a benchmark you can run on your own data:

```bash
mycelium eval                      # bundled cross-domain sample
mycelium eval --dataset mine.json  # your own {memories, queries}
```

It builds a throwaway DB, loads the memories, and reports how often each query's
target memory surfaces in recall — once with semantic **off**, once **on**. No
data of yours is touched; results print as a table (add `--json` for raw output).

## Should you enable it?

**Enable it if:**
- You search by *concept* — "how do credentials refresh" rather than the exact
  word you stored.
- Your memories use varied vocabulary, or you don't remember the exact phrasing.
- Your corpus is more than a few dozen notes (keyword collisions grow with size).
- You already run, or don't mind running, an embedding endpoint (Ollama is a
  one-liner).

**Keep it off if:**
- You search with the exact terms you stored (FTS is already great, and free).
- Your corpus is tiny.
- You don't want to run an embedding service. Lexical recall has zero extra
  moving parts.

It's **off by default and dependency-free** — nothing changes until you set
`[semantic] embed_url`, and recall falls back to lexical if the endpoint is down.

## What the numbers look like

### Bundled sample — 20 paraphrase queries over 22 cross-domain memories

The sample queries deliberately avoid their target's keywords (e.g. *"things that
helped with my insomnia"* → a note that says "trouble drifting off"), so it
isolates where lexical search struggles. Embedding model: EmbeddingGemma-300M via
a local server.

| method | recall@1 | recall@3 | recall@5 | MRR |
|---|---:|---:|---:|---:|
| lexical (default) | 25% | 35% | 35% | 0.32 |
| hybrid (`weight=10`, default) | 25% | 35% | 50% | 0.39 |
| hybrid (`weight=25`) | 55% | 65% | 75% | 0.64 |
| hybrid (`weight=50`) | 75% | 85% | 85% | 0.82 |

**The big lesson: `weight` is the dial, and its sweet spot depends on your
embedding model.** Different models compress cosine similarity differently —
EmbeddingGemma's relevant-pair scores sit in a narrow band, so the default
`weight=10` only nudges results, while `25`–`50` lets meaning lead. Don't guess:
sweep it on your data.

```bash
for w in 5 10 20 40; do
  MYCELIUM_SEMANTIC_WEIGHT=$w mycelium eval | grep hybrid
done
```

Pick the lowest weight that recovers your paraphrase queries **without** demoting
exact-keyword hits (test a few of those too — raising weight trades exact-match
sharpness for meaning).

### A larger real corpus

On a ~950-memory personal knowledge base, with reworded queries that each target
a specific real memory (`weight=10`, EmbeddingGemma), lexical recall@5 was ~20%
and hybrid ~70%, with exact-keyword queries unaffected. Bigger, denser corpora —
where keyword collisions are worse and there's more signal to embed — tend to
benefit more.

## Honest caveats

- These are **upper bounds for the reworded-query case** — the queries are chosen
  to dodge keywords. Your real mix includes plenty of exact-term searches that FTS
  already nails, so day-to-day lift is smaller than the paraphrase numbers.
- Results swing with corpus size, content type, embedding model, and `weight`.
  That's exactly why this is a *harness you run*, not a number to take on faith.
- Pure-Python similarity is fine for thousands of memories; for much larger stores
  install `numpy` (used automatically if present) or expect recall to slow down.

## Make it your own

The dataset format is just two lists:

```json
{
  "memories": [{"ref": "note1", "content": "..."}],
  "queries":  [{"query": "how I phrase the search", "expect": "note1"}]
}
```

Export ~20–50 of your real memories, write the queries the way you'd actually
search for them, and run `mycelium eval --dataset yours.json`. That number is the
only one that matters for your decision.
