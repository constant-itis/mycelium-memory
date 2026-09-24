# Demo recording pipeline

Everything needed to (re)record the README demo. The video is a real Claude
Code session talking to a real mycelium server over MCP against a seeded
throwaway DB; nothing is mocked.

## Pieces

- `env.sh` — demo environment: DB path, embedder endpoint, display knobs.
  Set `DEMO_EMBED_URL` / `DEMO_EMBED_MODEL` to your embeddings endpoint.
- `seed.sh` — wipes the demo DB and saves a small believable corpus, including
  `maintenance-log.txt` (a long memory with one fact buried mid-paragraph) and
  a `--contradicts-prior` exception.
- `mcp.sample.json` — MCP config pointing Claude Code at the demo server.
  Copy next to a scratch working directory, fix the paths, and add a short
  CLAUDE.md telling Claude to recall before answering.
- `record.py` — scripted take: starts Claude Code in tmux, records the
  attached client with asciinema at 110x30, types the demo prompts, and stamps
  section timestamps into `marks.txt` for the caption pass.
- `captions.py` — turns `marks.txt` + `take.cast` into an ffmpeg drawtext
  filter, mapping wall-clock marks through agg's idle-time compression so the
  captions stay aligned in the shortened video.
- `render.sh` — cast -> agg gif -> captioned mp4 + gif.
- `demo-run.sh` — alternative pure-CLI take (save/recall from the shell, no
  Claude session), same render pipeline.

## Record a new take

```bash
demo/seed.sh
python3 demo/record.py     # drives the Claude session, ~90s
demo/render.sh             # -> demo/mycelium-demo.{mp4,gif}
```

Requires: asciinema, tmux, agg, ffmpeg (with drawtext), pexpect, an
embeddings endpoint, and a Claude Code login.
