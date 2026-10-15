<#
.SYNOPSIS
  Node 22 선택 공용 함수(프런트 빌드용). collect-offline.ps1(묶음)·setup.ps1·update-repo.ps1(git 폴더)이 dot-source 한다.
.DESCRIPTION
  후보 순서: 대시보드 고정 Node(<대시보드>\.tools\node-v22.*-win-x64\node.exe, dashboard-env.ps1) > PATH의 node.
  각 후보를 실제로 실행해(node --version) 22.x인지 확인하고, 아니면 다음 후보로 간다. npm은 고른 Node 폴더의 npm.cmd > PATH의 npm.
  기준 버전은 저장소 .node-version(대시보드와 같은 값). 22.x지만 기준과 다르면 안내만 하고 계속한다.
  저장소 빌드본 frontend-dist(phase3 D3-40)가 현재 소스와 같으면 Node가 필요 없다: Test-PhysicsAIFrontendDist(해시 규칙은
  scripts/frontend_source_hash.py와 동일 — 시험 backend/tests/test_frontend_dist.py가 대조).
#>

$PhysicsAIFrontendTopPatterns = @('index.html', 'package.json', 'package-lock.json', 'vite.config.*', 'tsconfig*.json')

function Get-PhysicsAIFrontendSourceHash {
    <#
      프런트 빌드 입력 해시(scripts/frontend_source_hash.py와 같은 규칙): frontend\ 최상위 index.html·package.json·package-lock.json·vite.config.*·tsconfig*.json
      + src\**·public\** → frontend 기준 '/' 상대경로를 서수 정렬 → 각 파일 내용(CRLF→LF) sha256 → "경로\0hex\n"을 이어 UTF-8 sha256(hex 소문자).
    #>
    param([Parameter(Mandatory = $true)][string]$FrontendDir)
    $fe = [IO.Path]::GetFullPath($FrontendDir).TrimEnd('\', '/')
    $rels = New-Object 'System.Collections.Generic.List[string]'
    if ([IO.Directory]::Exists($fe)) {
        foreach ($f in [IO.Directory]::GetFiles($fe)) {
            $n = [IO.Path]::GetFileName($f)
            foreach ($pat in $PhysicsAIFrontendTopPatterns) { if ($n -clike $pat) { $rels.Add($n); break } }
        }
        foreach ($tree in @('src', 'public')) {
            $root = [IO.Path]::Combine($fe, $tree)
            if (-not [IO.Directory]::Exists($root)) { continue }
            foreach ($f in [IO.Directory]::GetFiles($root, '*', [IO.SearchOption]::AllDirectories)) {
                $rels.Add($f.Substring($fe.Length).TrimStart('\', '/').Replace('\', '/'))
            }
        }
    }
    $arr = $rels.ToArray()
    [Array]::Sort($arr, [StringComparer]::Ordinal)
    $sha = [Security.Cryptography.SHA256]::Create()
    $latin1 = [Text.Encoding]::GetEncoding(28591)   # 바이트 1:1 — CRLF→LF를 바이트 그대로 바꾸기 위해
    $sb = New-Object Text.StringBuilder
    try {
        foreach ($rel in $arr) {
            $bytes = [IO.File]::ReadAllBytes([IO.Path]::Combine($fe, $rel))
            $norm = $latin1.GetBytes($latin1.GetString($bytes).Replace("`r`n", "`n"))
            $hex = -join ($sha.ComputeHash($norm) | ForEach-Object { $_.ToString('x2') })
            [void]$sb.Append($rel).Append([char]0).Append($hex).Append("`n")
        }
        return (-join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($sb.ToString())) | ForEach-Object { $_.ToString('x2') }))
    } finally { $sha.Dispose() }
}

function Test-PhysicsAIFrontendDist {
    <# <RepoRoot>\frontend-dist가 현재 프런트 소스의 빌드본인지: {Fresh, Reason, Recorded, Current}. 읽기만 한다. #>
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    $dist = Join-Path $RepoRoot 'frontend-dist'
    $info = Join-Path $dist 'BUILD_INFO.json'
    $r = [pscustomobject]@{ Fresh = $false; Reason = ''; Recorded = ''; Current = '' }
    if (-not (Test-Path -LiteralPath $info -PathType Leaf)) { $r.Reason = '저장소 빌드본 frontend-dist가 없습니다(BUILD_INFO.json 없음)'; return $r }
    if (-not (Test-Path -LiteralPath (Join-Path $dist 'index.html') -PathType Leaf)) { $r.Reason = '저장소 빌드본 frontend-dist에 index.html이 없습니다'; return $r }
    try { $r.Recorded = "$((Get-Content -Raw -Encoding UTF8 -LiteralPath $info | ConvertFrom-Json).source_hash)" }
    catch { $r.Reason = "frontend-dist\BUILD_INFO.json을 읽을 수 없습니다($($_.Exception.Message))"; return $r }
    $r.Current = Get-PhysicsAIFrontendSourceHash -FrontendDir (Join-Path $RepoRoot 'frontend')
    if ($r.Recorded -ne $r.Current) {
        $rec = if ($r.Recorded.Length -ge 12) { $r.Recorded.Substring(0, 12) } else { '-' }
        $r.Reason = "저장소 빌드본 frontend-dist가 현재 프런트 소스와 다릅니다(기록 $rec ≠ 현재 $($r.Current.Substring(0, 12)))"
        return $r
    }
    $r.Fresh = $true
    return $r
}

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

function Invoke-PhysicsAINpm {
    <#
      npm을 사용자가 창에서 직접 친 것과 똑같이 실행한다(phase3 D3-39): 파이프·리다이렉트 없음 — 출력은 콘솔로 바로 가고
      자식(vite build의 esbuild 등)은 콘솔을 그대로 물려받는다. PowerShell 파이프(2>&1 | ...)로 받으면 Windows에서 esbuild가
      spawn EPERM으로 실패한다(같은 관리자 창에서 직접 실행은 성공). 종료코드로만 판단하고(5.1에서 stderr로 중단되지 않게
      ErrorActionPreference 일시 Continue), 실패하면 -RetryDelaySec(기본 10초) 뒤 한 번 더 실행한다. 그래도 실패면 던진다.
      반환값 없음 — 이 함수와 이를 부르는 함수의 결과를 변수에 받지 말 것(받으면 npm 출력이 다시 파이프가 된다).
    #>
    param([Parameter(Mandatory = $true)][string]$Npm, [Parameter(Mandatory = $true)][string[]]$Arguments,
          [string]$Hint = '위 npm 출력을 확인하세요', [int]$RetryDelaySec = 10)
    $what = "npm $($Arguments -join ' ')"
    $rc = 0
    for ($try = 1; $try -le 2; $try++) {
        Write-Host "+ $what$(if ($try -gt 1) { ' (다시 실행)' })"
        $eap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try { & $Npm @Arguments; $rc = $LASTEXITCODE } finally { $ErrorActionPreference = $eap }
        if ($rc -eq 0) { return }
        if ($try -eq 1) {
            Write-Warning "$what 실패(종료코드 $rc) — $RetryDelaySec 초 뒤 한 번 더 실행합니다"
            Start-Sleep -Seconds $RetryDelaySec
        }
    }
    throw "실패: $what (종료코드 $rc)`n다음 행동: $Hint"
}

function Invoke-PhysicsAIFrontendBuild {
    <#
      <RepoRoot>\frontend에서 npm ci(package-lock.json이 바뀌었거나 node_modules가 없을 때만 — 기록 파일 -StampFile) → npm run build.
      결과는 <RepoRoot>\frontend\dist(index.html이 없으면 던짐). 반환값 없음 — 결과를 변수에 받지 말 것(Invoke-PhysicsAINpm, phase3 D3-39).
      고른 Node를 이 실행 동안만 PATH 맨 앞에 둔다(npm.cmd가 같은 node.exe를 쓰게). npm의 사내 레지스트리·프록시 설정(npm config)은 그대로 쓴다.
    #>
    param([Parameter(Mandatory = $true)]$Node, [Parameter(Mandatory = $true)][string]$RepoRoot, [string]$StampFile = '', [int]$RetryDelaySec = 10)
    $fe = Join-Path $RepoRoot 'frontend'
    $lock = Join-Path $fe 'package-lock.json'
    $want = (Get-FileHash -LiteralPath $lock -Algorithm SHA256).Hash.ToLowerInvariant() + " $($Node.Version)"
    $have = if ($StampFile -and (Test-Path -LiteralPath $StampFile)) { ([IO.File]::ReadAllText($StampFile)).Trim() } else { '' }
    $savedPath = $env:PATH
    $env:PATH = "$($Node.Dir)$([IO.Path]::PathSeparator)$savedPath"
    Push-Location $fe
    try {
        if ($have -eq $want -and (Test-Path -LiteralPath (Join-Path $fe 'node_modules'))) {
            Write-Host '+ npm ci 건너뜀(package-lock.json·Node 변경 없음)'
        } else {
            Invoke-PhysicsAINpm -Npm $Node.Npm -Arguments @('ci') -RetryDelaySec $RetryDelaySec `
                -Hint '위 npm 출력을 확인하세요(사내 프록시면 npm config의 registry·proxy·https-proxy 확인).'
            if ($StampFile) { [IO.File]::WriteAllText($StampFile, $want) }
        }
        Invoke-PhysicsAINpm -Npm $Node.Npm -Arguments @('run', 'build') -RetryDelaySec $RetryDelaySec `
            -Hint "frontend 폴더($fe)에서 npm run build를 직접 실행해 결과를 알려 주세요."
    } finally { Pop-Location; $env:PATH = $savedPath }
    $dist = Join-Path $fe 'dist'
    if (-not (Test-Path -LiteralPath (Join-Path $dist 'index.html'))) { throw "프런트 빌드 결과가 없습니다: $dist\index.html" }
}
