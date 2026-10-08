#!/usr/bin/env bash
# PHYSICSAI_DATABASE_URL의 DB에 alembic upgrade head (계약 §4.6)
set -euo pipefail
source "$(dirname "$0")/_env.sh"
: "${PHYSICSAI_DATABASE_URL:?PHYSICSAI_DATABASE_URL을 설정하세요 (예: postgresql+psycopg://physicsai_app:비밀번호@127.0.0.1:5432/physicsai)}"
cd "$REPO_ROOT"
"$PYTHON" -m alembic -c migrations/alembic.ini upgrade head
