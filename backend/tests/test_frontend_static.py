"""운영 정적 서빙(phase3 변경 메모 S5): server.frontend_root → 백엔드가 /physicsai/ 아래에 프런트 빌드를 직접 서빙(Caddy 없이).

대시보드 Vite 프록시가 /physicsai 전체를 경로 rewrite 없이 127.0.0.1:<server.port>로 넘기는 운영 구성을 시험한다."""

from __future__ import annotations

import copy
import os

import httpx
import pytest
from fastapi.testclient import TestClient

from physicsai_test_support import API, H

INDEX = "<!doctype html><p>app</p>"


def _build(tmp_path):
    fe = tmp_path / "fe"
    (fe / "assets").mkdir(parents=True)
    (fe / "index.html").write_text(INDEX, encoding="utf-8")
    (fe / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (fe / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("SECRET", encoding="utf-8")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "x.txt").write_text("SECRET", encoding="utf-8")
    return fe


def _app(settings_dict, engine, fake_dashboard, frontend_root):
    from physicsai_api.context import build_context
    from physicsai_api.main import create_app
    from physicsai_core.config import load_config_dict

    d = copy.deepcopy(settings_dict)
    d["server"] = {**d.get("server", {}), "frontend_root": frontend_root}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    ctx = build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler))
    return ctx, create_app(ctx)


def _is_not_found_json(r) -> bool:
    return r.status_code == 404 and r.headers["content-type"].startswith("application/json") and r.json()["detail"]["code"] == "NOT_FOUND"


def test_static_serving_rules(settings_dict, tmp_path, engine, fake_dashboard):
    fe = _build(tmp_path)
    _, app = _app(settings_dict, engine, fake_dashboard, str(fe))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        # SPA: 루트·없는 경로 → index.html(no-cache), 인증 없이
        for p in ("/physicsai/", "/physicsai/stage/3", "/physicsai/studies/abc/manage", "/physicsai/assets"):
            r = c.get(p)
            assert r.status_code == 200 and r.text == INDEX, p
            assert r.headers["cache-control"] == "no-cache" and r.headers["content-type"].startswith("text/html"), p
        assert c.head("/physicsai/stage/3").status_code == 200
        # 존재하는 파일: 해시 자산은 긴 캐시, 그 밖은 no-cache
        r = c.get("/physicsai/assets/index-abc123.js")
        assert r.status_code == 200 and r.text == "console.log(1)" and "immutable" in r.headers["cache-control"]
        r = c.get("/physicsai/favicon.svg")
        assert r.status_code == 200 and r.text == "<svg/>" and r.headers["cache-control"] == "no-cache"
        # 없는 해시 자산(이전 빌드 lazy chunk)은 index.html이 아니라 404, 없는 일반 경로는 계속 index.html 200
        for p in ("/physicsai/assets/old-chunk-9f8e7d.js", "/physicsai/assets/sub/x.css", "/physicsai/assets/sub"):
            r = c.get(p)
            assert _is_not_found_json(r) and "<p>app</p>" not in r.text, (p, r.status_code)
        assert c.head("/physicsai/assets/old-chunk-9f8e7d.js").status_code == 404
        r = c.get("/physicsai/not-an-asset/old-chunk.js")
        assert r.status_code == 200 and r.text == INDEX and r.headers["cache-control"] == "no-cache"
        # /physicsai → 308 /physicsai/(쿼리 유지)
        r = c.get("/physicsai", follow_redirects=False)
        assert r.status_code == 308 and r.headers["location"] == "/physicsai/"
        r = c.get("/physicsai?x=1", follow_redirects=False)
        assert r.status_code == 308 and r.headers["location"] == "/physicsai/?x=1"
        # 경로 탈출(평문·인코딩·역슬래시·드라이브) → 404, 비밀 내용 노출 없음
        for p in ("/physicsai/../secret.txt", "/physicsai/%2e%2e/secret.txt", "/physicsai/..%2fsecret.txt",
                  "/physicsai/%2E%2E%2Fsecret.txt", "/physicsai/assets/..%5c..%5csecret.txt", "/physicsai/assets/%2e%2e/%2e%2e/secret.txt",
                  "/physicsai/C:%5cWindows%5cwin.ini", "/physicsai/x%00.js"):
            r = c.get(p)
            assert _is_not_found_json(r) and "SECRET" not in r.text, (p, r.status_code, r.text)
        # API 접두는 정적 처리로 가지 않는다: 없는 경로 = 기존 JSON 404(메서드 무관), 있는 경로의 다른 메서드 = 405
        for method in ("GET", "POST", "DELETE"):
            for p in (f"{API}/nonexistent", f"{API}/stage/3", API, f"{API}/", "/physicsai/%61pi/nonexistent"):
                assert _is_not_found_json(c.request(method, p)), (method, p)
        assert c.get(f"{API}/health").json()["status"] == "ok"
        assert c.delete(f"{API}/health").status_code == 405
        # 인증 영향 없음: 정적은 인증 없이, API는 그대로 인증 필요
        assert c.get(f"{API}/me").status_code == 401
        assert c.get(f"{API}/me", headers=H("tok-admin")).status_code == 200
        # 운영에서는 '/'를 가로채지 않는다(대시보드 몫), openapi에 정적 라우트 없음
        assert c.get("/", follow_redirects=False).status_code == 404
        paths = c.get(f"{API}/openapi.json").json()["paths"]
        assert not [p for p in paths if not p.startswith(API)]


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink 없음")
def test_static_symlink_escape_is_rejected(settings_dict, tmp_path, engine, fake_dashboard):
    fe = _build(tmp_path)
    try:
        os.symlink(tmp_path / "secret.txt", fe / "leak.txt")
        os.symlink(tmp_path / "outside", fe / "leakdir", target_is_directory=True)
        os.symlink(fe / "favicon.svg", fe / "inside.svg")
    except OSError as exc:  # Windows 권한 없음(개발자 모드 꺼짐)
        pytest.skip(f"symlink 생성 불가: {exc}")
    _, app = _app(settings_dict, engine, fake_dashboard, str(fe))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        for p in ("/physicsai/leak.txt", "/physicsai/leakdir/x.txt", "/physicsai/leakdir"):
            r = c.get(p)
            assert _is_not_found_json(r) and "SECRET" not in r.text, p
        assert c.get("/physicsai/inside.svg").text == "<svg/>"   # 빌드 폴더 안을 가리키는 링크는 허용


def test_static_root_missing_starts_and_warns(settings_dict, tmp_path, engine, fake_dashboard):
    """빌드 폴더·index.html이 없어도 기동하고(설정 오류 아님), 환경 점검 항목이 WARN, 요청은 JSON 404."""
    from physicsai_api.services.env_checks import _api_items

    missing = tmp_path / "nofe"
    ctx, app = _app(settings_dict, engine, fake_dashboard, str(missing))
    items = {i["key"]: i for i in _api_items(ctx, None, "rid")}
    it = items["server.frontend_root"]
    assert it["status"] == "WARN" and it["category"] == "CONFIG" and it["label"] == "프런트 정적 서빙"
    assert "폴더가 없습니다" in it["message"] and it["detail"] == {"path": str(missing)}
    assert items["config.valid"]["status"] == "OK"
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r = c.get("/physicsai/stage/1")
        assert _is_not_found_json(r) and "프런트 빌드가 없습니다" in r.json()["detail"]["message"]
        assert c.get(f"{API}/health").status_code == 200
    missing.mkdir()  # 폴더는 있지만 index.html 없음
    ctx, _ = _app(settings_dict, engine, fake_dashboard, str(missing))
    it = {i["key"]: i for i in _api_items(ctx, None, "rid")}["server.frontend_root"]
    assert it["status"] == "WARN" and "index.html" in it["message"]
    fe = _build(tmp_path)
    ctx, _ = _app(settings_dict, engine, fake_dashboard, str(fe))
    assert {i["key"]: i for i in _api_items(ctx, None, "rid")}["server.frontend_root"]["status"] == "OK"


def test_static_not_configured(client, app_ctx):
    """기본(null): 정적 서빙 없음, 환경 점검 SKIP."""
    from physicsai_api.services.env_checks import _api_items

    assert app_ctx.settings.server.frontend_root is None
    assert _is_not_found_json(client.get("/physicsai/"))
    assert _is_not_found_json(client.get("/physicsai/stage/3"))
    assert client.get("/physicsai", follow_redirects=False).status_code == 404
    it = {i["key"]: i for i in _api_items(app_ctx, None, "rid")}["server.frontend_root"]
    assert it["status"] == "SKIP" and it["detail"] is None


def test_frontend_root_config_rules(settings_dict):
    from physicsai_core.config import load_config_dict

    for v in (None, ""):
        d = copy.deepcopy(settings_dict)
        d["server"] = {**d.get("server", {}), "frontend_root": v}
        assert load_config_dict(d, environ={}).ok
    d = copy.deepcopy(settings_dict)
    d["server"] = {**d.get("server", {}), "frontend_root": "relative/frontend"}
    assert "server.frontend_root" in load_config_dict(d, environ={}).error_keys()
    d["server"]["frontend_root"] = "D:/physicsai-platform/.runtime/frontend"   # Windows 절대경로 형식도 허용(존재 여부는 경고만)
    assert "server.frontend_root" not in load_config_dict(d, environ={}).error_keys()


def test_demo_frontend_root_still_served_with_login_redirect(settings_dict, tmp_path, engine):
    """시연(demo.frontend_root)은 기존대로: 공용 규칙으로 서빙 + '/' → 시연 로그인. server.frontend_root보다 우선."""
    from physicsai_api.context import build_context
    from physicsai_api.demo import LOGIN_PATH
    from physicsai_api.main import create_app
    from physicsai_core.config import load_config_dict

    fe = _build(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    (other / "index.html").write_text("OTHER", encoding="utf-8")
    d = copy.deepcopy(settings_dict)
    d["demo"] = {"enabled": True, "frontend_root": str(fe)}
    d["auth"] = {**d["auth"], "mode": "demo"}
    d["server"] = {**d.get("server", {}), "frontend_root": str(other)}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    with TestClient(create_app(build_context(lc, engine)), base_url="http://127.0.0.1") as c:
        r = c.get("/", follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == LOGIN_PATH
        assert c.get("/physicsai/stage/1").text == INDEX
        assert _is_not_found_json(c.get("/physicsai/%2e%2e/secret.txt"))
        assert c.get(f"{API}/demo/login").status_code == 200


def test_safe_parts_unit():
    from physicsai_api.frontend_static import _safe_parts

    assert _safe_parts("") == []
    assert _safe_parts("assets/a.js") == ["assets", "a.js"]
    assert _safe_parts("./a//b/") == ["a", "b"]
    for bad in ("..", "a/../b", "a\\..\\b", "/etc/passwd", "\\\\srv\\share", "C:/x", "a/C:", "x\x00", "a.txt:stream"):
        assert _safe_parts(bad) is None, bad
