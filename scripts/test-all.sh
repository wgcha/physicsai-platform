#!/usr/bin/env bash
# 백엔드·워커 pytest(+PostgreSQL) + 프런트 vitest·타입 검사 (계약 §4.6, §18.2)
# PostgreSQL: PHYSICSAI_TEST_DATABASE_URL이 있으면 사용, 없으면 PHYSICSAI_TEST_PGBIN·PG_BIN(예 /usr/lib/postgresql/18/bin) 또는
# /usr/lib/postgresql/<최신>/bin으로 임시 클러스터(기준: 대시보드와 같은 PostgreSQL 18). Python 3.12(.python-version 3.12.13).
set -euo pipefail
source "$(dirname "$0")/_env.sh"
cd "$REPO_ROOT"
echo "== frontend-dist 최신 여부(빌드본 = 현재 프런트 소스, phase3 D3-40) =="
"$PYTHON" scripts/frontend_source_hash.py --check "$REPO_ROOT"
echo "== backend/worker pytest =="
# --slow: slow 마커 시험까지 전체(nightly 등 별도 명령). 기본은 pyproject addopts의 -m 'not slow'
if [ "${1:-}" = "--slow" ]; then shift; set -- -m "" "$@"; fi
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
