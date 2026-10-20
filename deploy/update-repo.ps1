<#
.SYNOPSIS
  PhysicsAI git 폴더 설치(setup.ps1)의 업데이트. 이 스크립트 한 줄(인자·질문 없음, git pull 포함)로 반영한다.
.DESCRIPTION
  일반 Windows PowerShell(관리자 권한 불필요 — phase3 D3-41)에서, 어느 폴더에서든:
    powershell -NoProfile -ExecutionPolicy Bypass -File <git 폴더>\deploy\update-repo.ps1
  모든 값은 <git>\.runtime\deploy.json(setup.ps1이 만든 것)에서 읽고, 아무것도 묻지 않는다(phase3 D3-39).
  ⓪ git pull --ff-only(스스로 — D3-40, 자격 증명을 묻지 않음 — GIT_TERMINAL_PROMPT=0·credential.interactive=never, 인증 실패는 기다리지 않고
     "바꾼 것 없음"으로 중단). 추적 파일에 로컬 변경이 있으면 안내 후 중단(바꾼 것 없음). 분리된 HEAD(특정 커밋 고정 — 되돌리기)면
     pull 없이 그 커밋으로 반영. 새 커밋을 받았으면 새 update-repo.ps1로 다시 실행한다(-SkipPull).
     이전 설치의 머신 환경변수 DB URL은 런타임 파일(.runtime\secrets\database_url)로 옮긴다(머신 환경변수는 그대로).
  ① 대기·실행 중 작업·진행 중 환경 점검 확인(DB 직접 조회) → 있으면 안내 후 중단(-Force면 진행)
  ② 작업 2개 중지(이전 설치가 관리자 권한으로 만든 작업이라 거부되면 바꾼 것 없이 "처음 한 번만 같은 사용자 계정으로 '관리자 권한으로 실행'" 안내)
  ③ venv 패키지 갱신(requirements.lock → simdash_adapters → 플랫폼, 일반 설치 — 새 소스 반영)
  ④ 설정 보충(setup_config.py: 기존 값 유지, 새로 생긴 관리 키만 보충 — 바뀌면 먼저 _backup 복사)
  ⑤ 프런트 배치: 저장소 빌드본 frontend-dist가 현재 소스와 같으면 그대로 복사(Node·npm 단계 없음, D3-40). 다를 때만 Node 22로 빌드
     (npm은 창에서 직접 친 것과 같이 콘솔 그대로 — 실패하면 10초 뒤 한 번 더) → <런타임>\frontend(이전 것은 _backup)
  ⑤' 작업 인자가 새 방식(--runtime)이 아니면 다시 등록 — venv·프런트가 새 코드로 바뀐 뒤에만(phase3 D3-42: 그 전 단계가 실패하면 작업 정의는
     이전 그대로라 이전 코드가 이전 인자로 다시 시작된다. 이전 코드는 --runtime을 모른다)
  ⑥ alembic upgrade head ⑦ 작업 시작·health. 끝 줄은 "업데이트 성공 — 접속: …" 또는 "업데이트 실패 — 접속: …".
  ⑥ 전에 실패하면 이전 프런트를 되돌리고 작업 2개를 다시 시작한다(서비스를 멈춘 채 두지 않음). ⑥ 이후 실패는 되돌리는 방법을 안내.
.PARAMETER Force
  대기·실행 중 작업이 있어도 진행(실행 중 작업은 lease 만료 후 INTERRUPTED)
.PARAMETER NonInteractive
  호환용(이 스크립트는 묻는 것이 없다)
.PARAMETER NoStart
  작업 시작·health 확인을 하지 않는다
.PARAMETER SkipPull
  git pull 없이 현재 커밋을 반영한다(새 커밋을 받은 뒤 스스로 다시 실행할 때 쓰는 값 — 직접 쓸 일은 드묾)
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$NonInteractive,
    [switch]$NoStart,
    [switch]$SkipPull
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

function Invoke-UpdateGit {
    <#
      git 실행. safe.directory는 이 저장소 경로만·이 실행에만(관리자 계정이 받은 폴더를 일반 사용자가 갱신해도 "dubious ownership"으로 막히지 않게).
      자격 증명을 묻지 않는다(GIT_TERMINAL_PROMPT=0, Git Credential Manager도 GCM_INTERACTIVE=never·credential.interactive=never) —
      인증이 필요하면 기다리지 않고 실패한다(저장된 자격 증명은 그대로 쓰임). 출력·종료코드.
    #>
    param([Parameter(Mandatory = $true)][string[]]$GitArgs, [switch]$Console)
    $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $saved = @{}
    foreach ($k in 'GIT_TERMINAL_PROMPT', 'GCM_INTERACTIVE') { $saved[$k] = [Environment]::GetEnvironmentVariable($k, 'Process') }
    $env:GIT_TERMINAL_PROMPT = '0'
    $env:GCM_INTERACTIVE = 'never'
    $safe = $repo -replace '\\', '/'   # git은 '/' 경로로 비교(Windows도)
    $pre = @('-c', "safe.directory=$safe", '-c', 'credential.interactive=never', '-C', $repo)
    try {
        if ($Console) {   # pull: 출력은 화면으로만(함수 결과에 섞이지 않게 Out-Host, stderr는 콘솔 그대로)
            & $script:gitExe @pre @GitArgs | Out-Host
            return [pscustomobject]@{ Rc = $LASTEXITCODE; Out = '' }
        }
        $o = @(& $script:gitExe @pre @GitArgs 2>&1 | ForEach-Object { "$_" })
        return [pscustomobject]@{ Rc = $LASTEXITCODE; Out = ($o -join "`n").Trim() }
    } finally {
        $ErrorActionPreference = $eap
        foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k], 'Process') }
    }
}

function Sync-UpdateRepo {
    <# ⓪ git pull --ff-only. 새 커밋을 받았으면 $true(호출 쪽이 새 스크립트로 다시 실행). 로컬 변경·pull 실패는 던진다(바꾼 것 없음). #>
    $script:gitExe = (Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
    if (-not $script:gitExe) { Write-Step 'git이 없어 git pull을 건너뜁니다(현재 파일로 반영)'; return $false }
    $top = Invoke-UpdateGit @('rev-parse', '--show-toplevel')
    if ($top.Rc -ne 0 -or -not $top.Out -or ([IO.Path]::GetFullPath($top.Out).TrimEnd('\', '/') -ine $repo)) {
        Write-Step "git 저장소가 아니어서 git pull을 건너뜁니다: $repo"
        return $false
    }
    $before = (Invoke-UpdateGit @('rev-parse', 'HEAD')).Out
    $head = (Invoke-UpdateGit @('log', '-1', '--format=%h %s')).Out
    Write-Step "git 폴더: $repo — 현재 커밋 $head"
    if ($SkipPull) { Write-Step 'git pull 건너뜀(-SkipPull)'; return $false }
    $dirty = Invoke-UpdateGit @('status', '--porcelain', '--untracked-files=no')
    if ($dirty.Rc -ne 0) { throw "git status 실패: $($dirty.Out)" }
    if ($dirty.Out) {
        throw ("git 폴더에 로컬 변경이 있어 업데이트(git pull)를 하지 않았습니다:`n$($dirty.Out)`n" +
            "다음 행동: 변경을 되돌리거나(git -C `"$repo`" checkout -- <파일>) 따로 보관한 뒤 다시 실행하세요. 설정은 .runtime\config\platform.yaml에서 고칩니다(git 밖).")
    }
    if ((Invoke-UpdateGit @('symbolic-ref', '-q', 'HEAD')).Rc -ne 0) {
        Write-Step '분리된 HEAD(특정 커밋 고정 — 되돌리기 상태)라 git pull을 건너뜁니다(이 커밋으로 반영). 최신으로 가려면: git checkout <브랜치>'
        return $false
    }
    if ((Invoke-UpdateGit @('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}')).Rc -ne 0) {
        Write-Step '현재 브랜치에 추적(upstream) 브랜치가 없어 git pull을 건너뜁니다(이 커밋으로 반영). 설정: git branch --set-upstream-to=origin/<브랜치>'
        return $false
    }
    Write-Step 'git pull --ff-only'
    $pull = Invoke-UpdateGit @('pull', '--ff-only') -Console
    if ($pull.Rc -ne 0) {
        throw ("git pull --ff-only 실패(종료코드 $($pull.Rc)) — 위 git 출력을 확인하세요(자격 증명은 묻지 않습니다 — 인증이 필요하면 바로 실패).`n" +
            "다음 행동: 네트워크를 확인하거나, 자격 증명이 필요하면 이 창에서 git -C `"$repo`" pull 을 한 번 직접 실행해 저장한 뒤 다시 실행하세요. " +
            "받은 커밋 그대로 반영하려면 -SkipPull을 붙여 다시 실행하세요.")
    }
    $after = (Invoke-UpdateGit @('rev-parse', 'HEAD')).Out
    if ($after -eq $before) { Write-Step 'git: 이미 최신'; return $false }
    Write-Step "git: $($before.Substring(0, [Math]::Min(7, $before.Length))) → $((Invoke-UpdateGit @('log', '-1', '--format=%h %s')).Out)"
    return $true
}

try {
    if (-not (Test-Path -LiteralPath $deployPath)) {
        throw "git 폴더 설치 정보가 없습니다: $deployPath — 먼저 설치하세요: powershell -NoProfile -ExecutionPolicy Bypass -File $(Join-Path $PSScriptRoot 'setup.ps1')"
    }
    $cfg = Get-Content -Raw -Encoding UTF8 -LiteralPath $deployPath | ConvertFrom-Json
    Set-PhysicsAIDeployOptions -Config $cfg     # task_prefix(기본 PhysicsAI)·inherit_existing(기본 true)
    $dash = $null
    if ($cfg.dashboard_root -and (Test-Path -LiteralPath $cfg.dashboard_root)) { $dash = Get-DashboardRuntimeDefaults -DashboardRoot $cfg.dashboard_root }
    $accessUrl = Get-PhysicsAIAccessUrl -Dash $dash

    # ---- ⓪ git pull — 새 커밋이면 새 스크립트로 다시 실행(콘솔 그대로 물려줌: npm 콘솔 규칙 D3-39 유지) ----------------------
    $stage = 'git pull'
    if (Sync-UpdateRepo) {
        $hostExe = (Get-Process -Id $PID).Path
        Write-Step '받은 새 버전의 update-repo.ps1로 이어서 실행합니다'
        $relaunch = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath, '-SkipPull')
        if ($Force) { $relaunch += '-Force' }
        if ($NoStart) { $relaunch += '-NoStart' }
        $ErrorActionPreference = 'Continue'   # 자식의 stderr로 중단되지 않게(종료코드로만 판단)
        & $hostExe @relaunch
        exit $LASTEXITCODE
    }
    $stage = '준비'
    $venvPy = Join-Path $rt 'venv\Scripts\python.exe'
    $mCfg = Get-PhysicsAIMachineEnv 'PHYSICSAI_CONFIG'
    if ($mCfg -and -not (Test-PhysicsAIUnderPath $mCfg $rt)) {
        Write-Warning "이전 설치의 머신 환경변수 PHYSICSAI_CONFIG가 이 git 폴더 설치가 아닌 곳을 가리킵니다: $mCfg — 이 설치의 작업은 --runtime으로 $($cfg.config_path)를 씁니다"
    }
    # 이전 설치(관리자 권한, 머신 환경변수) → 런타임 파일(값은 출력하지 않음, 머신 환경변수는 그대로)
    Move-PhysicsAIMachineEnvToRuntime -RuntimeDir $rt -ServiceUser "$($cfg.service_user)" | Out-Null
    $dbUrl = Get-PhysicsAIDbUrl -RuntimeDir $rt

    # venv가 Python 3.12로 실행되지 않으면(대시보드 Python 교체 등) 옮기고 새로 만든다 — 아무것도 바꾸기 전에 Python부터 확인
    $why = ''
    $venvOk = (Test-Path -LiteralPath $venvPy) -and (Test-PhysicsAIPython312 -Exe $venvPy -Reason ([ref]$why))
    $basePy = $null
    if (-not $venvOk) {
        $cands = Get-PhysicsAIPythonCandidates -PythonExe "$($cfg.python_exe)" -DashboardPython $(if ($dash) { "$($dash.PythonExe)" } else { '' })
        $basePy = Select-PhysicsAIPython -Candidates $cands -Tag $PhysicsAITag
    }
    $port = Get-PhysicsAIBackendPort $cfg.config_path $(if ($venvOk) { $venvPy } else { '' })

    # ---- ① 실행 중 작업 확인(묻지 않고 DB 직접) · ② 중지(거부되면 바꾼 것 없이 안내) ---------------------------------------
    Assert-PhysicsAINoActiveJobs -Port $port -PgBin $cfg.pg_bin -DbUrl $dbUrl -Force:$Force
    Stop-PhysicsAITasks
    $stopped = $true
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
    $inputs['computer_name'] = "$env:COMPUTERNAME"; $inputs['smb_shares'] = @(Get-PhysicsAISmbShares)   # 받은 파일 공유 안내(phase3 D3-46)
    $result = Invoke-PhysicsAISetupConfig -VenvPy $venvPy -Action write -RuntimeDir $rt -Inputs $inputs
    foreach ($w in @($result.warnings)) { if ($w) { Write-Warning $w } }
    Write-PhysicsAIConfigValidation -Result $result | Out-Null

    # ---- ⑤ 프런트: 저장소 빌드본(frontend-dist)이 소스와 같으면 그대로, 아니면 Node 22로 빌드(D3-40) -----------------------
    # 결과를 변수에 받지 않는다 — 받으면 npm 출력이 파이프가 되어 esbuild spawn EPERM(D3-39)
    $stage = '프런트 배치'
    Install-PhysicsAIFrontendFromRepo -RepoRoot $repo -Dest $cfg.caddy_frontend_root -BackupDir $backupDir `
        -DashboardNode $(if ($dash) { "$($dash.NodeExe)" } else { '' }) -StampFile (Join-Path $rt 'frontend-deps.sha256')

    # ---- ⑤' 작업 인자 갱신(--runtime) — venv·프런트가 새 코드가 된 뒤에만(D3-42). 이전 단계가 실패하면 작업 정의는 이전 그대로 -------
    $stage = '작업 등록'
    $runMode = if ("$($cfg.run_mode)" -eq 'Background') { 'Background' } else { 'Interactive' }
    Update-PhysicsAITaskRegistration -VenvPy $venvPy -WorkDir $rt -RuntimeDir $rt -ConfigPath $cfg.config_path -ServiceUser "$($cfg.service_user)" -RunMode $runMode | Out-Null

    # ---- ⑥ migration(DB URL은 런타임 파일 → 이 프로세스 환경으로만) ------------------------------------------
    $stage = 'migration'
    $migrationStarted = $true
    if (-not $dbUrl) { throw "DB 접속 정보가 없습니다: $(Get-PhysicsAIRuntimeSecretPath $rt) — setup.ps1을 다시 실행하세요" }
    $env:PHYSICSAI_DATABASE_URL = $dbUrl
    $env:PHYSICSAI_CONFIG = $cfg.config_path
    Invoke-PhysicsAIMigration -VenvPy $venvPy -AlembicIni (Join-Path $repo 'migrations\alembic.ini')

    # ---- ⑦ 시작·health ------------------------------------------------------------------------
    $stage = '작업 시작'
    $port = Get-PhysicsAIBackendPort $cfg.config_path $venvPy
    if ($NoStart) {
        Write-Step "-NoStart: 작업 시작·health 확인을 건너뜁니다(Start-ScheduledTask -TaskName $((Get-PhysicsAITaskNames) -join ', ')로 시작)"
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
    Write-Step "업데이트 실패 — 접속: $accessUrl"
    exit 1
}
Write-Host ''
Write-Step "업데이트 성공 — 접속: $accessUrl"
