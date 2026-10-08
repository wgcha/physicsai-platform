# 공용 환경(개발). . .\scripts\_env.ps1 로 불러 쓴다.
$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:PYTHONPATH = "$RepoRoot\backend;$RepoRoot\worker" + $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { "" })
if (-not $env:PHYSICSAI_CONFIG) { $env:PHYSICSAI_CONFIG = "$RepoRoot\config\platform.yaml" }
$script:Python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
function Require-DbUrl { if (-not $env:PHYSICSAI_DATABASE_URL) { throw "PHYSICSAI_DATABASE_URL을 설정하세요" } }
