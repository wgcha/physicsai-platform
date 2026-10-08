<#
.SYNOPSIS
  PhysicsAI Windows 폐쇄망 설치(phase2 §11). 실제 Windows 실행은 사용자 E2E로 확인한다(미검증).
.DESCRIPTION
  ① 관리자 권한·Python 3.13 확인 ② venv 생성·오프라인 wheel 설치 ③ 프런트 배치 ④ 설정 파일(없을 때만 예시 복사)
  ⑤ DB 역할·DB(없을 때만 생성) ⑥ 머신 환경변수 PHYSICSAI_CONFIG·PHYSICSAI_DATABASE_URL ⑦ alembic upgrade head
  ⑧ 작업 스케줄러 등록(PhysicsAI-Backend, PhysicsAI-Worker) ⑨ 시작·health 확인 ⑩ Caddy 스니펫 안내.
  경로 문자열은 deploy.json(예: deploy.example.json 복사)과 매개변수에만 있다. 비밀번호는 Read-Host -AsSecureString으로
  받아 PGPASSWORD 프로세스 환경변수로만 전달하고 로그·파일·명령 인자에 남기지 않는다.
.PARAMETER ConfigFile
  설치 매개변수 JSON(기본: 이 폴더의 deploy.json).
.PARAMETER ServiceUser
  작업 실행 계정(기본 deploy.json service_user). NT AUTHORITY\SYSTEM이 아닌, AI 루트·Altair 라이선스 접근 권한이 있는 계정.
.PARAMETER RunMode
  Background(로그온 여부와 관계없이, 세션 0) | Interactive(로그온 사용자 세션). 기본 deploy.json run_mode.
#>
[CmdletBinding()]
param(
    [string]$ConfigFile = (Join-Path $PSScriptRoot 'deploy.json'),
    [string]$ServiceUser,
    [ValidateSet('Background', 'Interactive')][string]$RunMode
)
$ErrorActionPreference = 'Stop'

function Write-Step([string]$m) { Write-Host "[PhysicsAI 설치] $m" }
function Assert-Ok([string]$what) { if ($LASTEXITCODE -ne 0) { throw "$what 실패(종료코드 $LASTEXITCODE)" } }
function ConvertTo-Plain([Security.SecureString]$s) {
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

# ---- 매개변수 -------------------------------------------------------------------
if (-not (Test-Path $ConfigFile)) { throw "설치 매개변수 파일이 없습니다: $ConfigFile (deploy.example.json을 복사해 수정하세요)" }
$cfg = Get-Content -Raw -Encoding UTF8 $ConfigFile | ConvertFrom-Json
if (-not $ServiceUser) { $ServiceUser = $cfg.service_user }
if (-not $RunMode) { $RunMode = $cfg.run_mode }
$root = $cfg.install_root
$pkg = Split-Path -Parent $PSScriptRoot          # 오프라인 묶음 루트(wheels, frontend, migrations, config, deploy)
$venvPy = Join-Path $root 'venv\Scripts\python.exe'
$psql = Join-Path $cfg.pg_bin 'psql.exe'

# ---- ① 관리자 권한·Python 3.13 --------------------------------------------------------
$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw '관리자 권한 PowerShell에서 실행하세요' }
$pyver = & $cfg.python_exe -c "import sys; print('%d.%d' % sys.version_info[:2])"
Assert-Ok 'Python 확인'
if ($pyver.Trim() -ne '3.13') { throw "Python 3.13이 필요합니다(현재 $pyver): $($cfg.python_exe)" }

# ---- ② venv + 오프라인 wheel -------------------------------------------------------------
Write-Step "venv 생성: $root\venv"
New-Item -ItemType Directory -Force -Path $root | Out-Null
& $cfg.python_exe -m venv (Join-Path $root 'venv'); Assert-Ok 'venv 생성'
& $venvPy -m pip install --no-index --find-links (Join-Path $pkg 'wheels') physicsai-platform; Assert-Ok 'wheel 설치'
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

# ---- ⑤ DB(없을 때만) — 비밀번호는 PGPASSWORD 프로세스 환경으로만 --------------------------------
$adminPw = Read-Host -AsSecureString 'PostgreSQL 관리자(postgres) 비밀번호'
$appPwSecure = Read-Host -AsSecureString "앱 DB 역할($($cfg.db_role)) 비밀번호"
$appPw = ConvertTo-Plain $appPwSecure
$env:PGPASSWORD = ConvertTo-Plain $adminPw
try {
    $common = @('-h', $cfg.pg_host, '-p', [string]$cfg.pg_port, '-U', 'postgres', '-v', 'ON_ERROR_STOP=1', '-q')
    $hasRole = & $psql @common -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname = '$($cfg.db_role)'"; Assert-Ok 'psql 역할 확인'
    if (-not $hasRole) {
        Write-Step "DB 역할 생성: $($cfg.db_role)"
        # 비밀번호가 서버 로그에 남지 않게: 이 세션만 문장 로그·오류 문장 로그·느린 문장 로그를 끈 뒤 생성(superuser 세션 SET)
        # SQL은 표준 입력으로(명령 인자에 비밀번호 없음)
        $sql = "SET log_statement = 'none'; SET log_min_error_statement = 'panic'; SET log_min_duration_statement = -1; " +
            "SET password_encryption = 'scram-sha-256'; " +
            "CREATE ROLE `"$($cfg.db_role)`" LOGIN PASSWORD '" + $appPw.Replace("'", "''") + "';"
        $sql | & $psql @common -d postgres; Assert-Ok 'CREATE ROLE'
        Remove-Variable -Name sql -ErrorAction SilentlyContinue
    }
    $hasDb = & $psql @common -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$($cfg.db_name)'"; Assert-Ok 'psql DB 확인'
    if (-not $hasDb) {
        Write-Step "DB 생성: $($cfg.db_name)"
        "CREATE DATABASE `"$($cfg.db_name)`" OWNER `"$($cfg.db_role)`";" | & $psql @common -d postgres; Assert-Ok 'CREATE DATABASE'
    }
} finally {
    Remove-Variable -Name adminPw -ErrorAction SilentlyContinue
    $env:PGPASSWORD = $null
}

# ---- ⑥ 머신 환경변수 ----------------------------------------------------------------------
$url = "postgresql+psycopg://$($cfg.db_role):$([Uri]::EscapeDataString($appPw))@$($cfg.pg_host):$($cfg.pg_port)/$($cfg.db_name)"
[Environment]::SetEnvironmentVariable('PHYSICSAI_CONFIG', $cfg.config_path, 'Machine')
[Environment]::SetEnvironmentVariable('PHYSICSAI_DATABASE_URL', $url, 'Machine')
$env:PHYSICSAI_CONFIG = $cfg.config_path
$env:PHYSICSAI_DATABASE_URL = $url
Write-Step '머신 환경변수 PHYSICSAI_CONFIG·PHYSICSAI_DATABASE_URL 설정(값은 출력하지 않음)'

# ---- ⑦ migration --------------------------------------------------------------------------
& $venvPy -m alembic -c (Join-Path $root 'migrations\alembic.ini') upgrade head; Assert-Ok 'alembic upgrade head'

# ---- ⑧ 작업 스케줄러 등록 -----------------------------------------------------------------------
# ExecutionTimeLimit = 0(무제한) 필수 — 기본 72시간이면 장시간 작업 중 워커가 종료된다(phase2 §11.1)
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
if ($RunMode -eq 'Interactive') {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $ServiceUser
} else {
    $trigger = New-ScheduledTaskTrigger -AtStartup
}
$tasks = @(
    @{ Name = 'PhysicsAI-Backend'; Args = '-m physicsai_api.serve' },
    @{ Name = 'PhysicsAI-Worker'; Args = '-m physicsai_worker' }
)
if ($RunMode -eq 'Interactive') {
    $principal = New-ScheduledTaskPrincipal -UserId $ServiceUser -LogonType Interactive -RunLevel Limited
} else {
    $svcPw = Read-Host -AsSecureString "작업 실행 계정($ServiceUser) 비밀번호"
}
foreach ($t in $tasks) {
    $action = New-ScheduledTaskAction -Execute $venvPy -Argument $t.Args -WorkingDirectory $root
    if (Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false
    }
    if ($RunMode -eq 'Interactive') {
        Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
    } else {
        Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings `
            -User $ServiceUser -Password (ConvertTo-Plain $svcPw) -RunLevel Limited | Out-Null
    }
    Write-Step "작업 등록: $($t.Name) ($RunMode)"
}
Remove-Variable -Name appPw, appPwSecure, svcPw -ErrorAction SilentlyContinue

# ---- ⑨ 시작·health ------------------------------------------------------------------------
foreach ($t in $tasks) { Start-ScheduledTask -TaskName $t.Name }
$health = "http://127.0.0.1:$($cfg.backend_port)/physicsai/api/health"
$ok = $false
for ($i = 0; $i -lt 30 -and -not $ok; $i++) {
    Start-Sleep -Seconds 2
    try { $r = Invoke-RestMethod -Uri $health -TimeoutSec 3; $ok = ($r.status -eq 'ok') } catch { $ok = $false }
}
if (-not $ok) { throw "health 확인 실패: $health — 작업 스케줄러 기록과 설정을 확인하세요" }
Write-Step "health OK: $health"

# ---- ⑩ Caddy 안내 --------------------------------------------------------------------------
Write-Step "대시보드 Caddyfile의 catch-all handle 앞에 $(Join-Path $PSScriptRoot 'caddy\physicsai.caddy') 내용을 넣고"
Write-Step "환경변수 PHYSICSAI_PORT=$($cfg.backend_port), PHYSICSAI_FRONTEND_ROOT=$($cfg.caddy_frontend_root) 로 Caddy를 다시 읽으세요"
Write-Step '원본 반입 자원(resources.*)은 RESOURCES.txt를 참고해 배치하고 "관리 > 환경 점검"으로 확인하세요'
