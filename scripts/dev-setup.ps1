# 개발 설치(phase3.md §6.5): 공통 어댑터 패키지(편집 가능) → 플랫폼 런타임 의존성(deploy/requirements.lock) + 시험 도구.
# simdash-adapters는 PyPI에 없으므로 lock보다 먼저 저장소 소스로 설치한다(이미 설치되어 있으면 lock 설치가 다시 받지 않는다).
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_env.ps1"
Push-Location $RepoRoot
try {
  & $Python -m pip install -e packages/simdash_adapters; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  & $Python -m pip install -r deploy/requirements.lock "pytest>=8" "pytest-timeout>=2.2"; exit $LASTEXITCODE
} finally { Pop-Location }
