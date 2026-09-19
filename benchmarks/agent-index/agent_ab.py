#!/usr/bin/env python3
"""Tier 2: agentic A/B of the agent-index against a local model.
Two arms answer the same code-navigation tasks with the same tools (grep,
read_lines); the INDEX arm also gets agent-index.json preloaded. Measures real
tokens (endpoint `usage`), steps, tool calls, correctness. JSON-action loop with
thinking disabled.

Needs any OpenAI-compatible chat endpoint. Configure with env:
  MYCELIUM_BENCH_ENDPOINT   default http://localhost:8080/v1/chat/completions
  MYCELIUM_BENCH_MODEL      default "local"
Run: python3 benchmarks/agent-index/agent_ab.py"""
import json, os, subprocess, urllib.request
from pathlib import Path

def find_root(start):
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").is_file() and (p / "mycelium").is_dir():
            return p
    raise SystemExit("could not locate repo root")

HERE = Path(__file__).resolve().parent
ROOT = find_root(HERE)
ENDPOINT = os.environ.get("MYCELIUM_BENCH_ENDPOINT", "http://localhost:8080/v1/chat/completions")
MODEL = os.environ.get("MYCELIUM_BENCH_MODEL", "local")
MAX_STEPS = 8
LOG = open(HERE / "agentic_run.log", "w")

g = json.loads((ROOT / "agent-graph.json").read_text())
idx = json.loads((ROOT / "agent-index.json").read_text())
idx_json = json.dumps(idx)
sym = {s["id"]: s for s in g["symbols"]}
tool_sym = {s["name"]: s for s in g["symbols"] if s.get("mcp_tool")}
comp = {c["id"]: c for c in idx["components"]}

def log(*a):
    print(*a, file=LOG, flush=True)

def t_grep(pattern):
    try:
        out = subprocess.run(["grep", "-rn", "--include=*.py", "--", pattern, "mycelium"],
                             cwd=ROOT, capture_output=True, text=True, timeout=15).stdout
    except Exception as e:
        return "grep error: %s" % e
    ls = out.splitlines()[:25]
    return "\n".join(ls) if ls else "(no matches)"

def t_read_lines(path, start, end):
    p = ROOT / path
    if not p.exists():
        return "no such file: %s" % path
    ls = p.read_text().splitlines()
    start = max(1, int(start)); end = min(len(ls), int(end))
    return "\n".join("%d: %s" % (start + i, x) for i, x in enumerate(ls[start - 1:end]))

def call(messages, max_tokens=320):
    body = json.dumps({"model": MODEL, "messages": messages, "temperature": 0,
                       "max_tokens": max_tokens,
                       "chat_template_kwargs": {"enable_thinking": False}}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"]["content"], d.get("usage", {})

def extract_json(text):
    i = text.find("{")
    if i < 0:
        return None
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{": depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[i:j + 1])
                except Exception:
                    return None
    return None

SYS_CRAWL = (
 "You are a code-navigation agent in a Python repo (package `mycelium`).\n"
 "Answer the QUESTION by finding the exact source location or exact set.\n"
 "Each turn respond with ONE JSON object and NOTHING else. Actions:\n"
 '  {"action":"grep","pattern":"..."}\n'
 '  {"action":"read_lines","path":"mycelium/x.py","start":N,"end":M}\n'
 '  {"action":"answer","path":"mycelium/x.py","line_start":N,"line_end":M}\n'
 '  {"action":"answer","value":["a","b"]}\n'
 "Be efficient; stop and answer as soon as you know. Files live under mycelium/.\n")
SYS_INDEX = SYS_CRAWL + ("\nYou ALSO have an AGENT INDEX mapping tools/concepts/components"
 " to file paths and line spans. Consult it FIRST and jump straight to the answer"
 " instead of grepping. AGENT INDEX (JSON):\n" + idx_json + "\n")

def run_agent(task, arm):
    messages = [{"role": "system", "content": SYS_INDEX if arm == "index" else SYS_CRAWL},
                {"role": "user", "content": "QUESTION: " + task["q"]}]
    total_tok = comp_tok = steps = 0
    calls = {"grep": 0, "read_lines": 0}
    answer = None
    for _ in range(MAX_STEPS):
        steps += 1
        content, usage = call(messages)
        total_tok += usage.get("total_tokens", 0)
        comp_tok += usage.get("completion_tokens", 0)
        act = extract_json(content)
        log("[%s/%s] step%d raw=%s" % (arm, task["id"], steps, content[:160].replace("\n", " ")))
        if not act or "action" not in act:
            messages += [{"role": "assistant", "content": content},
                         {"role": "user", "content": "Respond with ONE JSON action object only."}]
            continue
        a = act["action"]
        if a == "answer":
            answer = act; break
        elif a == "grep":
            obs = t_grep(act.get("pattern", "")); calls["grep"] += 1
        elif a == "read_lines":
            obs = t_read_lines(act.get("path", ""), act.get("start", 1), act.get("end", 1)); calls["read_lines"] += 1
        else:
            obs = "unknown action"
        messages += [{"role": "assistant", "content": json.dumps(act)},
                     {"role": "user", "content": "OBSERVATION:\n" + obs}]
    return {"answer": answer, "total_tokens": total_tok, "completion_tokens": comp_tok,
            "steps": steps, "tool_calls": calls}

def overlaps(a0, a1, b0, b1):
    return a0 <= b1 and b0 <= a1
def grade(task, ans):
    if not ans:
        return False
    if task["kind"] == "locate":
        p = (ans.get("path") or "").replace("./", "")
        if not p.endswith(task["gt_path"]) or ans.get("line_start") is None:
            return False
        ls = int(ans["line_start"]); le = int(ans.get("line_end") or ls)
        return any(overlaps(ls, le, s, e) for (s, e) in task["gt_spans"])
    if task["kind"] == "set":
        v = ans.get("value")
        return isinstance(v, list) and set(x.strip().lower() for x in v) == set(x.lower() for x in task["gt_set"])
    return False

def tool_span(n):
    s = tool_sym[n]; return ("mycelium/server.py", [(s["line_start"], s["line_end"])])
tasks = []
for n in ["recall", "save", "discover", "connections"]:
    p, spans = tool_span(n)
    tasks.append({"id": "loc_" + n, "kind": "locate",
                  "q": "Where is the `%s` MCP tool implemented? Give path and line range." % n,
                  "gt_path": p, "gt_spans": spans})
gd = comp["comp.graph_dynamics"]
tasks.append({"id": "concept_decay", "kind": "locate",
              "q": "Where is memory `decay` implemented? Give path and line range.",
              "gt_path": "mycelium/server.py",
              "gt_spans": [(sym[s]["line_start"], sym[s]["line_end"]) for s in gd["symbols"]]})
tasks.append({"id": "surface_tools", "kind": "set",
              "q": "List the names of all MCP tools mycelium exposes.",
              "gt_set": sorted(tool_sym.keys())})

rows = []
for task in tasks:
    for arm in ("crawl", "index"):
        r = run_agent(task, arm)
        ok = grade(task, r["answer"])
        rows.append({"task": task["id"], "arm": arm, "correct": ok, **r})
        print("%-16s %-6s correct=%-5s tok=%-6d steps=%d" % (task["id"], arm, ok, r["total_tokens"], r["steps"]))

def agg(arm):
    rs = [r for r in rows if r["arm"] == arm]; n = len(rs)
    return {"correct": sum(r["correct"] for r in rs), "n": n,
            "tokens_mean": round(sum(r["total_tokens"] for r in rs) / n),
            "steps_mean": round(sum(r["steps"] for r in rs) / n, 1),
            "grep": sum(r["tool_calls"]["grep"] for r in rs),
            "read": sum(r["tool_calls"]["read_lines"] for r in rs)}
summary = {"endpoint": ENDPOINT, "model": MODEL, "crawl": agg("crawl"), "index": agg("index"), "rows": rows}
(HERE / "agentic_results.json").write_text(json.dumps(summary, indent=2) + "\n")
c, ix = summary["crawl"], summary["index"]
print("\nCRAWL: %d/%d correct | %d tok | %.1f steps | grep %d read %d" %
      (c["correct"], c["n"], c["tokens_mean"], c["steps_mean"], c["grep"], c["read"]))
print("INDEX: %d/%d correct | %d tok | %.1f steps | grep %d read %d" %
      (ix["correct"], ix["n"], ix["tokens_mean"], ix["steps_mean"], ix["grep"], ix["read"]))
LOG.close()
