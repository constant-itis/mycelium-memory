#!/usr/bin/env python3
"""Build the ffmpeg drawtext filter chain from demo/marks.txt section timestamps."""
import sys
from pathlib import Path

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

CAPTIONS = {
    "intro": "A fresh Claude session, connected to mycelium over MCP",
    "q1":    "It recalls the answer - buried mid-paragraph in a long saved log",
    "q2":    "Stored exceptions outrank stale model assumptions",
    "q3":    "Tell it something once - saved for every future session",
    "outro": "github.com/constant-itis/mycelium-memory",
}

IDLE_LIMIT = 3.0  # must match agg --idle-time-limit in render.sh


def compressed_timeline(cast_path):
    """Map real cast time -> agg's idle-compressed time.

    agg caps any gap between consecutive events at IDLE_LIMIT seconds; replay
    that here so caption timestamps land on the compressed video."""
    import json
    lines = Path(cast_path).read_text().splitlines()
    header = json.loads(lines[0])
    times = [json.loads(ln)[0] for ln in lines[1:]]
    return header["timestamp"], times


def to_compressed(rel_t, times):
    out = prev = 0.0
    for t in times:
        if t >= rel_t:
            return out + min(rel_t - prev, IDLE_LIMIT)
        out += min(t - prev, IDLE_LIMIT)
        prev = t
    return out + min(rel_t - prev, IDLE_LIMIT)


def main():
    marks = {}
    order = []
    for line in Path("demo/marks.txt").read_text().splitlines():
        ts, label = line.split()
        marks[label] = float(ts)
        order.append(label)
    rec_start, times = compressed_timeline("demo/take.cast")
    rel = {k: to_compressed(max(0.0, v - rec_start), times) for k, v in marks.items()}

    spans = []
    for i, label in enumerate(order):
        if label not in CAPTIONS:
            continue
        start = rel[label]
        end = rel[order[i + 1]] if i + 1 < len(order) else start + 3
        spans.append((CAPTIONS[label], start, end))

    parts = []
    for text, a, b in spans:
        # keep caption text free of apostrophes/colons — ffmpeg filter quoting
        # is fragile; strip rather than escape
        esc = text.replace("'", "").replace(":", "").replace("\\", "")
        parts.append(
            f"drawtext=fontfile={FONT}:text='{esc}':fontsize=24:fontcolor=white:"
            f"x=(w-text_w)/2:y=h-52:box=1:boxcolor=black@0.6:boxborderw=14:"
            f"enable='between(t,{a:.2f},{b:.2f})'"
        )
    Path("demo/captions.filter").write_text(",".join(parts) + "\n")
    print(f"{len(spans)} captions -> demo/captions.filter")

if __name__ == "__main__":
    sys.exit(main())
