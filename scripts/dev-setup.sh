#!/usr/bin/env bash
# 개발 설치(phase3.md §6.5): 공통 어댑터 패키지(편집 가능) → 플랫폼 런타임 의존성(deploy/requirements.lock) + 시험 도구.
# simdash-adapters는 PyPI에서 받지 않는다(lock에 없음, deploy/requirements.local.lock) — 저장소 소스로 먼저 설치한다.
set -euo pipefail
source "$(dirname "$0")/_env.sh"
cd "$REPO_ROOT"
"$PYTHON" -m pip install -e packages/simdash_adapters
# native 형상 엔진(별도 프로세스로만 실행, geometry-engine.md §7.8). 외부 의존(cadquery-ocp 등)은 아래 requirements.lock
"$PYTHON" -m pip install --no-deps -e packages/paicad
"$PYTHON" -m pip install -r deploy/requirements.lock "pytest>=8" "pytest-timeout>=2.2"
