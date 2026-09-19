#!/usr/bin/env python3
"""Layer A: deterministic structural graph of the mycelium package.
Walks the AST to extract modules, symbols, imports, intra-repo call edges,
MCP tools, and docs. No LLM, no summaries. Writes <repo>/agent-graph.json.
Run: python3 scripts/build_agent_graph.py"""
import ast, json, re, sys
from pathlib import Path

def find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").is_file() and (p / "mycelium").is_dir():
            return p
    raise SystemExit("could not locate repo root (pyproject.toml + mycelium/)")

ROOT = find_root(Path(__file__).resolve().parent)
PKG = "mycelium"
pkg_dir = ROOT / PKG

def mod_name(p: Path) -> str:
    parts = list(p.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)

symbols, by_bare, import_edges, call_edges, mcp_tools, modules = {}, {}, [], [], [], []
pyfiles = sorted(pkg_dir.rglob("*.py"))
known_mods = {mod_name(p) for p in pyfiles}

def deco_names(node):
    out = []
    for d in getattr(node, "decorator_list", []):
        t = d.func if isinstance(d, ast.Call) else d
        if isinstance(t, ast.Attribute):
            out.append(f"{getattr(t.value,'id','?')}.{t.attr}")
        elif isinstance(t, ast.Name):
            out.append(t.id)
    return out

def first_doc_line(node):
    ds = ast.get_docstring(node)
    return ds.strip().splitlines()[0].strip() if ds else None

trees = {}
for p in pyfiles:
    m = mod_name(p); src = p.read_text(); tree = ast.parse(src); trees[m] = (p, tree)
    rel = str(p.relative_to(ROOT))
    modules.append({"id": f"mod:{m}", "module": m, "path": rel,
                    "loc": src.count("\n") + 1, "doc": first_doc_line(tree)})

    def add_fn(node, cls=None):
        qual = f"{cls+'.' if cls else ''}{node.name}"
        sid = f"fn:{m}:{qual}"
        decos = deco_names(node)
        symbols[sid] = {"id": sid, "kind": "method" if cls else "function", "module": m,
                        "name": node.name, "qualname": qual, "path": rel,
                        "line_start": node.lineno, "line_end": node.end_lineno,
                        "doc": first_doc_line(node), "decorators": decos,
                        "mcp_tool": any(d.endswith("tool") for d in decos)}
        by_bare.setdefault(node.name, []).append(sid)
        if symbols[sid]["mcp_tool"]:
            mcp_tools.append(sid)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add_fn(node)
        elif isinstance(node, ast.ClassDef):
            symbols[f"cls:{m}:{node.name}"] = {"id": f"cls:{m}:{node.name}", "kind": "class",
                "module": m, "name": node.name, "qualname": node.name, "path": rel,
                "line_start": node.lineno, "line_end": node.end_lineno,
                "doc": first_doc_line(node), "decorators": deco_names(node), "mcp_tool": False}
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add_fn(sub, cls=node.name)

for m, (p, tree) in trees.items():
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = ".".join(m.split(".")[:-1]) if "." in m else PKG
                base = (parent + ("." + base if base else "")).lstrip(".")
                if not base.startswith(PKG):
                    base = PKG + ("." + base if base else "")
            if base.startswith(PKG):
                for a in node.names:
                    cand = f"{base}.{a.name}"
                    targets.append(cand if cand in known_mods else base)
        elif isinstance(node, ast.Import):
            targets += [a.name for a in node.names if a.name.startswith(PKG)]
        for t in targets:
            if t in known_mods and t != m:
                import_edges.append({"from": f"mod:{m}", "to": f"mod:{t}"})
seen = set(); import_edges = [e for e in import_edges
    if (e["from"], e["to"]) not in seen and not seen.add((e["from"], e["to"]))]

FUNC = {sid for sid, s in symbols.items() if s["kind"] in ("function", "method")}
unique_name = {n: ids[0] for n, ids in by_bare.items() if len(ids) == 1}
def enclosing(m, lineno):
    best = None
    for sid, s in symbols.items():
        if s["module"] == m and s["kind"] in ("function", "method") \
           and s["line_start"] <= lineno <= s["line_end"]:
            if best is None or s["line_start"] > symbols[best]["line_start"]:
                best = sid
    return best
cseen = set()
for m, (p, tree) in trees.items():
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            tgt = unique_name.get(name) if name else None
            if not tgt:
                continue
            src = enclosing(m, node.lineno)
            if not src or src == tgt or (src, tgt) in cseen:
                continue
            cseen.add((src, tgt)); call_edges.append({"from": src, "to": tgt})

docs = []
for md in sorted((ROOT / "docs").rglob("*.md")):
    text = md.read_text().splitlines()
    heads = [{"level": len(mm.group(1)), "text": mm.group(2).strip(), "line": i + 1}
             for i, ln in enumerate(text) if (mm := re.match(r"^(#{1,3})\s+(.*)", ln))]
    docs.append({"path": str(md.relative_to(ROOT)), "loc": len(text), "headings": heads})

graph = {"schema": "mycelium.agent-graph/v1", "root": PKG, "modules": modules,
         "symbols": list(symbols.values()), "import_edges": import_edges,
         "call_edges": call_edges, "mcp_tools": mcp_tools, "docs": docs}
(ROOT / "agent-graph.json").write_text(json.dumps(graph, indent=2) + "\n")
print("wrote agent-graph.json: %d modules, %d symbols, %d import + %d call edges, %d tools, %d docs"
      % (len(modules), len(symbols), len(import_edges), len(call_edges), len(mcp_tools), len(docs)))
