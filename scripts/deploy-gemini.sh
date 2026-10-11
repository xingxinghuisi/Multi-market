#!/usr/bin/env bash
# First-time Gemini setup for the existing MIRAO VPS. Never prints credentials.
set -Eeuo pipefail
umask 077
project=/opt/korea-market-radar
expected=${1:?Pass the reviewed 40-character commit SHA}
[[ "$expected" =~ ^[0-9a-f]{40}$ ]] || exit 2
cd "$project"
exec 9>/opt/mirao-gemini-deploy.lock
flock -n 9 || { echo 'STOP: another Gemini setup is running'; exit 2; }
test "$(git rev-parse --show-toplevel)" = "$project"
test "$(git branch --show-current)" = main
if [ -n "$(git status --porcelain)" ]; then
  echo 'STOP: server source has local changes; nothing overwritten.'
  git status --short
  exit 2
fi
if docker inspect korea-radar-signals >/dev/null 2>&1; then
  echo 'STOP: signal service already exists; use the documented update procedure.'
  exit 2
fi
test -f .env.production
test -f app/data/market_radar.db
for protected in .env.production app/data/market_radar.db; do
  if git ls-files --error-unmatch "$protected" >/dev/null 2>&1; then
    echo 'STOP: a production runtime file is tracked by Git.'
    exit 2
  fi
done
case "$(git remote get-url origin)" in
  https://github.com/xingxinghuisi/Multi-market.git|git@github.com:xingxinghuisi/Multi-market.git) ;;
  *) echo 'STOP: unexpected origin repository'; exit 2 ;;
esac
export GIT_TERMINAL_PROMPT=0
git fetch --no-tags origin main
test "$(git rev-parse origin/main)" = "$expected"
git merge-base --is-ancestor HEAD "$expected"

stamp=$(date -u +%Y%m%d%H%M%S)
backup="/opt/korea-market-radar-releases/gemini-$stamp"
mkdir -p "$backup/source" "$backup/check-data"
echo "BACKUP_DIRECTORY=$backup"
cp -p .env.production "$backup/env.before"
cp -p compose.yaml "$backup/compose.before.yaml"
git rev-parse HEAD > "$backup/previous-commit.txt"
old_image=$(docker inspect --format '{{.Image}}' korea-radar-api)
docker tag "$old_image" "korea-market-radar-app:before-gemini-$stamp"
git archive "$expected" | tar -x -C "$backup/source"

python3 - "$project" "$backup" <<'PY'
import json, os, pathlib, re, shutil, sqlite3, sys
root, saved = map(pathlib.Path, sys.argv[1:])
credentials = pathlib.Path('/opt/mirao-secrets/google-adc.json')
incoming = pathlib.Path('/opt/mirao-secrets/google-adc.upload.json')
source = incoming if incoming.exists() else credentials
try:
    key = json.loads(source.read_text(encoding='utf-8-sig'))
    assert key.get('type') == 'service_account'
    assert key.get('project_id') == 'api-test-510819'
    assert key.get('client_email') == 'mirao-signals@api-test-510819.iam.gserviceaccount.com'
    assert key.get('private_key', '').startswith('-----BEGIN PRIVATE KEY-----')
except Exception:
    raise SystemExit('STOP: credential missing, incomplete, or for a different project/account; no content shown.')
if incoming.exists():
    if credentials.exists():
        shutil.copy2(credentials, saved / 'credential.before.json')
    os.replace(incoming, credentials)
credentials.chmod(0o600)
text = (root / '.env.production').read_text(encoding='utf-8-sig')
updates = dict(GEMINI_ENABLED='1', GOOGLE_CLOUD_PROJECT='api-test-510819',
    GEMINI_MODEL='gemini-3.1-flash-lite', GEMINI_MONTHLY_WARNING_USD='8.5',
    GEMINI_BUDGET_USERNAME='xingxinghuisi', GEMINI_MAX_CALLS_PER_DAY='100',
    GEMINI_CREDENTIALS_FILE=str(credentials))
lines = [line for line in text.splitlines() if not any(
    re.match(r'^\s*(?:export\s+)?' + name + r'\s*=', line) for name in updates)]
text = '\n'.join(lines + [f'{k}={v}' for k,v in updates.items()]) + '\n'
(saved / 'env.candidate').write_text(text, encoding='utf-8')
(saved / 'source/.env.production').write_text(text, encoding='utf-8')
with sqlite3.connect(f'file:{root / "app/data/market_radar.db"}?mode=ro', uri=True) as live:
    assert live.execute('SELECT telegram_chat_id FROM users WHERE username=?',
                        ('xingxinghuisi',)).fetchone()[0], 'Budget owner has no Telegram target'
    with sqlite3.connect(saved / 'database.before.sqlite3') as copy:
        live.backup(copy)
shutil.copy2(saved / 'database.before.sqlite3', saved / 'check-data/market_radar.db')
print('CREDENTIAL_PROJECT_OK; DATABASE_BACKUP_OK; BUDGET_OWNER_OK')
PY

candidate="korea-market-radar-app:gemini-${expected:0:12}"
docker compose --env-file "$backup/env.candidate" -f "$backup/source/compose.yaml" \
  -f "$backup/source/compose.gemini.yaml" config --quiet
docker build -f "$backup/source/Dockerfile.app" -t "$candidate" "$backup/source/app"
docker run --rm --env-file "$backup/env.candidate" "$candidate" python deployment_preflight.py
docker run --rm -i --network none --env-file "$backup/env.candidate" \
  -v "$backup/check-data:/app/data" "$candidate" python - <<'PY'
import sqlite3
from database import engine
from signal_models import initialize_signal_tables
with sqlite3.connect('/app/data/market_radar.db') as db:
    before = [db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('users','assets','alert_rules')]
initialize_signal_tables(engine)
with sqlite3.connect('/app/data/market_radar.db') as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert before == [db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('users','assets','alert_rules')]
print('CANDIDATE_DATABASE_OK')
PY

# One explicitly requested setup call. The live ledger records its cost.
# A failure here leaves the running API and other workers unchanged.
docker run --rm --env-file "$backup/env.candidate" \
  -e GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/google-adc.json \
  -v /opt/mirao-secrets/google-adc.json:/run/secrets/google-adc.json:ro \
  -v "$project/app/data:/app/data" "$candidate" python gemini_check.py --symbol KORUUSDT

changed=0
rollback() {
  code=$?
  trap - ERR
  set +e
  if [ "$changed" = 1 ]; then
    docker rm -f korea-radar-signals >/dev/null 2>&1
    cp -p "$backup/env.before" .env.production
    cp -p "$backup/compose.before.yaml" compose.yaml
    docker tag "$old_image" korea-market-radar-app:latest
    docker compose --env-file .env.production up -d --no-deps --force-recreate api
    echo 'ROLLBACK: previous API restored; live database retained. Git working tree may require review.' >&2
  fi
  echo "BACKUP_DIRECTORY=$backup" >&2
  exit "$code"
}
trap rollback ERR
test -z "$(git status --porcelain)"
git pull --ff-only origin main
test "$(git rev-parse HEAD)" = "$expected"
changed=1
cp -p "$backup/env.candidate" .env.production
docker tag "$candidate" korea-market-radar-app:latest
dc=(docker compose --env-file .env.production -f compose.yaml -f compose.gemini.yaml)
"${dc[@]}" up -d --no-deps --force-recreate api
ready=0
for attempt in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
test "$ready" = 1
"${dc[@]}" up -d --no-deps signal_worker
"${dc[@]}" exec -T api python - <<'PY'
import requests
assert requests.get('http://127.0.0.1:8000/api/signals',timeout=5).status_code == 401
assert requests.get('http://127.0.0.1:8000/api/client-version',timeout=5).json()['version'] == '2026.10.12.1'
print('API_VERSION_AND_AUTH_OK')
PY
sleep 3
test "$(docker inspect --format '{{.State.Running}}' korea-radar-signals)" = true
"${dc[@]}" ps api signal_worker
"${dc[@]}" logs --since=2m --tail=15 signal_worker
echo "GEMINI_DEPLOY_COMPLETE=$expected"
echo "BACKUP_DIRECTORY=$backup"
