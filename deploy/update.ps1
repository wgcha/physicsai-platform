<#
.SYNOPSIS
  PhysicsAI 업데이트(phase2 §11.2). 기존 venv·프런트·migrations를 _backup\<UTC>로 이동(삭제 없음)한 뒤 새 묶음 설치.
.DESCRIPTION
  ① 실행 중 작업 확인(GET /physicsai/api/queue — 대시보드 세션 토큰 필요. 토큰이 없으면 DB 직접 조회) → 있으면 중단(-Force면 경고 후 진행)
  ② 작업 2개 중지 ③ 기존 venv·frontend·migrations를 <install_root>\_backup\<UTC>로 이동 ④ 새 wheel·프런트 배치
  ⑤ alembic upgrade head ⑥ 시작·health 확인 ⑦ 실패 시 되돌리는 방법 안내(자동 되돌림 없음)
#>
[CmdletBinding()]
param(
    [string]$ConfigFile = (Join-Path $PSScriptRoot 'deploy.json'),
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
function Write-Step([string]$m) { Write-Host "[PhysicsAI 업데이트] $m" }
function Assert-Ok([string]$what) { if ($LASTEXITCODE -ne 0) { throw "$what 실패(종료코드 $LASTEXITCODE)" } }
function ConvertTo-Plain([Security.SecureString]$s) {
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

$cfg = Get-Content -Raw -Encoding UTF8 $ConfigFile | ConvertFrom-Json
$root = $cfg.install_root
$pkg = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $root 'venv\Scripts\python.exe'
$tasks = @('PhysicsAI-Backend', 'PhysicsAI-Worker')
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$backup = Join-Path $root "_backup\$stamp"

# ---- ① 실행 중 작업 확인 -------------------------------------------------------------------
function Get-ActiveJobCount {
    $tokenSecure = Read-Host -AsSecureString '대시보드 세션 토큰(없으면 Enter — DB에서 직접 확인)'
    $token = ConvertTo-Plain $tokenSecure
    if ($token) {
        $q = Invoke-RestMethod -Uri "http://127.0.0.1:$($cfg.backend_port)/physicsai/api/queue" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 10
        $n = @($q.waiting_hpc).Count + @($q.collecting).Count + @($q.queued).Count + @($q.light.queued).Count
        if ($q.running) { $n++ }
        if ($q.light.running) { $n++ }
        return $n
    }
    # DB 직접 조회: 접속 정보는 머신 환경변수 URL에서 PG* 프로세스 환경으로만 전달(명령 인자에 비밀번호 없음)
    $url = [Environment]::GetEnvironmentVariable('PHYSICSAI_DATABASE_URL', 'Machine')
    $m = [regex]::Match($url, '^postgres(?:ql)?(?:\+\w+)?://(?<u>[^:]+):(?<p>[^@]*)@(?<h>[^:/]+):(?<port>\d+)/(?<d>.+)$')
    if (-not $m.Success) { throw 'PHYSICSAI_DATABASE_URL 형식을 해석할 수 없습니다' }
    $env:PGUSER = $m.Groups['u'].Value; $env:PGHOST = $m.Groups['h'].Value; $env:PGPORT = $m.Groups['port'].Value
    $env:PGDATABASE = $m.Groups['d'].Value; $env:PGPASSWORD = [Uri]::UnescapeDataString($m.Groups['p'].Value)
    try {
        $n = & (Join-Path $cfg.pg_bin 'psql.exe') -tAc "SELECT count(*) FROM jobs WHERE state IN ('QUEUED','RUNNING','WAITING_HPC','COLLECTING')"
        Assert-Ok 'psql 작업 확인'
        return [int]$n
    } finally { $env:PGPASSWORD = $null }
}
$active = Get-ActiveJobCount
if ($active -gt 0) {
    if (-not $Force) { throw "대기·실행 중 작업이 $active 건 있습니다. 끝난 뒤 다시 실행하거나 -Force로 진행하세요" }
    Write-Warning "-Force: 실행 중 작업은 lease 만료 후 INTERRUPTED가 됩니다($active 건)"
}

# ---- ② 중지 --------------------------------------------------------------------------------
foreach ($t in $tasks) { Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 5

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
    & $cfg.python_exe -m venv (Join-Path $root 'venv'); Assert-Ok 'venv 생성'
    & $venvPy -m pip install --no-index --find-links (Join-Path $pkg 'wheels') physicsai-platform; Assert-Ok 'wheel 설치'
    Copy-Item -Recurse -Force (Join-Path $pkg 'migrations') (Join-Path $root 'migrations')
    New-Item -ItemType Directory -Force -Path $cfg.caddy_frontend_root | Out-Null
    Copy-Item -Recurse -Force (Join-Path $pkg 'frontend\*') $cfg.caddy_frontend_root

    # ---- ⑤ migration(머신 환경변수의 DB URL을 이 프로세스로) -----------------------------------
    $env:PHYSICSAI_DATABASE_URL = [Environment]::GetEnvironmentVariable('PHYSICSAI_DATABASE_URL', 'Machine')
    $env:PHYSICSAI_CONFIG = $cfg.config_path
    & $venvPy -m alembic -c (Join-Path $root 'migrations\alembic.ini') upgrade head; Assert-Ok 'alembic upgrade head'

    # ---- ⑥ 시작·health ---------------------------------------------------------------------
    foreach ($t in $tasks) { Start-ScheduledTask -TaskName $t }
    $health = "http://127.0.0.1:$($cfg.backend_port)/physicsai/api/health"
    $ok = $false
    for ($i = 0; $i -lt 30 -and -not $ok; $i++) {
        Start-Sleep -Seconds 2
        try { $ok = ((Invoke-RestMethod -Uri $health -TimeoutSec 3).status -eq 'ok') } catch { $ok = $false }
    }
    if (-not $ok) { throw "health 확인 실패: $health" }
    Write-Step "업데이트 완료 — health OK"
} catch {
    # ---- ⑦ 되돌리는 방법 안내(자동 되돌림 없음) ----------------------------------------------------
    Write-Warning "업데이트 실패: $($_.Exception.Message)"
    Write-Warning "되돌리기: 작업 2개를 중지하고, 새 venv·migrations·프런트 폴더를 다른 이름으로 옮긴 뒤"
    Write-Warning "  $backup 의 venv·migrations·frontend_dist 를 원래 위치($root, $($cfg.caddy_frontend_root))로 이동하고 작업을 시작하세요"
    Write-Warning "  DB migration이 이미 올라갔다면 downgrade는 지원하지 않습니다 — 백업 DB 복원 절차를 따르세요"
    throw
}
