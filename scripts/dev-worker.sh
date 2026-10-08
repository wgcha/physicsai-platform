#!/usr/bin/env bash
# 워커(PC당 1개, worker.state_dir 잠금) (계약 §4.6, §11.1)
set -euo pipefail
source "$(dirname "$0")/_env.sh"
: "${PHYSICSAI_DATABASE_URL:?PHYSICSAI_DATABASE_URL을 설정하세요}"
cd "$REPO_ROOT"
exec "$PYTHON" -m physicsai_worker --config "$PHYSICSAI_CONFIG" "$@"
