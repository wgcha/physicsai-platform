#!/usr/bin/env bash
# 실제 백엔드 스모크(Linux 개발용): 임시 PostgreSQL + dev_static 인증 설정으로
# scripts/dev-db-init.sh → scripts/dev-backend.sh를 띄우고 프런트 클라이언트로 주요 API를 호출한다.
# 필요: PG_BIN(기본 /usr/lib/postgresql/*/bin), python 의존성(pyproject), npm 의존성.
set -euo pipefail
FE="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$FE/.." && pwd)"
PG_BIN="${PG_BIN:-$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)}"
PORT_PG="${PORT_PG:-55432}"
PORT_API="${PORT_API:-8100}"
TMP="$(mktemp -d /tmp/physicsai_smoke_XXXXXX)"
chmod 755 "$TMP"
mkdir -p "$TMP/ai_root" "$TMP/pg"
AS=()
if [ "$(id -u)" = "0" ]; then chown postgres "$TMP/pg"; AS=(runuser -u postgres --); fi
cleanup() {
  [ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null || true
  "${AS[@]}" "$PG_BIN/pg_ctl" -D "$TMP/pg/data" -m immediate stop >/dev/null 2>&1 || true
}
trap cleanup EXIT

"${AS[@]}" "$PG_BIN/initdb" -D "$TMP/pg/data" -A trust -U postgres -E UTF8 --no-sync >/dev/null
"${AS[@]}" "$PG_BIN/pg_ctl" -D "$TMP/pg/data" -l "$TMP/pg/log" -w -o "-p $PORT_PG -k $TMP/pg -c listen_addresses=127.0.0.1" start >/dev/null
export PHYSICSAI_DATABASE_URL="postgresql+psycopg://postgres@127.0.0.1:$PORT_PG/postgres"

# 설정: 예시를 복사해 dev_static 인증·임시 ai_root·포트만 바꾼다
python3 - "$REPO/config/platform.example.yaml" "$TMP/platform.yaml" "$TMP/ai_root" "$PORT_API" <<'PY'
import sys, yaml
src, dst, root, port = sys.argv[1:]
c = yaml.safe_load(open(src, encoding="utf-8"))
c["profile"] = "dev"
c["server"]["port"] = int(port)
c["auth"]["mode"] = "dev_static"
c["auth"]["dev_static_principal"]["memberships"] = [{"project_id": "dev", "role": "power"}]
c["storage"]["ai_root"] = root
yaml.safe_dump(c, open(dst, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
PY
export PHYSICSAI_CONFIG="$TMP/platform.yaml"

bash "$REPO/scripts/dev-db-init.sh" >"$TMP/db-init.log" 2>&1 || { cat "$TMP/db-init.log"; exit 1; }
bash "$REPO/scripts/dev-backend.sh" >"$TMP/backend.log" 2>&1 &
API_PID=$!
for _ in $(seq 1 60); do
  curl -sf "http://127.0.0.1:$PORT_API/physicsai/api/health" >/dev/null && break
  sleep 0.5
done
curl -sf "http://127.0.0.1:$PORT_API/physicsai/api/health" >/dev/null || { echo "백엔드 기동 실패"; cat "$TMP/backend.log"; exit 1; }

cd "$FE"
SMOKE_BASE="http://127.0.0.1:$PORT_API" npx vite-node scripts/smoke-api.ts
