"""원클릭·관리자 권한 없는 설치(phase3 D3-40·D3-41).

D3-40 저장소 빌드본 frontend-dist: 해시 규칙 Python(scripts/frontend_source_hash.py) ↔ PowerShell(node-select.ps1) 동일, 최신 여부,
       update-repo.ps1이 최신이면 Node·npm을 부르지 않음(가짜 npm이 불리면 실패), 오래되면 빌드 경로, git pull --ff-only.
D3-41 런타임 파일: 머신 환경변수 → .runtime\\secrets\\database_url 이전, 비밀 파일 ACL 시도(icacls), 로더 우선순위,
       백엔드·워커가 환경변수 없이 --runtime으로 기동, 관리자 검사 없음, 작업 스케줄러 액세스 거부 시 안내.
출력 비교는 줄바꿈·색 코드와 무관하게(_plain).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from physicsai_test_support import REPO
from test_setup_repo import DEPLOY, _FAKE_NPM, _fake_exe, _pwsh, _run_pwsh, _task_stubs, _touch, _update_repo_tree

sys.path.insert(0, str(REPO / "scripts"))
import frontend_source_hash as fsh  # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _plain(text: str) -> str:
    """색 코드 제거 + 줄바꿈·연속 공백을 한 칸으로(터미널 폭·5.1/7 차이와 무관한 비교)."""
    return re.sub(r"\s+", " ", ANSI.sub("", text))


def _need_pwsh() -> str:
    p = _pwsh()
    if not p:
        pytest.skip("pwsh 없음 — PowerShell 실행 시험 미수행(CI linux·windows 잡은 pwsh 있음)")
    return p


# ---------------------------------------------------------------------------------------------------------------
# D3-40: frontend-dist
# ---------------------------------------------------------------------------------------------------------------


def test_frontend_dist_committed_fresh_and_not_ignored():
    ok, msg = fsh.check(REPO)
    assert ok, msg
    info = json.loads((REPO / "frontend-dist" / "BUILD_INFO.json").read_text(encoding="utf-8"))
    assert set(info) == {"source_hash", "built_at", "vite_version", "node_version"}
    assert re.fullmatch(r"[0-9a-f]{64}", info["source_hash"]) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", info["built_at"])
    lock = json.loads((REPO / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    assert info["vite_version"] == lock["packages"]["node_modules/vite"]["version"] and info["node_version"].startswith("v22.")
    assert (REPO / "frontend-dist" / "index.html").read_text(encoding="utf-8").count("/physicsai/assets/") >= 1
    attrs = (REPO / ".gitattributes").read_text(encoding="utf-8")
    assert re.search(r"(?m)^frontend-dist/\*\* .*-diff.*linguist-generated=true", attrs)
    if shutil.which("git") and (REPO / ".git").exists():
        r = subprocess.run(["git", "-C", str(REPO), "check-ignore", "frontend-dist/index.html", "frontend-dist/assets/x.js"], capture_output=True)
        assert r.returncode == 1, "frontend-dist가 .gitignore에 걸립니다"
    for n in ("test-all.sh", "test-all.ps1"):
        assert "frontend_source_hash.py --check" in (REPO / "scripts" / n).read_text(encoding="utf-8-sig"), n
    build = (REPO / "scripts" / "build-frontend-dist.sh").read_text(encoding="utf-8")
    assert "npm ci && npm run build" in build and "--write-info" in build and "rm -rf frontend-dist" in build


def _fake_frontend(root: Path, *, crlf: bool) -> Path:
    fe = root / "frontend"
    nl = "\r\n" if crlf else "\n"
    files = {
        "index.html": f"<html>{nl}<body></body>{nl}</html>{nl}",
        "package.json": '{"name": "x"}' + nl,
        "package-lock.json": "{}" + nl,
        "vite.config.ts": f"export default {{}};{nl}",
        "tsconfig.json": "{}" + nl,
        "tsconfig.node.json": "{}" + nl,
        "src/main.tsx": f"import a from './a';{nl}console.log(a);{nl}",
        "src/한글/화면.tsx": f"export const x = '한글';{nl}",
        "src/Zeta.ts": "z" + nl,
        "src/alpha.ts": "a" + nl,
        "src/styles/app.css": f"body {{ margin: 0 }}{nl}",
        "public/logo.bin": None,   # 바이너리(\r\n 바이트 포함 — 두 구현이 같은 규칙으로 바꾸는지)
    }
    for rel, text in files.items():
        p = fe / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            p.write_bytes(bytes(range(256)) + b"\r\n\r\r\n")
        else:
            p.write_bytes(text.encode("utf-8"))
    # 대상 밖: node_modules·dist·기타 최상위 파일
    _touch(fe / "node_modules" / "vite" / "index.js").write_text("x", encoding="utf-8")
    _touch(fe / "dist" / "index.html").write_text("built", encoding="utf-8")
    (fe / "README.md").write_text("readme", encoding="utf-8")
    return fe


def _ps_hash(pwsh: str, fe: Path) -> str:
    r = _run_pwsh(pwsh, f". '{(DEPLOY / 'node-select.ps1').as_posix()}'; Get-PhysicsAIFrontendSourceHash -FrontendDir '{fe.as_posix()}'")
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout.strip()


def test_frontend_source_hash_python_equals_powershell(tmp_path):
    """해시 규칙 동일성: 같은 트리 → Python·PowerShell 같은 값, CRLF/LF 체크아웃 같은 값, 대상 밖 파일 무관, 소스 변경은 다른 값."""
    pwsh = _need_pwsh()
    lf = _fake_frontend(tmp_path / "lf", crlf=False)
    crlf = _fake_frontend(tmp_path / "crlf", crlf=True)
    h = fsh.source_hash(lf)
    assert fsh.source_hash(crlf) == h
    assert fsh.source_files(lf)[:6] == ["index.html", "package-lock.json", "package.json", "public/logo.bin", "src/Zeta.ts", "src/alpha.ts"]
    assert "README.md" not in fsh.source_files(lf) and not any("node_modules" in f or f.startswith("dist") for f in fsh.source_files(lf))
    assert _ps_hash(pwsh, lf) == h and _ps_hash(pwsh, crlf) == h
    # 저장소 실제 프런트도 같은 값
    assert _ps_hash(pwsh, REPO / "frontend") == fsh.source_hash(REPO / "frontend")
    # 대상 밖 변경 → 그대로, 소스 변경 → 다름(두 구현 모두)
    (lf / "node_modules" / "vite" / "index.js").write_text("changed", encoding="utf-8")
    (lf / "README.md").write_text("changed", encoding="utf-8")
    assert fsh.source_hash(lf) == h
    (lf / "src" / "한글" / "화면.tsx").write_text("export const x = '바뀜';\n", encoding="utf-8")
    h2 = fsh.source_hash(lf)
    assert h2 != h and _ps_hash(pwsh, lf) == h2
    _touch(lf / "public" / "new.svg")
    assert fsh.source_hash(lf) != h2 and _ps_hash(pwsh, lf) == fsh.source_hash(lf)


def _copy_dist(repo: Path) -> None:
    shutil.copytree(REPO / "frontend-dist", repo / "frontend-dist")
    info = json.loads((repo / "frontend-dist" / "BUILD_INFO.json").read_text(encoding="utf-8"))
    info["source_hash"] = fsh.source_hash(repo / "frontend")
    (repo / "frontend-dist" / "BUILD_INFO.json").write_text(json.dumps(info), encoding="utf-8")


def test_frontend_dist_stale_detection(tmp_path):
    pwsh = _need_pwsh()
    repo = tmp_path / "repo"
    _fake_frontend(repo, crlf=False)
    ok, msg = fsh.check(repo)
    assert not ok and "frontend-dist가 최신이 아닙니다: scripts/build-frontend-dist 실행 후 커밋" in msg and "BUILD_INFO.json 없음" in msg
    _copy_dist(repo)
    assert fsh.check(repo)[0]
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "frontend_source_hash.py"), "--check", str(repo)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    def ps_state() -> str:
        r = _run_pwsh(pwsh, f". '{(DEPLOY / 'node-select.ps1').as_posix()}'; $s = Test-PhysicsAIFrontendDist -RepoRoot '{repo.as_posix()}'; "
                            "\"FRESH=$($s.Fresh) REASON=$($s.Reason)\"")
        assert r.returncode == 0, r.stdout + r.stderr
        return _plain(r.stdout)

    assert "FRESH=True" in ps_state()
    (repo / "frontend" / "src" / "main.tsx").write_text("changed\n", encoding="utf-8")
    ok, msg = fsh.check(repo)
    assert not ok and "frontend-dist가 최신이 아닙니다" in msg and "≠" in msg
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "frontend_source_hash.py"), "--check", str(repo)], capture_output=True, text=True)
    assert r.returncode == 1 and "scripts/build-frontend-dist 실행 후 커밋" in r.stderr
    st = ps_state()
    assert "FRESH=False" in st and "현재 프런트 소스와 다릅니다" in st


# ---- update-repo.ps1 전체 흐름(Linux pwsh, 가짜 git 폴더 — test_setup_repo._update_repo_tree) --------------------------

_STOP_START = ("function Stop-ScheduledTask { param($TaskName) if ($env:FAKE_DENY -eq 'stop') { throw [UnauthorizedAccessException]::new('Access is denied.') }; "
               "Write-Host \"STOP $TaskName\" }; "
               "function Start-ScheduledTask { [CmdletBinding()] param($TaskName) Write-Host \"START $TaskName\" }; "
               "function Start-Sleep { param($Seconds) Write-Host \"SLEEP $Seconds\" }; ")


def _run_update(pwsh: str, repo: Path, log: Path, env: dict | None = None, stubs: str | None = None) -> tuple[subprocess.CompletedProcess, str]:
    log.unlink(missing_ok=True)
    body = (stubs if stubs is not None else _task_stubs(repo)) + _STOP_START
    r = _run_pwsh(pwsh, body + f"& '{(repo / 'deploy' / 'update-repo.ps1').as_posix()}'; \"EXIT=$LASTEXITCODE\"",
                  {"NPM_LOG": str(log), "FAKE_ACTIVE": "0", **(env or {})})
    return r, _plain(r.stdout + r.stderr)


@pytest.mark.posix
def test_update_repo_uses_fresh_frontend_dist_without_node(tmp_path):
    """frontend-dist가 최신이면 Node 선택·npm 단계 자체가 없다(가짜 npm은 불리면 실패). 소스가 바뀌면(오래됨) 기존 빌드 경로."""
    pwsh = _need_pwsh()
    repo = _update_repo_tree(tmp_path)
    rt = repo / ".runtime"
    log = tmp_path / "npm.log"
    _fake_frontend(repo, crlf=True)
    _copy_dist(repo)
    nd = tmp_path / "dash" / ".tools" / "node-v22.12.0-win-x64"
    _fake_exe(nd / "npm.cmd", 'echo "npm $*" >> "$NPM_LOG"; echo "NPM SHOULD NOT RUN" >&2; exit 9\n')
    _fake_exe(nd / "node.exe", 'echo "node $*" >> "$NPM_LOG"; echo v22.12.0\n')

    r, out = _run_update(pwsh, repo, log)
    assert "EXIT=0" in out, out
    assert not log.exists(), log.read_text(encoding="utf-8")                      # node·npm 호출 없음
    assert "저장소 빌드본 frontend-dist 사용" in out and "Node 선택" not in out
    assert (rt / "frontend" / "BUILD_INFO.json").exists() and (rt / "frontend" / "index.html").read_bytes() == (repo / "frontend-dist" / "index.html").read_bytes()
    assert list(rt.glob("_backup/*/frontend/old.txt"))                             # 이전 배치는 _backup(규칙 유지)
    assert "업데이트 성공 — 접속:" in out

    # 소스가 바뀜(오래된 빌드본) → 기존 빌드 경로(npm ci → run build, 콘솔 그대로)
    (repo / "frontend" / "src" / "main.tsx").write_text("changed\n", encoding="utf-8")
    _fake_exe(nd / "npm.cmd", _FAKE_NPM)
    _fake_exe(nd / "node.exe", "echo v22.12.0\n")
    r, out = _run_update(pwsh, repo, log)
    assert "EXIT=0" in out, out
    assert log.read_text(encoding="utf-8").splitlines() == ["npm ci console=y", "npm run build console=y"]
    assert "현재 프런트 소스와 다릅니다" in out and "Node 22로 직접 빌드합니다" in out and "Node 선택" in out

    # 오래됐는데 Node도 없음 → 명확한 안내(빌드본 갱신 요청 또는 Node 설치), 이전 프런트 복구
    shutil.rmtree(tmp_path / "dash" / ".tools")
    r, out = _run_update(pwsh, repo, log, {"PATH": "/usr/bin:/bin:" + str(Path(pwsh).parent)})
    assert "EXIT=1" in out, out
    assert "Node 22가 없습니다" in out and "scripts/build-frontend-dist 실행 후 frontend-dist 커밋" in out
    assert "업데이트 실패 — 접속:" in out and "START PhysicsAI-Backend" in out


def _git(*args: str, cwd: Path) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout.strip()


@pytest.mark.posix
def test_update_repo_git_pull_ff_only(tmp_path):
    """update-repo.ps1이 스스로 git pull --ff-only: 로컬 변경이면 안내 후 중단(바꾼 것 없음), 새 커밋이면 새 스크립트로 다시 실행(-SkipPull),
    분리된 HEAD(되돌리기)면 pull 없이 그 커밋으로."""
    pwsh = _need_pwsh()
    if not shutil.which("git"):
        pytest.skip("git 없음")
    repo = _update_repo_tree(tmp_path)
    log = tmp_path / "npm.log"
    (repo / ".gitignore").write_text(".runtime/\n", encoding="utf-8")
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    bare = tmp_path / "origin.git"
    _git("clone", "-q", "--bare", str(repo), str(bare), cwd=tmp_path)
    _git("remote", "add", "origin", str(bare), cwd=repo)
    _git("fetch", "-q", "origin", cwd=repo)
    _git("branch", "-q", "--set-upstream-to=origin/main", cwd=repo)

    # ① 이미 최신 → 그대로 진행
    r, out = _run_update(pwsh, repo, log)
    assert "EXIT=0" in out and "git: 이미 최신" in out and "git pull --ff-only" in out, out

    # ② 추적 파일 로컬 변경 → 안내 후 중단(작업 중지·빌드 없음)
    upd = repo / "deploy" / "update-repo.ps1"
    original = upd.read_text(encoding="utf-8-sig")
    (repo / "frontend" / "package-lock.json").write_text('{"x": 1}', encoding="utf-8")
    r, out = _run_update(pwsh, repo, log)
    assert "EXIT=1" in out and "STOP" not in out and not log.exists(), out
    assert "업데이트하지 않았습니다(바꾼 것 없음): git 폴더에 로컬 변경이 있어" in out and "frontend/package-lock.json" in out
    assert "업데이트 실패 — 접속:" in out
    _git("checkout", "--", "frontend/package-lock.json", cwd=repo)

    # ③ 원격에 새 커밋(새 update-repo.ps1) → pull 후 새 스크립트로 다시 실행(-SkipPull), 종료코드 전달
    other = tmp_path / "other"
    _git("clone", "-q", str(bare), str(other), cwd=tmp_path)
    new = original.replace("$ErrorActionPreference = 'Stop'", "$ErrorActionPreference = 'Stop'\nWrite-Host \"NEW-SCRIPT SkipPull=$SkipPull\"; exit 7", 1)
    (other / "deploy" / "update-repo.ps1").write_text(new, encoding="utf-8-sig")
    _git("commit", "-qam", "new update script", cwd=other)
    _git("push", "-q", "origin", "main", cwd=other)
    r, out = _run_update(pwsh, repo, log)
    assert "git: " in out and "new update script" in out and "받은 새 버전의 update-repo.ps1로 이어서 실행합니다" in out, out
    assert "NEW-SCRIPT SkipPull=True" in out and "EXIT=7" in out and "STOP" not in out
    assert "fast-forward" in out.lower()                                                    # git pull 출력은 화면에(결과 값에 섞이지 않음)

    # ④ 분리된 HEAD(되돌리기) → pull 없이 그 커밋으로 반영
    first = _git("rev-list", "--max-parents=0", "HEAD", cwd=repo)
    _git("checkout", "-q", first, cwd=repo)
    r, out = _run_update(pwsh, repo, log)
    assert "EXIT=0" in out and "분리된 HEAD" in out and "git pull --ff-only" not in out, out


# ---------------------------------------------------------------------------------------------------------------
# D3-41: 런타임 파일·관리자 권한 없음
# ---------------------------------------------------------------------------------------------------------------


def _common_body(extra: str) -> str:
    return f". '{(DEPLOY / 'install-common.ps1').as_posix()}'; $PhysicsAITag = 'T'; " + extra


@pytest.mark.posix
def test_machine_env_migrates_to_runtime_secret_with_acl(tmp_path):
    """머신 환경변수 DB URL → .runtime\\secrets\\database_url(런타임 파일이 없을 때만, 머신 환경변수는 그대로 — 안내 한 줄),
    비밀 폴더 ACL은 icacls로 상속 해제 + 현재 사용자·SYSTEM(+다른 실행 계정 읽기). icacls가 없거나 실패하면 경고만."""
    pwsh = _need_pwsh()
    rt = tmp_path / "rt"
    bin_dir = tmp_path / "bin"
    icalog = tmp_path / "icacls.log"
    _fake_exe(bin_dir / "icacls", 'printf "%s\\n" "$@" > "$ICACLS_LOG"; [ "$FAKE_ICACLS" = fail ] && { echo "Access is denied." >&2; exit 5; }; exit 0\n')
    url = "postgresql+psycopg://physicsai_app:s3cr%40t@127.0.0.1:5434/physicsai"
    stub = "function Get-PhysicsAIMachineEnv { param($Name) [Environment]::GetEnvironmentVariable(\"FAKE_MACHINE_$Name\") }; "

    def run(extra: str, env: dict) -> str:
        r = _run_pwsh(pwsh, _common_body(stub + extra), {"PATH": f"{bin_dir}:{os.environ['PATH']}", "ICACLS_LOG": str(icalog), **env})
        assert r.returncode == 0, r.stdout + r.stderr
        return _plain(r.stdout + r.stderr)

    moved = f"$m = Move-PhysicsAIMachineEnvToRuntime -RuntimeDir '{rt.as_posix()}' -ServiceUser 'CORP\\svc'; \"MOVED=$m\"; \"URL=$(Get-PhysicsAIDbUrl -RuntimeDir '{rt.as_posix()}')\""
    out = run(moved, {"FAKE_MACHINE_PHYSICSAI_DATABASE_URL": url})
    secret = rt / "secrets" / "database_url"
    assert "MOVED=True" in out and secret.read_bytes() == url.encode("utf-8")                # BOM·줄바꿈 없음
    assert f"URL={url}" in out and out.count(url) == 1                                       # 진행 출력에는 값이 없음
    assert "머신 환경변수는 그대로 둠" in out and "SetEnvironmentVariable('PHYSICSAI_DATABASE_URL', $null, 'Machine')" in out
    args = icalog.read_text(encoding="utf-8").splitlines()
    assert args[0] == str(rt / "secrets") and "/inheritance:r" in args and "/grant:r" in args and "/T" in args
    assert "*S-1-5-18:(OI)(CI)F" in args and "CORP\\svc:(OI)(CI)R" in args and any(a.endswith(":(OI)(CI)F") and "S-1-5-18" not in a for a in args)
    assert "현재 사용자·SYSTEM만 읽기" in out

    # 이미 런타임 파일이 있으면 옮기지 않음(머신 값이 달라도 런타임 파일 우선)
    out = run(moved, {"FAKE_MACHINE_PHYSICSAI_DATABASE_URL": "postgresql://old:x@h:1/d"})
    assert "MOVED=False" in out and f"URL={url}" in out and secret.read_text(encoding="utf-8") == url

    # 머신 환경변수도 파일도 없으면 빈 값
    shutil.rmtree(rt)
    out = run(moved, {})
    assert "MOVED=False" in out and "URL= " in out + " " and not secret.exists()

    # icacls 실패 → 경고만(파일은 씀) / icacls 없음 → 경고만
    out = run(f"Write-PhysicsAIRuntimeSecret -RuntimeDir '{rt.as_posix()}' -DbUrl '{url}'; 'DONE'", {"FAKE_ICACLS": "fail"})
    assert "DONE" in out and "비밀 파일 권한 제한 실패(icacls 종료코드 5)" in out and secret.read_text(encoding="utf-8") == url
    r = _run_pwsh(pwsh, _common_body(f"Write-PhysicsAIRuntimeSecret -RuntimeDir '{rt.as_posix()}' -DbUrl '{url}'; 'DONE'"),
                  {"PATH": "/usr/bin:/bin"})
    assert r.returncode == 0 and "icacls 없음" in _plain(r.stdout + r.stderr), r.stdout + r.stderr


@pytest.mark.posix
def test_update_repo_migrates_machine_env_and_uses_runtime_file(tmp_path):
    """update-repo.ps1: 런타임 DB 파일이 없고 머신 환경변수가 있으면 파일로 옮긴 뒤 그 값으로 대기열 확인·migration."""
    pwsh = _need_pwsh()
    repo = _update_repo_tree(tmp_path)
    (repo / ".runtime" / "secrets" / "database_url").unlink()
    url = "postgresql+psycopg://physicsai_app:mpw@127.0.0.1:5434/physicsai"
    with open(repo / "deploy" / "install-common.ps1", "a", encoding="utf-8") as f:
        f.write("\nfunction Get-PhysicsAIMachineEnv { param($Name) [Environment]::GetEnvironmentVariable(\"FAKE_MACHINE_$Name\") }\n"
                "function Invoke-PhysicsAIMigration { param($VenvPy, $AlembicIni) Write-Host \"STUB migration url=$($env:PHYSICSAI_DATABASE_URL -eq $env:WANT_URL)\" }\n")
    r, out = _run_update(pwsh, repo, tmp_path / "npm.log", {"FAKE_MACHINE_PHYSICSAI_DATABASE_URL": url, "WANT_URL": url})
    assert "EXIT=0" in out, out
    assert (repo / ".runtime" / "secrets" / "database_url").read_text(encoding="utf-8") == url
    assert "런타임 파일로 옮겼습니다" in out and "STUB migration url=True" in out and "mpw" not in out


@pytest.mark.posix
def test_update_repo_task_access_denied_and_reregistration(tmp_path):
    """관리자 검사 없음. 이전 설치가 관리자 권한으로 만든 작업이라 중지가 거부되면 바꾼 것 없이 '처음 한 번만 관리자 PowerShell' 안내.
    작업 인자가 --runtime 방식이 아니면 현재 사용자 Interactive·Limited로 다시 등록, 등록이 거부되면 같은 안내 + 이전 상태 복구."""
    pwsh = _need_pwsh()
    repo = _update_repo_tree(tmp_path)
    rt = repo / ".runtime"
    log = tmp_path / "npm.log"
    _fake_frontend(repo, crlf=False)
    _copy_dist(repo)

    r, out = _run_update(pwsh, repo, log, {"FAKE_DENY": "stop"})
    assert "EXIT=1" in out and not log.exists(), out
    assert "업데이트하지 않았습니다(바꾼 것 없음): 작업 스케줄러 작업(PhysicsAI-Backend·PhysicsAI-Worker)을 바꿀 권한이 없습니다" in out
    assert "처음 한 번만 관리자 PowerShell로 update-repo.ps1을 실행하세요" in out and "update-repo.ps1" in out
    assert "STUB packages" not in out and "START" not in out

    old_style = ("$global:FakeTasks = @{}; "
                 "foreach ($n in 'PhysicsAI-Backend', 'PhysicsAI-Worker') { $global:FakeTasks[$n] = [pscustomobject]@{ Actions = @([pscustomobject]@{ "
                 f"Execute = '{(rt / 'venv' / 'Scripts' / 'python.exe').as_posix()}'; Arguments = '-m old'; WorkingDirectory = '{rt.as_posix()}' }}) }} }}; "
                 "function Get-ScheduledTask { param($TaskName) $global:FakeTasks[$TaskName] }; "
                 "function New-ScheduledTaskSettingsSet { 'settings' }; function New-ScheduledTaskTrigger { 'trigger' }; "
                 "function New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel) Write-Host \"PRINCIPAL $UserId $LogonType $RunLevel\"; 'principal' }; "
                 "function New-ScheduledTaskAction { param($Execute, $Argument, $WorkingDirectory) [pscustomobject]@{ Execute = $Execute; Arguments = $Argument; WorkingDirectory = $WorkingDirectory } }; "
                 "function Unregister-ScheduledTask { param($TaskName) if ($env:FAKE_DENY -eq 'register') { throw [UnauthorizedAccessException]::new('Access is denied.') }; $global:FakeTasks.Remove($TaskName) }; "
                 "function Register-ScheduledTask { param($TaskName, $Action, $Trigger, $Settings, $Principal) "
                 "$global:FakeTasks[$TaskName] = [pscustomobject]@{ Actions = @($Action) }; Write-Host \"REGISTER $TaskName | $($Action.Arguments)\" }; ")
    r, out = _run_update(pwsh, repo, log, {}, stubs=old_style)
    assert "EXIT=0" in out, out
    assert "작업 다시 등록(인자 --runtime" in out and "PRINCIPAL CORP\\me Interactive Limited" in out
    assert f"REGISTER PhysicsAI-Backend | -m physicsai_api.serve --runtime \"{rt.as_posix()}\"" in out
    assert f"REGISTER PhysicsAI-Worker | -m physicsai_worker --runtime \"{rt.as_posix()}\"" in out
    assert "--config" not in out.split("REGISTER", 1)[1] and "pw@" not in out           # 기본 위치 설정이면 --config 없음, 비밀값 없음

    r, out = _run_update(pwsh, repo, log, {"FAKE_DENY": "register"}, stubs=old_style)
    assert "EXIT=1" in out, out
    assert "업데이트 실패(작업 등록): 작업 스케줄러 작업(PhysicsAI-Backend·PhysicsAI-Worker)을 바꿀 권한이 없습니다" in out
    assert "처음 한 번만 관리자 PowerShell로 update-repo.ps1을 실행하세요" in out and "START PhysicsAI-Backend" in out and "STUB packages" not in out


def test_no_admin_check_no_machine_env_writes():
    """관리자 권한 확인·머신 환경변수 쓰기가 deploy 스크립트에서 사라졌다(안내 문구의 예시 명령만 남음). 작업은 Interactive·Limited + --runtime."""
    for p in sorted(DEPLOY.rglob("*.ps1")):
        t = p.read_text(encoding="utf-8-sig")
        assert "IsInRole" not in t and "Assert-PhysicsAIAdmin" not in t and "Test-PhysicsAIAdmin" not in t and "Set-PhysicsAIMachineEnv" not in t, p.name
        for line in t.splitlines():
            if "SetEnvironmentVariable(" in line and "'Machine'" in line:
                assert "Write-PhysicsAIStep" in line or "Write-Step" in line, f"{p.name}: {line.strip()}"
    common = (DEPLOY / "install-common.ps1").read_text(encoding="utf-8-sig")
    assert "-LogonType Interactive -RunLevel Limited" in common and "--runtime" in common
    assert "Background(부팅 시·비밀번호 저장) 등록은 관리자 권한이 필요할 수 있습니다" in common
    for n in ("setup.ps1", "install.ps1"):
        t = (DEPLOY / n).read_text(encoding="utf-8-sig")
        assert "관리자 권한이 필요할 수 있" in t, n                                   # Background 옵션에서만 안내
        assert "Write-PhysicsAIRuntimeSecret" in t and "-RuntimeDir" in t, n
    for n in ("update-repo.ps1", "update.ps1"):
        t = (DEPLOY / n).read_text(encoding="utf-8-sig")
        assert "Move-PhysicsAIMachineEnvToRuntime" in t and "Update-PhysicsAITaskRegistration" in t and "-DbUrl $dbUrl" in t, n


# ---- 로더 우선순위·백엔드·워커 기동(환경변수 없이 --runtime) -----------------------------------------------------------


def _runtime(tmp_path: Path, url: str = "postgresql+psycopg://u:pw@127.0.0.1:1/x", cfg_text: str = "schema_version: 1\n") -> Path:
    rt = tmp_path / "rt"
    _touch(rt / "config" / "platform.yaml").write_text(cfg_text, encoding="utf-8")
    _touch(rt / "secrets" / "database_url").write_text("\ufeff" + url + "\r\n", encoding="utf-8")
    return rt


def test_apply_runtime_priority(tmp_path):
    from physicsai_core.config.runtime import apply_runtime

    rt = _runtime(tmp_path)
    cfg, url = str(rt / "config" / "platform.yaml"), "postgresql+psycopg://u:pw@127.0.0.1:1/x"
    # 환경변수 없음 → 런타임 파일(BOM·줄바꿈 제거)
    env: dict[str, str] = {}
    src = apply_runtime(rt, environ=env, machine_env={})
    assert env == {"PHYSICSAI_CONFIG": cfg, "PHYSICSAI_DATABASE_URL": url}
    assert src["PHYSICSAI_CONFIG"].startswith("런타임 파일") and src["PHYSICSAI_DATABASE_URL"].startswith("런타임 파일") and "pw" not in str(src)
    # 직접 준 환경변수 > 인자·런타임 파일
    env = {"PHYSICSAI_CONFIG": "/x.yaml", "PHYSICSAI_DATABASE_URL": "postgresql://e"}
    src = apply_runtime(rt, config_arg="/arg.yaml", environ=env, machine_env={})
    assert env == {"PHYSICSAI_CONFIG": "/x.yaml", "PHYSICSAI_DATABASE_URL": "postgresql://e"} and set(src.values()) == {"환경변수"}
    # 머신 환경변수에서 물려받은 값(같은 값) → 런타임 파일이 우선(이전 설치 이전 후)
    env = {"PHYSICSAI_CONFIG": "/old.yaml", "PHYSICSAI_DATABASE_URL": "postgresql://old"}
    apply_runtime(rt, environ=env, machine_env=dict(env))
    assert env == {"PHYSICSAI_CONFIG": cfg, "PHYSICSAI_DATABASE_URL": url}
    # --config 인자 > 런타임 기본 위치
    env = {}
    src = apply_runtime(rt, config_arg="/arg.yaml", environ=env, machine_env={})
    assert env["PHYSICSAI_CONFIG"] == "/arg.yaml" and src["PHYSICSAI_CONFIG"] == "--config 인자"
    # 런타임 파일이 없으면 이전 머신 환경변수 그대로
    empty = tmp_path / "empty"
    env = {"PHYSICSAI_CONFIG": "/old.yaml", "PHYSICSAI_DATABASE_URL": "postgresql://old"}
    src = apply_runtime(empty, environ=env, machine_env=dict(env))
    assert env == {"PHYSICSAI_CONFIG": "/old.yaml", "PHYSICSAI_DATABASE_URL": "postgresql://old"} and src["PHYSICSAI_DATABASE_URL"] == "머신 환경변수(이전 설치)"
    env = {}
    src = apply_runtime(empty, environ=env, machine_env={})
    assert env == {} and src == {"PHYSICSAI_CONFIG": "기본값 config/platform.yaml", "PHYSICSAI_DATABASE_URL": "없음"}
    # 다른 url_env 이름도 같은 파일
    env = {}
    apply_runtime(rt, url_envs=("MY_DB",), environ=env, machine_env={})
    assert env["MY_DB"] == url


def test_backend_serve_starts_from_runtime_without_env(tmp_path, monkeypatch, settings_dict):
    """백엔드: 환경변수 없이 `serve --runtime <rt>` → 설정·DB URL을 런타임 파일에서(인자에는 경로만)."""
    import physicsai_api.serve as serve

    url = "postgresql+psycopg://u:pw@127.0.0.1:1/x"
    rt = _runtime(tmp_path, url, yaml.safe_dump({**settings_dict, "server": {**settings_dict.get("server", {}), "port": 8177}}, allow_unicode=True))
    for k in ("PHYSICSAI_CONFIG", "PHYSICSAI_DATABASE_URL", "PHYSICSAI_BIND_HOST"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("physicsai_core.config.runtime.machine_environment", lambda names: {})   # Windows CI: 레지스트리 무관
    seen = {}
    monkeypatch.setattr(serve.uvicorn, "run", lambda app, **kw: seen.update(app=app, env=dict(os.environ), **kw))
    monkeypatch.setattr(serve, "setup_file_logging", lambda s, name: str(tmp_path / f"{name}.log"))
    serve.main(["--runtime", str(rt)])
    assert seen["port"] == 8177 and seen["app"] == "physicsai_api.main:app"
    assert seen["env"]["PHYSICSAI_CONFIG"] == str(rt / "config" / "platform.yaml") and seen["env"]["PHYSICSAI_DATABASE_URL"] == url


def test_worker_starts_from_runtime_without_env(tmp_path, monkeypatch, settings_dict, capsys):
    """워커: 환경변수 없이 `physicsai_worker --runtime <rt>` → 런타임 설정으로 검증 통과, DB URL도 파일에서(여기서는 닿지 않는 주소라
    'DB 접속 정보가 없습니다'가 아닌 'DB 연결 … 실패'로 종료코드 2)."""
    from physicsai_worker.__main__ import main

    rt = _runtime(tmp_path, cfg_text=yaml.safe_dump(settings_dict, allow_unicode=True))
    for k in ("PHYSICSAI_CONFIG", "PHYSICSAI_DATABASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("physicsai_core.config.runtime.machine_environment", lambda names: {})
    monkeypatch.setattr("physicsai_core.logsetup.setup_file_logging", lambda st, name: str(tmp_path / f"{name}.log"))   # 저장소 ./logs에 쓰지 않게
    assert main(["--runtime", str(rt)]) == 2
    err = capsys.readouterr().err
    assert "DB 연결 또는 migration 확인 실패" in err and "DB 접속 정보가 없습니다" not in err and "설정 검증 실패" not in err
    assert os.environ["PHYSICSAI_CONFIG"] == str(rt / "config" / "platform.yaml")
    # 런타임 폴더가 비어 있으면 종전처럼 DB 정보 없음
    monkeypatch.delenv("PHYSICSAI_DATABASE_URL", raising=False)
    monkeypatch.setenv("PHYSICSAI_CONFIG", str(rt / "config" / "platform.yaml"))
    (rt / "secrets" / "database_url").unlink()
    assert main(["--runtime", str(rt)]) == 2
    assert "DB 접속 정보가 없습니다" in capsys.readouterr().err
