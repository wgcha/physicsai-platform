<#
.SYNOPSIS
  PhysicsAI 설치·업데이트 공용 함수. install.ps1(묶음)·update.ps1(묶음)·setup.ps1(git 폴더)·update-repo.ps1(git 폴더)이 dot-source 한다.
.DESCRIPTION
  DB 역할·DB 생성, 런타임 파일(DB 접속 정보), alembic, 작업 스케줄러 등록·시작·중지, health 확인, 실행 중 작업 확인을 한 곳에 둔다(설치 방식과 무관).
  관리자 권한이 필요 없다(phase3 D3-41): 머신 환경변수를 쓰지 않고 DB URL은 <런타임>\secrets\database_url(현재 사용자·SYSTEM만 읽기),
  설정 경로는 <런타임>\config\platform.yaml(또는 --config) — 작업은 현재 사용자 Interactive·Limited로 `--runtime <런타임>` 인자와 함께 등록.
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

function Test-PhysicsAIAccessDenied {
    <# 오류 레코드가 권한 부족(액세스 거부)인지 — 작업 스케줄러(CIM)·파일 API 공통. -AlreadyExists면 "이미 있음"도(보이지 않는 관리자 작업). #>
    param($ErrorRecord, [switch]$AlreadyExists)
    if (-not $ErrorRecord) { return $false }
    $e = if ($ErrorRecord -is [Management.Automation.ErrorRecord]) { $ErrorRecord.Exception } else { $ErrorRecord }
    if ($ErrorRecord -is [Management.Automation.ErrorRecord] -and "$($ErrorRecord.CategoryInfo.Category)" -eq 'PermissionDenied') { return $true }
    if ($e -is [UnauthorizedAccessException] -or $e.HResult -eq -2147024891) { return $true }   # 0x80070005
    $m = "$($e.Message)"
    if ($m -match '(?i)access is denied|access denied|액세스가 거부|0x80070005|E_ACCESSDENIED') { return $true }
    if ($AlreadyExists -and ($e.HResult -eq -2147024713 -or $m -match '(?i)already exists|0x800700B7|이미 있')) { return $true }
    return $false
}

function Get-PhysicsAITaskAdminMessage {
    <# 이전 설치가 관리자 권한으로 등록한 작업을 일반 PowerShell에서 바꿀 수 없을 때(처음 한 번만 관리자 실행). #>
    $cmd = "powershell -NoProfile -ExecutionPolicy Bypass -File $(Join-Path $PSScriptRoot 'update-repo.ps1')"
    return ("작업 스케줄러 작업(PhysicsAI-Backend·PhysicsAI-Worker)을 바꿀 권한이 없습니다(이전 설치가 관리자 권한으로 등록한 작업).`n" +
        "다음 행동: 처음 한 번만 지금과 같은 사용자 계정으로 PowerShell을 '관리자 권한으로 실행'해 update-repo.ps1을 실행하세요(그 뒤로는 일반 PowerShell로 됩니다).`n" +
        "  다른 관리자 계정으로 로그인해 실행하지 마세요 — DB 접속 정보 폴더(.runtime\secrets)는 지금 사용자만 읽을 수 있고 작업도 지금 사용자로 등록됩니다:`n  $cmd")
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
      -ReuseExisting: 기존 DB URL(-ExistingUrl — 런타임 파일 또는 이전 설치의 머신 환경변수, Get-PhysicsAIDbUrl)이 같은 host·port·DB·역할을
      가리키고 실제로 접속되면 그 값을 그대로 쓴다(비밀번호를 묻지 않음 — 재실행·기존 설치 이어받기).
    #>
    param([Parameter(Mandatory = $true)][string]$PgBin, [Parameter(Mandatory = $true)][string]$PgHost, [Parameter(Mandatory = $true)][int]$PgPort,
          [Parameter(Mandatory = $true)][string]$DbName, [Parameter(Mandatory = $true)][string]$DbRole,
          [switch]$PasswordsFromEnv, [switch]$ReuseExisting, [switch]$NonInteractive, [string]$ExistingUrl = '')
    $psql = Join-Path $PgBin 'psql.exe'
    if (-not (Test-Path -LiteralPath $psql)) { throw "psql.exe가 없습니다: $psql (pg_bin 또는 대시보드 .env의 POSTGRES_BIN 확인)" }
    if ($ReuseExisting) {
        $cur = ConvertFrom-PhysicsAIDbUrl $ExistingUrl
        if ($cur -and $cur.Host -eq $PgHost -and $cur.Port -eq $PgPort -and $cur.Db -eq $DbName -and $cur.User -eq $DbRole) {
            if (Test-PhysicsAIDbLogin -PgBin $PgBin -Parts $cur) {
                Write-PhysicsAIStep "DB: 기존 연결 재사용($DbRole@${PgHost}:$PgPort/$DbName — 비밀번호를 다시 묻지 않음)"
                return $ExistingUrl
            }
            Write-PhysicsAIStep '기존 DB 접속 정보로 접속되지 않습니다 — 비밀번호를 다시 받습니다'
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

# ---- 런타임 파일(관리자 권한 없이 — phase3 D3-41) ------------------------------------------------------------------
# DB URL(앱 비밀번호 포함)은 <런타임>\secrets\database_url 한 파일(UTF-8, BOM·줄바꿈 없음)에만 둔다. 백엔드·워커는
# `--runtime <런타임>` 인자(파일 경로만 — 비밀값은 인자·로그에 없음)로 찾는다(physicsai_core.config.runtime).

function Get-PhysicsAIMachineEnv([string]$Name) {
    <# 이전 설치의 머신 환경변수 읽기(읽기만 — 쓰지 않는다. 일반 사용자도 읽을 수 있음). #>
    return [Environment]::GetEnvironmentVariable($Name, 'Machine')
}

function Get-PhysicsAIRuntimeSecretPath([string]$RuntimeDir) { return (Join-Path (Join-Path $RuntimeDir 'secrets') 'database_url') }

function Get-PhysicsAIDbUrl {
    <# DB URL: 런타임 파일 → (없으면) 이전 설치의 머신 환경변수(읽기만) → 빈 문자열. 값은 출력하지 않는다. #>
    param([string]$RuntimeDir = '')
    if ($RuntimeDir) {
        $f = Get-PhysicsAIRuntimeSecretPath $RuntimeDir
        if (Test-Path -LiteralPath $f -PathType Leaf) {
            $v = ([IO.File]::ReadAllText($f)).Trim().TrimStart([char]0xFEFF)
            if ($v) { return $v }
        }
    }
    $m = Get-PhysicsAIMachineEnv 'PHYSICSAI_DATABASE_URL'
    if ($m) { return $m }
    return ''
}

function Protect-PhysicsAISecretPath {
    <#
      비밀 폴더 ACL: 상속 해제 + 현재 사용자·SYSTEM 모든 권한(+작업 실행 계정이 다르면 읽기)만, 하위로 상속((OI)(CI)) — icacls(Windows 기본 도구).
      폴더에만 적용한다(/T 없음 — 파일에 (OI)(CI)를 직접 주면 거부되어 빈 ACL이 남을 수 있음). 파일은 폴더에서 상속받는다.
      실패하거나 icacls가 없으면 경고만 하고 계속한다(설치를 막지 않음). 성공하면 $true.
    #>
    param([Parameter(Mandatory = $true)][string]$Path, [string]$ServiceUser = '')
    $icacls = Get-Command icacls -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $icacls) { Write-Warning "비밀 파일 권한 제한을 건너뜁니다(icacls 없음): $Path"; return $false }
    $me = "$env:USERDOMAIN\$env:USERNAME"
    try { $me = '*' + [Security.Principal.WindowsIdentity]::GetCurrent().User.Value } catch { Write-Verbose '현재 사용자 SID를 읽지 못함 — 이름으로 지정' }
    $grants = @("${me}:(OI)(CI)F", '*S-1-5-18:(OI)(CI)F')
    $cur = "$env:USERDOMAIN\$env:USERNAME"
    if ($ServiceUser -and $ServiceUser -ine $cur) { $grants += "${ServiceUser}:(OI)(CI)R" }
    $icArgs = @($Path, '/inheritance:r', '/grant:r') + $grants + @('/Q')
    $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $out = @(& $icacls.Source @icArgs 2>&1 | ForEach-Object { "$_" }); $rc = $LASTEXITCODE }
    catch { $out = @("$($_.Exception.Message)"); $rc = -1 }
    finally { $ErrorActionPreference = $eap }
    if ($rc -ne 0) {
        Write-Warning "비밀 파일 권한 제한 실패(icacls 종료코드 $rc): $Path — $(($out | Where-Object { $_ }) -join ' ') (설치는 계속합니다. 다른 사용자가 이 PC에 로그온한다면 이 폴더 권한을 직접 확인하세요)"
        return $false
    }
    return $true
}

function Write-PhysicsAIRuntimeSecret {
    <#
      DB URL을 <런타임>\secrets\database_url에 쓴다(값은 출력하지 않음, 같은 값이면 다시 쓰지 않음) + ACL 제한 시도 + 이 프로세스 환경에도
      (alembic용 — 프로세스 범위라 다른 프로세스·머신 환경변수에는 남지 않음). 관리자 권한 불필요.
    #>
    param([Parameter(Mandatory = $true)][string]$RuntimeDir, [Parameter(Mandatory = $true)][string]$DbUrl, [string]$ServiceUser = '', [string]$ConfigPath = '')
    $dir = Join-Path $RuntimeDir 'secrets'
    $f = Get-PhysicsAIRuntimeSecretPath $RuntimeDir
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $ok = Protect-PhysicsAISecretPath -Path $dir -ServiceUser $ServiceUser   # 폴더 먼저 → 파일은 그 ACL을 상속
    $same = $false
    if (Test-Path -LiteralPath $f -PathType Leaf) {
        try { $same = (([IO.File]::ReadAllText($f)).Trim() -ceq $DbUrl) }
        catch {
            # 읽을 수 없는 파일(빈 ACL 등): 상속을 되살려 폴더 ACL을 받게 한다(소유자는 권한을 바꿀 수 있음)
            Write-Warning "DB 접속 정보 파일을 읽을 수 없어 권한을 폴더 기준으로 되돌립니다: $f"
            $ic = Get-Command icacls -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($ic) { $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'; try { & $ic.Source $f '/reset' '/Q' 2>&1 | Out-Null } finally { $ErrorActionPreference = $eap } }
        }
    }
    if (-not $same) { [IO.File]::WriteAllText($f, $DbUrl, (New-Object Text.UTF8Encoding($false))) }
    if (([IO.File]::ReadAllText($f)).Trim() -cne $DbUrl) { throw "DB 접속 정보 파일을 다시 읽지 못했습니다: $f" }
    $env:PHYSICSAI_DATABASE_URL = $DbUrl
    if ($ConfigPath) { $env:PHYSICSAI_CONFIG = $ConfigPath }
    Write-PhysicsAIStep "DB 접속 정보: $f $(if ($same) { '(변경 없음)' } else { '(저장)' })$(if ($ok) { ' — 현재 사용자·SYSTEM만 읽기' }) (값은 출력하지 않음)"
}

function Move-PhysicsAIMachineEnvToRuntime {
    <#
      이전 설치(관리자 권한, 머신 환경변수) → 런타임 파일 이전: 런타임 DB 파일이 없고 머신 환경변수 PHYSICSAI_DATABASE_URL이 있으면 그 값을 파일로.
      머신 환경변수는 지우지 않는다(관리자 필요) — 이후에는 런타임 파일이 우선(--runtime). 옮겼으면 $true.
    #>
    param([Parameter(Mandatory = $true)][string]$RuntimeDir, [string]$ServiceUser = '')
    $f = Get-PhysicsAIRuntimeSecretPath $RuntimeDir
    $m = Get-PhysicsAIMachineEnv 'PHYSICSAI_DATABASE_URL'
    if ((Test-Path -LiteralPath $f -PathType Leaf) -or -not $m) { return $false }
    Write-PhysicsAIRuntimeSecret -RuntimeDir $RuntimeDir -DbUrl $m -ServiceUser $ServiceUser
    Write-PhysicsAIStep '이전 설치의 머신 환경변수 DB URL을 런타임 파일로 옮겼습니다 — 이제 런타임 파일이 우선입니다(머신 환경변수는 그대로 둠)'
    Write-PhysicsAIStep "  머신 환경변수를 지우려면(선택, 관리자 PowerShell): [Environment]::SetEnvironmentVariable('PHYSICSAI_DATABASE_URL', `$null, 'Machine'); [Environment]::SetEnvironmentVariable('PHYSICSAI_CONFIG', `$null, 'Machine')"
    return $true
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

function Get-PhysicsAITaskArguments {
    <# 작업 실행 인자: -m <모듈> --runtime "<런타임>" [--config "<설정>"](설정이 <런타임>\config\platform.yaml이 아닐 때만). 비밀값 없음(파일 경로만). #>
    param([Parameter(Mandatory = $true)][string]$Module, [Parameter(Mandatory = $true)][string]$RuntimeDir, [string]$ConfigPath = '')
    $a = "-m $Module --runtime `"$($RuntimeDir.TrimEnd('\', '/'))`""
    $defCfg = Join-Path (Join-Path $RuntimeDir 'config') 'platform.yaml'
    if ($ConfigPath -and -not ([IO.Path]::GetFullPath($ConfigPath) -ieq [IO.Path]::GetFullPath($defCfg))) { $a += " --config `"$ConfigPath`"" }
    return $a
}

function Get-PhysicsAITaskSpecs {
    param([Parameter(Mandatory = $true)][string]$RuntimeDir, [string]$ConfigPath = '')
    return @(
        @{ Name = 'PhysicsAI-Backend'; Args = (Get-PhysicsAITaskArguments -Module 'physicsai_api.serve' -RuntimeDir $RuntimeDir -ConfigPath $ConfigPath) },
        @{ Name = 'PhysicsAI-Worker'; Args = (Get-PhysicsAITaskArguments -Module 'physicsai_worker' -RuntimeDir $RuntimeDir -ConfigPath $ConfigPath) }
    )
}

function Grant-PhysicsAITaskAccess {
    <#
      등록한 작업의 보안 설명자에 실행 계정 모든 권한(FA)을 더한다(최선 노력 — 실패는 조용히). 관리자 PowerShell로 한 번 등록(이전 설치 이어받기)해도
      그 뒤 일반 PowerShell에서 중지·시작·다시 등록할 수 있게(phase3 D3-41).
    #>
    param([Parameter(Mandatory = $true)][string]$TaskName, [Parameter(Mandatory = $true)][string]$User)
    try {
        $sid = (New-Object Security.Principal.NTAccount($User)).Translate([Security.Principal.SecurityIdentifier]).Value
        $svc = New-Object -ComObject 'Schedule.Service'
        $svc.Connect()
        $task = $svc.GetFolder('\').GetTask($TaskName)
        $sd = $task.GetSecurityDescriptor(4)   # DACL
        if ($sd -notmatch [regex]::Escape(";;;$sid)")) { $task.SetSecurityDescriptor($sd + "(A;;FA;;;$sid)", 0) }
    } catch { Write-Verbose "작업 권한 추가 건너뜀($TaskName): $($_.Exception.Message)" }
}

function Register-PhysicsAITasks {
    <#
      작업 스케줄러 등록 PhysicsAI-Backend(-m physicsai_api.serve)·PhysicsAI-Worker(-m physicsai_worker) — 인자 --runtime <런타임>(Get-PhysicsAITaskArguments).
      이미 있으면 다시 등록(같은 이름). ExecutionTimeLimit = 0(무제한) 필수 — 기본 72시간이면 장시간 작업 중 워커가 종료된다(phase2 §11.1).
      Interactive(기본): 실행 계정(기본 현재 사용자) 로그온 시, LogonType Interactive·RunLevel Limited — 관리자 권한 불필요.
      Background: 부팅 시(AtStartup)·비밀번호 저장 — 이 모드만 관리자 권한이 필요할 수 있다(거부되면 안내).
      이전 설치가 관리자 권한으로 만든 작업이라 바꿀 수 없으면(액세스 거부) "처음 한 번만 같은 사용자 계정으로 '관리자 권한으로 실행'해 update-repo.ps1" 안내로 중단.
    #>
    param([Parameter(Mandatory = $true)][string]$VenvPy, [Parameter(Mandatory = $true)][string]$WorkDir,
          [Parameter(Mandatory = $true)][string]$ServiceUser, [Parameter(Mandatory = $true)][ValidateSet('Background', 'Interactive')][string]$RunMode,
          [Parameter(Mandatory = $true)][string]$RuntimeDir, [string]$ConfigPath = '',
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
    foreach ($t in (Get-PhysicsAITaskSpecs -RuntimeDir $RuntimeDir -ConfigPath $ConfigPath)) {
        $action = New-ScheduledTaskAction -Execute $VenvPy -Argument $t.Args -WorkingDirectory $WorkDir
        try {
            if (Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue) {
                Stop-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
                Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false -ErrorAction Stop
            }
            if ($RunMode -eq 'Interactive') {
                Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -ErrorAction Stop | Out-Null
            } else {
                Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings `
                    -User $ServiceUser -Password (ConvertTo-PhysicsAIPlain $svcPw) -RunLevel Limited -ErrorAction Stop | Out-Null
            }
        } catch {
            Remove-Variable -Name svcPw -ErrorAction SilentlyContinue
            if (Test-PhysicsAIAccessDenied $_ -AlreadyExists) {
                if ($RunMode -eq 'Background') {
                    throw ("작업 등록이 거부되었습니다($($t.Name), Background 모드). Background(부팅 시·비밀번호 저장) 등록은 관리자 권한이 필요할 수 있습니다.`n" +
                        "다음 행동: 기본 Interactive 모드를 쓰거나(deploy.json run_mode 또는 -RunMode Interactive), 이 모드만 같은 사용자 계정으로 PowerShell을 '관리자 권한으로 실행'해 실행하세요(다른 관리자 계정이면 런타임 비밀 파일을 읽지 못함).")
                }
                throw (Get-PhysicsAITaskAdminMessage)
            }
            throw
        }
        Grant-PhysicsAITaskAccess -TaskName $t.Name -User $ServiceUser
        Write-PhysicsAIStep "작업 등록: $($t.Name) ($RunMode, $ServiceUser, 작업 폴더 $WorkDir, 인자 $($t.Args))"
    }
    Remove-Variable -Name svcPw -ErrorAction SilentlyContinue
}

function Test-PhysicsAITasksCurrent {
    <# 등록된 두 작업의 실행 파일·인자·작업 폴더가 원하는 값과 같으면 $true(다시 등록할 필요 없음). #>
    param([Parameter(Mandatory = $true)][string]$VenvPy, [Parameter(Mandatory = $true)][string]$WorkDir,
          [Parameter(Mandatory = $true)][string]$RuntimeDir, [string]$ConfigPath = '')
    foreach ($t in (Get-PhysicsAITaskSpecs -RuntimeDir $RuntimeDir -ConfigPath $ConfigPath)) {
        $cur = Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
        if (-not $cur -or -not $cur.Actions.Count) { return $false }
        $a = $cur.Actions[0]
        if ("$($a.Execute)" -ne $VenvPy -or "$($a.Arguments)" -ne $t.Args -or "$($a.WorkingDirectory)" -ne $WorkDir) { return $false }
    }
    return $true
}

function Update-PhysicsAITaskRegistration {
    <#
      업데이트(update-repo.ps1·update.ps1): 작업 인자가 새 방식(--runtime)과 다르면 다시 등록(Interactive만 — 질문 없음). 다시 등록했으면 $true.
      Background는 비밀번호가 필요해 자동으로 다시 등록하지 않고 안내만 한다(기존 작업은 이전 머신 환경변수로 계속 동작).
      새 코드(venv·프런트)가 배치된 뒤에 부를 것(phase3 D3-42) — 이전 코드는 --runtime 인자를 몰라 다시 등록된 작업으로 시작하지 못한다.
    #>
    param([Parameter(Mandatory = $true)][string]$VenvPy, [Parameter(Mandatory = $true)][string]$WorkDir,
          [Parameter(Mandatory = $true)][string]$RuntimeDir, [string]$ConfigPath = '', [string]$ServiceUser = '', [string]$RunMode = 'Interactive')
    if (Test-PhysicsAITasksCurrent -VenvPy $VenvPy -WorkDir $WorkDir -RuntimeDir $RuntimeDir -ConfigPath $ConfigPath) {
        Write-PhysicsAIStep '작업 등록 그대로(인자 --runtime 확인)'
        return $false
    }
    if (-not $ServiceUser) { $ServiceUser = "$env:USERDOMAIN\$env:USERNAME" }
    if ($RunMode -eq 'Background') {
        Write-Warning ("작업 인자가 새 방식(--runtime)이 아니지만 Background 모드라 자동으로 다시 등록하지 않습니다(비밀번호 필요). " +
            "기존 작업은 이전 머신 환경변수로 계속 동작합니다. 바꾸려면 setup.ps1을 다시 실행하세요(Background 등록은 관리자 권한이 필요할 수 있음).")
        return $false
    }
    Write-PhysicsAIStep '작업 다시 등록(인자 --runtime <런타임> — 머신 환경변수 대신 런타임 파일)'
    Register-PhysicsAITasks -VenvPy $VenvPy -WorkDir $WorkDir -ServiceUser $ServiceUser -RunMode 'Interactive' -RuntimeDir $RuntimeDir -ConfigPath $ConfigPath -NonInteractive
    return $true
}

function Stop-PhysicsAITasks {
    <# 두 작업 중지(없으면 건너뜀). 이전 설치가 관리자 권한으로 만든 작업이라 거부되면 안내와 함께 중단(Get-PhysicsAITaskAdminMessage).
       -TaskNames로 중지 순서를 바꿀 수 있다(restart.ps1: 워커 → 백엔드). #>
    param([string[]]$TaskNames = $PhysicsAITaskNames)
    foreach ($t in $TaskNames) {
        if (-not (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue)) { continue }
        try { Stop-ScheduledTask -TaskName $t -ErrorAction Stop }
        catch {
            if (Test-PhysicsAIAccessDenied $_) { throw (Get-PhysicsAITaskAdminMessage) }
            Write-Warning "작업 중지 실패: $t — $($_.Exception.Message)"
        }
    }
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
    foreach ($t in $PhysicsAITaskNames) {
        try { Start-ScheduledTask -TaskName $t -ErrorAction Stop }
        catch { if (Test-PhysicsAIAccessDenied $_) { throw (Get-PhysicsAITaskAdminMessage) }; throw }
    }
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
      대기·실행 중 작업 + 진행 중 환경 점검 수. 묻지 않고 DB URL(-DbUrl = Get-PhysicsAIDbUrl: 런타임 파일 → 이전 머신 환경변수)로 psql 직접 조회한다
      (대시보드 세션 토큰 질문 없음 — phase3 D3-39). 접속 정보는 PG* 프로세스 환경으로만 전달(명령 인자에 비밀번호 없음).
    #>
    param([Parameter(Mandatory = $true)][int]$Port, [Parameter(Mandatory = $true)][string]$PgBin, [string]$DbUrl = '')
    $p = ConvertFrom-PhysicsAIDbUrl $DbUrl
    if (-not $p) { throw 'DB 접속 정보(런타임 파일 .runtime\secrets\database_url 또는 이전 설치의 머신 환경변수 PHYSICSAI_DATABASE_URL)가 없거나 형식을 해석할 수 없어 대기열을 확인할 수 없습니다(설치 setup.ps1·install.ps1을 먼저 하세요)' }
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
    param([Parameter(Mandatory = $true)][int]$Port, [Parameter(Mandatory = $true)][string]$PgBin, [string]$DbUrl = '', [switch]$Force)
    $active = Get-PhysicsAIActiveJobCount -Port $Port -PgBin $PgBin -DbUrl $DbUrl
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

function Install-PhysicsAIFrontendFromRepo {
    <#
      git 폴더의 프런트를 배치(phase3 D3-40): 저장소 빌드본 <RepoRoot>\frontend-dist가 있고 BUILD_INFO.json source_hash가 현재 소스와 같으면
      그대로 복사 — Node 선택·npm 단계 자체를 건너뜀. 다르거나 없을 때만 Node 22로 직접 빌드(Invoke-PhysicsAIFrontendBuild, 콘솔 그대로 — D3-39).
      반환값 없음 — 결과를 변수에 받지 말 것(받으면 npm 출력이 파이프가 된다). node-select.ps1을 함께 dot-source 해야 한다.
    #>
    param([Parameter(Mandatory = $true)][string]$RepoRoot, [Parameter(Mandatory = $true)][string]$Dest, [Parameter(Mandatory = $true)][string]$BackupDir,
          [string]$DashboardNode = '', [string]$StampFile = '')
    $st = Test-PhysicsAIFrontendDist -RepoRoot $RepoRoot
    if ($st.Fresh) {
        Write-PhysicsAIStep "프런트: 저장소 빌드본 frontend-dist 사용(소스와 일치 $($st.Current.Substring(0, 12)) — Node·npm 불필요)"
        Publish-PhysicsAIFrontend -Dist (Join-Path $RepoRoot 'frontend-dist') -Dest $Dest -BackupDir $BackupDir
    } else {
        Write-PhysicsAIStep "프런트: $($st.Reason) — Node 22로 직접 빌드합니다"
        try { $node = Select-PhysicsAINode -DashboardNode $DashboardNode -RepoRoot $RepoRoot -Tag $script:PhysicsAITag }
        catch {
            throw ("저장소 빌드본(frontend-dist)이 현재 소스와 맞지 않아 직접 빌드해야 하는데 Node 22가 없습니다.`n" +
                "다음 행동: 개발 쪽에 'scripts/build-frontend-dist 실행 후 frontend-dist 커밋'을 요청한 뒤 다시 업데이트하세요(Node 불필요). 또는 Node 22를 설치하세요.`n" +
                "($($_.Exception.Message))")
        }
        Invoke-PhysicsAIFrontendBuild -Node $node -RepoRoot $RepoRoot -StampFile $StampFile
        Publish-PhysicsAIFrontend -Dist (Join-Path $RepoRoot 'frontend\dist') -Dest $Dest -BackupDir $BackupDir
    }
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

function Get-PhysicsAISmbShares {
    <# 받은 파일 공유 안내(phase3 §12 S7, D3-46): 이 PC의 SMB 공유 이름·경로를 조회만 한다(관리자 권한 없이, 만들거나 바꾸지 않음).
       Get-SmbShare가 없거나 실패하면 빈 목록 — setup_config.py가 Path가 <ai_root>\inbox인 공유로 storage.inbox_share_hint를 채운다. #>
    $out = @()
    try {
        if (Get-Command Get-SmbShare -ErrorAction SilentlyContinue) {
            foreach ($s in @(Get-SmbShare -ErrorAction Stop)) {
                if ($s.Name -and $s.Path) { $out += [ordered]@{ name = "$($s.Name)"; path = "$($s.Path)" } }
            }
        }
    } catch {
        Write-PhysicsAIStep "SMB 공유 조회를 건너뜁니다: $($_.Exception.Message)"
    }
    return $out   # 호출부가 @(...)로 감싼다(0개 = 빈 배열)
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
