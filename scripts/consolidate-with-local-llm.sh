#!/usr/bin/env bash
# consolidate-with-local-llm.sh — draft memory-consolidation summaries with a LOCAL LLM.
#
# Mycelium's built-in `maintain` pass is heuristic (decay + protected guard). This helper
# adds an OPTIONAL, human-in-the-loop layer: it asks a *local* model to
#   (A) group a batch of consolidation candidates into themes + dense cold summaries, and
#   (B) PROPOSE which originals are safe to archive — which YOU verify before `forget`.
#
# The model DRAFTS; a human (or the forget-safety guard) DISPOSES. Never pipe this output
# straight into deletion — small local models over-archive. See docs/local-llm-maintenance.md.
#
# Endpoint: any OpenAI-compatible /v1/chat/completions server (llama.cpp, vLLM, Ollama,
# LM Studio). Configure via env:
#   LOCAL_LLM_URL      default http://localhost:8080/v1/chat/completions
#   LOCAL_LLM_MODEL    default "local"  (Ollama needs the real tag, e.g. "qwen3:8b")
#   LOCAL_LLM_NOTHINK  set to 1 for reasoning models that hide output in reasoning_content
#                      unless thinking is disabled (Qwen3-style)
#
# Usage:
#   mycelium review                                    # find dense clusters
#   mycelium consolidate --project infra > cands.txt   # dump candidates (id + text)
#   ./scripts/consolidate-with-local-llm.sh < cands.txt
#
# Deps: curl, jq.
set -euo pipefail

URL="${LOCAL_LLM_URL:-http://localhost:8080/v1/chat/completions}"
MODEL="${LOCAL_LLM_MODEL:-local}"

read -r -d '' SYS <<'PROMPT' || true
You consolidate an AI agent's long-term memory. Input: memory entries as [#ID] (date) content.

Do TWO things:
(A) Group entries into themes. Per theme output THEME / MEMBERS / SUMMARY — a dense cold
    summary preserving EVERY ID, date, file path, and identifier, noting what supersedes what.
(B) Recommend an archive/keep split — CONSERVATIVELY.

ARCHIVING RULES (this is where local models overreach — do not):
- DEFAULT IS KEEP. An entry is KEEP unless you can PROVE it is dead.
- Mark ARCHIVE only if ONE holds, and cite the evidence inline:
  1. SUPERSEDED — a newer entry (cite its #ID) fully captures this one.
  2. HISTORICAL-EVENT — a one-time completed event whose durable state now lives elsewhere (say where).
  3. DEAD — describes decommissioned/removed infrastructure (name what is dead).
- NEVER archive: live config, credentials/access, standing conventions or feedback,
  index/hub entries, or anything with an unresolved TODO/blocker.
- FORBIDDEN reasons: "likely", "probably", "may be", "no mention" — any absence-of-evidence
  guess. Not seeing a thing mentioned is NOT proof it is dead; that is a KEEP.
- If you cannot cite a reason, it is KEEP. It is NORMAL for most entries to be KEEP;
  a pass that archives everything is WRONG.

OUTPUT (plain text, no preamble):
<themes as above>
ARCHIVE: one line per id -> `#ID — SUPERSEDED by #X` | `#ID — HISTORICAL-EVENT: state in Y` | `#ID — DEAD: Z`
KEEP: comma-separated `#ID (short reason)`
Every input ID must appear exactly once across ARCHIVE + KEEP.
PROMPT

CANDS="$(cat)"
[ -n "$CANDS" ] || { echo "no candidates on stdin" >&2; exit 1; }

BODY=$(jq -n --arg m "$MODEL" --arg sys "$SYS" --arg user "$CANDS" \
  '{model:$m, temperature:0.2, max_tokens:4096,
    messages:[{role:"system",content:$sys},{role:"user",content:$user}]}')

# Reasoning models often return empty content unless thinking is disabled. The exact knob
# is model-specific; enable_thinking=false covers Qwen3 and similar via chat_template_kwargs.
if [ "${LOCAL_LLM_NOTHINK:-0}" = "1" ]; then
  BODY=$(printf '%s' "$BODY" | jq '. + {chat_template_kwargs:{enable_thinking:false}}')
fi

printf '%s' "$BODY" \
  | curl -sS "$URL" -H 'Content-Type: application/json' -d @- \
  | jq -r '.choices[0].message.content // .error.message // "no response from endpoint"'
