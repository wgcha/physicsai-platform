<#
.SYNOPSIS
  PhysicsAI 시연 모드 종료: 워커(가짜 도구 자식 포함)·백엔드 종료, 시연 전용 PostgreSQL 중지.
  시연 폴더·DB 파일은 지우지 않는다(다시 start-demo.ps1로 이어서 시연).
.PARAMETER DemoRoot
  start-demo.ps1에 준 시연 폴더. 기본 <시스템 드라이브>\physicsai-demo
.PARAMETER PythonExe
  <시연 폴더>\venv가 없을 때만 쓰는 Python(보통 비워 둔다 — start-demo.ps1이 만든 venv를 자동 사용)
.PARAMETER KeepDb
  시연 전용 PostgreSQL은 계속 실행
#>
[CmdletBinding()]
param(
    [string]$DemoRoot = (Join-Path $env:SystemDrive 'physicsai-demo'),
    [string]$PythonExe = 'python',
    [switch]$KeepDb
)
$ErrorActionPreference = 'Stop'
$pkg = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$setup = Join-Path $PSScriptRoot 'demo_setup.py'
$venvPy = Join-Path $DemoRoot 'venv\Scripts\python.exe'
# start-demo.ps1은 저장소·묶음 모두 <시연 폴더>\venv를 만든다(예전 저장소 시연은 venv 없이 -PythonExe)
$py = if (Test-Path $venvPy) { $venvPy } else { (Get-Command $PythonExe -ErrorAction Stop).Source }
if (Test-Path (Join-Path $pkg 'backend\physicsai_api')) {   # 저장소: 소스는 PYTHONPATH로
    $env:PYTHONPATH = (Join-Path $pkg 'backend') + [IO.Path]::PathSeparator + (Join-Path $pkg 'worker') + [IO.Path]::PathSeparator + (Join-Path $pkg 'packages\simdash_adapters\src')
}
$env:PYTHONUTF8 = '1'
& $py $setup down --root $DemoRoot
if ($LASTEXITCODE -ne 0) { throw "시연 종료(down) 실패(종료코드 $LASTEXITCODE)" }
if (-not $KeepDb) {
    & $py $setup db-down --root $DemoRoot
    if ($LASTEXITCODE -ne 0) { throw "시연 PostgreSQL 중지(db-down) 실패(종료코드 $LASTEXITCODE)" }
}
Write-Host "[PhysicsAI 시연] 종료했습니다. 시연 폴더($DemoRoot)는 그대로 둡니다."
