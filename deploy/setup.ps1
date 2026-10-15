<#
.SYNOPSIS
  PhysicsAI 같은 PC·git 폴더 설치(권장). 저장소를 받은 폴더에 그대로 설치한다 — 묶음·압축 없음. 다시 실행해도 안전(이미 있으면 확인 후 갱신).
.DESCRIPTION
  관리자 권한 Windows PowerShell에서 git 폴더 루트에서:
    powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\setup.ps1
  ① Python 3.12 선택(python-select.ps1: -PythonExe > deploy.json > 대시보드 고정 Python > py -3.12 > PATH, 각 후보를 실제 실행해 확인 — 망가진 pyenv shim은 건너뜀)
  ② 런타임 폴더 <git>\.runtime\(git 제외): venv, frontend(빌드 배치), config\platform.yaml, deploy.json, logs, state, _backup
  ③ venv에 deploy\requirements.lock + packages\simdash_adapters + 플랫폼 패키지(일반 설치. 사내 pip 설정·프록시 그대로)
  ④ 설정 계획(setup_config.py): deploy.json·platform.yaml — 이미 있으면 보존하고 빠진 키만 보충(사용자 수정값 덮어쓰기 없음)
     profile prod, server.port 8100, storage.ai_root(폴더 생성), resources.*(원본 앱 폴더 하위 확인), altair.*(탐색), hpc.gateway none, worker 기본값
  ⑤ 확인 표 출력 후 Y/N(-NonInteractive면 생략)
  ⑥ 기존 설치가 있으면 대기열 확인 후 작업 중지 → 설정 작성 → Node 22로 프런트 빌드·배치
  ⑦ DB(대시보드와 같은 PostgreSQL에 physicsai DB·physicsai_app 역할 — 없을 때만, 기존 연결이 되면 비밀번호를 다시 묻지 않음) → 머신 환경변수 → alembic
     → 작업 스케줄러 등록(작업 폴더 <git>\.runtime) → 시작·health  (install-common.ps1 — 묶음 install.ps1과 같은 코드)
  ⑧ 접속 연결 안내: 대시보드 .env VITE_PHYSICSAI_TARGET·SIMDASH_PHYSICSAI_ENABLED=true(백엔드가 /physicsai/ 직접 서빙), Caddy는 대안(physicsai.caddy)
  기존 묶음 설치(install.ps1, 다른 install_root)가 있으면 감지해 그 설정 파일을 복사해 이어받고(원본은 그대로), 같은 DB 연결을 이어 쓰며,
  기존 작업 정의는 .runtime\_backup\<UTC>\tasks\*.xml로 남긴 뒤 새 venv로 다시 등록한다. 덮어쓰는 파일은 먼저 .runtime\_backup\<UTC>로 복사한다.
  업데이트: git pull 후 powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\update-repo.ps1
.PARAMETER DashboardRoot
  대시보드 폴더. 기본: deploy.json 값 → <git 폴더의 부모>\simdashboard(있으면). .env의 POSTGRES_BIN·DATABASE_URL(host·port만)과 .tools의 Python 3.12·Node 22를 쓴다
.PARAMETER AiRoot
  AI 루트(산출물, SPDM master 밖, 공백·특수문자 없는 경로). 기본: deploy.json 값 → <git 폴더의 부모>\physicsai-data
.PARAMETER OriginalAppRoot
  원본 앱 폴더(CONFIG\BATCHRUN·BUILD_PYD·CONFIG\TEMPLATE·CONFIG\DATA가 있는 곳). 비우면(Enter) resources.* 비움 → 그 기능만 비활성
.PARAMETER AltairRoot
  (선택) Altair 설치 폴더($env:ProgramFiles\Altair 또는 그 아래 2026.1 같은 버전 폴더). 비우면 레지스트리(설치 프로그램 목록)·$env:ProgramFiles\Altair\<최신 버전>을 탐색
.PARAMETER PythonExe
  (선택) Python 3.12 python.exe
.PARAMETER ServiceUser
  작업 실행 계정. 기본: deploy.json 값 → 현재 사용자(<도메인>\<이름>)
.PARAMETER RunMode
  Interactive(기본, 그 계정 로그온 세션 — Altair 그래픽 배치용) | Background(로그온 무관, 세션 0 — 계정 비밀번호를 한 번 더 받음)
.PARAMETER NonInteractive
  묻지 않는다(기본값·deploy.json 값 사용, 확인 표 Y/N 생략). 비밀번호가 필요하면 -PasswordsFromEnv
.PARAMETER PasswordsFromEnv
  비밀번호를 화면 입력 대신 프로세스 환경변수에서(PHYSICSAI_INSTALL_PG_ADMIN_PASSWORD, PHYSICSAI_INSTALL_DB_PASSWORD, Background면 PHYSICSAI_INSTALL_SERVICE_PASSWORD)
.PARAMETER NoStart
  작업 등록까지만(시작·health 확인 생략)
.PARAMETER Force
  재실행 때 대기·실행 중 작업이 있어도 진행(실행 중 작업은 INTERRUPTED)
#>
[CmdletBinding()]
param(
    [string]$DashboardRoot = '',
    [string]$AiRoot = '',
    [string]$OriginalAppRoot = '',
    [string]$AltairRoot = '',
    [string]$PythonExe = '',
    [string]$ServiceUser = '',
    [ValidateSet('Background', 'Interactive')][string]$RunMode,
    [switch]$NonInteractive,
    [switch]$PasswordsFromEnv,
    [switch]$NoStart,
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
# 경로 기본값은 본문에서 만든다(Windows PowerShell 5.1은 param 기본값에서 $PSScriptRoot가 빔)
$PhysicsAITag = 'PhysicsAI 설치'
. (Join-Path $PSScriptRoot 'install-common.ps1')
. (Join-Path $PSScriptRoot 'python-select.ps1')
. (Join-Path $PSScriptRoot 'node-select.ps1')
. (Join-Path $PSScriptRoot 'dashboard-env.ps1')
function Write-Step([string]$m) { Write-PhysicsAIStep $m }

$repo = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
$parent = Split-Path -Parent $repo
$rt = Join-Path $repo '.runtime'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$backupDir = Join-Path $rt "_backup\$stamp"
$selfCmd = "cd `"$repo`"; powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\setup.ps1"

# ---- 0. 위치·권한 -----------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath (Join-Path $repo 'pyproject.toml')) -or -not (Test-Path -LiteralPath (Join-Path $repo 'frontend\package.json'))) {
    throw "git 폴더(저장소)가 아닙니다: $repo`n다음 행동: 오프라인 묶음을 풀어 둔 폴더라면 deploy\install.ps1(폐쇄망 서버용)을 쓰세요."
}
Assert-PhysicsAIAdmin $selfCmd
Write-Step "git 폴더: $repo  (런타임 폴더: $rt — git에서 제외)"
New-Item -ItemType Directory -Force -Path $rt | Out-Null

$deployPath = Join-Path $rt 'deploy.json'
$prev = $null
if (Test-Path -LiteralPath $deployPath) {
    $prev = Get-Content -Raw -Encoding UTF8 -LiteralPath $deployPath | ConvertFrom-Json
    Write-Step "기존 설치 발견(deploy.json) — 확인 후 갱신합니다(기존 값 유지, 빠진 값만 보충)"
}
function Get-Prev([string]$Key) {
    if ($prev -and $prev.PSObject.Properties[$Key] -and "$($prev.$Key)" -ne '') { return "$($prev.$Key)" }
    return ''
}

# ---- 기존 묶음 설치(install.ps1) 감지: 머신 환경변수·작업 스케줄러가 .runtime 밖을 가리키면 ------------------------
$legacyConfig = ''
$mCfg = [Environment]::GetEnvironmentVariable('PHYSICSAI_CONFIG', 'Machine')
if ($mCfg -and -not (Test-PhysicsAIUnderPath $mCfg $rt)) {
    if (Test-Path -LiteralPath $mCfg) {
        $legacyConfig = $mCfg
        Write-Step "기존 묶음 설치 감지: 설정 $mCfg — 런타임 설정이 없으면 복사해 이어받습니다(원본 파일은 그대로)"
    } else {
        Write-Step "머신 환경변수 PHYSICSAI_CONFIG가 없는 파일을 가리킵니다($mCfg) — 새 설정으로 바꿉니다"
    }
}
$taskExe = Get-PhysicsAITaskExecute
$legacyTasks = [bool]($taskExe -and -not (Test-PhysicsAIUnderPath $taskExe $rt))
if ($legacyTasks) { Write-Step "기존 작업 스케줄러 등록 감지: $taskExe — 정의를 _backup에 남기고 이 git 폴더의 venv로 다시 등록합니다" }
$legacyDb = ConvertFrom-PhysicsAIDbUrl ([Environment]::GetEnvironmentVariable('PHYSICSAI_DATABASE_URL', 'Machine'))

# ---- 입력 값(명시 인자 > deploy.json > 파생 기본값). -NonInteractive가 아니면 Enter로 기본값 -------------------------
$explicit = [ordered]@{}
function Resolve-FullPath([string]$p) {
    # 상대경로는 현재 PowerShell 위치($PWD) 기준(프로세스 작업 폴더가 아니라)
    return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($p.Trim().Trim('"')).TrimEnd('\')
}
function Resolve-SetupValue {
    param([string]$Key, [string]$Given, [string]$Derived, [string]$Prompt, [switch]$AllowSkip)
    if ($Given) { $v = Resolve-FullPath $Given; $script:explicit[$Key] = $v; return $v }
    $def = Get-Prev $Key
    if (-not $def) { $def = $Derived }
    if ($NonInteractive) { return $def }
    $hint = if ($def) { " [Enter = $def$(if ($AllowSkip) { ", '-' = 비움" })]" } elseif ($AllowSkip) { ' [Enter = 건너뜀]' } else { '' }
    $ans = "$(Read-Host "$Prompt$hint")".Trim().Trim('"')
    if ($AllowSkip -and $ans -eq '-') { $script:explicit[$Key] = ''; return '' }
    if ($ans) { $v = Resolve-FullPath $ans; $script:explicit[$Key] = $v; return $v }
    return $def
}
$derivedDash = Join-Path $parent 'simdashboard'
if (-not (Test-Path -LiteralPath $derivedDash -PathType Container)) { $derivedDash = '' }
$dashRoot = Resolve-SetupValue -Key 'dashboard_root' -Given $DashboardRoot -Derived $derivedDash -Prompt '대시보드 폴더'
$aiRootV = Resolve-SetupValue -Key 'ai_root' -Given $AiRoot -Derived (Join-Path $parent 'physicsai-data') -Prompt 'AI 루트(산출물 폴더, SPDM 밖)'
$origRoot = Resolve-SetupValue -Key 'original_app_root' -Given $OriginalAppRoot -Derived '' -Prompt '원본 앱 폴더(CONFIG\BATCHRUN·BUILD_PYD가 있는 곳)' -AllowSkip
if ($origRoot -and -not (Test-Path -LiteralPath $origRoot -PathType Container)) { throw "원본 앱 폴더가 없습니다: $origRoot" }
if ($AltairRoot) { $altRoot = Resolve-FullPath $AltairRoot; $explicit['altair_root'] = $altRoot } else { $altRoot = Get-Prev 'altair_root' }
if ($ServiceUser) { $svcUser = $ServiceUser; $explicit['service_user'] = $svcUser } else { $svcUser = Get-Prev 'service_user' }
if (-not $svcUser) { $svcUser = "$env:USERDOMAIN\$env:USERNAME" }
# $RunMode는 ValidateSet 변수라 빈 값을 다시 넣을 수 없다 → 별도 변수
if ($RunMode) { $runModeV = $RunMode; $explicit['run_mode'] = $runModeV } else { $runModeV = Get-Prev 'run_mode' }
if ($runModeV -notin @('Background', 'Interactive')) { $runModeV = 'Interactive' }

$dash = $null
if ($dashRoot) {
    $dash = Get-DashboardRuntimeDefaults -DashboardRoot $dashRoot
    Write-Step "대시보드 환경: $dashRoot (POSTGRES_BIN $(if ($dash.PgBin) { '있음' } else { '없음' }), DB 포트 $(if ($dash.PgPort) { $dash.PgPort } else { '없음' }), Python 3.12 $(if ($dash.PythonExe) { '있음' } else { '없음' }), Node 22 $(if ($dash.NodeExe) { '있음' } else { '없음' }))"
}
$pgBin = Get-Prev 'pg_bin'; if (-not $pgBin -and $dash) { $pgBin = "$($dash.PgBin)" }
$pgHost = Get-Prev 'pg_host'; if (-not $pgHost -and $dash) { $pgHost = "$($dash.PgHost)" }; if (-not $pgHost -and $legacyDb) { $pgHost = $legacyDb.Host }
$pgPort = Get-Prev 'pg_port'; if (-not $pgPort -and $dash -and $dash.PgPort) { $pgPort = "$($dash.PgPort)" }; if (-not $pgPort -and $legacyDb) { $pgPort = "$($legacyDb.Port)" }
if (-not $pgBin -or -not $pgHost -or -not $pgPort) {
    throw ("PostgreSQL 위치를 정하지 못했습니다(pg_bin=$pgBin, host=$pgHost, port=$pgPort).`n" +
        "다음 행동: -DashboardRoot <대시보드 폴더>를 주세요(.env의 POSTGRES_BIN·DATABASE_URL을 씁니다). 또는 $deployPath 에 pg_bin·pg_host·pg_port를 쓰세요.")
}
$dbName = Get-Prev 'db_name'; if (-not $dbName) { $dbName = if ($legacyDb) { $legacyDb.Db } else { 'physicsai' } }
$dbRole = Get-Prev 'db_role'; if (-not $dbRole) { $dbRole = if ($legacyDb) { $legacyDb.User } else { 'physicsai_app' } }

# ---- ① Python 3.12 --------------------------------------------------------------------------
$pyFirst = if ($PythonExe) { $PythonExe } else { Get-Prev 'python_exe' }
$cands = Get-PhysicsAIPythonCandidates -PythonExe $pyFirst -DashboardPython $(if ($dash) { "$($dash.PythonExe)" } else { '' })
$basePy = Select-PhysicsAIPython -Candidates $cands -Tag $PhysicsAITag
if ($PythonExe) { $explicit['python_exe'] = $basePy.Exe }

# ---- ② venv(.runtime\venv) — 있으면 재사용, 3.12가 아니면 _backup으로 옮기고 새로 ----------------------------------------
$venv = Join-Path $rt 'venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'
$freshVenv = $false
if (Test-Path -LiteralPath $venvPy) {
    $why = ''
    if (Test-PhysicsAIPython312 -Exe $venvPy -Reason ([ref]$why)) {
        Write-Step "venv 재사용: $venv"
    } else {
        New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
        Move-Item -LiteralPath $venv -Destination (Join-Path $backupDir 'venv')
        Write-Step "기존 venv가 Python 3.12로 실행되지 않아($why) 옮겼습니다: $backupDir\venv"
    }
}
if (-not (Test-Path -LiteralPath $venvPy)) {
    Write-Step "venv 생성: $venv"
    Invoke-PhysicsAINative 'venv 생성' $basePy.Exe @('-m', 'venv', $venv) "런타임 폴더 쓰기 권한과 Python($($basePy.Exe))의 venv 모듈을 확인하세요"
    $freshVenv = $true
}
$hasCore = $false
if (-not $freshVenv) {
    $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & $venvPy -c "import yaml, physicsai_core" 2>$null | Out-Null; $hasCore = ($LASTEXITCODE -eq 0) } finally { $ErrorActionPreference = $eap }
}
if (-not $hasCore) {
    # ③ 처음(또는 패키지가 없는 venv): 설정 계획에 yaml·physicsai_core가 필요하므로 먼저 설치
    Write-Step 'venv에 패키지 설치(requirements.lock → simdash_adapters → 플랫폼, 처음 한 번 몇 분 걸림)'
    Install-PhysicsAIRepoPackages -VenvPy $venvPy -RepoRoot $repo
}

# ---- ④ 설정 계획(파일은 아직 바꾸지 않음) ----------------------------------------------------------------
$defaults = [ordered]@{
    install_mode = 'repo'; repo_root = $repo; install_root = $rt; dashboard_root = $dashRoot; python_exe = $basePy.Exe
    pg_bin = $pgBin; pg_host = $pgHost; pg_port = [int]$pgPort; db_name = $dbName; db_role = $dbRole
    config_path = (Join-Path $rt 'config\platform.yaml'); service_user = $svcUser; run_mode = $runModeV
    caddy_frontend_root = (Join-Path $rt 'frontend'); ai_root = $aiRootV; original_app_root = $origRoot; altair_root = $altRoot
}
$inputs = [ordered]@{ repo_root = $repo; runtime_dir = $rt; stamp = $stamp; deploy_defaults = $defaults; deploy_explicit = $explicit; legacy_config = $legacyConfig; program_files_dirs = @(@($env:ProgramFiles, $env:ProgramW6432) | Where-Object { $_ } | Select-Object -Unique) }
# 대시보드 웹 경로(WINDOWS_WEB_BASE_PATH) → auth.dashboard_public_login_url(없으면 setup_config.py가 .env를 직접 읽거나 기본 /home/, phase3 D3-38)
if ($dash -and $dash.WebBasePath) { $inputs['dashboard_web_base_path'] = "$($dash.WebBasePath)" }
$plan = Invoke-PhysicsAISetupConfig -VenvPy $venvPy -Action plan -RuntimeDir $rt -Inputs $inputs
$d = $plan.deploy

# ---- ⑤ 확인 표 ------------------------------------------------------------------------------------
$resFound = @($plan.resources.PSObject.Properties | Where-Object { $_.Value.found }).Count
$resAll = @($plan.resources.PSObject.Properties).Count
$cfgState = switch ($plan.config_source) {
    'existing' { if ($plan.config_changed) { "기존 유지 + 보충 $(@($plan.config_changed_keys).Count)개" } else { '기존 유지(변경 없음)' } }
    'legacy' { "기존 묶음 설치에서 이어받음($legacyConfig)" }
    default { '새로 만듦(config\platform.example.yaml 기준)' }
}
$rows = @(
    [pscustomobject]@{ 항목 = 'git 폴더(설치 위치)'; 값 = $repo }
    [pscustomobject]@{ 항목 = '런타임 폴더'; 값 = "$rt (venv·frontend·config·logs·deploy.json)" }
    [pscustomobject]@{ 항목 = '대시보드'; 값 = $(if ($d.dashboard_root) { $d.dashboard_root } else { '(없음)' }) }
    [pscustomobject]@{ 항목 = 'Python'; 값 = "$($basePy.Exe) ($($basePy.Version))" }
    [pscustomobject]@{ 항목 = 'PostgreSQL'; 값 = "$($d.pg_host):$($d.pg_port)  DB $($d.db_name) / 역할 $($d.db_role)  (psql: $($d.pg_bin))" }
    [pscustomobject]@{ 항목 = 'AI 루트'; 값 = "$($d.ai_root)$(if (-not (Test-Path -LiteralPath $d.ai_root)) { ' (만듦)' })" }
    [pscustomobject]@{ 항목 = '원본 앱 폴더'; 값 = $(if ($d.original_app_root) { "$($d.original_app_root) — 자원 $resFound/$resAll 찾음" } else { '(건너뜀 — resources.* 비움, 해당 기능 비활성)' }) }
    [pscustomobject]@{ 항목 = 'Altair'; 값 = $(if ($plan.altair.found) { "$($plan.altair.version_label) $($plan.altair.root) — 실행 파일 $($plan.altair.found)/5" } else { '(찾지 못함 — altair.* 비움)' }) }
    [pscustomobject]@{ 항목 = '설정 파일'; 값 = "$($plan.config_path) — $cfgState" }
    [pscustomobject]@{ 항목 = 'deploy.json'; 값 = "$deployPath — $(if (-not $plan.deploy_exists) { '새로 만듦' } elseif ($plan.deploy_changed) { "보충: $(@($plan.deploy_added) -join ', ')$(if (@($plan.deploy_overridden).Count) { " / 인자로 바꿈: $(@($plan.deploy_overridden) -join ', ')" })" } else { '변경 없음' })" }
    [pscustomobject]@{ 항목 = '작업 실행'; 값 = "$($d.service_user) / $($d.run_mode)  (작업 폴더 $rt)" }
    [pscustomobject]@{ 항목 = '프런트 배치'; 값 = $d.caddy_frontend_root }
    [pscustomobject]@{ 항목 = '기존 묶음 설치'; 값 = $(if ($legacyConfig -or $legacyTasks) { "감지 — 설정·DB 이어받기, 작업은 다시 등록(이전 정의는 _backup)" } else { '없음' }) }
)
Write-Host ''
Write-Host ($rows | Format-Table -AutoSize -Wrap | Out-String -Width 240)
$detail = @($plan.config_rows | Where-Object { $_.key -like 'resources.*' -or $_.key -like 'altair.*' -or $_.action -notin @('유지', '예시 값') })
if ($detail.Count) {
    Write-Host '설정 파일 값(관리 대상 키):'
    Write-Host ($detail | Select-Object @{ n = '키'; e = { $_.key } }, @{ n = '처리'; e = { $_.action } }, @{ n = '값'; e = { if ("$($_.value)" -eq '') { '(빈 값)' } else { $_.value } } } | Format-Table -AutoSize -Wrap | Out-String -Width 240)
}
foreach ($w in @($plan.warnings)) { if ($w) { Write-Warning $w } }
if (-not $NonInteractive) {
    $ans = "$(Read-Host '이대로 설치할까요? (Y/N)')".Trim()
    if ($ans -notmatch '^(?i:y|yes|예|ㅛ)$') { Write-Step '취소했습니다(설정 파일·DB·작업 스케줄러는 바꾸지 않았습니다)'; return }
}

# ---- ⑥ 기존 설치 갱신이면 대기열 확인 → 작업 중지(venv 파일 교체 전에) ------------------------------------------
$tasksExist = [bool](Get-ScheduledTask -TaskName 'PhysicsAI-Backend' -ErrorAction SilentlyContinue)
if ($tasksExist) {
    if ([Environment]::GetEnvironmentVariable('PHYSICSAI_DATABASE_URL', 'Machine') -and (Test-Path -LiteralPath (Join-Path $d.pg_bin 'psql.exe'))) {
        $cfgForPort = if ($legacyConfig -and -not (Test-Path -LiteralPath $d.config_path)) { $legacyConfig } else { $d.config_path }
        Assert-PhysicsAINoActiveJobs -Port (Get-PhysicsAIBackendPort $cfgForPort $venvPy) -PgBin $d.pg_bin -Force:$Force
    }
    $n = Export-PhysicsAITasks -Dest (Join-Path $backupDir 'tasks')
    if ($n) { Write-Step "기존 작업 정의를 남겼습니다: $backupDir\tasks" }
    Stop-PhysicsAITasks
    Write-Step '기존 작업 중지'
}
if (-not $freshVenv -and $hasCore) {
    Write-Step 'venv 패키지 갱신(requirements.lock → simdash_adapters → 플랫폼)'
    Install-PhysicsAIRepoPackages -VenvPy $venvPy -RepoRoot $repo
}

# ---- 설정 작성(바뀌는 기존 파일은 먼저 _backup으로 복사) + AI 루트 폴더 -----------------------------------------
$result = Invoke-PhysicsAISetupConfig -VenvPy $venvPy -Action write -RuntimeDir $rt -Inputs $inputs
$d = $result.deploy
Write-PhysicsAIConfigValidation -Result $result | Out-Null

# ---- 프런트 빌드(Node 22) → <런타임>\frontend ------------------------------------------------------------
$node = Select-PhysicsAINode -DashboardNode $(if ($dash) { "$($dash.NodeExe)" } else { '' }) -RepoRoot $repo -Tag $PhysicsAITag
Invoke-PhysicsAIFrontendBuild -Node $node -RepoRoot $repo -StampFile (Join-Path $rt 'frontend-deps.sha256')   # 결과를 변수에 받지 않는다(npm 콘솔 그대로 — D3-39)
Publish-PhysicsAIFrontend -Dist (Join-Path $repo 'frontend\dist') -Dest $d.caddy_frontend_root -BackupDir $backupDir

# ---- ⑦ DB → 머신 환경변수 → alembic → 작업 스케줄러 → 시작·health(install-common.ps1) ----------------------------------
$url = Initialize-PhysicsAIDatabase -PgBin $d.pg_bin -PgHost $d.pg_host -PgPort ([int]$d.pg_port) -DbName $d.db_name -DbRole $d.db_role `
    -PasswordsFromEnv:$PasswordsFromEnv -NonInteractive:$NonInteractive -ReuseExisting
Set-PhysicsAIMachineEnv -ConfigPath $d.config_path -DbUrl $url
Remove-Variable -Name url -ErrorAction SilentlyContinue
Invoke-PhysicsAIMigration -VenvPy $venvPy -AlembicIni (Join-Path $repo 'migrations\alembic.ini')
Register-PhysicsAITasks -VenvPy $venvPy -WorkDir $rt -ServiceUser $d.service_user -RunMode $d.run_mode -PasswordsFromEnv:$PasswordsFromEnv -NonInteractive:$NonInteractive
$port = Get-PhysicsAIBackendPort $d.config_path $venvPy
if ($NoStart) {
    Write-Step '-NoStart: 작업 시작·health 확인을 건너뜁니다(Start-ScheduledTask -TaskName PhysicsAI-Backend, PhysicsAI-Worker로 시작)'
} else {
    Start-PhysicsAITasksAndWait -Port $port -LogDir (Join-Path $rt 'logs') | Out-Null
}

# ---- ⑧ 안내 -----------------------------------------------------------------------------------------
Write-Host ''
Write-Step '설치 완료. 남은 연결 작업:'
Write-PhysicsAIConnectGuide -Port $port -DashboardRoot "$($d.dashboard_root)" -FrontendRoot "$($d.caddy_frontend_root)" -RepoRoot $repo
Write-Step '  3) 관리 > 환경 점검으로 Altair·자원·AI 루트를 확인하세요. 설정은 이 파일에서 고칩니다:'
Write-Step "     $($d.config_path)  (고친 뒤 Stop/Start-ScheduledTask PhysicsAI-Worker, PhysicsAI-Backend)"
Write-Step "업데이트: git pull 후  powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\update-repo.ps1"
if ($legacyConfig -or $legacyTasks) {
    Write-Step '기존 묶음 설치 폴더는 지우지 않았습니다 — 새 설치를 확인한 뒤 필요 없으면 직접 정리하세요(Caddy를 쓰면 PHYSICSAI_FRONTEND_ROOT도 위 값으로 바꿀 것)'
}
