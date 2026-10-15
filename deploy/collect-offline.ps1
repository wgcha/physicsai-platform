<#
.SYNOPSIS
  인터넷 되는 준비 PC(Windows)에서 폐쇄망 설치 묶음 physicsai-offline-<version>.zip을 만든다(phase2 §11.2).
.DESCRIPTION
  Python 3.12 선택(deploy\python-select.ps1, 시연과 같은 규칙): -PythonExe > -DashboardRoot의 고정 Python 3.12 > py -3.12 > PATH의 python.
  각 후보를 실제로 실행해 확인하므로 PATH 첫 python이 망가진 pyenv shim이어도 다음 후보로 넘어간다.
  pip wheel·pip download는 고른 Python으로 만든 빌드용 임시 venv(dist\_buildvenv)에서 실행한다 — 대시보드 런타임·시스템 Python에는 아무것도 설치하지 않고,
  임시 venv는 끝나면 지우며 묶음에도 넣지 않는다.
  프런트 빌드(npm)는 Node 22: -DashboardRoot의 고정 Node(.tools\node-v22.*-win-x64) > PATH의 node 순으로 실행해 확인한다.
.PARAMETER DryRun
  Python·Node만 확인하고 실행할 명령을 출력한다(빌드·내려받기 없음).
.PARAMETER PythonExe
  Python 3.12 실행 파일(대시보드와 같은 3.12.13 권장). 비우면 자동 선택(위 순서).
.PARAMETER DashboardRoot
  대시보드 폴더(예 E:\VD_SIMULATION_WEB\simdashboard, 선택). .tools의 고정 Python 3.12·Node 22를 후보로 쓴다(dashboard-env.ps1, .env 비밀번호는 읽지 않음).
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [string]$PythonExe = '',
    [string]$DashboardRoot = ''
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$version = (Select-String -Path (Join-Path $root 'pyproject.toml') -Pattern '^version = "(.*)"').Matches[0].Groups[1].Value
$out = "physicsai-offline-$version.zip"
$tag = 'PhysicsAI 묶음'
function Write-Step([string]$m) { Write-Host "[$tag] $m" }

function Invoke-Step([string]$Text, [scriptblock]$Block) {
    Write-Host "+ $Text"
    if (-not $DryRun) { & $Block }
}

function Invoke-Native([string]$What, [string]$Exe, [string[]]$Arguments, [string]$Hint = '위 출력을 확인하세요') {
    # Windows PowerShell 5.1: 자식의 stderr(pip 경고 등)가 오류 레코드로 중단되지 않게 하고, 종료코드로만 판단한다
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Exe @Arguments 2>&1 | ForEach-Object { Write-Host "$_" }; $rc = $LASTEXITCODE } finally { $ErrorActionPreference = $eap }
    if ($rc -ne 0) { throw "실패: $What (종료코드 $rc)`n다음 행동: $Hint" }
}

# ---- 실행 환경: Python 3.12·Node 22(대시보드 고정 런타임 우선) -------------------------------------------
$dash = $null
if ($DashboardRoot) {
    . (Join-Path $PSScriptRoot 'dashboard-env.ps1')
    $dash = Get-DashboardRuntimeDefaults -DashboardRoot $DashboardRoot
    Write-Step "대시보드 환경: $DashboardRoot (Python 3.12 $(if ($dash.PythonExe) { '있음' } else { '없음' }), Node 22 $(if ($dash.NodeExe) { '있음' } else { '없음' }))"
}
. (Join-Path $PSScriptRoot 'python-select.ps1')
$cands = Get-PhysicsAIPythonCandidates -PythonExe $PythonExe -DashboardPython $(if ($dash) { "$($dash.PythonExe)" } else { '' })
$base = Select-PhysicsAIPython -Candidates $cands -Tag $tag

# Node 22 선택(deploy\node-select.ps1 공용 — setup.ps1과 같은 규칙): 대시보드 고정 Node > PATH의 node
. (Join-Path $PSScriptRoot 'node-select.ps1')
$node = Select-PhysicsAINode -DashboardNode $(if ($dash) { "$($dash.NodeExe)" } else { '' }) -RepoRoot $root -Tag $tag
$npm = [pscustomobject]@{ Source = $node.Npm }

# ---- 빌드용 임시 venv(고른 Python 3.12로 만든다 — 대시보드 런타임에는 설치하지 않음, 끝나면 지움·묶음 미포함) ----------------
$buildVenv = Join-Path $root 'dist\_buildvenv'
$py = Join-Path $buildVenv 'Scripts\python.exe'
Invoke-Step "python -m venv dist\_buildvenv (빌드용 임시 — pip는 여기서, 끝나면 지움·묶음 미포함)" {
    if (Test-Path -LiteralPath $buildVenv) { Remove-Item -LiteralPath $buildVenv -Recurse -Force }
    Invoke-Native 'python -m venv dist\_buildvenv' $base.Exe @('-m', 'venv', $buildVenv) "dist 폴더 쓰기 권한과 Python($($base.Exe))의 venv 모듈을 확인하거나 -PythonExe로 다른 Python 3.12를 지정하세요."
    if (-not (Test-Path -LiteralPath $py)) { throw "빌드용 venv에 python.exe가 없습니다: $py" }
}
$pipHint = '위 pip 출력을 확인하세요(인덱스 접근 문제면 사내 프록시 pip 설정 PIP_INDEX_URL·HTTPS_PROXY 확인).'
$pipOpts = @('--disable-pip-version-check')
$savedPath = $env:PATH
try {
    Invoke-Step 'mkdir dist\wheels dist\frontend dist\config dist\migrations dist\deploy' {
        New-Item -ItemType Directory -Force -Path 'dist\wheels', 'dist\frontend', 'dist\config', 'dist\migrations', 'dist\deploy' | Out-Null
    }
    # 공통 어댑터 패키지는 PyPI에서 받지 않는다: 저장소 소스로 wheel을 만들고 requirements.local.lock 고정을 --no-index로만 확인(phase3.md §6.5·D3-27)
    Invoke-Step 'pip wheel packages/simdash_adapters --no-deps -w dist/wheels' {
        Invoke-Native 'pip wheel packages/simdash_adapters' $py (@('-m', 'pip', 'wheel', 'packages/simdash_adapters', '--no-deps', '-w', 'dist/wheels') + $pipOpts) $pipHint
    }
    Invoke-Step 'pip download --no-index --find-links dist/wheels -r deploy/requirements.local.lock --only-binary=:all: --platform win_amd64 --python-version 3.12 -d dist/wheels' {
        Invoke-Native 'pip download (requirements.local.lock)' $py (@('-m', 'pip', 'download', '--no-index', '--find-links', 'dist/wheels', '-r', 'deploy/requirements.local.lock',
            '--only-binary=:all:', '--platform', 'win_amd64', '--python-version', '3.12', '-d', 'dist/wheels') + $pipOpts) $pipHint
    }
    Invoke-Step 'pip download -r deploy/requirements.lock --only-binary=:all: --platform win_amd64 --python-version 3.12 -d dist/wheels' {
        Invoke-Native 'pip download (requirements.lock)' $py (@('-m', 'pip', 'download', '-r', 'deploy/requirements.lock',
            '--only-binary=:all:', '--platform', 'win_amd64', '--python-version', '3.12', '-d', 'dist/wheels') + $pipOpts) $pipHint
    }
    Invoke-Step 'pip wheel . --no-deps -w dist/wheels' {
        Invoke-Native 'pip wheel .' $py (@('-m', 'pip', 'wheel', '.', '--no-deps', '-w', 'dist/wheels') + $pipOpts) $pipHint
    }
    Invoke-Step "npm ci && npm run build (frontend, Node $($node.Version))" {
        $env:PATH = "$($node.Dir);$savedPath"   # 고른 Node를 이 프로세스에서만 맨 앞에(npm.cmd가 같은 node.exe를 쓰게)
        Push-Location frontend
        try {
            # npm은 창에서 직접 친 것과 같이 콘솔 그대로(파이프면 esbuild spawn EPERM — node-select.ps1 Invoke-PhysicsAINpm, phase3 D3-39)
            Invoke-PhysicsAINpm -Npm $npm.Source -Arguments @('ci') -Hint '위 npm 출력을 확인하세요(사내 프록시면 npm config의 registry·proxy 확인).'
            Invoke-PhysicsAINpm -Npm $npm.Source -Arguments @('run', 'build')
        } finally { Pop-Location; $env:PATH = $savedPath }
    }
    Invoke-Step 'copy frontend\dist, migrations, config(+demo), deploy(+demo fake_tools)' {
        # 폴더 안으로 내용만 복사(다시 실행해도 dist\deploy\deploy처럼 겹치지 않게)
        Copy-Item -Recurse -Force 'frontend\dist\*' 'dist\frontend\'
        Copy-Item -Recurse -Force 'migrations\*' 'dist\migrations\'
        Copy-Item -Force 'config\platform.example.yaml' 'dist\config\platform.example.yaml'
        Copy-Item -Force 'config\platform.demo.yaml' 'dist\config\platform.demo.yaml'
        Copy-Item -Recurse -Force 'deploy\*' 'dist\deploy\'
        New-Item -ItemType Directory -Force -Path 'dist\deploy\demo\fake_tools' | Out-Null
        Copy-Item -Recurse -Force 'backend\tests\fake_tools\*' 'dist\deploy\demo\fake_tools\'   # 시연 모드 가짜 도구 원본
    }
} finally {
    $env:PATH = $savedPath
    if (-not $DryRun -and (Test-Path -LiteralPath $buildVenv)) { Remove-Item -LiteralPath $buildVenv -Recurse -Force -ErrorAction SilentlyContinue }
}
# 묶음에는 이 5개 폴더만(빌드용 임시 venv 등은 넣지 않음 — collect-offline.sh와 같은 구성)
Invoke-Step "Compress-Archive dist\{wheels,frontend,migrations,config,deploy} $out" {
    Compress-Archive -Path 'dist\wheels', 'dist\frontend', 'dist\migrations', 'dist\config', 'dist\deploy' -DestinationPath $out -Force
}
Write-Host "묶음: $out"
