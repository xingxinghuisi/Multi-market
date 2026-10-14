#!/usr/bin/env bash
# Reviewed-code deployment for read-only Smart Signal snapshots. Only recreates the API.
set -Eeuo pipefail
umask 077
project=/opt/korea-market-radar
expected=${1:?Pass the reviewed 40-character commit SHA}
[[ "$expected" =~ ^[0-9a-f]{40}$ ]] || exit 2
cd "$project"
exec 9>/opt/mirao-smart-money-deploy.lock
flock -n 9 || { echo 'STOP: another smart-money deploy is running'; exit 2; }
test "$(git rev-parse --show-toplevel)" = "$project"
test "$(git branch --show-current)" = main
case "$(git remote get-url origin)" in
  https://github.com/xingxinghuisi/Multi-market.git|git@github.com:xingxinghuisi/Multi-market.git) ;;
  *) echo 'STOP: unexpected source repository'; exit 2 ;;
esac
if [ -n "$(git status --porcelain)" ]; then
  echo 'STOP: source has local changes; nothing overwritten.'
  git status --short
  exit 2
fi
test -f .env.production
test -f app/data/market_radar.db
for protected in .env.production app/data/market_radar.db; do
  if git ls-files --error-unmatch "$protected" >/dev/null 2>&1; then
    echo 'STOP: runtime data or secrets are tracked by Git.'; exit 2
  fi
done
export GIT_TERMINAL_PROMPT=0
git fetch --no-tags origin main
test "$(git rev-parse origin/main)" = "$expected"
git merge-base --is-ancestor HEAD "$expected"
previous=$(git rev-parse HEAD)
image=$(docker inspect korea-radar-api --format '{{.Image}}')
stamp=$(date -u +%Y%m%d%H%M%S)
backup="/opt/korea-market-radar-releases/smart-money-$stamp"
mkdir -p "$backup"
docker image tag "$image" "korea-market-radar-app:before-smart-money-$stamp"
printf '%s\n' "$previous" > "$backup/previous-commit.txt"
printf '%s\n' "$image" > "$backup/previous-image.txt"
git merge --ff-only "$expected"
docker build -f Dockerfile.app -t "korea-market-radar-app:smart-money-$stamp" app
docker run --rm --env-file .env.production "korea-market-radar-app:smart-money-$stamp" python deployment_preflight.py
changed=0
rollback() {
  status=$?
  trap - ERR
  if [ "$changed" = 1 ]; then
    docker image tag "$image" korea-market-radar-app:latest
    docker compose --env-file .env.production up -d --no-deps --force-recreate --wait --wait-timeout 90 api || true
    echo "API_IMAGE_ROLLBACK_ATTEMPTED; source remains at $expected"
  fi
  echo "DEPLOY_FAILED; backup=$backup"
  exit "$status"
}
trap rollback ERR
docker image tag "korea-market-radar-app:smart-money-$stamp" korea-market-radar-app:latest
changed=1
docker compose --env-file .env.production up -d --no-deps --force-recreate --wait --wait-timeout 90 api
curl -fsS http://127.0.0.1:8000/api/client-version | python3 -c 'import json,sys; assert json.load(sys.stdin)["version"]=="2026.10.14.1"; print("API_VERSION_OK")'
curl -fsS http://127.0.0.1:8000/openapi.json | python3 -c 'import json,sys; assert "/api/assets/{asset_id}/smart-money" in json.load(sys.stdin)["paths"]; print("SMART_MONEY_ROUTE_OK")'
trap - ERR
docker compose --env-file .env.production ps api
echo "SMART_MONEY_DEPLOY_COMPLETE=$expected"
echo "BACKUP_DIRECTORY=$backup"
