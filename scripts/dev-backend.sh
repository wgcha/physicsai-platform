#!/usr/bin/env bash
# FastAPI 백엔드(설정 server.host·port, 기본 127.0.0.1:8100) (계약 §4.6)
set -euo pipefail
source "$(dirname "$0")/_env.sh"
: "${PHYSICSAI_DATABASE_URL:?PHYSICSAI_DATABASE_URL을 설정하세요}"
cd "$REPO_ROOT"
exec "$PYTHON" -m physicsai_api.serve
