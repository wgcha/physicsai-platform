# 백엔드·워커 pytest + 프런트 vitest·타입 검사 (계약 §4.6). PostgreSQL은 PHYSICSAI_TEST_DATABASE_URL 필요(Windows).
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_env.ps1"
Push-Location $RepoRoot
try {
  & $Python scripts/frontend_source_hash.py --check $RepoRoot; if ($LASTEXITCODE) { exit $LASTEXITCODE }   # frontend-dist 최신 여부(phase3 D3-40)
  & $Python scripts/check_paicad.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }   # paicad 버전·import 금지 검사(geometry-engine.md §17.5·§18.6)
  & $Python scripts/check_releases.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }   # RELEASES.md·플랫폼 버전 일치(버전 게시판)
  $pyArgs = @($args)
  if ($pyArgs.Count -gt 0 -and $pyArgs[0] -eq "--slow") { $pyArgs = @("-m", "") + @($pyArgs | Select-Object -Skip 1) }   # slow 마커 포함 전체
  & $Python -m pytest -q -rs @pyArgs; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  # paicad 단독 시험(플랫폼 모듈·DB 없이). PAICAD_SKIP_SLOW=1이면 G1 envelope 재생성 시험(약 2분)을 뺀다
  Push-Location packages/paicad
  $savedPyPath = $env:PYTHONPATH
  try {
    $env:PYTHONPATH = ""
    $paicadArgs = @()
    if ($env:PAICAD_SKIP_SLOW -eq "1") { $paicadArgs = @("--deselect", "tests/test_v050.py::test_golden_report_regenerates_byte_identical") }
    & $Python -m pytest -q -rs @paicadArgs; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  } finally { $env:PYTHONPATH = $savedPyPath; Pop-Location }
  & $Python -c "import sys; from physicsai_api.export_openapi import render; sys.exit(0 if open('backend/openapi.json', encoding='utf-8').read() == render() else 1)"
  if ($LASTEXITCODE) { Write-Error "backend/openapi.json이 최신이 아닙니다"; exit 1 }
  & $Python scripts/gen_tool_specs.py --check   # MCP 도구 스펙·용어집 최신·이식 가능 스키마·호환 여부(mcp.md §9)
  if ($LASTEXITCODE) { Write-Error "MCP 도구 스펙이 최신이 아니거나 깨지는 변경입니다: python scripts/gen_tool_specs.py"; exit 1 }
  if ((Test-Path frontend/package.json) -and (Get-Command npm -ErrorAction SilentlyContinue)) {
    Push-Location frontend
    try { if (-not (Test-Path node_modules)) { npm ci }; npm test; if ($LASTEXITCODE) { exit $LASTEXITCODE }; npm run lint; if ($LASTEXITCODE) { exit $LASTEXITCODE } } finally { Pop-Location }
  }
} finally { Pop-Location }
