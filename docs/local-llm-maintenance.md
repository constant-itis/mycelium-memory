# Local-LLM-assisted maintenance

Memory maintenance is mostly bulk text work: summarizing dense clusters, drafting cold
summaries, proposing which stale entries to fold away. That's a great fit for a **local
LLM** — you keep memory content on your own hardware and spend zero paid API quota on
housekeeping.

Mycelium's built-in `maintain` pass is heuristic (decay + a protected-memory guard, dry-run
by default). This page adds an **optional** layer: use a local model to *draft* the
summaries and an archive/keep proposal for the clusters `review` surfaces — which a human
then verifies. The model drafts; you (or the forget-safety guard) dispose.

> **The one rule:** never wire a model's output straight into deletion. A local model
> *proposes*; a human or a guard *disposes*. See [Why local models over-archive](#why-local-models-over-archive).

## What you need

Any OpenAI-compatible chat endpoint — no cloud account required:

| Runtime | Endpoint | Notes |
|---|---|---|
| [llama.cpp](https://github.com/ggml-org/llama.cpp) `llama-server` | `http://localhost:8080/v1/chat/completions` | lightweight, single binary |
| [Ollama](https://ollama.com) | `http://localhost:11434/v1/chat/completions` | set `LOCAL_LLM_MODEL` to the real tag, e.g. `qwen3:8b` |
| [vLLM](https://github.com/vllm-project/vllm) | `http://localhost:8000/v1/chat/completions` | fast batched serving |
| LM Studio | `http://localhost:1234/v1/chat/completions` | GUI |

A small instruct or MoE model (roughly 7B–35B) is plenty for summarize/classify work.
Point the helper at whatever you're running:

```bash
export LOCAL_LLM_URL=http://localhost:8080/v1/chat/completions
export LOCAL_LLM_MODEL=local          # Ollama: the real tag, e.g. qwen3:8b
# export LOCAL_LLM_NOTHINK=1           # only for reasoning models — see gotcha below
```

## The consolidation workflow

```bash
# 1. Find dense clusters worth folding
mycelium review

# 2. Dump the candidates for one project (id + text, one block each)
mycelium consolidate --project infra > candidates.txt

# 3. Let the local model DRAFT summaries + a conservative archive/keep split
./scripts/consolidate-with-local-llm.sh < candidates.txt

# 4. YOU verify every proposed archive against reality, then act:
#    - save the theme summaries you like as new cold memories
#    - forget() only the originals you confirmed are captured
```

The helper (`scripts/consolidate-with-local-llm.sh`) is ~40 lines of `curl` + `jq` with no
extra dependencies. It sends a **hardened system prompt** (below) and prints the model's
grouped summaries plus an `ARCHIVE:` / `KEEP:` proposal.

## The hardened prompt

The prompt is the whole game. A naive "summarize these and tell me what to delete" makes a
local model delete almost everything. The shipped prompt forces conservative behavior:

- **Default is KEEP.** An entry stays unless the model can *prove* it's dead.
- **Every `ARCHIVE` must cite evidence** — `SUPERSEDED by #ID`, `HISTORICAL-EVENT: state now in Y`, or `DEAD: <what died>`.
- **Absence-of-evidence reasons are banned** — "likely", "probably", "no mention". Not
  seeing something referenced is *not* proof it's dead; that's a KEEP.
- **Never-archive classes are named** — live config, credentials/access, standing
  conventions, index/hub entries, anything with an open TODO.

## Why local models over-archive

In testing, handing a small local model 34 real consolidation candidates with a plain prompt
produced **33 of 34 marked for deletion, keep-list empty** — it would have wiped live config
(DNS caches, access setup, standing conventions) to "tidy up." Adding the rules above cut
that to ~4 archived, each with a citation. Banning absence-of-evidence reasoning flipped the
last fabricated deletion ("this looks unused") back to KEEP.

Even hardened, a small model still **miscites IDs occasionally and floats weak supersession
guesses.** That's fine — because it never decides. Its job is to turn an opaque wall of
memories into a *reviewable proposal* where every deletion arrives with a claim you can check
in seconds. This is the same contract Mycelium's [forget safety guard](configuration.md)
enforces at the substrate: protected memories refuse deletion without an explicit override,
so an over-eager pass can't quietly remove load-bearing knowledge.

**Local model drafts. Human (or guard) disposes.**

## Reasoning-model gotcha

Some "thinking" models (Qwen3 and similar) route their answer into a separate
`reasoning_content` field and leave `content` **empty** until the reasoning finishes — so a
naive call looks like it returned nothing. Disable thinking for these summarize/classify
tasks:

```bash
export LOCAL_LLM_NOTHINK=1   # adds chat_template_kwargs.enable_thinking=false to the request
```

The exact switch is model-specific (`enable_thinking`, a `/no_think` tag, a `reasoning`
parameter…). If your endpoint returns empty content, that's the first thing to check.
