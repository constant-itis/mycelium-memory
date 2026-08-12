#!/usr/bin/env python3
"""Hub-vs-recency divergence: does hub-ranked context() surface recent work?

Two mechanisms, one claim: ranking memories by hub centrality
(access_count x (degree+1)) is NOT a proxy for ranking by recency
(max(created, last_accessed)). This is structural, not incidental —

  A memory can only accumulate accesses and co-access connections AFTER it is
  created, so the all-time top hubs are necessarily OLD, high-traffic nodes; a
  just-created memory, however important, has not had time to become a hub. So
  the top-K by centrality and the top-K by recency are near-disjoint — the
  set context() would surface at startup structurally excludes recent work.

This script quantifies that with NO private data required:

  --synthetic  (default)  seeded synthetic graph -> identical numbers for every
                          reader; reproduces the result + a sensitivity sweep.
  --db PATH               measure it on YOUR OWN mycelium graph (read-only).

Metrics (both modes):
  * top-K overlap / Jaccard       -- THE ROBUST HEADLINE: how many of the K most
    recent memories does context()'s top-K also surface (near 0 in practice).
  * Spearman(hub_score, recency)  -- whole-graph rank correlation, reported as a
    diagnostic. Its SIGN is dataset-dependent (a live graph where sessions bump
    access+recency together can be positive) — which is exactly why you can't
    substitute hub-rank for recency: even when the bulk correlates, the tails
    (the top-K you actually surface) do not.

Stdlib only. Read-only (never writes to a real DB).
"""
import argparse
import math
import os
import random
import sqlite3


def _ranks(vals):
    """Fractional ranks (ties share the average rank)."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs, ys):
    rx, ry = _ranks(xs), _ranks(ys)
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    vx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    vy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    return cov / (vx * vy) if vx and vy else 0.0


def measure(rows, k=15):
    """rows: list of (hub_score, recency_key). recency_key: larger = more recent."""
    hub = [r[0] for r in rows]
    rec = [r[1] for r in rows]
    idx = list(range(len(rows)))
    top_hub = set(sorted(idx, key=lambda i: hub[i], reverse=True)[:k])
    top_rec = set(sorted(idx, key=lambda i: rec[i], reverse=True)[:k])
    inter = top_hub & top_rec
    union = top_hub | top_rec
    return {
        "n": len(rows),
        "spearman": _spearman(hub, rec),
        "overlap": len(inter),
        "k": min(k, len(rows)),
        "jaccard": len(inter) / len(union) if union else 0.0,
    }


def build_synthetic(n, seed, days=180):
    """A store simulated over `days`. Cumulative access & degree accumulate with
    age (older memories have had more time + more co-access). A fraction are
    'revisited' recently, which — realistically — bumps BOTH their recency AND
    their access (a recall touches both), so recent work co-moves with access
    just like a live graph. Nothing is tuned to force the result: the top hubs
    are still the oldest highest-traffic nodes, and the newest memories haven't
    had time to accumulate centrality — so the top-K sets separate regardless of
    the (dataset-dependent) sign of the whole-graph correlation."""
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        age = rng.uniform(0, days)                          # days since created
        cum = max(0.0, rng.gauss(age * 0.5, age * 0.2 + 1)) # accumulates with age
        revisit = rng.random() < 0.15                       # 15% touched recently
        if revisit:
            recency_age = rng.uniform(0, 7)
            cum += rng.uniform(3, 12)                        # recent burst bumps access too
        else:
            recency_age = age
        access = int(cum)
        degree = max(0, int(access * rng.uniform(0.3, 0.7)))  # co-access wiring
        hub_score = access * (degree + 1)
        rows.append((hub_score, -recency_age))              # -age: larger = more recent
    return rows


def load_db(db_path, k=15):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rs = conn.execute("""
        SELECT m.id, (m.access_count * (COUNT(c.target) + 1)) AS hub_score,
               max(m.created, m.last_accessed) AS recency
        FROM memories m LEFT JOIN connections c ON m.id = c.source
        GROUP BY m.id
    """).fetchall()
    conn.close()
    # recency is an ISO string; rank lexically (UTC isoformat sorts chronologically)
    return [(r["hub_score"], r["recency"]) for r in rs]


def _report(title, m):
    print(f"{title}")
    print(f"  n = {m['n']}")
    print(f"  top-{m['k']} overlap = {m['overlap']}/{m['k']}   Jaccard = {m['jaccard']:.3f}"
          f"   <- robust headline: context()'s top-K ~excludes recent work")
    print(f"  Spearman(hub, recency) = {m['spearman']:+.3f}"
          f"   (diagnostic; sign is dataset-dependent)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", help="measure on a real mycelium DB (read-only)")
    ap.add_argument("--synthetic", action="store_true", help="seeded synthetic graph (default)")
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--k", type=int, default=15)
    args = ap.parse_args()

    # --db wins. Otherwise, if not forced synthetic and the configured store
    # actually exists (env override, else the default single-user path), measure
    # it; a fresh clone with no store falls through to reproducible synthetic.
    default_db = os.path.expanduser(
        os.environ.get("MYCELIUM_STORAGE_DB_PATH", "~/.mycelium/memory.db")
    )
    db = args.db
    if db is None and not args.synthetic and os.path.exists(default_db):
        db = default_db
    if db:
        _report(f"=== Real graph: {db} ===", measure(load_db(db, args.k), args.k))
        return

    print(f"=== Synthetic graph (seed={args.seed}, accumulation-with-age model) ===")
    _report(f"n={args.n}:", measure(build_synthetic(args.n, args.seed), args.k))
    print("\n--- sensitivity: top-K overlap stays low across sizes (not a small-sample artifact) ---")
    for n in (200, 500, 2000, 5000):
        m = measure(build_synthetic(n, args.seed), args.k)
        print(f"  n={n:>4}:  top-{m['k']} overlap {m['overlap']}/{m['k']}"
              f"   (Spearman {m['spearman']:+.3f})")


if __name__ == "__main__":
    main()
