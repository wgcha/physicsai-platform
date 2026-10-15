<#
.SYNOPSIS
  PhysicsAI 업데이트(phase2 §11.2). 기존 venv·프런트·migrations를 _backup\<UTC>로 이동(삭제 없음)한 뒤 새 묶음 설치.
.DESCRIPTION
  ① 실행 중 작업·진행 중 환경 점검 확인(묻지 않고 DB 직접 조회) → 있으면 중단(-Force면 경고 후 진행)
  ② 작업 2개 중지 ③ 기존 venv·frontend·migrations를 <install_root>\_backup\<UTC>로 이동 ④ 새 wheel·프런트 배치
  ⑤ alembic upgrade head ⑥ 시작·health 확인 ⑦ 실패 시 되돌리는 방법 안내(자동 되돌림 없음)
#>
[CmdletBinding()]
param(
    [string]$ConfigFile = '',   # 비우면 이 스크립트 폴더의 deploy.json (PS 5.1은 param 기본값에서 $PSScriptRoot가 빔)
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
if (-not $ConfigFile) { $ConfigFile = Join-Path $PSScriptRoot 'deploy.json' }
$PhysicsAITag = 'PhysicsAI 업데이트'
. (Join-Path $PSScriptRoot 'install-common.ps1')   # 작업 확인·중지·시작·health 공용 함수(update-repo.ps1과 같은 코드)
function Write-Step([string]$m) { Write-PhysicsAIStep $m }
function Assert-Ok([string]$what) { Assert-PhysicsAIExit $what }

$cfg = Get-Content -Raw -Encoding UTF8 $ConfigFile | ConvertFrom-Json
if ($cfg.dashboard_root) {
    # install.ps1과 같은 규칙: 비어 있는 pg_bin·pg_host·pg_port·python_exe만 대시보드 환경으로 채운다(dashboard-env.ps1)
    . (Join-Path $PSScriptRoot 'dashboard-env.ps1')
    Merge-DashboardDefaults -Config $cfg -Defaults (Get-DashboardRuntimeDefaults -DashboardRoot $cfg.dashboard_root) | Out-Null
}
# 기존 설치를 옮기기 전에 python_exe가 실제로 Python 3.12로 실행되는지 확인(망가진 pyenv shim 등이면 원인·다음 행동과 함께 여기서 중단 — 아무것도 바꾸지 않음)
. (Join-Path $PSScriptRoot 'python-select.ps1')
$basePy = Assert-PhysicsAIPython312 -Exe "$($cfg.python_exe)"
Write-Step "Python $($basePy.Version): $($basePy.Exe)"
$root = $cfg.install_root
$pkg = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $root 'venv\Scripts\python.exe'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$backup = Join-Path $root "_backup\$stamp"
$port = Get-PhysicsAIBackendPort $cfg.config_path $venvPy   # 기존 venv로 읽음(없으면 yaml에서 직접)

# ---- ① 실행 중 작업 확인(묻지 않고 DB 직접) ----------------------------------
Assert-PhysicsAINoActiveJobs -Port $port -PgBin $cfg.pg_bin -Force:$Force

# ---- ② 중지 --------------------------------------------------------------------------------
Stop-PhysicsAITasks

# ---- ③ 기존 설치 백업 이동(삭제 없음) -------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $backup | Out-Null
foreach ($p in @('venv', 'migrations')) {
    $src = Join-Path $root $p
    if (Test-Path $src) { Move-Item -Path $src -Destination (Join-Path $backup $p) }
}
if (Test-Path $cfg.caddy_frontend_root) { Move-Item -Path $cfg.caddy_frontend_root -Destination (Join-Path $backup 'frontend_dist') }
Write-Step "기존 venv·migrations·프런트를 이동했습니다: $backup"

try {
    # ---- ④ 새 설치 ---------------------------------------------------------------------------
    & $basePy.Exe -m venv (Join-Path $root 'venv'); Assert-Ok 'venv 생성'
    & $venvPy -m pip install --no-index --find-links (Join-Path $pkg 'wheels') physicsai-platform; Assert-Ok 'wheel 설치'
    Copy-Item -Recurse -Force (Join-Path $pkg 'migrations') (Join-Path $root 'migrations')
    New-Item -ItemType Directory -Force -Path $cfg.caddy_frontend_root | Out-Null
    Copy-Item -Recurse -Force (Join-Path $pkg 'frontend\*') $cfg.caddy_frontend_root

    # ---- ⑤ migration(머신 환경변수의 DB URL을 이 프로세스로) -----------------------------------
    $env:PHYSICSAI_DATABASE_URL = [Environment]::GetEnvironmentVariable('PHYSICSAI_DATABASE_URL', 'Machine')
    $env:PHYSICSAI_CONFIG = $cfg.config_path
    Invoke-PhysicsAIMigration -VenvPy $venvPy -AlembicIni (Join-Path $root 'migrations\alembic.ini')

    # ---- ⑥ 시작·health(/physicsai/api/health) ------------------------------------------------
    Start-PhysicsAITasksAndWait -Port $port -LogDir (Join-Path $root 'logs') | Out-Null
    Write-Step "업데이트 완료 — health OK"
} catch {
    # ---- ⑦ 되돌리는 방법 안내(자동 되돌림 없음) ----------------------------------------------------
    Write-Warning "업데이트 실패: $($_.Exception.Message)"
    Write-Warning "되돌리기: 작업 2개를 중지하고, 새 venv·migrations·프런트 폴더를 다른 이름으로 옮긴 뒤"
    Write-Warning "  $backup 의 venv·migrations·frontend_dist 를 원래 위치($root, $($cfg.caddy_frontend_root))로 이동하고 작업을 시작하세요"
    Write-Warning "  DB migration이 이미 올라갔다면 downgrade는 지원하지 않습니다 — 백업 DB 복원 절차를 따르세요"
    throw
}
