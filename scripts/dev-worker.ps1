# 워커(PC당 1개, worker.state_dir 잠금, Windows Job Object 제한기) (계약 §4.6, §11)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_env.ps1"
Require-DbUrl
Push-Location $RepoRoot
try { & $Python -m physicsai_worker --config $env:PHYSICSAI_CONFIG @args; exit $LASTEXITCODE } finally { Pop-Location }
