"""Concurrency hardening regression test (Python 3.11+).

Asserts the server stays stable under multi-agent contention:
  A. sanity — every tool callable once, no error
  B. hammer — 16 threads x 40 mixed ops, zero jams / zero unhandled exceptions
  C. leak guard — a handler that throws mid-write must NOT jam the next write
  D. decay throttle — _apply_decay runs at most once per interval
  E. integrity — PRAGMA integrity_check == ok after the storm

Run: MYCELIUM_STORAGE__DB_PATH=<tmp> python3.11 tests/test_concurrency_hardening.py
"""
import itertools
import os
import sys
import tempfile
import threading
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = tempfile.mkdtemp(prefix="myc-oss-test-")
os.environ["MYCELIUM_STORAGE__DB_PATH"] = os.path.join(_TMP, "test.db")
sys.argv = ["server"]

from mycelium import server  # noqa: E402

FAIL = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


print("seeding...")
TOPICS = ["subnetting", "OSPF", "TLS handshake", "NAT traversal", "VLAN trunking",
          "BGP peering", "DNS caching", "TCP windowing", "IPsec tunnel", "QoS shaping",
          "spanning tree", "DHCP relay"]
for i in range(300):
    server.save(f"Seed {i}: distinct note on {TOPICS[i % len(TOPICS)]} case {i} "
                f"with unique detail {i * 7 + 3} for row {i}",
                project="test", agent="seed", force=True)
conn = server.get_db()
ids = [row["id"] for row in conn.execute("SELECT id FROM memories").fetchall()]
now = server._now()
pairs = []
for a, b in itertools.islice(itertools.combinations(ids, 2), 4000):
    pairs.append((a, b, 2.0, now))
    pairs.append((b, a, 2.0, now))
conn.executemany(
    "INSERT OR IGNORE INTO connections (source, target, strength, last_activated, co_access_count) "
    "VALUES (?,?,?,?,1)", pairs)
conn.commit()
n_conn = conn.execute("SELECT COUNT(*) FROM connections").fetchone()[0]
conn.close()
print(f"seeded {len(ids)} memories, {n_conn} connections")

print("\n[A] sanity — each tool once")
try:
    server.save("sanity memory about firewalls", project="test", agent="a", force=True)
    server.recall("TLS handshake", project="test", agent="a")
    server.context(project="test", agent="a")
    server.connections(ids[0])
    server.pin(ids[0]); server.pin(ids[0], unpin=True)
    check(True, "tools callable, no exception")
except Exception:
    traceback.print_exc()
    check(False, "tools callable, no exception")

print("\n[B] hammer — 16 threads x 40 ops")
errors, jam_strings, soft_fails = [], [], []
counter = itertools.count()

def worker(wid):
    import random as _r
    for j in range(40):
        n = next(counter)
        try:
            op = _r.random()
            if op < 0.40:
                res = server.save(f"worker {wid} unique note {n} about {TOPICS[n % len(TOPICS)]} "
                                  f"detail {n * 3}", project="test", agent=f"w{wid}", force=True)
            elif op < 0.80:
                res = server.recall(f"{TOPICS[n % len(TOPICS)]}", project="test", agent=f"w{wid}")
            elif op < 0.90:
                res = server.context(project="test", agent=f"w{wid}")
            elif op < 0.97:
                res = server.connections(_r.choice(ids))
            else:
                res = server.forget(_r.choice(ids))
            if isinstance(res, str):
                low = res.lower()
                if "database is locked" in low or "malformed" in low or "contention" in low:
                    jam_strings.append((wid, res[:80]))
                elif res.startswith("⚠️"):
                    soft_fails.append((wid, res[:80]))
        except Exception as e:
            errors.append((wid, repr(e)))

threads = [threading.Thread(target=worker, args=(w,)) for w in range(16)]
for t in threads: t.start()
for t in threads: t.join()

check(not errors, f"zero unhandled exceptions (got {len(errors)})")
for e in errors[:5]: print("      ", e)
check(not jam_strings, f"zero lock/malformed jams surfaced (got {len(jam_strings)})")
for e in jam_strings[:5]: print("      ", e)
print(f"      (benign soft-fails from concurrent forget/recall races: {len(soft_fails)})")

print("\n[C] leak guard — throw mid-write, next write must still succeed")

@server.resilient
def _boom():
    c = server.get_db()
    c.execute("INSERT INTO memories (content, project, tier, created, last_accessed, access_count) "
              "VALUES ('leak test uncommitted', 'test', 'hot', ?, ?, 0)", (server._now(), server._now()))
    raise RuntimeError("simulated mid-write crash")

try:
    _boom()
except RuntimeError:
    pass
try:
    server.save("post-crash write proves no jam", project="test", agent="c", force=True)
    check(True, "write after mid-write crash succeeded (no jam)")
except Exception:
    traceback.print_exc()
    check(False, "write after mid-write crash succeeded (no jam)")
conn = server.get_db()
leaked = conn.execute("SELECT COUNT(*) FROM memories WHERE content='leak test uncommitted'").fetchone()[0]
conn.close()
check(leaked == 0, f"uncommitted row was rolled back (found {leaked}, want 0)")

print("\n[D] decay throttle — second call within interval is skipped")
server._last_decay_ts = 0.0
c = server.get_db(); first = server._apply_decay(c); c.close()
c2 = server.get_db(); second = server._apply_decay(c2); c2.close()
check(second == 0, f"second decay within interval skipped (returned {second})")

print("\n[E] integrity check after the storm")
conn = server.get_db()
integ = conn.execute("PRAGMA integrity_check").fetchone()[0]
conn.close()
check(integ == "ok", f"integrity_check == ok (got {integ!r})")

print("\n" + ("=" * 50))
if FAIL:
    print(f"RESULT: {len(FAIL)} FAILURE(S)")
    for f in FAIL: print("  -", f)
    sys.exit(1)
print("RESULT: ALL PASS")
