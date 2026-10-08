#!/usr/bin/env bash
# Vite dev server(프런트 설정: 127.0.0.1:5174, /physicsai/api → 127.0.0.1:8100 프록시) (계약 §4.6)
set -euo pipefail
cd "$(dirname "$0")/../frontend"
[ -d node_modules ] || npm ci
exec npm run dev
