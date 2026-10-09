#!/usr/bin/env bash
# Update Locuvi to the newest published release and restart it.
#   ./update.sh
# Locuvi backs itself up before it upgrades the database (BACKUP_DIR), so this is safe to run
# at any time. To go back to an earlier release, see README "Updates".
set -euo pipefail
cd "$(dirname "$0")"

if git rev-parse --git-dir >/dev/null 2>&1; then
  git pull --ff-only || echo "⚠  git pull failed (local changes?) — updating the app image only"
fi
docker compose pull locuvi
docker compose up -d --remove-orphans

printf 'Waiting for Locuvi to become healthy'
cid="$(docker compose ps -q locuvi)"
for _ in $(seq 1 60); do
  status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid")"
  if [ "$status" = "healthy" ]; then
    echo " ✓"
    docker image prune -f >/dev/null
    docker compose logs --tail=5 locuvi
    exit 0
  fi
  printf '.'
  sleep 3
done
echo " ✗ not healthy after 3 minutes (status: $status)"
docker compose logs --tail=40 locuvi
exit 1
