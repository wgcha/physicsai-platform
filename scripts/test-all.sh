#!/usr/bin/env bash
# 백엔드·워커 pytest(+PostgreSQL) + 프런트 vitest·타입 검사 (계약 §4.6, §18.2)
# PostgreSQL: PHYSICSAI_TEST_DATABASE_URL이 있으면 사용, 없으면 PG_BIN(예 /usr/lib/postgresql/16/bin)으로 임시 클러스터.
set -euo pipefail
source "$(dirname "$0")/_env.sh"
cd "$REPO_ROOT"
echo "== backend/worker pytest =="
"$PYTHON" -m pytest -q -rs "$@"
echo "== openapi.json 최신 여부 =="
"$PYTHON" -c "import sys; from physicsai_api.export_openapi import render; sys.exit(0 if open('backend/openapi.json', encoding='utf-8').read() == render() else 1)" \
  || { echo "backend/openapi.json이 최신이 아닙니다: python -m physicsai_api.export_openapi"; exit 1; }
if [ -f frontend/package.json ] && command -v npm >/dev/null 2>&1; then
  echo "== frontend vitest + tsc =="
  (cd frontend && { [ -d node_modules ] || npm ci; } && npm test && npm run lint)
else
  echo "frontend 시험 생략: npm 또는 frontend/package.json 없음"
fi
