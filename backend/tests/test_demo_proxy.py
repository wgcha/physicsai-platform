"""GitHub #1: 회사 PC의 HTTP_PROXY·HTTPS_PROXY 환경에서도 루프백 호출(시연 health·seed, 대시보드 인증, ps1 health)은 프록시를 타지 않는다.

재현 조건: 프록시 환경변수를 닫힌 포트(127.0.0.1:9)로, NO_PROXY는 비운다. 시연 up 실패 시 띄운 프로세스 정리·남은 프로세스 인식도 본다.
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import sys
import threading

import pytest

from physicsai_test_support import REPO, _free_port

BOGUS = "http://127.0.0.1:9"  # 닫힌 포트 — 프록시를 타면 즉시 연결 거부
DEMO = REPO / "deploy" / "demo"


def _demo_import(name: str):
    """deploy/demo 모듈을 import(deploy/ 아래에 __pycache__를 만들지 않게 — 정적 검사·오프라인 묶음 대상 폴더)."""
    import importlib

    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(DEMO))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(DEMO))
        sys.dont_write_bytecode = old


def _proxy_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    for k in ("NO_PROXY", "no_proxy"):
        env.pop(k, None)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[k] = BOGUS
    return env


@pytest.fixture()
def bogus_proxy(monkeypatch):
    for k in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(k, raising=False)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(k, BOGUS)


@pytest.fixture()
def local_server():
    """127.0.0.1 가짜 대시보드(/api/auth/me)·health."""

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = {"status": "ok"} if self.path.endswith("/health") else {"id": "u1", "username": "u", "display_name": "U"}
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def test_bogus_proxy_reproduces_without_fix(bogus_proxy, local_server):
    """재현 확인: 기본 urllib·httpx는 루프백도 프록시로 보내 실패한다(수정 전 demo _health·인증 클라이언트 동작)."""
    import urllib.request

    import httpx

    with pytest.raises(OSError):
        urllib.request.urlopen(f"http://127.0.0.1:{local_server}/health", timeout=2)  # noqa: S310
    with pytest.raises(httpx.HTTPError):
        httpx.get(f"http://127.0.0.1:{local_server}/health", timeout=2)


def test_demo_local_urlopen_ignores_proxy(bogus_proxy, local_server):
    local_urlopen = _demo_import("demo_common").local_urlopen
    with local_urlopen(f"http://127.0.0.1:{local_server}/health", timeout=2) as r:
        assert json.loads(r.read())["status"] == "ok"


@pytest.mark.parametrize("url,loop", [
    ("http://127.0.0.1:8000", True), ("http://127.1.2.3:80/", True), ("http://localhost:8000", True),
    ("http://[::1]:8000", True), ("http://dash.corp.example:8000", False), ("http://10.0.0.5:8000", False),
])
def test_is_loopback_url(url, loop):
    from physicsai_api.auth import is_loopback_url

    assert is_loopback_url(url) is loop


def test_dashboard_client_loopback_ignores_proxy(bogus_proxy, local_server):
    """대시보드 인증 클라이언트: 루프백이면 HTTP(S)_PROXY 무시(trust_env=False), 그 외는 기존 동작(환경 프록시 존중)."""
    from physicsai_api.auth import DashboardClient
    from physicsai_core.config import AuthCfg

    c = DashboardClient(AuthCfg(dashboard_internal_url=f"http://127.0.0.1:{local_server}"))
    try:
        assert c.me("tok", "rid")["id"] == "u1"
    finally:
        c.close()
    remote = DashboardClient(AuthCfg(dashboard_internal_url="http://dash.corp.example:8000"))
    try:
        assert remote._client.trust_env is True
    finally:
        remote.close()


def test_loopback_ps1_helper_ignores_proxy(local_server):
    """deploy/loopback-http.ps1 Invoke-LoopbackRest(PS 7 경로): 프록시 환경에서 루프백 성공, 일반 Invoke-RestMethod는 실패(재현)."""
    pwsh = os.environ.get("PHYSICSAI_PWSH") or shutil.which("pwsh")
    if not pwsh:
        pytest.skip("pwsh 없음(CI linux·windows 잡은 pwsh 있음, Windows 5.1 경로는 CI windows 시연 단계에서 실행)")
    helper = (REPO / "deploy" / "loopback-http.ps1").as_posix()
    u = f"http://127.0.0.1:{local_server}/health"
    script = (f". '{helper}'; try {{ Invoke-RestMethod -Uri '{u}' -TimeoutSec 3 | Out-Null; 'PLAIN_OK' }} catch {{ 'PLAIN_FAIL' }}; "
              f"(Invoke-LoopbackRest -Uri '{u}' -TimeoutSec 3).status; "
              f"try {{ Invoke-LoopbackRest -Uri 'http://example.com/' }} catch {{ 'REJECT' }}")
    r = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", script], env=_proxy_env(),
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    out = r.stdout.split()
    assert r.returncode == 0, r.stdout + r.stderr
    assert out == ["PLAIN_FAIL", "ok", "REJECT"], r.stdout + r.stderr


def _setup(env, *args, timeout=240) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(DEMO / "demo_setup.py"), *args], env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)


def _procs(root) -> dict:
    return json.loads((root / "state" / "demo-procs.json").read_text(encoding="utf-8") or "{}")


def test_demo_up_e2e_with_bogus_proxy(db_url, tmp_path):
    """시연 init → up(migration·백엔드·health·seed·워커) → down, HTTP_PROXY 닫힌 포트 환경(GitHub #1 재현→수정).

    + 이전 실행이 일부만 남아 있으면(워커 없음) 정리 후 다시 기동, 정상 실행 중이면 그대로
    """
    import psutil

    _proc_alive = _demo_import("demo_procs")._proc_alive
    root = tmp_path / "demo"
    port = _free_port()
    env = _proxy_env()
    env.update({"PHYSICSAI_DATABASE_URL": db_url, "FAKE_DEMO_DELAY_S": "0", "PYTHONUTF8": "1"})
    r = _setup(env, "init", "--root", str(root), "--port", str(port))
    assert r.returncode == 0, r.stdout + r.stderr
    try:
        # 2) 정상 경로(프록시 환경): health·seed·워커
        r = _setup(env, "up", "--root", str(root))
        assert r.returncode == 0, r.stdout + r.stderr + _tail(root)
        assert json.loads(r.stdout.strip().splitlines()[-1]) == {"url": f"http://127.0.0.1:{port}/", "already_running": False}
        procs = _procs(root)
        assert set(procs) == {"backend", "worker"} and all(_proc_alive(v) for v in procs.values())
        r = _setup(env, "up", "--root", str(root))
        assert r.returncode == 0 and '"already_running": true' in r.stdout
        # 3) 이전 실행이 일부만 남음(워커 죽음) → 정리 후 다시 기동
        psutil.Process(procs["worker"]["pid"]).kill()
        psutil.Process(procs["worker"]["pid"]).wait(10)
        r = _setup(env, "up", "--root", str(root))
        assert r.returncode == 0, r.stdout + r.stderr + _tail(root)
        assert "정리하고 다시 시작" in r.stdout and '"already_running": false' in r.stdout
        assert not _proc_alive(procs["backend"])  # 이전 백엔드는 종료됨
        assert all(_proc_alive(v) for v in _procs(root).values())
    finally:
        _setup(env, "down", "--root", str(root))
    assert not any(_proc_alive(v) for v in procs.values())


def test_demo_up_failure_stops_spawned_backend(db_url, tmp_path, monkeypatch):
    """up 실패(health 시간 초과) → 원인(마지막 health 오류) 출력·logs/demo-setup.log 기록, 이번에 띄운 백엔드 종료, 실행 정보 비움.

    health를 항상 실패로 바꿔 시점과 무관하게 재현한다(Windows는 닫힌 포트 연결 거부가 ~2초 걸려 실제 기동과 경합).
    """
    import argparse

    ds = _demo_import("demo_setup")
    root = tmp_path / "demo"
    env = _proxy_env()
    r = _setup(env, "init", "--root", str(root), "--port", str(_free_port()))
    assert r.returncode == 0, r.stdout + r.stderr
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setenv("PHYSICSAI_DATABASE_URL", db_url)
    monkeypatch.setenv("FAKE_DEMO_DELAY_S", "0")
    monkeypatch.setattr(ds, "_health_error", lambda port: "URLError: 가짜 연결 실패")
    spawned = []
    real_spawn = ds._spawn

    def spy(*a, **kw):
        p = real_spawn(*a, **kw)
        spawned.append(p)
        return p

    monkeypatch.setattr(ds, "_spawn", spy)
    with pytest.raises(SystemExit) as ei:
        ds.cmd_up(argparse.Namespace(root=str(root), timeout=2))
    msg = str(ei.value)
    assert "백엔드 기동 실패" in msg and "마지막 health 오류: URLError: 가짜 연결 실패" in msg, msg
    assert len(spawned) == 1 and spawned[0].wait(30) is not None  # 이번에 띄운 백엔드는 종료됨
    assert _procs(root) == {}
    log = (root / "logs" / "demo-setup.log").read_text(encoding="utf-8")
    assert "시연 기동 실패" in log and "프로세스 정리: backend" in log


def _tail(root) -> str:
    out = []
    for f in sorted((root / "logs").glob("*.log")):
        out.append(f"--- {f.name}\n" + "\n".join(f.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]))
    return "\n".join(out)
