<#
.SYNOPSIS
  PhysicsAI 작업 스케줄러 등록 해제만 한다(phase2 §11.2). 파일·DB·환경변수는 그대로 둔다.
.DESCRIPTION
  해제할 작업 이름 = <접두사>-Backend·<접두사>-Worker. 접두사는 -TaskPrefix > deploy.json task_prefix > "PhysicsAI"(기본, 기존 동작).
  deploy.json은 -ConfigFile > 이 폴더의 deploy.json > git 폴더 설치의 <저장소>\.runtime\deploy.json 순서로 찾는다(없으면 기본 접두사).
  병행 설치라면 이 설치의 deploy.json을 가리키거나 -TaskPrefix를 주세요 — 기본값으로 실행하면 운영 작업(PhysicsAI-*)이 해제됩니다.
.PARAMETER TaskPrefix
  작업 이름 접두사(비우면 deploy.json 값 → PhysicsAI).
.PARAMETER ConfigFile
  deploy.json 경로(비우면 위 순서로 찾음).
#>
[CmdletBinding()]
param(
    [string]$TaskPrefix = '',
    [string]$ConfigFile = ''
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'install-common.ps1')   # Set-PhysicsAITaskPrefix·Get-PhysicsAITaskNames(이름 규칙 한 곳)
if (-not $TaskPrefix) {
    $cands = @($ConfigFile, (Join-Path $PSScriptRoot 'deploy.json'), (Join-Path (Split-Path -Parent $PSScriptRoot) '.runtime\deploy.json')) | Where-Object { $_ }
    foreach ($c in $cands) {
        if (Test-Path -LiteralPath $c -PathType Leaf) {
            $j = Get-Content -Raw -Encoding UTF8 -LiteralPath $c | ConvertFrom-Json
            if ($j.PSObject.Properties['task_prefix'] -and "$($j.task_prefix)".Trim()) { $TaskPrefix = "$($j.task_prefix)".Trim() }
            break
        }
    }
}
Set-PhysicsAITaskPrefix $TaskPrefix
foreach ($t in (Get-PhysicsAITaskNames)) {
    if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $t -Confirm:$false
        Write-Host "[PhysicsAI] 작업 등록 해제: $t"
    } else {
        Write-Host "[PhysicsAI] 등록되지 않음: $t"
    }
}
