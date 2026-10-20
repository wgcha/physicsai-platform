<#
.SYNOPSIS
  PhysicsAI 백엔드·워커를 한 번에 재시작한다(작업 스케줄러 작업 <task_prefix>-Backend·<task_prefix>-Worker, 기본 PhysicsAI-Backend·PhysicsAI-Worker). 설정을 고친 뒤 반영할 때 쓴다.
.DESCRIPTION
  일반 Windows PowerShell(관리자 권한 불필요)에서, 어느 폴더에서든:
    powershell -NoProfile -ExecutionPolicy Bypass -File <git 폴더>\deploy\restart.ps1
  (더블클릭: deploy\restart.bat — 같은 스크립트를 부르는 래퍼.)
  순서: 워커 중지 → 백엔드 중지 → (프로세스 종료 확인) → 백엔드 시작 → 워커 시작 → 두 작업 State 표 출력.
  워커를 멈추면 실행 중인 Altair 프로세스 트리도 끝나고 그 작업은 약 1분(lease) 뒤 INTERRUPTED가 된다 — 실행 중 작업이 없을 때 재시작하세요.
  작업 이름·중지·권한 거부 안내는 install-common.ps1(공용 함수)을 그대로 쓴다. 경로·비밀값은 쓰지 않는다(스크립트 위치 기준).
  병행 설치: 작업 이름 접두사 = -TaskPrefix > deploy.json task_prefix > PhysicsAI. deploy.json은 -ConfigFile > 이 폴더의 deploy.json >
  <저장소>\.runtime\deploy.json 순서로 찾는다(Set-PhysicsAITaskPrefixFromDeployJson, uninstall-tasks.ps1과 같은 규칙).
.PARAMETER Stop
  중지만 한다(시작하지 않음).
.PARAMETER Start
  시작만 한다(중지하지 않음).
.PARAMETER TaskPrefix
  작업 이름 접두사(비우면 deploy.json 값 → PhysicsAI).
.PARAMETER ConfigFile
  deploy.json 경로(비우면 위 순서로 찾음).
#>
[CmdletBinding()]
param(
    [switch]$Stop,
    [switch]$Start,
    [string]$TaskPrefix = '',
    [string]$ConfigFile = ''
)
$ErrorActionPreference = 'Stop'
$PhysicsAITag = 'PhysicsAI 재시작'
. (Join-Path $PSScriptRoot 'install-common.ps1')
function Write-Step([string]$m) { Write-PhysicsAIStep $m }
Set-PhysicsAITaskPrefixFromDeployJson -TaskPrefix $TaskPrefix -ConfigFile $ConfigFile
$PhysicsAITaskNames = @(Get-PhysicsAITaskNames)   # [Backend, Worker] — 이름 규칙은 install-common.ps1 한 곳

function Wait-PhysicsAITasksStopped {
    <# 작업 State가 Running이 아닐 때까지(최대 약 30초). 끝났으면 $true. #>
    param([string[]]$Names, [int]$Tries = 15)
    for ($i = 0; $i -lt $Tries; $i++) {
        $running = @($Names | Where-Object { $t = Get-ScheduledTask -TaskName $_ -ErrorAction SilentlyContinue; $t -and "$($t.State)" -eq 'Running' })
        if ($running.Count -eq 0) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Show-PhysicsAITaskStates {
    $rows = foreach ($n in $PhysicsAITaskNames) {
        $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
        [pscustomobject]@{ Task = $n; State = $(if ($t) { "$($t.State)" } else { '(없음)' }) }
    }
    ($rows | Format-Table -AutoSize | Out-String).TrimEnd() | Write-Host
}

try {
    if ($Stop -and $Start) { throw '-Stop과 -Start는 함께 쓸 수 없습니다(둘 다 생략하면 재시작).' }
    $missing = @($PhysicsAITaskNames | Where-Object { -not (Get-ScheduledTask -TaskName $_ -ErrorAction SilentlyContinue) })
    if ($missing.Count -gt 0) {
        throw ("작업 스케줄러에 등록되지 않았거나 이 계정에서 보이지 않습니다: $($missing -join ', ')`n" +
            "다음 행동: 설치(deploy\setup.ps1)가 끝났는지 확인하세요. 이전 설치를 관리자 권한으로 했다면 이 계정에서는 작업이 보이지 않을 수 있습니다.`n" +
            (Get-PhysicsAITaskAdminMessage))
    }
    if (-not $Start) {
        Write-Step '워커 → 백엔드 순서로 중지'
        $order = @($PhysicsAITaskNames[1], $PhysicsAITaskNames[0])   # 워커 → 백엔드
        Stop-PhysicsAITasks -TaskNames $order
        if (-not (Wait-PhysicsAITasksStopped -Names $PhysicsAITaskNames)) {
            throw '작업이 아직 Running입니다(중지 확인 시간 초과) — 잠시 뒤 다시 실행하거나 작업 스케줄러에서 상태를 확인하세요.'
        }
    }
    if (-not $Stop) {
        Write-Step '백엔드 → 워커 순서로 시작'
        foreach ($t in $PhysicsAITaskNames) {   # 백엔드 → 워커
            try { Start-ScheduledTask -TaskName $t -ErrorAction Stop }
            catch { if (Test-PhysicsAIAccessDenied $_) { throw (Get-PhysicsAITaskAdminMessage) }; throw }
            Write-Step "작업 시작: $t"
            if ($t -eq $PhysicsAITaskNames[0]) { Start-Sleep -Seconds 2 }   # 백엔드가 먼저 뜨게
        }
        Start-Sleep -Seconds 2
    }
} catch {
    Write-Host ''
    Write-Step "재시작하지 못했습니다: $($_.Exception.Message)"
    exit 1
}
Write-Host ''
Show-PhysicsAITaskStates
Write-Step $(if ($Stop) { '중지 완료' } elseif ($Start) { '시작 완료' } else { '재시작 완료' })
