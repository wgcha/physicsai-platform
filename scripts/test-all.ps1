# 백엔드·워커 pytest + 프런트 vitest·타입 검사 (계약 §4.6). PostgreSQL은 PHYSICSAI_TEST_DATABASE_URL 필요(Windows).
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_env.ps1"
Push-Location $RepoRoot
try {
  & $Python -m pytest -q -rs @args; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  & $Python -c "import sys; from physicsai_api.export_openapi import render; sys.exit(0 if open('backend/openapi.json', encoding='utf-8').read() == render() else 1)"
  if ($LASTEXITCODE) { Write-Error "backend/openapi.json이 최신이 아닙니다"; exit 1 }
  if ((Test-Path frontend/package.json) -and (Get-Command npm -ErrorAction SilentlyContinue)) {
    Push-Location frontend
    try { if (-not (Test-Path node_modules)) { npm ci }; npm test; if ($LASTEXITCODE) { exit $LASTEXITCODE }; npm run lint; if ($LASTEXITCODE) { exit $LASTEXITCODE } } finally { Pop-Location }
  }
} finally { Pop-Location }
