# PHYSICSAI_DATABASE_URL의 DB에 alembic upgrade head (계약 §4.6)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_env.ps1"
Require-DbUrl
Push-Location $RepoRoot
try { & $Python -m alembic -c migrations/alembic.ini upgrade head; if ($LASTEXITCODE) { exit $LASTEXITCODE } } finally { Pop-Location }
