#!/usr/bin/env bash
# V3-S4-6(phase3.md §6.6): simdash-adapters wheel을 만들어 빈 venv에 wheel만(인덱스 없이) 설치하고 import·버전을 확인한다.
# 사용: bash scripts/check-adapters-wheel.sh [작업 폴더(기본: 임시 폴더)]
set -euo pipefail
source "$(dirname "$0")/_env.sh"
cd "$REPO_ROOT"
WORK="${1:-$(mktemp -d)}"
[ ! -e "$WORK/src" ] || { echo "작업 폴더가 비어 있지 않습니다: $WORK"; exit 1; }
mkdir -p "$WORK/wheels"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' packages/simdash_adapters/pyproject.toml | head -1)"
WHL="$WORK/wheels/simdash_adapters-${VERSION}-py3-none-any.whl"
# 저장소 트리에 build/·egg-info를 남기지 않도록 소스 사본에서 만든다
"$PYTHON" -c "import shutil, sys; shutil.copytree('packages/simdash_adapters', sys.argv[1], ignore=shutil.ignore_patterns('build', '*.egg-info', '__pycache__'))" "$WORK/src"
"$PYTHON" -m pip wheel "$WORK/src" --no-deps -w "$WORK/wheels"
[ -f "$WHL" ] || { echo "wheel 이름이 다릅니다: $(ls "$WORK/wheels")"; exit 1; }
"$PYTHON" -m venv "$WORK/venv"
VPY="$WORK/venv/bin/python"
[ -x "$VPY" ] || VPY="$WORK/venv/Scripts/python.exe"
env -u PYTHONPATH "$VPY" -m pip install --no-index --no-deps "$WHL"
# 저장소 소스가 아니라 설치본을 쓰도록 PYTHONPATH 없이, 저장소 밖에서 실행
(cd "$WORK" && env -u PYTHONPATH "$VPY" -c "import simdash_adapters as s, sys; print(s.__name__, s.__version__, s.__file__); sys.exit(s.__version__ != '$VERSION')")
echo "wheel 확인: $(basename "$WHL")"
