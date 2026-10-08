<#
.SYNOPSIS
  인터넷 되는 준비 PC(Windows)에서 폐쇄망 설치 묶음 physicsai-offline-<version>.zip을 만든다(phase2 §11.2).
.PARAMETER DryRun
  실행할 명령만 출력한다.
#>
[CmdletBinding()]
param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = if ($env:PYTHON) { $env:PYTHON } else { 'python' }
$version = (Select-String -Path (Join-Path $root 'pyproject.toml') -Pattern '^version = "(.*)"').Matches[0].Groups[1].Value
$out = "physicsai-offline-$version.zip"

function Invoke-Step([string]$Text, [scriptblock]$Block) {
    Write-Host "+ $Text"
    if (-not $DryRun) { & $Block; if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "실패: $Text" } }
}

Invoke-Step 'mkdir dist\wheels dist\frontend dist\config' { New-Item -ItemType Directory -Force -Path 'dist\wheels', 'dist\frontend', 'dist\config' | Out-Null }
Invoke-Step 'pip download -r deploy/requirements.lock --only-binary=:all: --platform win_amd64 --python-version 3.13 -d dist/wheels' {
    & $py -m pip download -r deploy/requirements.lock --only-binary=:all: --platform win_amd64 --python-version 3.13 -d dist/wheels
}
Invoke-Step 'pip wheel . --no-deps -w dist/wheels' { & $py -m pip wheel . --no-deps -w dist/wheels }
Invoke-Step 'npm ci && npm run build (frontend)' { Push-Location frontend; try { npm ci; npm run build } finally { Pop-Location } }
Invoke-Step 'copy frontend\dist, migrations, config, deploy' {
    Copy-Item -Recurse -Force 'frontend\dist\*' 'dist\frontend\'
    Copy-Item -Recurse -Force 'migrations' 'dist\migrations'
    Copy-Item -Force 'config\platform.example.yaml' 'dist\config\platform.example.yaml'
    Copy-Item -Recurse -Force 'deploy' 'dist\deploy'
}
Invoke-Step "Compress-Archive dist\* $out" { Compress-Archive -Path 'dist\*' -DestinationPath $out -Force }
Write-Host "묶음: $out"
