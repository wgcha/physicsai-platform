<#
.SYNOPSIS
  PhysicsAI 설치·업데이트 공용 함수. install.ps1(묶음)·update.ps1(묶음)·setup.ps1(git 폴더)·update-repo.ps1(git 폴더)이 dot-source 한다.
.DESCRIPTION
  DB 역할·DB 생성, 머신 환경변수, alembic, 작업 스케줄러 등록·시작·중지, health 확인, 실행 중 작업 확인을 한 곳에 둔다(설치 방식과 무관).
  비밀번호는 Read-Host -AsSecureString(대화형) 또는 -PasswordsFromEnv(프로세스 환경변수)로만 받고, psql에는 PGPASSWORD 프로세스 환경으로만 넘긴다
  (명령 인자·로그·파일에 남기지 않음). 출력 머리말은 호출 스크립트의 $PhysicsAITag(예 'PhysicsAI 설치')를 쓴다.
  127.0.0.1 호출은 loopback-http.ps1(Invoke-LoopbackRest, 프록시 미사용)을 쓴다.
#>

. (Join-Path $PSScriptRoot 'loopback-http.ps1')

$PhysicsAITaskNames = @('PhysicsAI-Backend', 'PhysicsAI-Worker')

function Write-PhysicsAIStep([string]$Message) {
    $t = if ($script:PhysicsAITag) { $script:PhysicsAITag } else { 'PhysicsAI' }
    Write-Host "[$t] $Message"
}

function Assert-PhysicsAIExit([string]$What) {
    if ($LASTEXITCODE -ne 0) { throw "$What 실패(종료코드 $LASTEXITCODE)" }
}

function Test-PhysicsAIAdmin {
    $me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    return $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-PhysicsAIAdmin([string]$Command = '') {
    if (Test-PhysicsAIAdmin) { return }
    $how = if ($Command) { "`n  $Command" } else { '' }
    throw ("관리자 권한 PowerShell에서 실행하세요(머신 환경변수·작업 스케줄러 등록에 필요).`n" +
        "다음 행동: 시작 메뉴에서 'Windows PowerShell'을 오른쪽 클릭 → '관리자 권한으로 실행' → 같은 폴더로 이동한 뒤 다시 실행:$how")
}

function ConvertTo-PhysicsAIPlain([Security.SecureString]$Secure) {
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

function Read-PhysicsAISecret {
    <# 기본은 Read-Host -AsSecureString(대화형). -FromEnv면 프로세스 환경변수(명령 인자·로그에 남지 않음). #>
    param([string]$Prompt, [string]$EnvName, [switch]$FromEnv, [switch]$NonInteractive)
    if ($FromEnv) {
        $v = [Environment]::GetEnvironmentVariable($EnvName, 'Process')
        if ($null -eq $v) { throw "-PasswordsFromEnv: 환경변수 $EnvName 이 없습니다" }
        $ss = New-Object Security.SecureString   # ConvertTo-SecureString(모듈 자동 로드) 없이
        foreach ($ch in $v.ToCharArray()) { $ss.AppendChar($ch) }
        $ss.MakeReadOnly()
        return $ss
    }
    if ($NonInteractive) { throw "-NonInteractive: '$Prompt' 을(를) 물을 수 없습니다. -PasswordsFromEnv와 환경변수 $EnvName 을(를) 쓰세요" }
    return (Read-Host -AsSecureString $Prompt)
}

function Get-PhysicsAIBackendPort([string]$ConfigPath, [string]$Py) {
    # 포트는 platform.yaml server.port 한 곳에서만 읽는다(deploy.json에 포트 없음)
    if ($Py -and (Test-Path $Py)) {
        try {
            $p = & $Py -c "import sys; from physicsai_core.config import load_config; print(load_config(sys.argv[1], environ={}).settings.server.port)" $ConfigPath 2>$null
            if ($LASTEXITCODE -eq 0 -and "$p" -match '^\s*(\d+)\s*$') { return [int]$Matches[1] }
        } catch { Write-Verbose "venv로 포트 읽기 실패 — yaml에서 직접 읽습니다" }
    }
    if ($ConfigPath -and (Test-Path $ConfigPath)) {
        $m = [regex]::Match((Get-Content -Raw -Encoding UTF8 $ConfigPath), '(?m)^server:\s*\r?\n(?:[ \t]+.*\r?\n)*?[ \t]+port:\s*(\d+)')
        if ($m.Success) { return [int]$m.Groups[1].Value }
    }
    return 8100   # 설정 기본값
}

function Invoke-PhysicsAINative {
    <# 외부 명령 실행(출력은 화면으로). Windows PowerShell 5.1에서 자식 stderr가 오류 레코드로 중단되지 않게 하고 종료코드로만 판단한다. #>
    param([Parameter(Mandatory = $true)][string]$What, [Parameter(Mandatory = $true)][string]$Exe,
          [string[]]$Arguments = @(), [string]$Hint = '위 출력을 확인하세요')
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Exe @Arguments 2>&1 | ForEach-Object { Write-Host "$_" }; $rc = $LASTEXITCODE } finally { $ErrorActionPreference = $eap }
    if ($rc -ne 0) { throw "실패: $What (종료코드 $rc)`n다음 행동: $Hint" }
}

function Invoke-PhysicsAIPip {
    <# venv의 pip. 사내 pip 설정(PIP_INDEX_URL·pip.ini)·프록시(HTTPS_PROXY)는 그대로 쓴다. 실패하면 인덱스 접근 문제인지 판단해 한국어로 중단. #>
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
            "다음 행동: 사내 프록시면 pip 설정(pip.ini의 index-url·proxy, 또는 환경변수 PIP_INDEX_URL·HTTPS_PROXY)을 확인하세요. 인터넷이 안 되는 서버면 오프라인 묶음(deploy\collect-offline.ps1 → install.ps1)을 쓰세요.")
    }
    throw ("$What 실패(pip 종료코드 $rc).`n다음 행동: 위 pip 출력을 확인하세요.")
}

function ConvertFrom-PhysicsAIDbUrl([string]$Url) {
    <# postgresql+psycopg://user:pw@host:port/db → 각 부분(비밀번호 포함 — 호출 쪽은 출력·로그에 쓰지 않는다). 해석 불가면 $null. #>
    if (-not $Url) { return $null }
    $m = [regex]::Match($Url, '^postgres(?:ql)?(?:\+\w+)?://(?<u>[^:@/]+):(?<p>[^@]*)@(?<h>[^:/]+):(?<port>\d+)/(?<d>[^?]+)')
    if (-not $m.Success) { return $null }
    return [pscustomobject]@{
        User = [Uri]::UnescapeDataString($m.Groups['u'].Value); Password = [Uri]::UnescapeDataString($m.Groups['p'].Value)
        Host = $m.Groups['h'].Value; Port = [int]$m.Groups['port'].Value; Db = $m.Groups['d'].Value
    }
}

function Test-PhysicsAIDbLogin {
    <# 앱 역할로 접속 가능한지(비밀번호는 PGPASSWORD 프로세스 환경으로만, 끝나면 지움). #>
    param([Parameter(Mandatory = $true)][string]$PgBin, [Parameter(Mandatory = $true)]$Parts)
    $psql = Join-Path $PgBin 'psql.exe'
    if (-not (Test-Path -LiteralPath $psql)) { return $false }
    $env:PGPASSWORD = $Parts.Password
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $r = & $psql -h $Parts.Host -p ([string]$Parts.Port) -U $Parts.User -d $Parts.Db -w -tAc 'SELECT 1' 2>$null
        return ($LASTEXITCODE -eq 0 -and "$r".Trim() -eq '1')
    } catch { return $false } finally { $ErrorActionPreference = $eap; $env:PGPASSWORD = $null }
}

function Initialize-PhysicsAIDatabase {
    <#
      대시보드와 같은 PostgreSQL(기준 18)에 앱 역할·DB를 없을 때만 만들고, 앱 DB URL(비밀번호 포함)을 돌려준다.
      -ReuseExisting: 머신 환경변수 PHYSICSAI_DATABASE_URL이 같은 host·port·DB·역할을 가리키고 실제로 접속되면 그 값을 그대로 쓴다(비밀번호를 묻지 않음 — 재실행·기존 설치 이어받기).
    #>
    param([Parameter(Mandatory = $true)][string]$PgBin, [Parameter(Mandatory = $true)][string]$PgHost, [Parameter(Mandatory = $true)][int]$PgPort,
          [Parameter(Mandatory = $true)][string]$DbName, [Parameter(Mandatory = $true)][string]$DbRole,
          [switch]$PasswordsFromEnv, [switch]$ReuseExisting, [switch]$NonInteractive)
    $psql = Join-Path $PgBin 'psql.exe'
    if (-not (Test-Path -LiteralPath $psql)) { throw "psql.exe가 없습니다: $psql (pg_bin 또는 대시보드 .env의 POSTGRES_BIN 확인)" }
    if ($ReuseExisting) {
        $cur = ConvertFrom-PhysicsAIDbUrl ([Environment]::GetEnvironmentVariable('PHYSICSAI_DATABASE_URL', 'Machine'))
        if ($cur -and $cur.Host -eq $PgHost -and $cur.Port -eq $PgPort -and $cur.Db -eq $DbName -and $cur.User -eq $DbRole) {
            if (Test-PhysicsAIDbLogin -PgBin $PgBin -Parts $cur) {
                Write-PhysicsAIStep "DB: 기존 연결 재사용($DbRole@${PgHost}:$PgPort/$DbName — 비밀번호를 다시 묻지 않음)"
                return [Environment]::GetEnvironmentVariable('PHYSICSAI_DATABASE_URL', 'Machine')
            }
            Write-PhysicsAIStep '기존 머신 환경변수 DB URL로 접속되지 않습니다 — 비밀번호를 다시 받습니다'
        }
    }
    $adminPw = Read-PhysicsAISecret 'PostgreSQL 관리자(postgres) 비밀번호' 'PHYSICSAI_INSTALL_PG_ADMIN_PASSWORD' -FromEnv:$PasswordsFromEnv -NonInteractive:$NonInteractive
    $appPwSecure = Read-PhysicsAISecret "앱 DB 역할($DbRole) 비밀번호(이미 있으면 기존과 같은 값)" 'PHYSICSAI_INSTALL_DB_PASSWORD' -FromEnv:$PasswordsFromEnv -NonInteractive:$NonInteractive
    $appPw = ConvertTo-PhysicsAIPlain $appPwSecure
    $env:PGPASSWORD = ConvertTo-PhysicsAIPlain $adminPw
    try {
        $common = @('-h', $PgHost, '-p', [string]$PgPort, '-U', 'postgres', '-v', 'ON_ERROR_STOP=1', '-q')
        # 대시보드와 같은 PostgreSQL 18 인스턴스(별도 DB·역할)를 기준으로 한다 — 다른 주 버전이면 경고만(설치는 계속)
        $verNum = & $psql @common -d postgres -tAc 'SHOW server_version_num'; Assert-PhysicsAIExit 'psql 서버 버전 확인'
        $verMajor = [int][math]::Floor([int]("$verNum".Trim()) / 10000)
        if ($verMajor -ne 18) { Write-Warning "PostgreSQL 서버 주 버전이 $verMajor 입니다(기준: 대시보드와 같은 18). 계속 진행합니다" }
        else { Write-PhysicsAIStep "PostgreSQL 서버 버전: $("$verNum".Trim())" }
        $hasRole = & $psql @common -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname = '$DbRole'"; Assert-PhysicsAIExit 'psql 역할 확인'
        if (-not $hasRole) {
            Write-PhysicsAIStep "DB 역할 생성: $DbRole"
            # 비밀번호가 서버 로그에 남지 않게: 이 세션만 문장 로그·오류 문장 로그·느린 문장 로그를 끈 뒤 생성(superuser 세션 SET)
            # SQL은 표준 입력으로(명령 인자에 비밀번호 없음)
            $sql = "SET log_statement = 'none'; SET log_min_error_statement = 'panic'; SET log_min_duration_statement = -1; " +
                "SET password_encryption = 'scram-sha-256'; " +
                "CREATE ROLE `"$DbRole`" LOGIN PASSWORD '" + $appPw.Replace("'", "''") + "';"
            $sql | & $psql @common -d postgres | Out-Host; Assert-PhysicsAIExit 'CREATE ROLE'
            Remove-Variable -Name sql -ErrorAction SilentlyContinue
        } else {
            Write-PhysicsAIStep "DB 역할 있음: $DbRole (비밀번호는 바꾸지 않음)"
        }
        $hasDb = & $psql @common -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$DbName'"; Assert-PhysicsAIExit 'psql DB 확인'
        if (-not $hasDb) {
            Write-PhysicsAIStep "DB 생성: $DbName"
            "CREATE DATABASE `"$DbName`" OWNER `"$DbRole`";" | & $psql @common -d postgres | Out-Host; Assert-PhysicsAIExit 'CREATE DATABASE'
        } else {
            Write-PhysicsAIStep "DB 있음: $DbName"
        }
    } finally {
        Remove-Variable -Name adminPw -ErrorAction SilentlyContinue
        $env:PGPASSWORD = $null
    }
    $url = "postgresql+psycopg://${DbRole}:$([Uri]::EscapeDataString($appPw))@${PgHost}:$PgPort/$DbName"
    Remove-Variable -Name appPw, appPwSecure -ErrorAction SilentlyContinue
    return $url
}

function Set-PhysicsAIMachineEnv {
    <# 머신 환경변수 PHYSICSAI_CONFIG·PHYSICSAI_DATABASE_URL(값은 출력하지 않음) + 이 프로세스에도. #>
    param([Parameter(Mandatory = $true)][string]$ConfigPath, [Parameter(Mandatory = $true)][string]$DbUrl)
    [Environment]::SetEnvironmentVariable('PHYSICSAI_CONFIG', $ConfigPath, 'Machine')
    [Environment]::SetEnvironmentVariable('PHYSICSAI_DATABASE_URL', $DbUrl, 'Machine')
    $env:PHYSICSAI_CONFIG = $ConfigPath
    $env:PHYSICSAI_DATABASE_URL = $DbUrl
    Write-PhysicsAIStep '머신 환경변수 PHYSICSAI_CONFIG·PHYSICSAI_DATABASE_URL 설정(값은 출력하지 않음)'
}

function Invoke-PhysicsAIMigration {
    param([Parameter(Mandatory = $true)][string]$VenvPy, [Parameter(Mandatory = $true)][string]$AlembicIni)
    & $VenvPy -m alembic -c $AlembicIni upgrade head | Out-Host; Assert-PhysicsAIExit 'alembic upgrade head'
}

function Export-PhysicsAITasks {
    <# 기존 작업 정의를 XML로 남긴다(덮어쓰기 전 _backup). 없으면 아무것도 하지 않는다. 남긴 개수를 돌려준다. #>
    param([Parameter(Mandatory = $true)][string]$Dest)
    $n = 0
    foreach ($name in $PhysicsAITaskNames) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            New-Item -ItemType Directory -Force -Path $Dest | Out-Null
            Export-ScheduledTask -TaskName $name | Set-Content -LiteralPath (Join-Path $Dest "$name.xml") -Encoding Unicode
            $n++
        }
    }
    return $n
}

function Get-PhysicsAITaskExecute {
    <# 등록된 PhysicsAI-Backend 작업의 실행 파일 경로(없으면 빈 문자열). #>
    $t = Get-ScheduledTask -TaskName $PhysicsAITaskNames[0] -ErrorAction SilentlyContinue
    if ($t -and $t.Actions.Count) { return "$($t.Actions[0].Execute)" }
    return ''
}

function Register-PhysicsAITasks {
    <#
      작업 스케줄러 등록 PhysicsAI-Backend(-m physicsai_api.serve)·PhysicsAI-Worker(-m physicsai_worker). 이미 있으면 다시 등록(같은 이름).
      ExecutionTimeLimit = 0(무제한) 필수 — 기본 72시간이면 장시간 작업 중 워커가 종료된다(phase2 §11.1)
    #>
    param([Parameter(Mandatory = $true)][string]$VenvPy, [Parameter(Mandatory = $true)][string]$WorkDir,
          [Parameter(Mandatory = $true)][string]$ServiceUser, [Parameter(Mandatory = $true)][ValidateSet('Background', 'Interactive')][string]$RunMode,
          [switch]$PasswordsFromEnv, [switch]$NonInteractive)
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -StartWhenAvailable `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    if ($RunMode -eq 'Interactive') {
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $ServiceUser
        $principal = New-ScheduledTaskPrincipal -UserId $ServiceUser -LogonType Interactive -RunLevel Limited
    } else {
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $svcPw = Read-PhysicsAISecret "작업 실행 계정($ServiceUser) 비밀번호" 'PHYSICSAI_INSTALL_SERVICE_PASSWORD' -FromEnv:$PasswordsFromEnv -NonInteractive:$NonInteractive
    }
    $tasks = @(
        @{ Name = 'PhysicsAI-Backend'; Args = '-m physicsai_api.serve' },
        @{ Name = 'PhysicsAI-Worker'; Args = '-m physicsai_worker' }
    )
    foreach ($t in $tasks) {
        $action = New-ScheduledTaskAction -Execute $VenvPy -Argument $t.Args -WorkingDirectory $WorkDir
        if (Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue) {
            Stop-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false
        }
        if ($RunMode -eq 'Interactive') {
            Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
        } else {
            Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings `
                -User $ServiceUser -Password (ConvertTo-PhysicsAIPlain $svcPw) -RunLevel Limited | Out-Null
        }
        Write-PhysicsAIStep "작업 등록: $($t.Name) ($RunMode, 작업 폴더 $WorkDir)"
    }
    Remove-Variable -Name svcPw -ErrorAction SilentlyContinue
}

function Stop-PhysicsAITasks {
    foreach ($t in $PhysicsAITaskNames) { Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 5
}

function Wait-PhysicsAIHealth {
    <# http://127.0.0.1:<port>/physicsai/api/health 가 {"status":"ok"}가 될 때까지(최대 약 60초). 성공하면 $true. #>
    param([Parameter(Mandatory = $true)][int]$Port, [int]$Tries = 30)
    $health = "http://127.0.0.1:$Port/physicsai/api/health"
    for ($i = 0; $i -lt $Tries; $i++) {
        Start-Sleep -Seconds 2
        try { if ((Invoke-LoopbackRest -Uri $health -TimeoutSec 3).status -eq 'ok') { return $true } } catch { Write-Verbose "health 대기: $($_.Exception.Message)" }
    }
    return $false
}

function Start-PhysicsAITasksAndWait {
    <# 두 작업 시작 → health 확인. 실패하면 원인 확인 위치와 함께 중단. health 주소를 돌려준다. #>
    param([Parameter(Mandatory = $true)][int]$Port, [string]$LogDir = '')
    foreach ($t in $PhysicsAITaskNames) { Start-ScheduledTask -TaskName $t }
    $health = "http://127.0.0.1:$Port/physicsai/api/health"
    if (-not (Wait-PhysicsAIHealth -Port $Port)) {
        $where = if ($LogDir) { " 로그: $LogDir\backend.log" } else { '' }
        throw "health 확인 실패: $health — 작업 스케줄러 기록과 설정을 확인하세요.$where"
    }
    Write-PhysicsAIStep "health OK: $health"
    return $health
}

function Get-PhysicsAIActiveJobCount {
    <#
      대기·실행 중 작업 + 진행 중 환경 점검 수. 묻지 않고 머신 환경변수 DB URL로 psql 직접 조회한다(대시보드 세션 토큰 질문 없음 — phase3 D3-39).
      접속 정보는 PG* 프로세스 환경으로만 전달(명령 인자에 비밀번호 없음).
    #>
    param([Parameter(Mandatory = $true)][int]$Port, [Parameter(Mandatory = $true)][string]$PgBin)
    $p = ConvertFrom-PhysicsAIDbUrl ([Environment]::GetEnvironmentVariable('PHYSICSAI_DATABASE_URL', 'Machine'))
    if (-not $p) { throw '머신 환경변수 PHYSICSAI_DATABASE_URL이 없거나 형식을 해석할 수 없어 대기열을 확인할 수 없습니다(설치 setup.ps1·install.ps1을 먼저 하세요)' }
    $env:PGUSER = $p.User; $env:PGHOST = $p.Host; $env:PGPORT = [string]$p.Port; $env:PGDATABASE = $p.Db; $env:PGPASSWORD = $p.Password
    try {
        $n = & (Join-Path $PgBin 'psql.exe') -w -tAc "SELECT (SELECT count(*) FROM jobs WHERE state IN ('QUEUED','RUNNING','WAITING_HPC','COLLECTING')) + (SELECT count(*) FROM env_checks WHERE state IN ('PENDING','RUNNING'))"
        Assert-PhysicsAIExit 'psql 작업 확인'
        return [int]"$n".Trim()
    } finally {
        $env:PGPASSWORD = $null; $env:PGUSER = $null; $env:PGHOST = $null; $env:PGPORT = $null; $env:PGDATABASE = $null
    }
}

function Assert-PhysicsAINoActiveJobs {
    <# 대기·실행 중 작업이 있으면 묻지 않고 안내와 함께 중단(-Force면 경고 후 진행). #>
    param([Parameter(Mandatory = $true)][int]$Port, [Parameter(Mandatory = $true)][string]$PgBin, [switch]$Force)
    $active = Get-PhysicsAIActiveJobCount -Port $Port -PgBin $PgBin
    if ($active -gt 0) {
        if (-not $Force) { throw "대기·실행 중 작업 또는 진행 중 환경 점검이 $active 건 있습니다. 끝난 뒤 다시 실행하세요(기다리지 않으려면 -Force)" }
        Write-Warning "-Force: 실행 중 작업은 lease 만료 후 INTERRUPTED가 됩니다($active 건)"
    } else {
        Write-PhysicsAIStep '대기·실행 중 작업 없음'
    }
}

# ---- git 폴더 설치(setup.ps1·update-repo.ps1) 공용 ---------------------------------------------------------------

function Test-PhysicsAIUnderPath {
    <# $Path가 $Root 자신이거나 그 안에 있으면 $true(대소문자 무시). #>
    param([string]$Path, [string]$Root)
    if (-not $Path -or -not $Root) { return $false }
    try {
        $p = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
        $r = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    } catch { return $false }
    return ($p -ieq $r) -or $p.StartsWith($r + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}

function Install-PhysicsAIRepoPackages {
    <#
      git 폴더의 소스를 venv에 일반 설치(editable 아님): deploy\requirements.lock(외부 의존성, 고정 버전) →
      packages\simdash_adapters → 플랫폼 패키지. 로컬 두 패키지는 --no-deps --force-reinstall로 매번 다시 설치(git pull 뒤 같은 버전 번호여도 새 소스 반영).
    #>
    param([Parameter(Mandatory = $true)][string]$VenvPy, [Parameter(Mandatory = $true)][string]$RepoRoot)
    Invoke-PhysicsAIPip -Py $VenvPy -PipArgs @('install', '-r', (Join-Path $RepoRoot 'deploy\requirements.lock')) -What '의존성(deploy\requirements.lock) 설치'
    Invoke-PhysicsAIPip -Py $VenvPy -PipArgs @('install', '--no-deps', '--force-reinstall', (Join-Path $RepoRoot 'packages\simdash_adapters')) -What '공통 어댑터 패키지(simdash-adapters) 설치'
    Invoke-PhysicsAIPip -Py $VenvPy -PipArgs @('install', '--no-deps', '--force-reinstall', $RepoRoot) -What '플랫폼 패키지(physicsai-platform) 설치'
    Invoke-PhysicsAINative '설치 확인(import)' $VenvPy @('-c', 'import physicsai_api, physicsai_worker, simdash_adapters, fastapi, psycopg, alembic, yaml') '위 오류를 확인하세요(venv 패키지 설치가 끝나지 않음)'
}

function Publish-PhysicsAIFrontend {
    <# 프런트 빌드 결과를 배치 위치로. 기존 배치는 지우지 않고 $BackupDir\frontend로 이동한다. #>
    param([Parameter(Mandatory = $true)][string]$Dist, [Parameter(Mandatory = $true)][string]$Dest, [Parameter(Mandatory = $true)][string]$BackupDir)
    if (Test-Path -LiteralPath $Dest) {
        New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
        Move-Item -LiteralPath $Dest -Destination (Join-Path $BackupDir 'frontend')
    }
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    Copy-Item -Recurse -Force (Join-Path $Dist '*') $Dest
    Write-PhysicsAIStep "프런트 배치: $Dest"
}

function Restore-PhysicsAIAfterFailedUpdate {
    <#
      update-repo.ps1이 migration 전에 실패했을 때(phase3 D3-39) 서비스가 멈춘 채 남지 않게:
      ① 이번에 $BackupDir\frontend로 옮긴 이전 프런트가 있으면 원위치($FrontendDest)로(새로 배치하던 것은 $BackupDir\frontend-failed로 — 삭제 없음)
      ② 작업 2개(PhysicsAI-Backend·Worker) 다시 시작(-NoStart면 생략). 스스로는 던지지 않는다(원래 실패를 가리지 않게).
    #>
    param([Parameter(Mandatory = $true)][string]$FrontendDest, [Parameter(Mandatory = $true)][string]$BackupDir, [switch]$NoStart)
    $prev = Join-Path $BackupDir 'frontend'
    try {
        if (Test-Path -LiteralPath $prev) {
            if (Test-Path -LiteralPath $FrontendDest) { Move-Item -LiteralPath $FrontendDest -Destination (Join-Path $BackupDir 'frontend-failed') }
            Move-Item -LiteralPath $prev -Destination $FrontendDest
            Write-PhysicsAIStep "이전 프런트로 되돌렸습니다: $FrontendDest"
        }
    } catch { Write-Warning "이전 프런트 되돌리기 실패: $($_.Exception.Message) — $prev 를 $FrontendDest 로 옮기세요" }
    if ($NoStart) { return }
    foreach ($t in $PhysicsAITaskNames) {
        try { Start-ScheduledTask -TaskName $t -ErrorAction Stop; Write-PhysicsAIStep "작업 다시 시작: $t" }
        catch { Write-Warning "작업 다시 시작 실패: $t — $($_.Exception.Message)" }
    }
}

function Get-PhysicsAIAccessUrl {
    <# 접속 주소 한 줄(update-repo.ps1 끝): 대시보드 .env의 WINDOWS_WEB_PORT(없으면 80) → http://<이 서버>[:포트]/physicsai/.
       대시보드 .env를 읽지 못했으면 http://<대시보드 주소>/physicsai/ ($Dash = Get-DashboardRuntimeDefaults 결과 또는 $null). #>
    param($Dash)
    if (-not $Dash -or -not $Dash.EnvFile) { return 'http://<대시보드 주소>/physicsai/' }
    $webPort = if ($Dash.WebPort) { [int]$Dash.WebPort } else { 80 }
    return "http://$([Environment]::MachineName)$(if ($webPort -ne 80) { ":$webPort" })/physicsai/"
}

function Write-PhysicsAIUtf8File {
    <# BOM 없는 UTF-8(Python json이 읽는 형식). #>
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Text)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false)))
}

function Invoke-PhysicsAISetupConfig {
    <# deploy\setup_config.py plan|write를 venv Python으로 실행하고 결과 JSON 객체를 돌려준다(입력·결과 파일은 <런타임>\setup-*.json, 비밀값 없음). #>
    param([Parameter(Mandatory = $true)][string]$VenvPy, [Parameter(Mandatory = $true)][ValidateSet('plan', 'write')][string]$Action,
          [Parameter(Mandatory = $true)][string]$RuntimeDir, [Parameter(Mandatory = $true)]$Inputs)
    $inFile = Join-Path $RuntimeDir 'setup-inputs.json'
    $outFile = Join-Path $RuntimeDir "setup-$Action.json"
    Write-PhysicsAIUtf8File -Path $inFile -Text ($Inputs | ConvertTo-Json -Depth 6)
    Invoke-PhysicsAINative "설정 파일 $Action" $VenvPy @((Join-Path $PSScriptRoot 'setup_config.py'), $Action, '--inputs', $inFile, '--out', $outFile) '위 오류를 확인하세요(설정 파일 형식 등)'
    return (Get-Content -Raw -Encoding UTF8 -LiteralPath $outFile | ConvertFrom-Json)
}

function Write-PhysicsAIConfigValidation {
    <# setup_config.py write 결과의 백업·검증 결과를 출력. 검증 오류가 있으면 $false. #>
    param([Parameter(Mandatory = $true)]$Result)
    foreach ($b in @($Result.write.backups)) { if ($b) { Write-PhysicsAIStep "바꾸기 전 사본: $b" } }
    foreach ($w in @($Result.write.written)) { if ($w) { Write-PhysicsAIStep "작성: $w" } }
    $v = $Result.write.validation
    foreach ($w in @($v.warnings)) { if ($w) { Write-PhysicsAIStep "설정 안내: $w" } }
    if ($v.ok -eq $false) {
        foreach ($i in @($v.issues)) { if ($i) { Write-Warning "설정 검증: $i" } }
        Write-Warning "설정 검증 오류가 있습니다 — 워커가 시작되지 않습니다(백엔드는 뜨지만 쓰기 API는 503). 설정 파일을 고친 뒤 Start-ScheduledTask PhysicsAI-Worker"
        return $false
    }
    Write-PhysicsAIStep '설정 검증 통과'
    return $true
}

function Write-PhysicsAIConnectGuide {
    <# 접속 연결 안내(setup.ps1·update-repo.ps1 끝). 기본: 대시보드 Vite 프록시(/physicsai → 이 백엔드) + 백엔드의 프런트 직접 서빙
       (platform.yaml server.frontend_root). Caddy는 대안. 대시보드 .env는 읽기만 한다(두 키가 이미 있는지 확인). #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][int]$Port, [string]$DashboardRoot = '', [string]$FrontendRoot = '', [string]$RepoRoot = '')
    $envFile = if ($DashboardRoot) { [IO.Path]::Combine($DashboardRoot, '.env') } else { '' }   # Join-Path는 없는 드라이브에서 오류
    $target = "http://127.0.0.1:$Port"
    $hasOn = $false; $hasTarget = $false
    if ($envFile -and (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        $hasOn = [bool](Select-String -LiteralPath $envFile -Pattern '^\s*SIMDASH_PHYSICSAI_ENABLED\s*=\s*"?(true|1|yes|on)"?\s*$' -Quiet)
        $hasTarget = [bool](Select-String -LiteralPath $envFile -Pattern ('^\s*VITE_PHYSICSAI_TARGET\s*=\s*"?' + [regex]::Escape($target) + '/?"?\s*$') -Quiet)
    }
    $where = if ($envFile) { $envFile } else { '대시보드 .env' }
    $state = if ($hasOn -and $hasTarget) { ' — 이미 들어 있음' } else { ' 를 넣고 대시보드를 다시 시작하세요' }
    Write-PhysicsAIStep "  1) $where 에 VITE_PHYSICSAI_TARGET=$target , SIMDASH_PHYSICSAI_ENABLED=true$state"
    Write-PhysicsAIStep "     (대시보드 Vite가 /physicsai 전체를 이 백엔드로 넘기고, 백엔드가 프런트 $FrontendRoot 를 /physicsai/ 아래에 서빙 — 설정 server.frontend_root)"
    Write-PhysicsAIStep "  2) 접속: http://<대시보드 주소>/physicsai/ (대시보드에 로그인한 상태로). 이 PC 확인용 health: $target/physicsai/api/health"
    $snippet = if ($RepoRoot) { [IO.Path]::Combine($RepoRoot, 'deploy', 'caddy', 'physicsai.caddy') } else { 'deploy\caddy\physicsai.caddy' }
    Write-PhysicsAIStep "  Caddy를 쓰는 설치: $snippet (Caddy 환경변수 PHYSICSAI_PORT=$Port, PHYSICSAI_FRONTEND_ROOT=$FrontendRoot)"
}
