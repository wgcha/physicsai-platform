<#
.SYNOPSIS
  PhysicsAI 시연 모드 원클릭 시작(Altair 없는 Windows PC). 관리자 권한 불필요.
.DESCRIPTION
  가짜 도구(fake tools)로 화면·대기열·알림·취소·리소스 제한·①~⑤ 흐름을 실제로 돌려 본다.
  ① Python 준비: 오프라인 묶음이면 <시연 폴더>\venv를 만들고 wheels에서 설치, 저장소면 지정 Python + PYTHONPATH
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
  Python 3.11 이상(묶음 설치는 3.13). 기본 PATH의 python
.PARAMETER PgBin
  PostgreSQL bin 폴더(initdb.exe·pg_ctl.exe·psql.exe). 비우면 PATH·PGBIN 환경변수에서 찾는다
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
    [string]$PythonExe = 'python',
    [string]$PgBin = '',
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

# ---- ① Python ----------------------------------------------------------------------------
$wheels = Join-Path $pkg 'wheels'
if (Test-Path $wheels) {
    # 오프라인 묶음: 시연 전용 venv(운영 설치와 분리)
    $py = Join-Path $DemoRoot 'venv\Scripts\python.exe'
    if (-not (Test-Path $py)) {
        Write-Step "시연용 venv 생성: $DemoRoot\venv"
        & $PythonExe -m venv (Join-Path $DemoRoot 'venv'); Assert-Ok 'venv 생성'
        & $py -m pip install --no-index --find-links $wheels physicsai-platform; Assert-Ok 'wheel 설치'
    }
    $frontend = Join-Path $pkg 'frontend'
} else {
    # 저장소: 지정 Python에 의존성이 설치되어 있어야 한다(pip install -r deploy/requirements.lock)
    $py = (Get-Command $PythonExe -ErrorAction Stop).Source
    $env:PYTHONPATH = (Join-Path $pkg 'backend') + [IO.Path]::PathSeparator + (Join-Path $pkg 'worker')
    & $py -c "import physicsai_api, physicsai_worker, fastapi, psutil"
    if ($LASTEXITCODE -ne 0) { throw "Python 의존성이 없습니다: $py -m pip install -r $pkg\deploy\requirements.lock" }
    $frontend = Join-Path $pkg 'frontend\dist'
}
if (-not (Test-Path (Join-Path $frontend 'index.html'))) { throw "프런트 빌드가 없습니다: $frontend (저장소면 frontend에서 npm ci; npm run build)" }
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
