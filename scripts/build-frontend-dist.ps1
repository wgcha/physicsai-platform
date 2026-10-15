# 프런트 빌드본을 저장소에 넣는다(phase3 D3-40, build-frontend-dist.sh와 같음): npm run build → frontend-dist + BUILD_INFO.json
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_env.ps1"
Push-Location $RepoRoot
try {
  Push-Location frontend
  try { npm ci; if ($LASTEXITCODE) { exit $LASTEXITCODE }; npm run build; if ($LASTEXITCODE) { exit $LASTEXITCODE } } finally { Pop-Location }
  if (-not (Test-Path frontend/dist/index.html)) { throw "빌드 결과 없음: frontend/dist/index.html" }
  if (Test-Path frontend-dist) { Remove-Item -Recurse -Force frontend-dist }
  Copy-Item -Recurse frontend/dist frontend-dist
  $vite = (& node -p "require('./frontend/node_modules/vite/package.json').version").Trim()
  & $Python scripts/frontend_source_hash.py --write-info $RepoRoot $vite ((& node --version).Trim()); if ($LASTEXITCODE) { exit $LASTEXITCODE }
  Write-Host "frontend-dist 갱신 — 함께 커밋하세요: git add frontend-dist"
} finally { Pop-Location }
