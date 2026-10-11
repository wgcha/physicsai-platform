# 개발 설치(phase3.md §6.5): 공통 어댑터 패키지(편집 가능) → 플랫폼 런타임 의존성(deploy/requirements.lock) + 시험 도구.
# simdash-adapters는 PyPI에서 받지 않는다(lock에 없음, deploy/requirements.local.lock) — 저장소 소스로 먼저 설치한다.
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_env.ps1"
Push-Location $RepoRoot
try {
  & $Python -m pip install -e packages/simdash_adapters; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  & $Python -m pip install -r deploy/requirements.lock "pytest>=8" "pytest-timeout>=2.2"; exit $LASTEXITCODE
} finally { Pop-Location }
