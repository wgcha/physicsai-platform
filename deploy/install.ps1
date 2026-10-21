<#
.SYNOPSIS
  PhysicsAI Windows 폐쇄망 설치(phase2 §11, 오프라인 묶음 방식 — 폐쇄망 서버용. 같은 PC·git 폴더 설치는 setup.ps1). 실제 Windows 실행은 사용자 E2E로 확인한다(미검증).
.DESCRIPTION
  일반 PowerShell(관리자 권한 불필요 — phase3 D3-41. Background 모드 작업 등록만 관리자 권한이 필요할 수 있음).
  ① Python 3.12 확인(대시보드와 같은 3.12.13 권장, python_exe를 실제로 실행 — python-select.ps1) ② venv 생성·오프라인 wheel 설치 ③ 프런트 배치(묶음의 빌드본) ④ 설정 파일(없을 때만 예시 복사)
  ⑤ DB 역할·DB(없을 때만 생성) ⑥ DB 접속 정보 파일 <install_root>\secrets\database_url(현재 사용자·SYSTEM만 읽기 — 머신 환경변수 쓰지 않음) ⑦ alembic upgrade head
  ⑧ 작업 스케줄러 등록(<task_prefix>-Backend, <task_prefix>-Worker, 기본 PhysicsAI-Backend·PhysicsAI-Worker — 인자 --runtime <install_root> --config <config_path>) ⑨ 시작·health 확인 ⑩ Caddy 스니펫 안내.
  경로 문자열은 deploy.json(예: deploy.example.json 복사)과 매개변수에만 있다. 비밀번호는 Read-Host -AsSecureString으로
  받아 PGPASSWORD 프로세스 환경변수로만 전달하고 로그·파일·명령 인자에 남기지 않는다.
  병행 설치(같은 서버에 두 번째 설치): deploy.json task_prefix(기본 "PhysicsAI" — 작업 이름 <prefix>-Backend·<prefix>-Worker)를 설치마다 다르게 주고,
  inherit_existing=false(기본 true)로 이전 설치의 머신 환경변수 DB·작업 정의 이어받기를 끈다(같은 이름 작업이 다른 설치에 있으면 건드리지 않고 중단).
  머신 환경변수 PHYSICSAI_DATABASE_URL이 있으면 경고한다(운영 DB 오접속 방지).
  deploy.json에 dashboard_root(선택)가 있으면 대시보드 .env의 POSTGRES_BIN과 DATABASE_URL의 host·port, 대시보드 고정 Python 3.12를
  pg_bin·pg_host·pg_port·python_exe의 기본값으로 쓴다(deploy.json 명시 값 우선, dashboard-env.ps1). PostgreSQL 서버가 18이 아니면 경고.
.PARAMETER ConfigFile
  설치 매개변수 JSON(기본: 이 폴더의 deploy.json).
.PARAMETER ServiceUser
  작업 실행 계정(기본 deploy.json service_user). NT AUTHORITY\SYSTEM이 아닌, AI 루트·Altair 라이선스 접근 권한이 있는 계정.
.PARAMETER RunMode
  Background(로그온 여부와 관계없이, 세션 0 — 작업 등록에 관리자 권한이 필요할 수 있음) | Interactive(로그온 사용자 세션, 관리자 불필요). 기본 deploy.json run_mode.
.PARAMETER PasswordsFromEnv
  무인 설치(CI·자동화)용: 비밀번호를 대화형 입력 대신 이 프로세스 환경변수에서 읽는다
  (PHYSICSAI_INSTALL_PG_ADMIN_PASSWORD, PHYSICSAI_INSTALL_DB_PASSWORD, Background면 PHYSICSAI_INSTALL_SERVICE_PASSWORD).
  명령 인자로는 받지 않는다. 사용 뒤 호출 쪽에서 환경변수를 지운다.
.PARAMETER NoStart
  작업 등록까지만 하고 시작·health 확인(⑨)은 하지 않는다(CI 검증·나중에 시작할 때).
#>
[CmdletBinding()]
param(
    [string]$ConfigFile = '',   # 비우면 이 스크립트 폴더의 deploy.json (PS 5.1은 param 기본값에서 $PSScriptRoot가 빔)
    [string]$ServiceUser,
    [ValidateSet('Background', 'Interactive')][string]$RunMode,
    [switch]$PasswordsFromEnv,
    [switch]$NoStart
)
$ErrorActionPreference = 'Stop'
if (-not $ConfigFile) { $ConfigFile = Join-Path $PSScriptRoot 'deploy.json' }
$PhysicsAITag = 'PhysicsAI 설치'
. (Join-Path $PSScriptRoot 'install-common.ps1')   # DB·환경변수·alembic·작업 스케줄러·health 공용 함수(setup.ps1과 같은 코드)
function Write-Step([string]$m) { Write-PhysicsAIStep $m }
function Assert-Ok([string]$what) { Assert-PhysicsAIExit $what }

# ---- 매개변수 -------------------------------------------------------------------
if (-not (Test-Path $ConfigFile)) { throw "설치 매개변수 파일이 없습니다: $ConfigFile (deploy.example.json을 복사해 수정하세요)" }
$cfg = Get-Content -Raw -Encoding UTF8 $ConfigFile | ConvertFrom-Json
if (-not $ServiceUser) { $ServiceUser = $cfg.service_user }
if (-not $RunMode) { $RunMode = $cfg.run_mode }
Set-PhysicsAIDeployOptions -Config $cfg     # task_prefix(기본 PhysicsAI)·inherit_existing(기본 true)
Write-PhysicsAIMachineEnvWarning | Out-Null
Write-Step "작업 이름: $((Get-PhysicsAITaskNames) -join ', ') (deploy.json task_prefix=$($cfg.task_prefix), inherit_existing=$($cfg.inherit_existing))"
# 대시보드 실행 환경 재사용(선택): 비어 있는 pg_bin·pg_host·pg_port·python_exe만 대시보드 값으로 채운다(비밀번호·사용자명은 읽지 않음)
if ($cfg.dashboard_root) {
    . (Join-Path $PSScriptRoot 'dashboard-env.ps1')
    $dash = Get-DashboardRuntimeDefaults -DashboardRoot $cfg.dashboard_root
    $filled = Merge-DashboardDefaults -Config $cfg -Defaults $dash
    Write-Step "대시보드 환경($($cfg.dashboard_root)): 기본값으로 채운 키 = $(if ($filled.Count) { $filled -join ', ' } else { '없음(deploy.json 명시 값 사용)' })"
}
foreach ($k in 'pg_bin', 'pg_host', 'pg_port', 'python_exe') {
    if ("$($cfg.$k)" -eq '') { throw "deploy.json에 $k 값이 없습니다(직접 쓰거나 dashboard_root로 대시보드 환경을 지정하세요)" }
}
$root = $cfg.install_root
$pkg = Split-Path -Parent $PSScriptRoot          # 오프라인 묶음 루트(wheels, frontend, migrations, config, deploy)
$venvPy = Join-Path $root 'venv\Scripts\python.exe'

# ---- ① Python 3.12(대시보드와 같은 마이너). 관리자 권한 확인 없음(phase3 D3-41) ---------------------------------
# python_exe를 실제로 실행해 3.12인지 확인(pyenv shim 미설정·Microsoft Store 별칭·다른 버전이면 원인·다음 행동과 함께 중단). 이후 venv는 확인된 실제 실행 파일로 만든다
. (Join-Path $PSScriptRoot 'python-select.ps1')
$basePy = Assert-PhysicsAIPython312 -Exe "$($cfg.python_exe)"
Write-Step "Python $($basePy.Version): $($basePy.Exe)"

# ---- ② venv + 오프라인 wheel -------------------------------------------------------------
Assert-PhysicsAITaskNamesFree -RuntimeDir $root   # inherit_existing=false: 다른 설치의 같은 이름 작업이 있으면 여기서 중단(아무것도 바꾸기 전)
Write-Step "venv 생성: $root\venv"
New-Item -ItemType Directory -Force -Path $root | Out-Null
& $basePy.Exe -m venv (Join-Path $root 'venv'); Assert-Ok 'venv 생성'
& $venvPy -m pip install --no-index --find-links (Join-Path $pkg 'wheels') physicsai-platform; Assert-Ok 'wheel 설치'
& $venvPy -m physicsai_mcp.stdio --version; Assert-Ok 'MCP 실행기 확인(physicsai-mcp --version, mcp.md §20.5)'
Copy-Item -Recurse -Force (Join-Path $pkg 'migrations') (Join-Path $root 'migrations')

# ---- ③ 프런트 배치 ----------------------------------------------------------------------
Write-Step "프런트 배치: $($cfg.caddy_frontend_root)"
New-Item -ItemType Directory -Force -Path $cfg.caddy_frontend_root | Out-Null
Copy-Item -Recurse -Force (Join-Path $pkg 'frontend\*') $cfg.caddy_frontend_root

# ---- ④ 설정 파일(있으면 그대로) -------------------------------------------------------------
if (-not (Test-Path $cfg.config_path)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $cfg.config_path) | Out-Null
    Copy-Item (Join-Path $pkg 'config\platform.example.yaml') $cfg.config_path
    Write-Step "설정 예시를 복사했습니다 — 경로·자원 값을 수정하세요: $($cfg.config_path)"
} else {
    Write-Step "기존 설정 유지: $($cfg.config_path)"
}

# ---- ⑤ DB(없을 때만) — 비밀번호는 Read-Host -AsSecureString(또는 -PasswordsFromEnv), PGPASSWORD 프로세스 환경으로만 ----------
$url = Initialize-PhysicsAIDatabase -PgBin $cfg.pg_bin -PgHost $cfg.pg_host -PgPort ([int]$cfg.pg_port) -DbName $cfg.db_name -DbRole $cfg.db_role `
    -PasswordsFromEnv:$PasswordsFromEnv -ReuseExisting -ExistingUrl (Get-PhysicsAIDbUrl -RuntimeDir $root)

# ---- ⑥ DB 접속 정보 파일(<install_root>\secrets\database_url — 머신 환경변수 대신, 관리자 권한 불필요) ----------------------
Write-PhysicsAIRuntimeSecret -RuntimeDir $root -DbUrl $url -ServiceUser $ServiceUser -ConfigPath $cfg.config_path
Remove-Variable -Name url -ErrorAction SilentlyContinue

# ---- ⑦ migration --------------------------------------------------------------------------
Invoke-PhysicsAIMigration -VenvPy $venvPy -AlembicIni (Join-Path $root 'migrations\alembic.ini')

# ---- ⑧ 작업 스케줄러 등록(ExecutionTimeLimit 0·RestartCount 999·IgnoreNew — install-common.ps1) ---------------------------------
Register-PhysicsAITasks -VenvPy $venvPy -WorkDir $root -ServiceUser $ServiceUser -RunMode $RunMode -RuntimeDir $root -ConfigPath $cfg.config_path `
    -PasswordsFromEnv:$PasswordsFromEnv

# ---- ⑨ 시작·health ------------------------------------------------------------------------
$port = Get-PhysicsAIBackendPort $cfg.config_path $venvPy
if ($NoStart) {
    Write-Step "-NoStart: 작업 시작·health 확인을 건너뜁니다(Start-ScheduledTask -TaskName $((Get-PhysicsAITaskNames) -join ', ')로 시작)"
    return
}
Start-PhysicsAITasksAndWait -Port $port -LogDir (Join-Path $root 'logs') | Out-Null

# ---- ⑩ Caddy 안내 --------------------------------------------------------------------------
Write-Step "대시보드 Caddyfile의 catch-all handle 앞에 $(Join-Path $PSScriptRoot 'caddy\physicsai.caddy') 내용을 넣고"
Write-Step "환경변수 PHYSICSAI_PORT=$port(platform.yaml server.port), PHYSICSAI_FRONTEND_ROOT=$($cfg.caddy_frontend_root) 로 Caddy를 다시 읽으세요"
Write-Step '원본 반입 자원(resources.*)은 RESOURCES.txt를 참고해 배치하고 "관리 > 환경 점검"으로 확인하세요'
