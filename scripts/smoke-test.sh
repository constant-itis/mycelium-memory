#!/bin/bash
# Mycelium smoke test — exercises the package end-to-end on a throwaway DB.
#
# Verifies:
#   - config loader picks up the test config
#   - semantic schema initializes cleanly
#   - save / recall round-trip works (with auto-connection)
#   - foundry publish writes JSONL
#   - foundry ingest drains JSONL into SQLite
#   - foundry query reads decisions back
#
# Run after `pip install -e .` (or any install). Pollutes only the temp dir.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
TMP="$(mktemp -d -t mycelium-smoke-XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

echo "== Mycelium smoke test =="
echo "python: $($PY --version)"
echo "tmp: $TMP"

# 1. Write a test config that points everything at $TMP
cat > "$TMP/config.toml" <<EOF
[server]
transport = "stdio"

[storage]
db_path = "$TMP/memory.db"
backup_dir = "$TMP/backups"

[memory]
keyword_clusters = ["acme corp"]

[foundry]
enabled = true
log_dir = "$TMP/foundry-logs"
db_path = "$TMP/foundry.db"
EOF

export MYCELIUM_CONFIG="$TMP/config.toml"

# 2. Verify config loads and shows the test paths
echo
echo "-- config --"
$PY -m mycelium.cli config | head -20

# 3. Run the round-trip checks via Python (no MCP client needed for smoke)
echo
echo "-- python round-trip --"
$PY - <<PY
from mycelium import config as _cfg
from mycelium import server, foundry
from mycelium.foundry import ingest as _ingest

server.set_config(_cfg.load())
cfg = _cfg.load()

# semantic
assert "Saved #" in server.save("the network strengthens with use", project="smoke"), "save failed"
assert "Saved #" in server.save("connections decay without access", project="smoke", force=True), "save 2 failed"
out = server.recall("network strengthens", project="smoke")
assert "Recall:" in out and "#1" in out, f"recall did not return expected: {out}"
ctx = server.context(project="smoke")
assert "Mycelium" in ctx and "smoke" in ctx, f"context did not include project: {ctx}"

# foundry
assert foundry.publish("smoke_test", "smoke-agent", "ok",
                       input_features={"x": 1}, outcome={"ok": True}) is True
assert foundry.publish("smoke_test", "smoke-agent", "fail",
                       failure_class="example", failure_detail="just a smoke check") is True

# ingest the JSONL into the foundry DB
n = _ingest.drain_all(cfg.foundry_db_path, cfg.foundry_log_dir)
assert n >= 2, f"foundry ingest drained {n} rows, expected >= 2"

# query back
rows = _ingest.query(cfg.foundry_db_path, agent="smoke-agent", limit=10)
assert len(rows) >= 2, f"foundry query returned {len(rows)} rows"
assert any(r.get("failure_class") == "example" for r in rows), "failure row missing"

print(f"  semantic: save+recall+context OK")
print(f"  foundry:  publish+ingest+query OK ({len(rows)} rows)")
PY

# 4. Verify the CLI foundry sub-commands work too
echo
echo "-- cli foundry --"
$PY -m mycelium.cli foundry ingest
$PY -m mycelium.cli foundry query --agent smoke-agent --limit 3

echo
echo "OK — smoke test passed."
