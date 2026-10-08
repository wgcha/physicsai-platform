#!/usr/bin/env bash
# 인터넷 되는 준비 PC에서 Windows 폐쇄망 설치 묶음(physicsai-offline-<version>.zip)을 만든다(phase2 §11.2).
# 사용: bash deploy/collect-offline.sh [--dry-run]
#   --dry-run : 실행할 명령만 출력하고 아무것도 실행하지 않는다.
# 산출 구조: dist/wheels/*.whl, dist/frontend/(vite build), dist/migrations/, dist/config/platform.example.yaml, dist/deploy/
# 원본 반입 자원(resources.*: 런처·pyd·TCL·tpl 템플릿)은 묶지 않는다 — 라이선스·사내 배포물(RESOURCES.txt 참고).
set -euo pipefail
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)"
OUT="physicsai-offline-${VERSION}.zip"

run() {
  echo "+ $*"
  if [ "$DRY" -eq 0 ]; then
    eval "$@"
  fi
}

run "mkdir -p dist/wheels dist/frontend dist/config"
run "$PY -m pip download -r deploy/requirements.lock --only-binary=:all: --platform win_amd64 --python-version 3.13 -d dist/wheels"
run "$PY -m pip wheel . --no-deps -w dist/wheels"
run "(cd frontend && npm ci && npm run build)"
run "cp -r frontend/dist/. dist/frontend/"
run "cp -r migrations dist/migrations"
run "cp config/platform.example.yaml dist/config/platform.example.yaml"
run "cp -r deploy dist/deploy"
run "(cd dist && $PY -m zipfile -c ../$OUT wheels frontend migrations config deploy)"
echo "묶음: $OUT"
