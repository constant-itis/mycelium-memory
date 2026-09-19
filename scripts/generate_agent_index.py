#!/usr/bin/env python3
"""Layer B: hand-authored overlay on top of agent-graph.json.
Mechanical parts (paths, line spans, tool list, docs, version) come from the
graph + pyproject; the semantic parts (component names, membership, summaries,
concepts) are authored here. Every named member is resolved to a real symbol;
unresolved names abort the build so the overlay can never point at missing code.
Run: python3 scripts/generate_agent_index.py"""
import json, sys, re
from pathlib import Path

def find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").is_file() and (p / "mycelium").is_dir():
            return p
    raise SystemExit("could not locate repo root")

ROOT = find_root(Path(__file__).resolve().parent)
g = json.loads((ROOT / "agent-graph.json").read_text())
by_name = {}
for s in g["symbols"]:
    by_name.setdefault(s["name"], []).append(s)
docs = g["docs"]
tools = {s["name"]: s for s in g["symbols"] if s.get("mcp_tool")}
m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text())
VERSION = m.group(1) if m else "0.0.0"
errors = []

def resolve(names, prefer_module=None):
    ids, spans = [], []
    for n in names:
        cands = by_name.get(n, [])
        if not cands:
            errors.append("unresolved member: %s" % n); continue
        pick = cands[0]
        if prefer_module:
            pick = next((c for c in cands if c["module"] == prefer_module), pick)
        elif len(cands) > 1:
            errors.append("ambiguous member %s (%d)" % (n, len(cands)))
        ids.append(pick["id"])
        spans.append("%s:%d-%d" % (pick["path"], pick["line_start"], pick["line_end"]))
    return ids, spans

COMPONENTS = [
  {"id":"comp.substrate","label":"Substrate engine","module":"mycelium.server",
   "summary":"Storage, config, FTS and formatting that every tool composes.",
   "members":["get_db","_cfg","_now","_format_memory","_fts_search"],"depends_on":[]},
  {"id":"comp.config","label":"Config","module":"mycelium.config",
   "summary":"TOML + env config loading, search paths, defaults.",
   "members":["load","set_config","to_dict"],"depends_on":[]},
  {"id":"comp.semantic","label":"Semantic / embeddings","module":"mycelium.embeddings",
   "summary":"Embedding client and vector search; embed-on-save, semantic recall.",
   "members":["embed_query","embed_document","cosine_sims","_prefixes","_normalize","_mean",
              "to_blob","from_blob","_post","_semantic_sims","_embed_memory","_chunks",
              "_log_embed_failure","_log_stale_vectors"],"depends_on":["comp.substrate"]},
  {"id":"comp.graph_dynamics","label":"Graph dynamics","module":"mycelium.server",
   "summary":"Decay, co-access strengthening, neighbor walk: the neural mechanics.",
   "members":["_apply_decay","_decay_strength","_touch_memory","_get_neighbors",
              "_strengthen_connection","_track_session_access"],"depends_on":["comp.substrate"]},
  {"id":"comp.write_path","label":"Write path","module":"mycelium.server",
   "summary":"save / resolve / pin: dedup, embed, connect, protect.",
   "members":["_check_duplicates"],
   "depends_on":["comp.substrate","comp.semantic","comp.graph_dynamics"]},
  {"id":"comp.read_path","label":"Read path","module":"mycelium.server",
   "summary":"recall / context / connections: FTS+semantic fusion, propagation.",
   "members":[],"depends_on":["comp.substrate","comp.semantic","comp.graph_dynamics"]},
  {"id":"comp.episodic","label":"Episodic / recent","module":"mycelium.server",
   "summary":"recent(): time-ordered digest of what was just worked on.",
   "members":["_recent_rows","_recent_summary_line","_humanize_age","_column_exists"],
   "depends_on":["comp.substrate"]},
  {"id":"comp.maintenance","label":"Maintenance","module":"mycelium.maintain",
   "summary":"consolidate/forget/review/maintain: snapshot, cold-mark, protect, rescue.",
   "members":["run_maintenance","_plan","_execute","_baseline","_is_protected","_protection_reason"],
   "depends_on":["comp.substrate","comp.graph_dynamics"]},
  {"id":"comp.discover","label":"Discover","module":"mycelium.server",
   "summary":"Find hidden connections and rescue orphan memories.",
   "members":[],"depends_on":["comp.substrate","comp.graph_dynamics"]},
  {"id":"comp.foundry","label":"Foundry (behavioral memory)","module":"mycelium.foundry",
   "summary":"Append-only decision log; queryable for pattern analysis. Separable.",
   "members":["publish","drain_all","drain_file","query","init_schema"],"depends_on":["comp.config"]},
  {"id":"comp.dashboard","label":"Dashboard","module":"mycelium.dashboard",
   "summary":"Read-only web viewer of the memory graph. Stdlib http.server.",
   "members":[],"depends_on":["comp.substrate"]},
  {"id":"comp.cli","label":"CLI","module":"mycelium.cli",
   "summary":"Entrypoint: serve/init/config/dash/backfill-vectors/maintain/foundry.",
   "members":["main"],"depends_on":["comp.config"]},
  {"id":"comp.evaluate","label":"Evaluate","module":"mycelium.evaluate",
   "summary":"Recall benchmark harness (paraphrase recall@k).",
   "members":["run_eval"],"depends_on":["comp.substrate"]},
]
TOOL_COMPONENT = {
  "save":"comp.write_path","resolve":"comp.write_path","pin":"comp.write_path",
  "recall":"comp.read_path","context":"comp.read_path","connections":"comp.read_path",
  "recent":"comp.episodic","consolidate":"comp.maintenance","forget":"comp.maintenance",
  "review":"comp.maintenance","maintain":"comp.maintenance","discover":"comp.discover"}
CONCEPTS = [
  {"id":"memory","label":"Memory","summary":"A short dense unit of knowledge; one idea.","components":["comp.write_path","comp.read_path"],"docs":["docs/concepts.md"]},
  {"id":"recall","label":"Recall","summary":"Query + one-hop propagation through connections.","components":["comp.read_path","comp.semantic"],"docs":["docs/concepts.md"]},
  {"id":"connections","label":"Connections","summary":"Co-access edges; strengthen with use.","components":["comp.graph_dynamics"],"docs":["docs/concepts.md"]},
  {"id":"decay","label":"Decay","summary":"Unused paths weaken over time.","components":["comp.graph_dynamics"],"docs":["docs/concepts.md"]},
  {"id":"tiers","label":"Tiers (hot/cold)","summary":"Access tier; cold = consolidated summary.","components":["comp.maintenance"],"docs":["docs/concepts.md"]},
  {"id":"pinning","label":"Pinning","summary":"Protect confirmed facts from decay.","components":["comp.write_path","comp.maintenance"],"docs":["docs/concepts.md"]},
  {"id":"resolvers","label":"Resolvers","summary":"Disambiguation memory for an ambiguous term.","components":["comp.write_path"],"docs":["docs/concepts.md"]},
  {"id":"semantic-recall","label":"Semantic recall","summary":"Optional embedding match by meaning.","components":["comp.semantic"],"docs":["docs/concepts.md","docs/benchmarks.md"]},
  {"id":"consolidation","label":"Consolidation","summary":"Merge hot cluster into a cold summary.","components":["comp.maintenance"],"docs":["docs/concepts.md"]},
  {"id":"recency","label":"Recency / episodic","summary":"What just happened; context() is blind to it.","components":["comp.episodic"],"docs":["docs/recency-precision.md"]},
  {"id":"foundry","label":"Foundry","summary":"Behavioral append-only decision log.","components":["comp.foundry"],"docs":["docs/concepts.md"]},
]

sym = {s["id"]: s for s in g["symbols"]}
comp_out = []
for c in COMPONENTS:
    ids, spans = resolve(c["members"], prefer_module=c["module"])
    comp_out.append({"id":c["id"],"label":c["label"],"summary":c["summary"],
                     "primary_module":c["module"],"depends_on":c["depends_on"],
                     "symbols":ids,"paths":spans})
tool_out = [{"name":n,"implemented_by":TOOL_COMPONENT.get(n,"?"),
             "path":"%s:%d-%d"%(s["path"],s["line_start"],s["line_end"]),
             "summary":(s.get("doc") or "").replace("—","-")} for n,s in tools.items()]

index = {
  "schema":"mycelium.agent-index/v1","project":"mycelium-memory","version":VERSION,
  "purpose":"Persistent memory for LLM CLIs that behaves like a brain, not a database.",
  "generated_from":"agent-graph.json (AST extraction)",
  "entrypoints":{"cli":"mycelium.cli:main","server":"mycelium/server.py (FastMCP `mcp`, serve())"},
  "read_order":["AGENTS.md","agent-index.json","docs/concepts.md","docs/everyday-use.md"],
  "concepts":CONCEPTS,"components":comp_out,
  "mcp_tools":sorted(tool_out,key=lambda t:t["name"]),
  "docs":[{"path":d["path"],"headings":[h["text"] for h in d["headings"] if h["level"]<=2][:8]} for d in docs],
  "important_paths":[
    {"path":"mycelium/server.py","role":"MCP server + 12 tools + engine (large module)"},
    {"path":"mycelium/embeddings.py","role":"embedding client + vector search"},
    {"path":"mycelium/config.py","role":"TOML+env config, search paths"},
    {"path":"mycelium/maintain.py","role":"consolidation/protection/orphan-rescue plan+execute"},
    {"path":"mycelium/foundry/","role":"behavioral memory subsystem (separable)"},
    {"path":"docs/","role":"canonical prose the map points into"}],
  "build_and_test":{"install":"pip install -e .","test":"pytest -q","python":">=3.11"},
  "terminology":{"hot":"recently/frequently accessed memory tier",
    "cold":"consolidated summary tier, decay-resistant",
    "substrate":"shared db/config/FTS/format helpers under every tool",
    "propagation":"one-hop spread through connections during recall"},
}
if errors:
    print("ABORT - overlay references code that does not exist:", file=sys.stderr)
    for e in errors:
        print("  " + e, file=sys.stderr)
    sys.exit(1)
(ROOT / "agent-index.json").write_text(json.dumps(index, indent=2) + "\n")
print("wrote agent-index.json: %d components, %d concepts, %d tools, %d symbols resolved"
      % (len(comp_out), len(CONCEPTS), len(tool_out), sum(len(c["symbols"]) for c in comp_out)))
