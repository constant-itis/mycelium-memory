#!/usr/bin/env python3
"""CI verifier: assert agent-index.json / agent-graph.json still match the code.
A stale map that confidently points at moved code is worse than no map, so this
fails the build on ANY drift. Checks:
  - version matches pyproject
  - every doc / important_path exists
  - every MCP tool resolves to a `def <name>` with an @mcp.tool() decorator nearby
  - every component path span exists, is in-bounds, and starts a def/class
  - referential integrity of component ids (concepts, depends_on, tool ownership)
Run: python3 scripts/verify_agent_index.py   (exit 0 = clean, 1 = drift)"""
import json, re, sys
from pathlib import Path

def find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").is_file() and (p / "mycelium").is_dir():
            return p
    raise SystemExit("could not locate repo root")

ROOT = find_root(Path(__file__).resolve().parent)
idx = json.loads((ROOT / "agent-index.json").read_text())
fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)

_filecache = {}
def lines(path):
    if path not in _filecache:
        f = ROOT / path
        _filecache[path] = f.read_text().splitlines() if f.exists() else None
    return _filecache[path]

def parse_span(spec):
    m = re.match(r"(.+):(\d+)-(\d+)$", spec)
    return (m.group(1), int(m.group(2)), int(m.group(3))) if m else (None, 0, 0)

# 1. version
pv = re.search(r'(?m)^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text())
check(pv and pv.group(1) == idx.get("version"),
      "version mismatch: index=%s pyproject=%s" % (idx.get("version"), pv and pv.group(1)))

# 2. docs + important_paths exist
for d in idx["docs"]:
    check((ROOT / d["path"]).exists(), "missing doc: %s" % d["path"])
for ip in idx["important_paths"]:
    check((ROOT / ip["path"]).exists(), "missing important_path: %s" % ip["path"])

# 3. MCP tools resolve to a decorated def
for t in idx["mcp_tools"]:
    path, s, e = parse_span(t["path"])
    ls = lines(path)
    if not ls:
        check(False, "tool %s: file missing %s" % (t["name"], path)); continue
    check(1 <= s <= e <= len(ls), "tool %s: span out of bounds %s" % (t["name"], t["path"]))
    window = "\n".join(ls[max(0, s - 2):s + 1])
    check(re.search(r"\bdef %s\b" % re.escape(t["name"]), window),
          "tool %s: no `def %s` at %s" % (t["name"], t["name"], t["path"]))
    deco = "\n".join(ls[max(0, s - 6):s])
    check(".tool(" in deco, "tool %s: no @mcp.tool() decorator above %s" % (t["name"], t["path"]))

# 4. component spans exist, in-bounds, start a def/class
for c in idx["components"]:
    check(len(c["symbols"]) == len(c["paths"]),
          "component %s: symbols/paths length mismatch" % c["id"])
    for spec in c["paths"]:
        path, s, e = parse_span(spec)
        ls = lines(path)
        if not ls:
            check(False, "component %s: file missing %s" % (c["id"], path)); continue
        check(1 <= s <= e <= len(ls), "component %s: span out of bounds %s" % (c["id"], spec))
        if 1 <= s <= len(ls):
            head = ls[s - 1].lstrip()
            check(head.startswith(("def ", "async def ", "class ")),
                  "component %s: %s does not start a def/class (got: %s)" % (c["id"], spec, head[:40]))

# 5. referential integrity
comp_ids = {c["id"] for c in idx["components"]}
for c in idx["components"]:
    for dep in c["depends_on"]:
        check(dep in comp_ids, "component %s: depends_on unknown %s" % (c["id"], dep))
for con in idx["concepts"]:
    for cc in con["components"]:
        check(cc in comp_ids, "concept %s: references unknown component %s" % (con["id"], cc))
for t in idx["mcp_tools"]:
    check(t["implemented_by"] in comp_ids,
          "tool %s: implemented_by unknown %s" % (t["name"], t["implemented_by"]))

if fails:
    print("FAIL: agent-index drifted from the code (%d issue(s)):" % len(fails))
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("OK: agent-index is consistent with the code "
      "(%d tools, %d components, %d concepts verified)"
      % (len(idx["mcp_tools"]), len(idx["components"]), len(idx["concepts"])))
