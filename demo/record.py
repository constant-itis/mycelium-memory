#!/usr/bin/env python3
"""Record a scripted Claude+mycelium session.

Spawns asciinema (attached to a fresh tmux session running Claude Code) in a
110x30 pty, types the user prompts via tmux send-keys, and stamps section
timestamps for the caption overlay pass.
"""
import os
import subprocess
import time
from pathlib import Path

import pexpect

DEMO = Path(os.environ.get("DEMO_WORKDIR", Path.home() / "mycelium-demo"))
OUT = Path(__file__).resolve().parent
CAST = OUT / "take.cast"
MARKS = OUT / "marks.txt"
SESSION = "mycdemo"

CLAUDE = (
    'claude --mcp-config mcp.json --strict-mcp-config '
    '--allowedTools "mcp__mycelium__recall,mcp__mycelium__context,mcp__mycelium__save" '
    '--model sonnet'
)

marks = []
def mark(label):
    marks.append(f"{time.time():.3f} {label}")

def tmux(*args):
    subprocess.run(["tmux", *args], check=False)

def type_prompt(text, wait):
    for ch in text:
        tmux("send-keys", "-t", SESSION, "-l", "--", ch)
        time.sleep(0.045)
    time.sleep(0.6)
    tmux("send-keys", "-t", SESSION, "Enter")
    time.sleep(wait)

tmux("kill-session", "-t", SESSION)
subprocess.run(
    ["tmux", "new-session", "-d", "-s", SESSION, "-x", "110", "-y", "30",
     f"cd {DEMO} && {CLAUDE}"],
    check=True,
)
tmux("set", "-t", SESSION, "status", "off")
tmux("set", "-g", "focus-events", "on")
time.sleep(8)  # banner + MCP connect before recording starts

rec = pexpect.spawn(
    "asciinema", ["rec", "--overwrite", "-q", "-c", f"tmux attach -t {SESSION}", str(CAST)],
    dimensions=(30, 110), timeout=300,
)
time.sleep(2)
mark("t0")
mark("intro")
time.sleep(3)

mark("q1")
type_prompt("which port does the wiki listen on now?", 20)

mark("q2")
type_prompt("should we upgrade the legacy report generator to Python 3?", 20)

mark("q3")
type_prompt("remember that the switch firmware upgrade is scheduled for the next maintenance window", 18)

mark("outro")
time.sleep(4)
tmux("kill-session", "-t", SESSION)
rec.expect(pexpect.EOF, timeout=60)

MARKS.write_text("\n".join(marks) + "\n")
print(f"cast: {CAST} ({CAST.stat().st_size} bytes)")
print(f"marks: {len(marks)}")
