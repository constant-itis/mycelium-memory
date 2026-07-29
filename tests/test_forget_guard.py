"""forget()/consolidate() substrate protection-guard regression test.

Asserts an autonomous caller cannot delete load-bearing memory:
  A. an ordinary (old, low-confidence) memory forgets normally
  B. a pinned memory is REFUSED, and only forgets with override=True
  C. a high-confidence memory is REFUSED
  D. a [pinned]-tagged memory is REFUSED
  E. a recently-accessed memory is REFUSED
  F. consolidate() excludes protected memories from the candidate list

Run: python3 tests/test_forget_guard.py
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="myc-guard-test-")
os.environ["MYCELIUM_STORAGE__DB_PATH"] = os.path.join(_TMP, "test.db")
sys.argv = ["server"]

from mycelium import server  # noqa: E402

FAIL = []


def check(cond, msg):
    print(f"  [{'ok' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAIL.append(msg)


def mk(content, project="guardtest"):
    out = server.save(content=content, project=project)
    return int(re.search(r"#(\d+)", out).group(1))


def setcols(mid, **cols):
    conn = server.get_db()
    for k, v in cols.items():
        conn.execute(f"UPDATE memories SET {k}=? WHERE id=?", (v, mid))
    conn.commit()
    conn.close()


def exists(mid):
    conn = server.get_db()
    r = conn.execute("SELECT 1 FROM memories WHERE id=?", (mid,)).fetchone()
    conn.close()
    return r is not None


OLD = "2020-01-01T00:00:00+00:00"

print("== A. ordinary memory forgets ==")
a = mk("plain stale note about widgets")
setcols(a, last_accessed=OLD, confidence=0.3, pinned=0)
r = server.forget(a)
check("Forgotten" in r and not exists(a), "old low-conf memory deleted")

print("== B. pinned refused unless override ==")
b = mk("load-bearing pinned decision")
setcols(b, last_accessed=OLD, confidence=0.3, pinned=1)
r = server.forget(b)
check("REFUSED" in r and "pinned" in r and exists(b), "pinned refused")
r2 = server.forget(b, override=True)
check("Forgotten" in r2 and not exists(b), "pinned deletes with override=True")

print("== C. high-confidence refused ==")
c = mk("high confidence fact")
setcols(c, last_accessed=OLD, confidence=0.9, pinned=0)
check("REFUSED" in server.forget(c) and exists(c), "confidence>=0.8 refused")

print("== D. [pinned] text tag refused ==")
d = mk("note with [pinned] tag in body")
setcols(d, last_accessed=OLD, confidence=0.3, pinned=0)
check("REFUSED" in server.forget(d) and exists(d), "[pinned] text refused")

print("== E. recently-accessed refused ==")
e = mk("touched just now")  # save() sets last_accessed = now
check("REFUSED" in server.forget(e) and exists(e), "recent memory refused")

print("== F. consolidate() excludes protected ==")
f_plain = mk("consolidatable stale item")
setcols(f_plain, last_accessed=OLD, confidence=0.3, pinned=0)
f_prot = mk("pinned item that must not be offered")
setcols(f_prot, last_accessed=OLD, confidence=0.3, pinned=1)
out = server.consolidate(project="guardtest")
check(f"#{f_plain}]" in out, "candidate list includes the stale item")
check(f"#{f_prot}]" not in out, "candidate list EXCLUDES the pinned item")
check("protected excluded" in out, "reports protected exclusions")

if FAIL:
    print(f"\n{len(FAIL)} FAILURES")
    sys.exit(1)
print("\nFORGET GUARD VERIFIED")
