<#
.SYNOPSIS
  시연 Python 선택·시연 venv 준비. deploy\demo\start-demo.ps1이 dot-source 한다(저장소·오프라인 묶음 공통).
.DESCRIPTION
  Python 선택 순서: -PythonExe > 대시보드 고정 Python 3.12(dashboard-env) > `py -3.12` > PATH의 python.
  각 후보는 실제로 실행해 sys.version_info[:2] == (3, 12)인지 확인하고, 실패하면(pyenv shim 미설정·Microsoft Store 별칭·다른 버전 등) 다음 후보로 간다.
  패키지는 대시보드 런타임이나 시스템 Python에 설치하지 않는다 — 항상 <시연 폴더>\venv에 설치한다.
#>

# 후보 실행 결과에서 찾을 표지(다른 출력과 섞여도 실제 실행 파일 경로를 찾는다). 코드에는 cmd 특수문자(| & < > ^ % ")를 쓰지 않는다(pyenv shim 등 .bat 경유)
$script:DemoPyMarker = 'PHYSICSAI_PY='

function Test-DemoPython312 {
    <# 후보를 실제로 실행한다. Python 3.12면 실제 실행 파일 경로(sys.executable)를, 아니면 $null을 돌려준다. 실패 이유는 -Reason 변수에. #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Exe, [string[]]$PreArgs = @(), [ref]$Reason)
    $code = "import sys; print('$script:DemoPyMarker' + '.'.join(map(str, sys.version_info[:3])) + ' ' + sys.executable); sys.exit(0 if sys.version_info[:2] == (3, 12) else 3)"
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'   # Windows PowerShell 5.1: 자식의 stderr가 오류 레코드가 되어 중단되지 않게
    try {
        $out = @(& $Exe @PreArgs -c $code 2>&1 | ForEach-Object { "$_" })
        $rc = $LASTEXITCODE
    } catch {
        if ($Reason) { $Reason.Value = "실행 불가($($_.Exception.Message))" }
        return $null
    } finally { $ErrorActionPreference = $eap }
    $line = $out | Where-Object { $_.StartsWith($script:DemoPyMarker) } | Select-Object -Last 1
    if (-not $line) {
        $first = ($out | Where-Object { "$_".Trim() } | Select-Object -First 1)
        if ($Reason) { $Reason.Value = "실행 실패(종료코드 $rc$(if ($first) { ": $("$first".Trim())" }))" }
        return $null
    }
    $ver, $exePath = $line.Substring($script:DemoPyMarker.Length).Trim().Split([char[]]' ', 2)
    if ($rc -ne 0) {
        if ($Reason) { $Reason.Value = "Python $ver(3.12 아님)" }
        return $null
    }
    return [pscustomobject]@{ Exe = $exePath; Version = $ver }
}

function Get-DemoPythonCandidates {
    <# 선택 순서대로 후보 목록(Label·Exe·PreArgs). 비어 있는 값은 건너뛴다. #>
    [CmdletBinding()]
    param([string]$PythonExe = '', [string]$DashboardPython = '')
    $c = New-Object System.Collections.Generic.List[object]
    if ($PythonExe) { $c.Add([pscustomobject]@{ Label = '-PythonExe'; Exe = $PythonExe; PreArgs = @() }) }
    if ($DashboardPython) { $c.Add([pscustomobject]@{ Label = '대시보드 Python 3.12'; Exe = $DashboardPython; PreArgs = @() }) }
    $pyLauncher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pyLauncher) { $c.Add([pscustomobject]@{ Label = 'py -3.12'; Exe = $pyLauncher.Source; PreArgs = @('-3.12') }) }
    foreach ($n in 'python', 'python3') {
        foreach ($g in @(Get-Command $n -CommandType Application -All -ErrorAction SilentlyContinue)) {
            if (-not ($c | Where-Object { $_.Exe -eq $g.Source })) { $c.Add([pscustomobject]@{ Label = "PATH $n"; Exe = $g.Source; PreArgs = @() }) }
        }
    }
    return , $c.ToArray()
}

function Select-DemoPython {
    <# 후보를 차례로 실행해 첫 Python 3.12를 고른다. 고른 것을 1줄 출력. 없으면 원인·다음 행동을 한 줄씩 담아 중단. #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$Candidates)
    $tried = @()
    foreach ($cand in $Candidates) {
        $why = ''
        $r = Test-DemoPython312 -Exe $cand.Exe -PreArgs $cand.PreArgs -Reason ([ref]$why)
        if ($r) {
            Write-Host "[PhysicsAI 시연] Python 선택: $($cand.Label) → $($r.Exe) (Python $($r.Version))"
            return [pscustomobject]@{ Exe = $r.Exe; Version = $r.Version; Label = $cand.Label }
        }
        Write-Host "[PhysicsAI 시연] Python 후보 건너뜀: $($cand.Label) ($($cand.Exe)) — $why"
        $tried += "$($cand.Label)"
    }
    throw ("Python 3.12를 찾지 못했습니다(시도: $(if ($tried) { $tried -join ', ' } else { '후보 없음' })).`n" +
        "다음 행동: -DashboardRoot <대시보드 폴더>(.tools\python\cpython-3.12.*) 또는 -PythonExe <python.exe 경로>로 Python 3.12를 지정하세요.")
}

function Get-DemoDepsStamp {
    <# 저장소 의존성 기록값: requirements.lock + simdash_adapters pyproject 내용 해시(바뀌면 다시 설치). #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = New-Object System.Collections.Generic.List[byte]
        foreach ($f in (Join-Path $RepoRoot 'deploy\requirements.lock'), (Join-Path $RepoRoot 'packages\simdash_adapters\pyproject.toml')) {
            $bytes.AddRange([IO.File]::ReadAllBytes($f))
        }
        return ([BitConverter]::ToString($sha.ComputeHash($bytes.ToArray())) -replace '-', '').ToLowerInvariant()
    } finally { $sha.Dispose() }
}

function Invoke-DemoPip {
    <# venv의 pip 실행. 출력은 보여 주면서 모아 두고, 실패하면 인덱스 접근 문제인지 판단해 한국어로 중단한다. 기존 pip 설정(PIP_INDEX_URL 등)은 그대로 쓴다. #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Py, [Parameter(Mandatory = $true)][string[]]$PipArgs, [Parameter(Mandatory = $true)][string]$What)
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = @(& $Py -m pip @PipArgs --progress-bar off --disable-pip-version-check 2>&1 | ForEach-Object { $s = "$_"; Write-Host $s; $s })
        $rc = $LASTEXITCODE
    } finally { $ErrorActionPreference = $eap }
    if ($rc -eq 0) { return }
    $text = $out -join "`n"
    if ($text -match '(?i)NewConnectionError|ConnectTimeout|ConnectionError|ProxyError|Max retries exceeded|Temporary failure in name resolution|getaddrinfo failed|No matching distribution found|Could not find a version that satisfies|SSLError|CERTIFICATE_VERIFY_FAILED|403 Client Error|407') {
        throw ("$What 실패: 패키지 인덱스(PyPI 또는 PIP_INDEX_URL)에 접근할 수 없습니다.`n" +
            "다음 행동: 인터넷이 안 되는 PC면 오프라인 묶음(deploy\collect-offline.ps1로 만든 zip)을 풀어 그 안의 deploy\demo\start-demo.bat로 실행하세요(사내 프록시면 pip 설정 PIP_INDEX_URL·HTTPS_PROXY 확인).")
    }
    throw ("$What 실패(pip 종료코드 $rc).`n다음 행동: 위 pip 출력을 확인하세요. 인덱스 접근이 안 되면 오프라인 묶음(deploy\collect-offline.ps1)으로 실행하세요.")
}

function Initialize-DemoVenv {
    <#
      <시연 폴더>\venv를 준비하고 그 python.exe 경로를 돌려준다.
      -Wheels: 오프라인 묶음(wheels에서 physicsai-platform 설치, venv가 이미 있으면 그대로).
      -RepoRoot: 저장소(packages\simdash_adapters 로컬 설치 → deploy\requirements.lock, 기록 해시가 같으면 건너뜀).
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$DemoRoot, [Parameter(Mandatory = $true)][object[]]$Candidates,
          [string]$Wheels = '', [string]$RepoRoot = '')
    $venv = Join-Path $DemoRoot 'venv'
    $py = Join-Path $venv 'Scripts\python.exe'
    if (Test-Path -LiteralPath $py) {
        $why = ''
        $r = Test-DemoPython312 -Exe $py -Reason ([ref]$why)
        if (-not $r) {
            throw ("기존 시연 venv가 Python 3.12가 아니거나 실행되지 않습니다: $venv ($why).`n" +
                "다음 행동: 그 venv 폴더 이름을 바꾼(예 venv_old) 뒤 다시 실행하세요(새 venv를 만듭니다).")
        }
        Write-Host "[PhysicsAI 시연] Python: 기존 시연 venv 사용 → $py (Python $($r.Version))"
    } else {
        $base = Select-DemoPython -Candidates $Candidates
        Write-Host "[PhysicsAI 시연] 시연용 venv 생성: $venv"
        $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try { & $base.Exe -m venv $venv 2>&1 | ForEach-Object { Write-Host "$_" }; $rc = $LASTEXITCODE } finally { $ErrorActionPreference = $eap }
        if ($rc -ne 0 -or -not (Test-Path -LiteralPath $py)) {
            throw ("venv 생성 실패(종료코드 $rc): $venv`n다음 행동: 시연 폴더 쓰기 권한과 Python($($base.Exe))의 venv 모듈을 확인하거나 -PythonExe로 다른 Python 3.12를 지정하세요.")
        }
        if ($Wheels) {
            Invoke-DemoPip -Py $py -PipArgs @('install', '--no-index', '--find-links', $Wheels, 'physicsai-platform') -What 'wheel 설치'
        }
    }
    if ($RepoRoot) {
        $stampFile = Join-Path $venv 'physicsai-repo-deps.sha256'
        $want = Get-DemoDepsStamp -RepoRoot $RepoRoot
        $have = if (Test-Path -LiteralPath $stampFile) { ([IO.File]::ReadAllText($stampFile)).Trim() } else { '' }
        if ($have -eq $want) {
            Write-Host '[PhysicsAI 시연] 시연 venv 의존성: 설치되어 있음(requirements.lock 변경 없음 — 건너뜀)'
        } else {
            Write-Host '[PhysicsAI 시연] 시연 venv에 의존성 설치: packages\simdash_adapters → deploy\requirements.lock (처음 한 번, 몇 분 걸림)'
            Invoke-DemoPip -Py $py -PipArgs @('install', (Join-Path $RepoRoot 'packages\simdash_adapters')) -What '공통 어댑터 패키지(simdash-adapters) 설치'
            Invoke-DemoPip -Py $py -PipArgs @('install', '-r', (Join-Path $RepoRoot 'deploy\requirements.lock')) -What '의존성(deploy\requirements.lock) 설치'
            [IO.File]::WriteAllText($stampFile, $want)
        }
    }
    return $py
}
