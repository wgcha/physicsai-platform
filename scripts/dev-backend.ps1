# FastAPI 백엔드(설정 server.host·port, 기본 127.0.0.1:8100) (계약 §4.6)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_env.ps1"
Require-DbUrl
Push-Location $RepoRoot
try { & $Python -m physicsai_api.serve; exit $LASTEXITCODE } finally { Pop-Location }
