<#
.SYNOPSIS
  PhysicsAI git 폴더 설치(setup.ps1)의 업데이트. git pull은 사용자가 먼저 하고, 이 스크립트 하나로 반영한다.
.DESCRIPTION
  관리자 권한 Windows PowerShell에서 git 폴더 루트에서:
    git pull
    powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\update-repo.ps1
  ① 대기·실행 중 작업·진행 중 환경 점검 확인(대시보드 세션 토큰이면 /physicsai/api/queue, Enter·-NonInteractive면 DB 직접) → 있으면 중단(-Force면 진행)
  ② 작업 2개 중지 ③ venv 패키지 갱신(requirements.lock → simdash_adapters → 플랫폼, 일반 설치 — 새 소스 반영)
  ④ 설정 보충(setup_config.py: 기존 값 유지, 새로 생긴 관리 키만 보충 — 바뀌면 먼저 _backup 복사) ⑤ 프런트 재빌드(Node 22) → <런타임>\frontend(이전 것은 _backup)
  ⑥ alembic upgrade head ⑦ 작업 시작·health. 실패하면 되돌리는 방법을 안내(자동 되돌림 없음).
  설치 정보는 <git>\.runtime\deploy.json(setup.ps1이 만든 것)에서 읽는다.
.PARAMETER Force
  대기·실행 중 작업이 있어도 진행(실행 중 작업은 lease 만료 후 INTERRUPTED)
.PARAMETER NonInteractive
  묻지 않는다(대기열은 DB로 직접 확인)
.PARAMETER NoStart
  작업 시작·health 확인을 하지 않는다
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$NonInteractive,
    [switch]$NoStart
)
$ErrorActionPreference = 'Stop'
$PhysicsAITag = 'PhysicsAI 업데이트'
. (Join-Path $PSScriptRoot 'install-common.ps1')
. (Join-Path $PSScriptRoot 'python-select.ps1')
. (Join-Path $PSScriptRoot 'node-select.ps1')
. (Join-Path $PSScriptRoot 'dashboard-env.ps1')
function Write-Step([string]$m) { Write-PhysicsAIStep $m }

$repo = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
$rt = Join-Path $repo '.runtime'
$deployPath = Join-Path $rt 'deploy.json'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$backupDir = Join-Path $rt "_backup\$stamp"
if (-not (Test-Path -LiteralPath $deployPath)) {
    throw "git 폴더 설치 정보가 없습니다: $deployPath`n다음 행동: 먼저 설치하세요 — powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\setup.ps1"
}
Assert-PhysicsAIAdmin "cd `"$repo`"; powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\update-repo.ps1"
$cfg = Get-Content -Raw -Encoding UTF8 -LiteralPath $deployPath | ConvertFrom-Json
$venvPy = Join-Path $rt 'venv\Scripts\python.exe'
$git = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($git) {
    $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $head = "$(& $git.Source -C $repo log -1 --format='%h %s' 2>$null)" } finally { $ErrorActionPreference = $eap }
    if ($head) { Write-Step "git 폴더: $repo — 현재 커밋 $head" }
}
$mCfg = [Environment]::GetEnvironmentVariable('PHYSICSAI_CONFIG', 'Machine')
if ($mCfg -and -not (Test-PhysicsAIUnderPath $mCfg $rt)) {
    Write-Warning "머신 환경변수 PHYSICSAI_CONFIG가 이 git 폴더 설치가 아닌 곳을 가리킵니다: $mCfg — setup.ps1을 다시 실행하세요"
}
$dash = $null
if ($cfg.dashboard_root -and (Test-Path -LiteralPath $cfg.dashboard_root)) { $dash = Get-DashboardRuntimeDefaults -DashboardRoot $cfg.dashboard_root }

# venv가 Python 3.12로 실행되지 않으면(대시보드 Python 교체 등) 옮기고 새로 만든다 — 아무것도 바꾸기 전에 Python부터 확인
$why = ''
$venvOk = (Test-Path -LiteralPath $venvPy) -and (Test-PhysicsAIPython312 -Exe $venvPy -Reason ([ref]$why))
$basePy = $null
if (-not $venvOk) {
    $cands = Get-PhysicsAIPythonCandidates -PythonExe "$($cfg.python_exe)" -DashboardPython $(if ($dash) { "$($dash.PythonExe)" } else { '' })
    $basePy = Select-PhysicsAIPython -Candidates $cands -Tag $PhysicsAITag
}
$port = Get-PhysicsAIBackendPort $cfg.config_path $(if ($venvOk) { $venvPy } else { '' })

# ---- ① 실행 중 작업 확인 · ② 중지 -----------------------------------------------------------------------
Assert-PhysicsAINoActiveJobs -Port $port -PgBin $cfg.pg_bin -Force:$Force -NonInteractive:$NonInteractive
Stop-PhysicsAITasks
Write-Step '작업 2개 중지'

try {
    # ---- ③ venv 패키지 갱신 -------------------------------------------------------------------
    if (-not $venvOk) {
        if (Test-Path -LiteralPath (Join-Path $rt 'venv')) {
            New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
            Move-Item -LiteralPath (Join-Path $rt 'venv') -Destination (Join-Path $backupDir 'venv')
            Write-Step "기존 venv가 Python 3.12로 실행되지 않아($why) 옮겼습니다: $backupDir\venv"
        }
        Invoke-PhysicsAINative 'venv 생성' $basePy.Exe @('-m', 'venv', (Join-Path $rt 'venv'))
    }
    Install-PhysicsAIRepoPackages -VenvPy $venvPy -RepoRoot $repo

    # ---- ④ 설정 보충(기존 값 유지) -------------------------------------------------------------------
    $inputs = [ordered]@{ repo_root = $repo; runtime_dir = $rt; stamp = $stamp; deploy_defaults = [ordered]@{}; deploy_explicit = [ordered]@{}; legacy_config = '' }
    $result = Invoke-PhysicsAISetupConfig -VenvPy $venvPy -Action write -RuntimeDir $rt -Inputs $inputs
    foreach ($w in @($result.warnings)) { if ($w) { Write-Warning $w } }
    Write-PhysicsAIConfigValidation -Result $result | Out-Null

    # ---- ⑤ 프런트 재빌드 ------------------------------------------------------------------------
    $node = Select-PhysicsAINode -DashboardNode $(if ($dash) { "$($dash.NodeExe)" } else { '' }) -RepoRoot $repo -Tag $PhysicsAITag
    $dist = Invoke-PhysicsAIFrontendBuild -Node $node -RepoRoot $repo -StampFile (Join-Path $rt 'frontend-deps.sha256')
    Publish-PhysicsAIFrontend -Dist $dist -Dest $cfg.caddy_frontend_root -BackupDir $backupDir

    # ---- ⑥ migration(머신 환경변수의 DB URL을 이 프로세스로) ------------------------------------------
    $env:PHYSICSAI_DATABASE_URL = [Environment]::GetEnvironmentVariable('PHYSICSAI_DATABASE_URL', 'Machine')
    $env:PHYSICSAI_CONFIG = $cfg.config_path
    Invoke-PhysicsAIMigration -VenvPy $venvPy -AlembicIni (Join-Path $repo 'migrations\alembic.ini')

    # ---- ⑦ 시작·health ------------------------------------------------------------------------
    $port = Get-PhysicsAIBackendPort $cfg.config_path $venvPy
    if ($NoStart) {
        Write-Step '-NoStart: 작업 시작·health 확인을 건너뜁니다(Start-ScheduledTask -TaskName PhysicsAI-Backend, PhysicsAI-Worker로 시작)'
    } else {
        Start-PhysicsAITasksAndWait -Port $port -LogDir (Join-Path $rt 'logs') | Out-Null
    }
    Write-Step '업데이트 완료'
} catch {
    Write-Warning "업데이트 실패: $($_.Exception.Message)"
    Write-Warning '되돌리기: git으로 이전 커밋을 받은 뒤(git log로 확인 → git checkout <커밋>) 이 스크립트를 다시 실행하세요.'
    Write-Warning "  이전 프런트·venv(옮긴 경우)는 $backupDir 에 있습니다. DB migration이 이미 올라갔다면 downgrade는 지원하지 않습니다 — 백업 DB 복원 절차를 따르세요"
    throw
}
