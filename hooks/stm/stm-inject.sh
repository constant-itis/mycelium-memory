#!/bin/bash
# PreToolUse hook — inject relevant short-term memory before execution.
# Reads tool input from stdin, matches command against STM domain keywords,
# returns additionalContext if a lesson matches.

STM_FILE="$HOME/.claude/short-term-memory/stm.json"
STM_LOG="$HOME/.claude/short-term-memory/stm.log"

if [ ! -f "$STM_FILE" ]; then
  exit 0
fi

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')

SEARCH_TEXT=$(echo "$TOOL_NAME $COMMAND $FILE_PATH" | tr '[:upper:]' '[:lower:]')

MATCHED_LESSONS=""
SLOT_COUNT=$(jq '.entries | length' "$STM_FILE")

for i in $(seq 0 $(( SLOT_COUNT - 1 ))); do
  KEYWORDS=$(jq -r ".entries[$i].keywords[]" "$STM_FILE" 2>/dev/null)

  while IFS= read -r kw; do
    [ -z "$kw" ] && continue
    if echo "$SEARCH_TEXT" | grep -qiF -- "$kw"; then
      LESSON=$(jq -r ".entries[$i].lesson" "$STM_FILE")
      DOMAIN=$(jq -r ".entries[$i].domain" "$STM_FILE")

      if [ -n "$MATCHED_LESSONS" ]; then
        MATCHED_LESSONS="$MATCHED_LESSONS\n"
      fi
      MATCHED_LESSONS="${MATCHED_LESSONS}[STM/${DOMAIN}] ${LESSON}"

      NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
      HITS=$(jq -r ".entries[$i].hits" "$STM_FILE")
      jq ".entries[$i].last_hit = \"$NOW\" | .entries[$i].hits = $(( HITS + 1 ))" "$STM_FILE" > "${STM_FILE}.tmp" && mv "${STM_FILE}.tmp" "$STM_FILE"

      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) INJECT domain=${DOMAIN} hits=$(( HITS + 1 )) cmd=$(echo "$COMMAND" | head -c 80)" >> "$STM_LOG"

      break
    fi
  done <<< "$KEYWORDS"
done

if [ -n "$MATCHED_LESSONS" ]; then
  CONTEXT=$(printf '%b' "$MATCHED_LESSONS")
  jq -n --arg ctx "$CONTEXT" '{
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "additionalContext": $ctx
    }
  }'
fi

exit 0
