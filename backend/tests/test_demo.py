"""시연 모드 가드·내장 가짜 대시보드 인증·정적 서빙·/status demo 플래그(deploy/demo)."""

from __future__ import annotations

import copy
import subprocess
import sys

import pytest
import yaml
from fastapi.testclient import TestClient

from physicsai_test_support import API, REPO, H

TEMPLATE = REPO / "config" / "platform.demo.yaml"


def _demo(settings_dict, tmp_path, **over):
    d = copy.deepcopy(settings_dict)
    fe = tmp_path / "fe"
    fe.mkdir(exist_ok=True)
    (fe / "index.html").write_text("<!doctype html><p>app</p>", encoding="utf-8")
    d["demo"] = {"enabled": True, "frontend_root": str(fe)}
    d["auth"] = {**d["auth"], "mode": "demo", "dashboard_public_login_url": "/physicsai/api/demo/login"}
    for k, v in over.items():
        d[k] = v
    return d


def _app(lc, engine, bind_host="127.0.0.1"):
    from physicsai_api.context import build_context
    from physicsai_api.main import create_app

    return create_app(build_context(lc, engine), bind_host=bind_host)


@pytest.mark.parametrize("case,key", [
    ({"profile": "prod"}, "demo.enabled"),
    ({"server": {"host": "0.0.0.0", "port": 8100, "base_path": "/physicsai"}}, "demo.enabled"),
])
def test_demo_config_guard(settings_dict, tmp_path, engine, case, key):
    """운영 설정(prod) 또는 127.0.0.1 이외 바인딩에서는 시연 모드가 설정 검증 오류 + 기동 거부."""
    from physicsai_api.main import StartupRefused
    from physicsai_core.config import load_config_dict

    lc = load_config_dict(_demo(settings_dict, tmp_path, **case), environ={})
    assert key in lc.error_keys()
    with pytest.raises(StartupRefused):
        _app(lc, engine)


def test_demo_guard_env_profile_and_bind_host(settings_dict, tmp_path, engine):
    from physicsai_api.main import StartupRefused
    from physicsai_core.config import load_config_dict

    d = _demo(settings_dict, tmp_path)
    assert load_config_dict(d, environ={}).ok
    lc = load_config_dict(d, environ={"PHYSICSAI_PROFILE": "prod"})  # 환경변수로 운영 전환 → 거부
    assert "demo.enabled" in lc.error_keys()
    with pytest.raises(StartupRefused):
        _app(lc, engine)
    with pytest.raises(StartupRefused):  # 설정은 127.0.0.1이어도 실제 바인드가 다르면 거부
        _app(load_config_dict(d, environ={}), engine, bind_host="0.0.0.0")


def test_demo_auth_requires_demo_enabled(settings_dict, tmp_path, engine):
    from physicsai_api.main import StartupRefused
    from physicsai_core.config import load_config_dict

    d = copy.deepcopy(settings_dict)
    d["auth"] = {**d["auth"], "mode": "demo"}
    lc = load_config_dict(d, environ={})
    assert "auth.mode" in lc.error_keys()
    with pytest.raises(StartupRefused):
        _app(lc, engine)
    d = copy.deepcopy(settings_dict)
    d["demo"] = {"enabled": False, "frontend_root": str(tmp_path)}
    assert "demo.frontend_root" in load_config_dict(d, environ={}).error_keys()


def test_production_has_no_demo_routes(client):
    """기본(대시보드) 설정: demo=false, 시연 로그인·정적 서빙 경로 없음, 가짜 토큰 거부."""
    st = client.get(f"{API}/status", headers=H("tok-power")).json()
    assert st["demo"] is False
    assert client.get(f"{API}/demo/login").status_code == 404
    assert client.post(f"{API}/demo/login", content=b"role=admin").status_code in (404, 405)
    assert client.get("/physicsai/").status_code == 404
    assert client.get(f"{API}/me", headers=H("demo-admin")).status_code == 401


def test_demo_login_and_roles(settings_dict, tmp_path, engine):
    from physicsai_core.config import load_config_dict

    lc = load_config_dict(_demo(settings_dict, tmp_path), environ={})
    assert lc.ok, lc.issues
    app = _app(lc, engine)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.get(f"{API}/me").status_code == 401
        r = c.post(f"{API}/demo/login", content=b"role=general", headers={"content-type": "application/x-www-form-urlencoded"},
                   follow_redirects=False)
        assert r.status_code == 303 and "httponly" in r.headers["set-cookie"].lower()
        me = c.get(f"{API}/me").json()
        assert me["username"] == "general" and me["roles"] == {"demo": "general"} and not me["is_global_admin"]
        assert c.get(f"{API}/status").json()["demo"] is True
        r = c.post(f"{API}/studies", headers={"X-PhysicsAI-Request": "1"},
                   json={"project_id": "demo", "folder_name": "g1", "title": "x"})
        assert r.status_code == 403
        c.post(f"{API}/demo/login", content=b"role=admin", headers={"content-type": "application/x-www-form-urlencoded"})
        assert c.get(f"{API}/me").json()["is_global_admin"] is True
        assert c.get(f"{API}/me", headers=H("tok-admin")).json()["is_global_admin"] is True  # 쿠키 우선(demo-admin)
        assert c.get("/physicsai/stage/1").text == "<!doctype html><p>app</p>"
        assert c.get(f"{API}/openapi.json").json()["paths"].get(f"{API}/demo/login") is None
    with TestClient(app, base_url="http://127.0.0.1") as other:  # 시연 사용자 외 토큰은 거부
        assert other.get(f"{API}/me", headers=H("tok-admin")).status_code == 401
    with TestClient(app, base_url="http://127.0.0.1", client=("10.1.2.3", 5000)) as remote:
        assert remote.get(f"{API}/demo/login").status_code == 403
        assert remote.post(f"{API}/demo/login", content=b"role=admin").status_code == 403


def test_demo_template_renders_valid_config(tmp_path):
    """config/platform.demo.yaml + demo_setup init → 설정 검증 통과(시연 폴더 구조·가짜 도구·자원)."""
    r = subprocess.run([sys.executable, str(REPO / "deploy" / "demo" / "demo_setup.py"), "init", "--root", str(tmp_path / "d"),
                        "--port", "18999"], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    from physicsai_core.config import load_config

    cfg = tmp_path / "d" / "config" / "platform.yaml"
    lc = load_config(str(cfg), environ={})
    assert lc.ok, lc.issues
    s = lc.settings
    assert s.demo.enabled and s.auth.mode == "demo" and s.profile == "dev" and s.server.host == "127.0.0.1" and s.server.port == 18999
    assert s.hpc.gateway == "none" and all(v is not None for v in s.commands.model_dump().values() if v is not None)
    raw = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert "{{" not in cfg.read_text(encoding="utf-8") and raw["demo"]["frontend_root"] == ""
    # 다시 실행해도 같은 설정(변경 없으면 그대로), 바뀌면 _backup으로 이동(삭제 없음)
    r = subprocess.run([sys.executable, str(REPO / "deploy" / "demo" / "demo_setup.py"), "init", "--root", str(tmp_path / "d"),
                        "--port", "18998"], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    assert list((tmp_path / "d" / "_backup").rglob("platform.yaml"))
    bad = subprocess.run([sys.executable, str(REPO / "deploy" / "demo" / "demo_setup.py"), "init", "--root", str(tmp_path / "a b")],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert bad.returncode != 0 and "공백" in (bad.stdout + bad.stderr)


def test_demo_deploy_files_static():
    """deploy/demo 정적 검사 + Windows PowerShell 5.1 대비 .ps1 UTF-8 BOM(없으면 한글이 cp949로 읽혀 깨짐)."""
    demo = REPO / "deploy" / "demo"
    for n in ("demo_setup.py", "start-demo.ps1", "stop-demo.ps1", "start-demo.bat", "stop-demo.bat"):
        assert (demo / n).is_file(), n
    for f in [*(REPO / "deploy").rglob("*.ps1"), *(REPO / "scripts").glob("*.ps1")]:
        assert f.read_bytes().startswith(b"\xef\xbb\xbf"), f"UTF-8 BOM 없음: {f}"
    for f in (REPO / "deploy").rglob("*.bat"):
        assert not f.read_bytes().startswith(b"\xef\xbb\xbf"), f"bat에 BOM 금지: {f}"
    start = (demo / "start-demo.ps1").read_text(encoding="utf-8-sig")
    stop = (demo / "stop-demo.ps1").read_text(encoding="utf-8-sig")
    for t in (start, stop):
        assert "Remove-Item" not in t and "Program Files" not in t
    assert "PHYSICSAI_DEMO_DATABASE_URL" in start and "[string]$DatabaseUrl" not in start  # 비밀번호 든 URL은 인자로 받지 않음
    for n in ("init", "db-up", "up"):
        assert f"$setup {n} " in start, n
    assert "$setup down" in stop and "$setup db-down" in stop
    for b in ("start-demo.bat", "stop-demo.bat"):
        assert "powershell -NoProfile -ExecutionPolicy Bypass -File" in (demo / b).read_text(encoding="utf-8")
    # 오프라인 묶음에 시연 템플릿·가짜 도구 포함
    for f in ("collect-offline.sh", "collect-offline.ps1"):
        t = (REPO / "deploy" / f).read_text(encoding="utf-8-sig")
        assert "platform.demo.yaml" in t and "fake_tools" in t, f
    inst = (REPO / "deploy" / "install.ps1").read_text(encoding="utf-8-sig")
    assert "[switch]$PasswordsFromEnv" in inst and "[switch]$NoStart" in inst and "Read-Host -AsSecureString" in inst
