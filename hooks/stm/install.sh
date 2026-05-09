#!/bin/bash
# STM installer — idempotent. Safe to re-run.
# Symlinks hooks into ~/.claude/hooks/, initializes stm.json, patches settings.json.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
HOOKS_DIR="$CLAUDE_DIR/hooks"
STM_DIR="$CLAUDE_DIR/short-term-memory"
SETTINGS="$CLAUDE_DIR/settings.json"

command -v jq >/dev/null 2>&1 || { echo "ERROR: jq is required (apt install jq / brew install jq)"; exit 1; }

mkdir -p "$HOOKS_DIR" "$STM_DIR"

for hook in stm-inject.sh stm-learn.sh; do
  src="$SCRIPT_DIR/$hook"
  dst="$HOOKS_DIR/$hook"
  chmod +x "$src"
  if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
    echo "ok     $dst (already linked)"
  else
    [ -e "$dst" ] && mv "$dst" "$dst.bak.$(date +%s)" && echo "backup $dst -> $dst.bak.*"
    ln -s "$src" "$dst"
    echo "linked $dst -> $src"
  fi
done

if [ ! -f "$STM_DIR/stm.json" ]; then
  cp "$SCRIPT_DIR/stm.json.template" "$STM_DIR/stm.json"
  echo "init   $STM_DIR/stm.json (empty)"
else
  echo "ok     $STM_DIR/stm.json (preserved)"
fi
touch "$STM_DIR/stm.log"

if [ ! -f "$SETTINGS" ]; then
  echo '{}' > "$SETTINGS"
  echo "init   $SETTINGS"
fi
cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"

INJECT_CMD="bash $HOOKS_DIR/stm-inject.sh"
LEARN_CMD="bash $HOOKS_DIR/stm-learn.sh"

jq --arg cmd "$INJECT_CMD" '
  .hooks //= {} |
  .hooks.PreToolUse //= [] |
  if (.hooks.PreToolUse | map(.hooks // [] | map(.command) | flatten) | flatten | any(. == $cmd))
  then .
  else .hooks.PreToolUse += [{
    "matcher": "Bash",
    "hooks": [{"type":"command","command":$cmd,"timeout":3}]
  }]
  end
' "$SETTINGS" > "$SETTINGS.tmp" && mv "$SETTINGS.tmp" "$SETTINGS"

jq --arg cmd "$LEARN_CMD" '
  .hooks //= {} |
  .hooks.PostToolUseFailure //= [] |
  if (.hooks.PostToolUseFailure | map(.hooks // [] | map(.command) | flatten) | flatten | any(. == $cmd))
  then .
  else .hooks.PostToolUseFailure += [{
    "matcher": "Bash",
    "hooks": [{"type":"command","command":$cmd,"timeout":3}]
  }]
  end
' "$SETTINGS" > "$SETTINGS.tmp" && mv "$SETTINGS.tmp" "$SETTINGS"

echo "patched $SETTINGS (PreToolUse + PostToolUseFailure on Bash)"
echo
echo "Smoke test:"
echo '{"tool_name":"Bash","tool_input":{"command":"echo hello"}}' \
  | bash "$HOOKS_DIR/stm-inject.sh" >/dev/null 2>&1 \
  && echo "  ok    inject hook runs cleanly on empty STM"
echo
cat <<'EOF'
Done. Next:
  1. Restart Claude Code (or open a new session) to pick up settings.json changes.
  2. Add the STM primer to your CLAUDE.md so Claude knows when to write entries.
     See: hooks/stm/README.md.
  3. STM stays empty until Claude writes its first lesson — that's by design.
EOF
