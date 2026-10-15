<#
.SYNOPSIS
  PhysicsAI git 폴더 설치(setup.ps1)의 업데이트. git pull 뒤 이 스크립트 한 번(인자·질문 없음)으로 반영한다.
.DESCRIPTION
  관리자 권한 Windows PowerShell에서 git 폴더 루트에서:
    git pull; powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\update-repo.ps1
  모든 값은 <git>\.runtime\deploy.json(setup.ps1이 만든 것)에서 읽고, 아무것도 묻지 않는다(phase3 D3-39).
  ① 대기·실행 중 작업·진행 중 환경 점검 확인(DB 직접 조회) → 있으면 안내 후 중단(-Force면 진행)
  ② 작업 2개 중지 ③ venv 패키지 갱신(requirements.lock → simdash_adapters → 플랫폼, 일반 설치 — 새 소스 반영)
  ④ 설정 보충(setup_config.py: 기존 값 유지, 새로 생긴 관리 키만 보충 — 바뀌면 먼저 _backup 복사)
  ⑤ 프런트 재빌드(Node 22, npm은 창에서 직접 친 것과 같이 콘솔 그대로 실행 — 실패하면 10초 뒤 한 번 더) → <런타임>\frontend(이전 것은 _backup)
  ⑥ alembic upgrade head ⑦ 작업 시작·health. 끝에 성공/실패와 접속 주소 한 줄.
  ⑥ 전에 실패하면 이전 프런트를 되돌리고 작업 2개를 다시 시작한다(서비스를 멈춘 채 두지 않음). ⑥ 이후 실패는 되돌리는 방법을 안내.
.PARAMETER Force
  대기·실행 중 작업이 있어도 진행(실행 중 작업은 lease 만료 후 INTERRUPTED)
.PARAMETER NonInteractive
  호환용(이 스크립트는 묻는 것이 없다)
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
$accessUrl = Get-PhysicsAIAccessUrl -Dash $null
$cfg = $null
$stopped = $false
$migrationStarted = $false
$stage = '준비'
try {
    if (-not (Test-Path -LiteralPath $deployPath)) {
        throw "git 폴더 설치 정보가 없습니다: $deployPath — 먼저 설치하세요: powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\setup.ps1"
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
    $accessUrl = Get-PhysicsAIAccessUrl -Dash $dash

    # venv가 Python 3.12로 실행되지 않으면(대시보드 Python 교체 등) 옮기고 새로 만든다 — 아무것도 바꾸기 전에 Python부터 확인
    $why = ''
    $venvOk = (Test-Path -LiteralPath $venvPy) -and (Test-PhysicsAIPython312 -Exe $venvPy -Reason ([ref]$why))
    $basePy = $null
    if (-not $venvOk) {
        $cands = Get-PhysicsAIPythonCandidates -PythonExe "$($cfg.python_exe)" -DashboardPython $(if ($dash) { "$($dash.PythonExe)" } else { '' })
        $basePy = Select-PhysicsAIPython -Candidates $cands -Tag $PhysicsAITag
    }
    $port = Get-PhysicsAIBackendPort $cfg.config_path $(if ($venvOk) { $venvPy } else { '' })

    # ---- ① 실행 중 작업 확인(묻지 않고 DB 직접) · ② 중지 ---------------------------------------------------------
    Assert-PhysicsAINoActiveJobs -Port $port -PgBin $cfg.pg_bin -Force:$Force
    $stopped = $true
    Stop-PhysicsAITasks
    Write-Step '작업 2개 중지'

    # ---- ③ venv 패키지 갱신 -------------------------------------------------------------------
    $stage = 'venv 패키지 갱신'
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
    $stage = '설정 보충'
    $inputs = [ordered]@{ repo_root = $repo; runtime_dir = $rt; stamp = $stamp; deploy_defaults = [ordered]@{}; deploy_explicit = [ordered]@{}; legacy_config = ''; program_files_dirs = @(@($env:ProgramFiles, $env:ProgramW6432) | Where-Object { $_ } | Select-Object -Unique) }
    if ($dash -and $dash.WebBasePath) { $inputs['dashboard_web_base_path'] = "$($dash.WebBasePath)" }   # phase3 D3-38
    $result = Invoke-PhysicsAISetupConfig -VenvPy $venvPy -Action write -RuntimeDir $rt -Inputs $inputs
    foreach ($w in @($result.warnings)) { if ($w) { Write-Warning $w } }
    Write-PhysicsAIConfigValidation -Result $result | Out-Null

    # ---- ⑤ 프런트 재빌드(결과를 변수에 받지 않는다 — 받으면 npm 출력이 파이프가 되어 esbuild spawn EPERM, D3-39) ---------
    $stage = '프런트 빌드'
    $node = Select-PhysicsAINode -DashboardNode $(if ($dash) { "$($dash.NodeExe)" } else { '' }) -RepoRoot $repo -Tag $PhysicsAITag
    Invoke-PhysicsAIFrontendBuild -Node $node -RepoRoot $repo -StampFile (Join-Path $rt 'frontend-deps.sha256')
    Publish-PhysicsAIFrontend -Dist (Join-Path $repo 'frontend\dist') -Dest $cfg.caddy_frontend_root -BackupDir $backupDir

    # ---- ⑥ migration(머신 환경변수의 DB URL을 이 프로세스로) ------------------------------------------
    $stage = 'migration'
    $migrationStarted = $true
    $env:PHYSICSAI_DATABASE_URL = [Environment]::GetEnvironmentVariable('PHYSICSAI_DATABASE_URL', 'Machine')
    $env:PHYSICSAI_CONFIG = $cfg.config_path
    Invoke-PhysicsAIMigration -VenvPy $venvPy -AlembicIni (Join-Path $repo 'migrations\alembic.ini')

    # ---- ⑦ 시작·health ------------------------------------------------------------------------
    $stage = '작업 시작'
    $port = Get-PhysicsAIBackendPort $cfg.config_path $venvPy
    if ($NoStart) {
        Write-Step '-NoStart: 작업 시작·health 확인을 건너뜁니다(Start-ScheduledTask -TaskName PhysicsAI-Backend, PhysicsAI-Worker로 시작)'
    } else {
        Start-PhysicsAITasksAndWait -Port $port -LogDir (Join-Path $rt 'logs') | Out-Null
    }
} catch {
    $msg = $_.Exception.Message
    Write-Host ''
    if (-not $stopped) {
        Write-Step "업데이트하지 않았습니다(바꾼 것 없음): $msg"
    } elseif (-not $migrationStarted) {
        Write-Step "업데이트 실패($stage): $msg"   # 프런트 빌드면 'frontend 폴더에서 npm run build를 직접 실행해 결과를 알려 주세요'(node-select.ps1)
        Restore-PhysicsAIAfterFailedUpdate -FrontendDest "$($cfg.caddy_frontend_root)" -BackupDir $backupDir -NoStart:$NoStart
        Write-Step "이전 상태로 계속 쓸 수 있습니다 — 접속: $accessUrl"
    } else {
        Write-Step "업데이트 실패($stage): $msg"
        Write-Step "되돌리기: git checkout <이전 커밋> 뒤 이 스크립트를 다시 실행(이전 프런트·venv: $backupDir). DB migration은 되돌리지 않습니다 — 필요하면 백업 DB 복원"
    }
    exit 1
}
Write-Host ''
Write-Step "업데이트 성공 — 접속: $accessUrl"
