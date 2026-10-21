#!/usr/bin/env bash
# 프런트 빌드본을 저장소에 넣는다(phase3 D3-40): frontend에서 npm run build → frontend-dist/로 교체 + BUILD_INFO.json
# (source_hash = scripts/frontend_source_hash.py). 서버(setup·update-repo)는 해시가 맞으면 Node·npm 없이 이 폴더를 배치한다.
# 프런트 소스를 고치면 이 스크립트를 실행하고 frontend-dist를 함께 커밋한다(scripts/test-all이 최신 여부를 검사).
set -euo pipefail
source "$(dirname "$0")/_env.sh"
cd "$REPO_ROOT"
# npm ci: package-lock.json 그대로 설치(남아 있던 node_modules와 무관하게 같은 빌드)
# 번들에 자기 소스 해시를 심는다(VITE_BUILD_HASH): 옛 index.html을 캐시한 브라우저를 /version의 build.source_hash와 비교해 알리려고
build_hash="$("$PYTHON" scripts/frontend_source_hash.py frontend)"
(cd frontend && npm ci && VITE_BUILD_HASH="$build_hash" npm run build)
[ -f frontend/dist/index.html ] || { echo "빌드 결과 없음: frontend/dist/index.html"; exit 1; }
rm -rf frontend-dist
cp -r frontend/dist frontend-dist
vite_version="$(node -p "require('./frontend/node_modules/vite/package.json').version")"
"$PYTHON" scripts/frontend_source_hash.py --write-info "$REPO_ROOT" "$vite_version" "$(node --version)"
echo "frontend-dist 갱신 — 함께 커밋하세요: git add frontend-dist"
