<#
.SYNOPSIS
  PhysicsAI 시연 모드 원클릭 시작(Altair 없는 Windows PC). 관리자 권한 불필요.
.DESCRIPTION
  가짜 도구(fake tools)로 화면·대기열·알림·취소·리소스 제한·①~⑤ 흐름을 실제로 돌려 본다.
  ① Python 준비(저장소·묶음 공통): Python 3.12를 골라 <시연 폴더>\venv를 만들고 거기에만 설치
     (묶음: wheels / 저장소: packages\simdash_adapters → deploy\requirements.lock, 이미 설치돼 있으면 건너뜀. 프런트 빌드가 없으면 Node 22로 빌드)
  ② demo_setup.py init: 시연 폴더·가짜 도구(.exe)·가짜 자원·설정(<시연 폴더>\config\platform.yaml)
  ③ DB: 시연 전용 PostgreSQL 클러스터(<시연 폴더>\pgdata, 127.0.0.1:PgPort, trust) 또는 -UseExistingDb
  ④ demo_setup.py up: migration → 백엔드(프런트 정적 서빙 포함) → 시연 Study·샘플 데이터 → 워커
  ⑤ 브라우저로 http://127.0.0.1:<Port>/ 열기 → 시연 사용자(관리자·파워·일반) 선택
  끝내기: stop-demo.ps1 (파일·DB는 지우지 않는다)
.PARAMETER DemoRoot
  시연 폴더(공백·특수문자 없는 경로). 기본 <시스템 드라이브>\physicsai-demo
.PARAMETER Port
  백엔드 포트(127.0.0.1 전용). 운영 설치(8100)와 겹치지 않게 기본 8190
.PARAMETER PythonExe
  Python 3.12(대시보드와 같은 3.12.13 권장). 선택 순서: -PythonExe > -DashboardRoot의 고정 Python 3.12 > py -3.12 > PATH의 python.
  각 후보를 실제로 실행해 3.12인지 확인하고, 실패하면(pyenv shim 미설정 등) 다음 후보로 간다. 시연 venv를 만들 때만 쓴다
.PARAMETER PgBin
  PostgreSQL bin 폴더(initdb.exe·pg_ctl.exe·psql.exe, 기준 18). 비우면 -DashboardRoot의 .env POSTGRES_BIN → PATH → PGBIN 환경변수 순으로 찾는다
.PARAMETER DashboardRoot
  대시보드 폴더(예 E:\simulation_workbench, 선택). .env의 POSTGRES_BIN과 .tools 고정 Python 3.12를 기본값으로 쓴다(비밀번호는 읽지 않음)
.PARAMETER PgPort
  시연 전용 PostgreSQL 포트(기본 55432)
.PARAMETER UseExistingDb
  시연 클러스터 대신 기존 PostgreSQL의 빈 DB 사용. 접속 URL은 환경변수 PHYSICSAI_DEMO_DATABASE_URL로 준다(명령 인자에 비밀번호 금지)
.PARAMETER ToolDelay
  가짜 도구 1회 실행마다 넣는 지연(초). 대기열·진행률·취소를 보기 쉽게. 기본 3
.PARAMETER NoBrowser
  브라우저를 열지 않는다
#>
[CmdletBinding()]
param(
    [string]$DemoRoot = (Join-Path $env:SystemDrive 'physicsai-demo'),
    [int]$Port = 8190,
    [string]$PythonExe = '',
    [string]$PgBin = '',
    [string]$DashboardRoot = '',
    [int]$PgPort = 55432,
    [switch]$UseExistingDb,
    [double]$ToolDelay = 3,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
function Write-Step([string]$m) { Write-Host "[PhysicsAI 시연] $m" }
function Assert-Ok([string]$what) { if ($LASTEXITCODE -ne 0) { throw "$what 실패(종료코드 $LASTEXITCODE)" } }

if ($DemoRoot -match '[\s&|<>^%!";,=()]') { throw "시연 폴더 경로에 공백·특수문자를 쓸 수 없습니다: $DemoRoot" }
$pkg = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # 저장소 루트 또는 오프라인 묶음 루트
$setup = Join-Path $PSScriptRoot 'demo_setup.py'
New-Item -ItemType Directory -Force -Path $DemoRoot | Out-Null
$dash = $null
if ($DashboardRoot) {
    . (Join-Path (Split-Path -Parent $PSScriptRoot) 'dashboard-env.ps1')
    $dash = Get-DashboardRuntimeDefaults -DashboardRoot $DashboardRoot
    Write-Step "대시보드 환경: $DashboardRoot (POSTGRES_BIN $(if ($dash.PgBin) { '있음' } else { '없음' }), Python 3.12 $(if ($dash.PythonExe) { '있음' } else { '없음' }))"
}

# ---- ① Python(저장소·묶음 공통: <시연 폴더>\venv — 대시보드 런타임·시스템 Python에는 설치하지 않는다) ----------------
. (Join-Path $PSScriptRoot 'demo-python.ps1')
$cands = Get-DemoPythonCandidates -PythonExe $PythonExe -DashboardPython $(if ($dash) { $dash.PythonExe } else { '' })
$wheels = Join-Path $pkg 'wheels'
if (Test-Path $wheels) {
    # 오프라인 묶음: wheels에서 설치(인덱스 접근 없음)
    $py = Initialize-DemoVenv -DemoRoot $DemoRoot -Candidates $cands -Wheels $wheels
    $frontend = Join-Path $pkg 'frontend'
} else {
    # 저장소: packages\simdash_adapters 로컬 설치 → deploy\requirements.lock(기존 pip 설정 PIP_INDEX_URL 등 존중). 소스는 PYTHONPATH로
    $py = Initialize-DemoVenv -DemoRoot $DemoRoot -Candidates $cands -RepoRoot $pkg
    $env:PYTHONPATH = (Join-Path $pkg 'backend') + [IO.Path]::PathSeparator + (Join-Path $pkg 'worker') + [IO.Path]::PathSeparator + (Join-Path $pkg 'packages\simdash_adapters\src')
    $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & $py -c "import physicsai_api, physicsai_worker, fastapi, psutil" 2>&1 | ForEach-Object { Write-Host "$_" }; $rc = $LASTEXITCODE } finally { $ErrorActionPreference = $eap }
    if ($rc -ne 0) {
        throw ("시연 venv에서 플랫폼 모듈을 불러오지 못했습니다(PYTHON=$py).`n" +
            "다음 행동: $DemoRoot\venv\physicsai-repo-deps.sha256 파일 이름을 바꿔 의존성을 다시 설치하게 한 뒤 다시 실행하세요.")
    }
    $frontend = Join-Path $pkg 'frontend\dist'
    if (-not (Test-Path (Join-Path $frontend 'index.html'))) {
        $node = Get-Command node -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $node) {
            throw ("프런트 빌드(frontend\dist)가 없고 Node.js도 없습니다.`n" +
                "다음 행동: Node 22(.node-version)를 설치한 뒤 다시 실행하거나, 오프라인 묶음(deploy\collect-offline.ps1)으로 실행하세요.")
        }
        $nodeVer = "$(& $node.Source --version)".Trim()
        if ($nodeVer -notmatch '^v22\.') {
            throw ("프런트 빌드(frontend\dist)가 없고 Node가 22가 아닙니다($nodeVer).`n" +
                "다음 행동: Node 22(저장소 .node-version $(try { (Get-Content (Join-Path $pkg '.node-version') -Raw).Trim() } catch { '22' }))를 PATH 맨 앞에 두고 다시 실행하세요.")
        }
        Write-Step "프런트 빌드가 없어 만듭니다: frontend에서 npm ci → npm run build (Node $nodeVer, 몇 분 걸림)"
        Push-Location (Join-Path $pkg 'frontend')
        try {
            & npm ci; if ($LASTEXITCODE -ne 0) { throw ("npm ci 실패(종료코드 $LASTEXITCODE).`n다음 행동: 위 npm 출력을 확인하세요(사내 프록시면 npm config의 registry·proxy 확인).") }
            & npm run build; if ($LASTEXITCODE -ne 0) { throw ("npm run build 실패(종료코드 $LASTEXITCODE).`n다음 행동: 위 출력을 확인하세요.") }
        } finally { Pop-Location }
    }
}
if (-not (Test-Path (Join-Path $frontend 'index.html'))) { throw "프런트 빌드가 없습니다: $frontend`n다음 행동: 저장소면 frontend에서 npm ci; npm run build, 묶음이면 묶음을 다시 만드세요(deploy\collect-offline.ps1)." }
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

# ---- ② 시연 폴더·가짜 도구·설정 --------------------------------------------------------------------
& $py $setup init --root $DemoRoot --port $Port --frontend $frontend; Assert-Ok '시연 준비(init)'

# ---- ③ DB --------------------------------------------------------------------------------------
if ($UseExistingDb) {
    if (-not $env:PHYSICSAI_DEMO_DATABASE_URL) { throw '-UseExistingDb: 환경변수 PHYSICSAI_DEMO_DATABASE_URL을 설정하세요(빈 DB)' }
    $env:PHYSICSAI_DATABASE_URL = $env:PHYSICSAI_DEMO_DATABASE_URL
    Write-Step '기존 PostgreSQL 사용(PHYSICSAI_DEMO_DATABASE_URL — 값은 출력하지 않음)'
} else {
    if (-not $PgBin -and $dash -and $dash.PgBin) { $PgBin = $dash.PgBin }
    if (-not $PgBin) {
        $initdb = Get-Command initdb.exe -ErrorAction SilentlyContinue
        if ($initdb) { $PgBin = Split-Path -Parent $initdb.Source }
        elseif ($env:PGBIN) { $PgBin = $env:PGBIN }
        else { throw 'PostgreSQL bin 폴더를 -PgBin으로 지정하세요(initdb.exe·pg_ctl.exe·psql.exe가 있는 폴더 — 포터블 zip 압축 해제본도 됨)' }
    }
    $env:PHYSICSAI_DATABASE_URL = $null   # 시연 클러스터 URL을 쓰게(이 프로세스 환경변수만 비움)
    & $py $setup db-up --root $DemoRoot --pg-bin $PgBin --pg-port $PgPort; Assert-Ok '시연 PostgreSQL 준비(db-up)'
}

# ---- ④ 백엔드·seed·워커 ------------------------------------------------------------------------------
$env:FAKE_DEMO_DELAY_S = [string]$ToolDelay
& $py $setup up --root $DemoRoot; Assert-Ok '시연 기동(up)'

# ---- ⑤ 안내 ------------------------------------------------------------------------------------
$url = "http://127.0.0.1:$Port/"
Write-Step "시연 주소: $url  (시연 사용자: 관리자 admin · 파워 power · 일반 general)"
Write-Step "①-5 결과 가져오기 경로: $DemoRoot\import\hpc_results   ③-4 모델 폴더: $DemoRoot\import\trained_model"
Write-Step "로그: $DemoRoot\logs   끝내기: $(Join-Path $PSScriptRoot 'stop-demo.ps1') -DemoRoot $DemoRoot"
if (-not $NoBrowser) { Start-Process $url }
