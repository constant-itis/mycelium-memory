# Agent-index benchmark results (Tier 1, deterministic)

Answer key = the frozen graph. token ~= chars/4. See bench.py for assumptions.

## A. Coverage (answerable without reading source)

| Machine surface | Queries answered |
|---|---|
| agent-index.json (L0, 4790 tok) | 26/38 (68%) |
| agent-graph.json (L2, 19173 tok) | 12/38 (32%) |
| either (full surface) | 38/38 (100%) |

## B. Context cost on code-reaching queries (WITH index vs crawl)

Per-query reduction: median 33.2x, mean 41.7x, range 6.3x-109.5x (n=16)

| query | archetype | file | with-index tok | crawl tok | reduction |
|---|---|---|---:|---:|---:|
| q010 | LOCATE | server.py | 158 | 17301 | 109.5x |
| q012 | LOCATE | server.py | 179 | 17301 | 96.7x |
| q011 | LOCATE | server.py | 246 | 17301 | 70.3x |
| q009 | LOCATE | server.py | 295 | 17301 | 58.6x |
| q002 | LOCATE | server.py | 309 | 17301 | 56.0x |
| q037 | CONCEPT | server.py | 342 | 17301 | 50.6x |
| q005 | LOCATE | server.py | 453 | 17301 | 38.2x |
| q007 | LOCATE | server.py | 519 | 17301 | 33.3x |
| q035 | CONCEPT | server.py | 522 | 17301 | 33.1x |
| q006 | LOCATE | server.py | 535 | 17301 | 32.3x |
| q036 | CONCEPT | embeddings.py | 51 | 1066 | 20.9x |
| q004 | LOCATE | server.py | 842 | 17301 | 20.5x |
| q001 | LOCATE | server.py | 1031 | 17301 | 16.8x |
| q008 | LOCATE | server.py | 1188 | 17301 | 14.6x |
| q003 | LOCATE | server.py | 1703 | 17301 | 10.2x |
| q038 | CONCEPT | maintain.py | 500 | 3150 | 6.3x |

## C. Cold-session model (answer all 16 code-reaching queries)

- WITH index (load once + read pointed spans): 13663 tok
- WITHOUT index (crawl, read each touched file once): 21517 tok
- Session reduction: 1.57x

