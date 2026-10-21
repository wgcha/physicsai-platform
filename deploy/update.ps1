<#
.SYNOPSIS
  PhysicsAI 업데이트(phase2 §11.2). 기존 venv·프런트·migrations를 _backup\<UTC>로 이동(삭제 없음)한 뒤 새 묶음 설치.
.DESCRIPTION
  일반 PowerShell(관리자 권한 불필요 — phase3 D3-41). 이전 설치의 머신 환경변수 DB URL은 <install_root>\secrets\database_url로 옮긴다(머신 환경변수는 그대로).
  ① 실행 중 작업·진행 중 환경 점검 확인(묻지 않고 DB 직접 조회) → 있으면 중단(-Force면 경고 후 진행)
  ② 작업 2개 중지 ③ 기존 venv·frontend·migrations를 <install_root>\_backup\<UTC>로 이동 ④ 새 wheel·프런트(묶음의 빌드본) 배치
  ④' 작업 인자가 --runtime 방식이 아니면 다시 등록(Interactive만) — 새 코드 배치가 끝난 뒤에만(phase3 D3-42: 그 전에 실패하면 작업 정의는
     이전 그대로라 백업한 이전 venv를 되돌려 놓으면 그대로 시작된다. 이전 코드는 --runtime을 모른다)
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
Set-PhysicsAIDeployOptions -Config $cfg     # task_prefix(기본 PhysicsAI)·inherit_existing(기본 true)
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
Move-PhysicsAIMachineEnvToRuntime -RuntimeDir $root -ServiceUser "$($cfg.service_user)" | Out-Null   # 이전 설치(머신 환경변수) → 런타임 파일
$dbUrl = Get-PhysicsAIDbUrl -RuntimeDir $root

# ---- ① 실행 중 작업 확인(묻지 않고 DB 직접) ----------------------------------
Assert-PhysicsAINoActiveJobs -Port $port -PgBin $cfg.pg_bin -DbUrl $dbUrl -Force:$Force

# ---- ② 중지(작업 인자 갱신은 새 코드 배치 뒤 ④' — D3-42) ------------------------------------------------
Stop-PhysicsAITasks
$taskReg = 'unchanged'   # 작업 등록 상태: unchanged | trying | done (실패 안내용)

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
    & $venvPy -m physicsai_mcp.stdio --version; Assert-Ok 'MCP 실행기 확인(physicsai-mcp --version, mcp.md §20.5)'
    Copy-Item -Recurse -Force (Join-Path $pkg 'migrations') (Join-Path $root 'migrations')
    New-Item -ItemType Directory -Force -Path $cfg.caddy_frontend_root | Out-Null
    Copy-Item -Recurse -Force (Join-Path $pkg 'frontend\*') $cfg.caddy_frontend_root

    # ---- ④' 작업 인자 갱신(--runtime) — 새 venv·프런트 배치가 끝난 뒤에만(D3-42) ------------------------------------
    $taskReg = 'trying'
    $re = Update-PhysicsAITaskRegistration -VenvPy $venvPy -WorkDir $root -RuntimeDir $root -ConfigPath $cfg.config_path -ServiceUser "$($cfg.service_user)" `
        -RunMode $(if ("$($cfg.run_mode)" -eq 'Background') { 'Background' } else { 'Interactive' })
    $taskReg = if (@($re)[-1] -eq $true) { 'done' } else { 'unchanged' }

    # ---- ⑤ migration(DB URL은 런타임 파일 → 이 프로세스 환경으로만) -----------------------------------
    $env:PHYSICSAI_DATABASE_URL = $dbUrl
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
    if ($taskReg -ne 'unchanged') {
        Write-Warning "  작업 인자를 새 방식(--runtime)으로 다시 등록했습니다(또는 등록 도중 실패) — 이전 venv로 되돌리면 이전 묶음의 install.ps1로 작업을 다시 등록해야 시작됩니다"
    } else {
        Write-Warning "  작업 등록(인자)은 바꾸지 않았습니다 — 이전 venv를 되돌리면 그대로 시작됩니다"
    }
    throw
}
