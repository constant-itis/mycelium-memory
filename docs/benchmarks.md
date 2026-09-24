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

## Point-fact recall: hybrid RRF + the semantic-unit index

The paraphrase benchmark above measures meaning-bridging. A different, very
common recall shape is the **point-fact question**: "what port does the wiki
listen on", "which Postgres version does the staging box run". The answer is a
short literal fact stored somewhere in memory, and the failure mode is not
vocabulary mismatch but *burial*: the fact lives inside a long memory whose
single whole-document vector averages over everything else it discusses, while
BM25 penalizes the memory for its length. No re-ranking can fix that, because
the answer-bearing memory never enters the candidate list at all.

Two retrieval changes target this shape (both on by default, both revertible
in config):

1. **Hybrid RRF gathering** (`[memory] hybrid_rrf`). Instead of a shallow
   FTS list truncated to the display limit, recall fuses a deep BM25 rank list
   and a deep cosine rank list with Reciprocal Rank Fusion and hands the fused
   top pool to the scorer. Rank fusion never mixes the incomparable BM25 and
   cosine scales, and each arm degrades on its own: embedder down leaves deep
   BM25, an FTS error leaves cosine.
2. **The semantic-unit index** (`[semantic] units`). Long memories are split
   at save time into overlapping sentence windows, each embedded into the
   additive `memory_units` table. At recall the query searches the unit index
   too: a matching window pulls its parent memory into the pool, and the
   memory scores by `max(whole-document cosine, best-window cosine)`. Both
   halves matter. In development, pool entry alone was not enough: the target
   reached the pool at rank 1 in two retrieval arms and was still re-ranked
   out of the top results by its weak whole-document vector.

On the development corpus (a ~3,000-memory real personal knowledge base, 30
point-fact questions with known answer-bearing memories, graded on the top 6
recall results), measured end to end through the full recall pipeline:

| configuration | answer in top 1 | MRR |
|---|---:|---:|
| legacy gather | 17/30 | 0.68 |
| hybrid RRF | 19/30 | 0.74 |
| hybrid RRF + units | 24/30 | 0.86 |

The same comparison on a smaller, older snapshot of the corpus showed the same
ordering (16 → 17 → 24 of 27), so the effect is not an artifact of one corpus
state. The RRF gain grows with corpus size; the unit-index gain is structural
and shows up at every size.

Costs: roughly 3 KB of storage per unit and 10 to 15 units per long memory;
saving a long memory makes a handful of extra embedding calls (best-effort,
never blocks the save); recall adds one similarity pass over the unit matrix.
After enabling, index existing memories once with `mycelium backfill-units`.

### Authoring your own point-fact set

Write `(question, expected-substring)` pairs where the substring is the fact
itself ("8080", "PostgreSQL 15"), then check whether the substring appears in
your top recall results. Three integrity rules learned the hard way:

- **Don't store the answers back into memory.** Saving notes that quote the
  questions and answers plants fresh answer-bearing memories that recency
  ranking then surfaces, and the benchmark silently starts grading its own
  notes. Keep question sets in files outside the memory store.
- **Benchmark on a copy.** `recall()` strengthens connections and bumps access
  counts; A/B arms run on separate copies of the database or the first arm
  biases the second.
- **Prefer distinctive substrings.** Short numeric answers ("47") match
  memories that contain the number incidentally and inflate every arm.
