#!/bin/bash
# PostToolUseFailure hook — prompt Claude to capture operational lessons.
# Fires after any tool failure. Injects a reminder to write what was learned.

STM_LOG="$HOME/.claude/short-term-memory/stm.log"

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // .tool_input.file_path // ""' | head -c 100)
ERROR=$(echo "$INPUT" | jq -r '.error // "unknown"' | head -c 200)

CONTEXT="[STM] ${TOOL_NAME} failed: ${ERROR}
Command was: ${COMMAND}
If you found a workaround, write the lesson to ~/.claude/short-term-memory/stm.json — format: {domain, keywords[], lesson, added, last_hit, hits:0}. Same domain replaces old entry. Max 6 entries — drop lowest-hits if full."

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) FAIL tool=${TOOL_NAME} cmd=$(echo "$COMMAND" | head -c 80) err=$(echo "$ERROR" | head -1 | head -c 80)" >> "$STM_LOG"

jq -n --arg ctx "$CONTEXT" '{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUseFailure",
    "additionalContext": $ctx
  }
}'

exit 0
