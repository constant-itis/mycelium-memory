"""[server] identity_header regression test.

Asserts proxy-stamped caller identity is opt-in and overrides agent= only when on:
  A. identity_header unset: a request header is ignored, client agent= kept
  B. identity_header set + header present: header wins over client agent=
  C. header lookup is case-insensitive (HTTP semantics)
  D. identity_header set but header missing/blank: falls back to client agent=
  E. no request context (stdio): falls back to client agent=

Run: python3 tests/test_identity_header.py
"""
import os
import re
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="myc-identity-test-")
os.environ["MYCELIUM_STORAGE__DB_PATH"] = os.path.join(_TMP, "test.db")
sys.argv = ["server"]

from starlette.datastructures import Headers  # noqa: E402

from mycelium import server  # noqa: E402

FAIL = []


def check(cond, msg):
    print(f"  [{'ok' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAIL.append(msg)


def with_request(headers):
    """Make mcp.get_context() look like an HTTP request carrying these headers."""
    req = SimpleNamespace(headers=Headers(headers=headers))
    server.mcp.get_context = lambda: SimpleNamespace(request_context=SimpleNamespace(request=req))


def no_request():
    def boom():
        raise LookupError("no request context")
    server.mcp.get_context = boom


def set_header(name):
    server._cfg().server["identity_header"] = name


def credited(mid):
    rows = server.get_db().execute(
        "SELECT agent FROM agent_access WHERE memory_id = ?", (mid,)).fetchall()
    return {r[0] for r in rows}


def mk(content, agent):
    out = server.save(content=content, project="idtest", agent=agent, force=True)
    return int(re.search(r"#(\d+)", out).group(1))


print("A. identity_header unset")
set_header("")
with_request({"x-forwarded-user": "alice"})
m = mk("alpha identity check memory one", agent="client-a")
check(credited(m) == {"client-a"}, f"header ignored, credited to client agent: {credited(m)}")

print("B. identity_header set, header present")
set_header("X-Forwarded-User")
with_request({"x-forwarded-user": "alice"})
m = mk("bravo identity check memory two", agent="spoofed")
check(credited(m) == {"alice"}, f"header overrides client agent: {credited(m)}")
server.recall(query="bravo identity check", agent="spoofed", limit=1)
check("spoofed" not in credited(m), "recall also credits the header identity")

print("C. case-insensitive header name")
set_header("x-FORWARDED-user")
with_request({"X-Forwarded-User": "bob"})
m = mk("charlie identity check memory three", agent="spoofed")
check(credited(m) == {"bob"}, f"mixed-case config matches: {credited(m)}")

print("D. header missing or blank")
set_header("X-Forwarded-User")
with_request({"x-other": "nobody"})
m = mk("delta identity check memory four", agent="client-d")
check(credited(m) == {"client-d"}, f"missing header falls back: {credited(m)}")
with_request({"x-forwarded-user": "   "})
m = mk("echo identity check memory five", agent="client-e")
check(credited(m) == {"client-e"}, f"blank header falls back: {credited(m)}")

print("E. no request context (stdio)")
no_request()
m = mk("foxtrot identity check memory six", agent="client-f")
check(credited(m) == {"client-f"}, f"stdio falls back: {credited(m)}")

print()
if FAIL:
    print(f"FAILED: {len(FAIL)}")
    sys.exit(1)
print("all identity_header checks passed")
