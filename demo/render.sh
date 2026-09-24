#!/usr/bin/env bash
# take.cast + marks.txt -> captioned demo/mycelium-demo.{mp4,gif}
set -e
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

python3 - <<'EOF'
import json
p = "demo/take.cast"
lines = open(p).read().splitlines()
h = json.loads(lines[0]); h["width"], h["height"] = 110, 30
lines[0] = json.dumps(h)
open(p, "w").write("\n".join(lines) + "\n")
EOF

# NOTE: system ffmpeg (4.4) has drawtext built in; the static ffmpeg 7 in
# ~/.local/bin does NOT — keep /usr/bin/ffmpeg here.
agg --theme dracula --font-size 16 --idle-time-limit 3 demo/take.cast demo/raw.gif 2>/dev/null
/usr/bin/ffmpeg -y -v error -i demo/raw.gif -movflags faststart -pix_fmt yuv420p \
  -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" demo/raw.mp4
python3 demo/captions.py
/usr/bin/ffmpeg -y -v error -i demo/raw.mp4 -vf "$(cat demo/captions.filter)" \
  -movflags faststart -pix_fmt yuv420p demo/mycelium-demo.mp4
/usr/bin/ffmpeg -y -v error -i demo/mycelium-demo.mp4 \
  -vf "fps=12,scale=900:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" \
  demo/mycelium-demo.gif
rm -f demo/raw.gif demo/raw.mp4
ls -la demo/mycelium-demo.mp4 demo/mycelium-demo.gif
