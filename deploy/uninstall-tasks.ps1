<#
.SYNOPSIS
  PhysicsAI 작업 스케줄러 등록 해제만 한다(phase2 §11.2). 파일·DB·환경변수는 그대로 둔다.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
foreach ($t in @('PhysicsAI-Backend', 'PhysicsAI-Worker')) {
    if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $t -Confirm:$false
        Write-Host "[PhysicsAI] 작업 등록 해제: $t"
    } else {
        Write-Host "[PhysicsAI] 등록되지 않음: $t"
    }
}
