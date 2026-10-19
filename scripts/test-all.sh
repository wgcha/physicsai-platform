#!/usr/bin/env bash
# 백엔드·워커 pytest(+PostgreSQL) + 프런트 vitest·타입 검사 (계약 §4.6, §18.2)
# PostgreSQL: PHYSICSAI_TEST_DATABASE_URL이 있으면 사용, 없으면 PHYSICSAI_TEST_PGBIN·PG_BIN(예 /usr/lib/postgresql/18/bin) 또는
# /usr/lib/postgresql/<최신>/bin으로 임시 클러스터(기준: 대시보드와 같은 PostgreSQL 18). Python 3.12(.python-version 3.12.13).
set -euo pipefail
source "$(dirname "$0")/_env.sh"
cd "$REPO_ROOT"
echo "== frontend-dist 최신 여부(빌드본 = 현재 프런트 소스, phase3 D3-40) =="
"$PYTHON" scripts/frontend_source_hash.py --check "$REPO_ROOT"
echo "== paicad 정적 검사(버전·CHANGELOG·고정, 플랫폼↔paicad import 금지, kernel/ 밖 OCP 금지 — geometry-engine.md §17.5·§18.6) =="
"$PYTHON" scripts/check_paicad.py
echo "== backend/worker pytest =="
# --slow: slow 마커 시험까지 전체(nightly 등 별도 명령). 기본은 pyproject addopts의 -m 'not slow'
if [ "${1:-}" = "--slow" ]; then shift; set -- -m "" "$@"; fi
"$PYTHON" -m pytest -q -rs "$@"
# paicad 단독 시험(플랫폼 모듈·DB·platform.yaml 없이 — V-GE-13). 가상 쿠션 골든이 OCP·build123d·gmsh를 실제로 쓴다(skip을 통과로 치지 않음).
# PAICAD_SKIP_SLOW=1이면 G1 envelope 바이트 동일 재생성 시험(약 2분)을 뺀다(개발 중 빠른 확인용 — 완료 판정·CI는 전체).
echo "== paicad 단독 pytest =="
PAICAD_DESELECT=()
[ "${PAICAD_SKIP_SLOW:-0}" = "1" ] && PAICAD_DESELECT=(--deselect "tests/test_v050.py::test_golden_report_regenerates_byte_identical")
(cd packages/paicad && env -u PYTHONPATH "$PYTHON" -m pytest -q -rs ${PAICAD_DESELECT[@]+"${PAICAD_DESELECT[@]}"})
echo "== openapi.json 최신 여부 =="
"$PYTHON" -c "import sys; from physicsai_api.export_openapi import render; sys.exit(0 if open('backend/openapi.json', encoding='utf-8').read() == render() else 1)" \
  || { echo "backend/openapi.json이 최신이 아닙니다: python -m physicsai_api.export_openapi"; exit 1; }
if [ -f frontend/package.json ] && command -v npm >/dev/null 2>&1; then
  echo "== frontend vitest + tsc =="
  (cd frontend && { [ -d node_modules ] || npm ci; } && npm test && npm run lint)
else
  echo "frontend 시험 생략: npm 또는 frontend/package.json 없음"
fi
