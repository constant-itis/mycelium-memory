# Demo environment. Sourced by demo.tape's hidden setup step.
# Fresh DB every take; embeddings via the local endpoint below.
export DEMO_DB="${DEMO_DB:-${TMPDIR:-/tmp}/mycelium-demo.db}"
[ "${DEMO_FRESH:-0}" = "1" ] && rm -f "$DEMO_DB"
export MYCELIUM_STORAGE_DB_PATH="$DEMO_DB"
export MYCELIUM_SEMANTIC_EMBED_URL="${DEMO_EMBED_URL:-http://localhost:11434/v1/embeddings}"
export MYCELIUM_SEMANTIC_EMBED_MODEL="${DEMO_EMBED_MODEL:-nomic-embed-text}"
export MYCELIUM_SEMANTIC_WEIGHT="10"
export MYCELIUM_FOUNDRY_ENABLED="false"
export MYCELIUM_MEMORY_RECALL_PROPAGATE="2"   # demo: hit + a couple of connected memories
mycelium() { python3.11 -m mycelium.cli "$@"; }
export -f mycelium
PS1='\[\e[38;5;114m\]demo\[\e[0m\] $ '
