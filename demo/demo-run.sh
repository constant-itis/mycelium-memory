#!/usr/bin/env bash
# Scripted demo take. Full pipeline:
#   demo/seed.sh                                          # fresh DB + background corpus
#   asciinema rec --overwrite -c demo/demo-run.sh demo/take.cast
#   (render + captions: see demo/render.sh)
# Emits section timestamps to demo/marks.txt for the caption overlay pass.
cd "$(dirname "$0")/.."
source demo/env.sh
stty cols 110 rows 30 2>/dev/null || true

MARKS=demo/marks.txt
: > "$MARKS"
mark() { printf '%s %s\n' "$(date +%s.%N)" "$1" >> "$MARKS"; }

P=$'\e[38;5;114mdemo\e[0m $ '
type_line() {
  printf '%s' "$P"
  local s="$1"
  for ((i = 0; i < ${#s}; i++)); do
    printf '%s' "${s:$i:1}"
    sleep 0.028
  done
  sleep 0.3
  printf '\n'
}
run() { type_line "$1"; eval "$1"; }
cls() { sleep 0.2; printf '\e[2J\e[H'; }

mark t0
mark save_start
run 'mycelium save "We run the legacy report generator on Python 2.7 ON PURPOSE. Do not suggest upgrading it." --contradicts-prior'
sleep 2
run 'mycelium save "$(cat demo/maintenance-log.txt)" --project homelab'
sleep 2.5

cls
mark recall_meaning
run 'mycelium recall "how do I roll out a new version" --limit 1'
sleep 4.5

cls
mark recall_buried
run 'mycelium recall "which port does the wiki listen on now" --limit 1 | grep --color=always -E "listens on port 8090|$"'
sleep 6

cls
mark recall_prior
run 'mycelium recall "should we upgrade the report generator" --limit 1'
sleep 4.5
mark outro
sleep 3
mark end
