#!/usr/bin/env bash
# Off-camera seed: gives the demo DB a believable little corpus so recalls
# return a real-looking network instead of three toy rows.
cd "$(dirname "$0")/.."
DEMO_FRESH=1 source demo/env.sh
seed() { python3.11 -m mycelium.cli save "$1" ${2:+--project "$2"} --force >/dev/null; }

seed "Grafana runs on port 3000 behind nginx; dashboards provisioned from git." homelab
seed "Nightly backups run at 02:30 to the NAS over NFS, keep-3 rotation." homelab
seed "Deploys go out through the runbook: tag, CI builds the image, then promote." deploys
seed "The staging environment resets its data every Sunday night." deploys
seed "Postgres connection pool is capped at 20; raising it caused lock storms once." deploys
seed "The reverse proxy config lives in /etc/nginx/sites-enabled, one file per app." homelab
echo "seeded $(python3.11 - <<'EOF'
import sqlite3, os
print(sqlite3.connect(os.environ["DEMO_DB"]).execute("select count(*) from memories").fetchone()[0])
EOF
) memories"
