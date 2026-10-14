<#
.SYNOPSIS
  Node 22 선택 공용 함수(프런트 빌드용). collect-offline.ps1(묶음)·setup.ps1·update-repo.ps1(git 폴더)이 dot-source 한다.
.DESCRIPTION
  후보 순서: 대시보드 고정 Node(<대시보드>\.tools\node-v22.*-win-x64\node.exe, dashboard-env.ps1) > PATH의 node.
  각 후보를 실제로 실행해(node --version) 22.x인지 확인하고, 아니면 다음 후보로 간다. npm은 고른 Node 폴더의 npm.cmd > PATH의 npm.
  기준 버전은 저장소 .node-version(대시보드와 같은 값). 22.x지만 기준과 다르면 안내만 하고 계속한다.
#>

function Select-PhysicsAINode {
    [CmdletBinding()]
    param([string]$DashboardNode = '', [string]$RepoRoot = '', [string]$Tag = 'PhysicsAI')
    $wantNode = 'v22'
    if ($RepoRoot) { try { $wantNode = (Get-Content (Join-Path $RepoRoot '.node-version') -Raw).Trim() } catch { $wantNode = 'v22' } }
    $nodeCands = @()
    if ($DashboardNode) { $nodeCands += [pscustomobject]@{ Label = '대시보드 Node'; Exe = $DashboardNode } }
    $pathNode = Get-Command node -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pathNode) { $nodeCands += [pscustomobject]@{ Label = 'PATH node'; Exe = $pathNode.Source } }
    $node = $null
    $nodeTried = @()
    foreach ($nc in $nodeCands) {
        $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try { $vo = @(& $nc.Exe --version 2>&1 | ForEach-Object { "$_" }); $rc = $LASTEXITCODE; $v = "$($vo | Where-Object { "$_".Trim() } | Select-Object -First 1)".Trim() } catch { $v = "실행 불가($($_.Exception.Message))"; $rc = -1 } finally { $ErrorActionPreference = $eap }
        if ($rc -eq 0 -and $v -match '^v22\.') {
            $node = [pscustomobject]@{ Label = $nc.Label; Exe = $nc.Exe; Dir = (Split-Path -Parent $nc.Exe); Version = $v; Npm = $null }
            break
        }
        $why = if ($rc -eq 0) { "Node $v(22 아님)" } else { "실행 실패(종료코드 $rc$(if ($v) { ": $v" }))" }
        Write-Host "[$Tag] Node 후보 건너뜀: $($nc.Label) ($($nc.Exe)) — $why"
        $nodeTried += "$($nc.Label) $why"
    }
    if (-not $node) {
        throw ("프런트 빌드에 필요한 Node 22를 찾지 못했습니다($(if ($nodeTried) { $nodeTried -join '; ' } else { 'PATH에 node 없음' })).`n" +
            "다음 행동: Node $wantNode(저장소 .node-version, 대시보드와 같은 값)를 설치해 PATH 맨 앞에 두거나 -DashboardRoot <대시보드 폴더>(.tools\node-v22.*-win-x64)를 지정하세요(폐쇄망 설치 PC에는 Node가 필요 없습니다).")
    }
    $npm = Get-Command (Join-Path $node.Dir 'npm.cmd') -ErrorAction SilentlyContinue
    if (-not $npm) { $npm = Get-Command npm -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1 }
    if (-not $npm) {
        throw ("npm을 찾지 못했습니다(Node: $($node.Exe)).`n다음 행동: Node $wantNode 배포본(npm 포함)을 설치해 PATH 맨 앞에 두거나 -DashboardRoot를 지정하세요.")
    }
    $node.Npm = $npm.Source
    Write-Host "[$Tag] Node 선택: $($node.Label) → $($node.Exe) (Node $($node.Version)$(if ($node.Version -ne $wantNode) { " — 기준 $wantNode 과 다름(주 버전 22라 계속)" }))"
    return $node
}

function Invoke-PhysicsAIFrontendBuild {
    <#
      <RepoRoot>\frontend에서 npm ci(package-lock.json이 바뀌었거나 node_modules가 없을 때만 — 기록 파일 -StampFile) → npm run build.
      고른 Node를 이 실행 동안만 PATH 맨 앞에 둔다(npm.cmd가 같은 node.exe를 쓰게). npm의 사내 레지스트리·프록시 설정(npm config)은 그대로 쓴다.
    #>
    param([Parameter(Mandatory = $true)]$Node, [Parameter(Mandatory = $true)][string]$RepoRoot, [string]$StampFile = '')
    $fe = Join-Path $RepoRoot 'frontend'
    $lock = Join-Path $fe 'package-lock.json'
    $want = (Get-FileHash -LiteralPath $lock -Algorithm SHA256).Hash.ToLowerInvariant() + " $($Node.Version)"
    $have = if ($StampFile -and (Test-Path -LiteralPath $StampFile)) { ([IO.File]::ReadAllText($StampFile)).Trim() } else { '' }
    $savedPath = $env:PATH
    $env:PATH = "$($Node.Dir);$savedPath"
    Push-Location $fe
    try {
        if ($have -eq $want -and (Test-Path -LiteralPath (Join-Path $fe 'node_modules'))) {
            Write-Host '+ npm ci 건너뜀(package-lock.json·Node 변경 없음)'
        } else {
            Write-Host '+ npm ci'
            Invoke-PhysicsAINative 'npm ci' $Node.Npm @('ci') '위 npm 출력을 확인하세요(사내 프록시면 npm config의 registry·proxy·https-proxy 확인).'
            if ($StampFile) { [IO.File]::WriteAllText($StampFile, $want) }
        }
        Write-Host '+ npm run build'
        Invoke-PhysicsAINative 'npm run build' $Node.Npm @('run', 'build')
    } finally { Pop-Location; $env:PATH = $savedPath }
    $dist = Join-Path $fe 'dist'
    if (-not (Test-Path -LiteralPath (Join-Path $dist 'index.html'))) { throw "프런트 빌드 결과가 없습니다: $dist\index.html" }
    return $dist
}
