#!/usr/bin/env bash
# Pinned additive upgrade: API plus the opt-in aggregate observation scheduler only.
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
  *) echo 'STOP: unexpected repository'; exit 2 ;;
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
stamp=$(date -u +%Y%m%d%H%M%S)
backup="/opt/korea-market-radar-releases/smart-money-alerts-$stamp"
mkdir -p "$backup/check-data"
git rev-parse HEAD > "$backup/previous-commit.txt"
cp -p compose.yaml "$backup/compose.before.yaml"
old_api=$(docker inspect korea-radar-api --format '{{.Image}}')
old_worker=$(docker inspect korea-radar-smart-money --format '{{.Image}}' 2>/dev/null || true)
docker image tag "$old_api" "korea-market-radar-app:before-smart-money-alerts-$stamp"
printf '%s\n' "$old_api" > "$backup/previous-image.txt"
if [ -n "$old_worker" ]; then
  docker image tag "$old_worker" "korea-market-radar-app:before-smart-money-worker-$stamp"
fi
# SQLite's online backup includes committed WAL content while other workers keep running.
python3 - "$project" "$backup" <<'PY'
import pathlib, shutil, sqlite3, sys
root, saved = map(pathlib.Path, sys.argv[1:])
with sqlite3.connect(f'file:{root / "app/data/market_radar.db"}?mode=ro', uri=True) as live:
    with sqlite3.connect(saved / 'database.before.sqlite3') as copy:
        live.backup(copy)
shutil.copy2(saved / 'database.before.sqlite3', saved / 'check-data/market_radar.db')
print('DATABASE_BACKUP_OK')
PY
git merge --ff-only "$expected"
docker compose --env-file .env.production config --quiet
candidate="korea-market-radar-app:smart-money-alerts-$stamp"
docker build -f Dockerfile.app -t "$candidate" app
docker run --rm --env-file .env.production "$candidate" python deployment_preflight.py
docker run --rm -i --network none -v "$backup/check-data:/app/data" "$candidate" python - <<'PY'
import sqlite3
from database import engine
from smart_money_models import initialize_smart_money_tables
with sqlite3.connect('/app/data/market_radar.db') as db:
    before = [db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
              for table in ('users', 'assets', 'alert_rules', 'alert_subscriptions')]
initialize_smart_money_tables(engine)
initialize_smart_money_tables(engine)
with sqlite3.connect('/app/data/market_radar.db') as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert before == [db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                      for table in ('users', 'assets', 'alert_rules', 'alert_subscriptions')]
    assert db.execute('SELECT COUNT(*) FROM smart_money_states').fetchone()[0] >= 0
import smart_money_worker
print('ADDITIVE_SCHEMA_OK; WORKER_IMPORT_OK')
PY
changed=0
rollback() {
  code=$?
  trap - ERR
  set +e
  if [ "$changed" = 1 ]; then
    docker image tag "$old_api" korea-market-radar-app:latest
    docker compose --env-file .env.production up -d --no-deps --force-recreate --wait --wait-timeout 90 api
    if [ -n "$old_worker" ]; then
      printf 'services:\n  smart_money_worker:\n    image: "%s"\n' "$old_worker" > "$backup/worker.rollback.yaml"
      docker compose --env-file .env.production -f compose.yaml -f "$backup/worker.rollback.yaml" up -d --no-deps --force-recreate smart_money_worker
    else
      docker compose --env-file .env.production stop smart_money_worker
      docker compose --env-file .env.production rm -f smart_money_worker
    fi
    echo "API_IMAGE_ROLLBACK_ATTEMPTED; source remains at $expected; additive table retained"
  fi
  echo "DEPLOY_FAILED; backup=$backup"
  exit "$code"
}
trap rollback ERR
docker image tag "$candidate" korea-market-radar-app:latest
changed=1
docker compose --env-file .env.production up -d --no-deps --force-recreate --wait --wait-timeout 90 api
curl -fsS http://127.0.0.1:8000/api/client-version | python3 -c 'import json,sys; assert json.load(sys.stdin)["version"]=="2026.10.17.1"; print("API_VERSION_OK")'
curl -fsS http://127.0.0.1:8000/openapi.json | python3 -c 'import json,sys; assert "/api/internal/smart-money/{asset_id}/poll" in json.load(sys.stdin)["paths"]; print("SMART_MONEY_POLL_ROUTE_OK")'
docker compose --env-file .env.production up -d --no-deps --force-recreate smart_money_worker
test "$(docker inspect korea-radar-smart-money --format '{{.State.Running}}')" = true
trap - ERR
docker compose --env-file .env.production ps api smart_money_worker
echo "SMART_MONEY_ALERTS_DEPLOY_COMPLETE=$expected"
echo "BACKUP_DIRECTORY=$backup"
