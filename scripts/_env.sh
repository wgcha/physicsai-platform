# 공용 환경(개발). source 해서 쓴다.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$REPO_ROOT/backend:$REPO_ROOT/worker${PYTHONPATH:+:$PYTHONPATH}"
export PHYSICSAI_CONFIG="${PHYSICSAI_CONFIG:-$REPO_ROOT/config/platform.yaml}"
PYTHON="${PYTHON:-python3}"
