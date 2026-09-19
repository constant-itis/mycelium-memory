#!/usr/bin/env python3
"""Projection: render llms.txt from agent-index.json (single source of truth).
llms.txt is the discovery convention (llmstxt.org); it is generated, never
hand-edited, so it cannot drift from the index.
Run: python3 scripts/build_llms_txt.py"""
import json
from pathlib import Path

def find_root(start):
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").is_file() and (p / "mycelium").is_dir():
            return p
    raise SystemExit("could not locate repo root")

ROOT = find_root(Path(__file__).resolve().parent)
idx = json.loads((ROOT / "agent-index.json").read_text())

def clean(s):
    return (s or "").replace("—", "-").replace("–", "-")

out = []
out.append("# mycelium")
out.append("")
out.append("> %s" % idx["purpose"])
out.append("")
out.append("Machine-readable map for agents. Read `agent-index.json` first to jump")
out.append("straight to a file span instead of crawling; see `AGENTS.md` for the protocol.")
out.append("")
out.append("## Bootstrap")
out.append("- [AGENTS.md](AGENTS.md): how agents should work in this repo; read first.")
out.append("- [agent-index.json](agent-index.json): concepts, components and tools mapped to file paths and line spans.")
out.append("- [agent-graph.json](agent-graph.json): full structural graph (every symbol, import and call edge).")
out.append("")
out.append("## Docs")
for d in idx["docs"]:
    head = d["headings"][0] if d["headings"] else ""
    out.append("- [%s](%s): %s" % (Path(d["path"]).name, d["path"], clean(head)))
out.append("")
out.append("## MCP tools")
for t in idx["mcp_tools"]:
    out.append("- `%s` (%s): %s" % (t["name"], t["path"], clean(t["summary"])))
out.append("")
out.append("## Components")
for c in idx["components"]:
    out.append("- `%s`: %s" % (c["id"], clean(c["summary"])))
out.append("")

(ROOT / "llms.txt").write_text("\n".join(out) + "\n")
print("wrote llms.txt (%d docs, %d tools, %d components)"
      % (len(idx["docs"]), len(idx["mcp_tools"]), len(idx["components"])))
