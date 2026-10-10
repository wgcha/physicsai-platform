"""V-AUTH-1~5: 대시보드 introspection·캐시·권한·CSRF·dev_static."""

from __future__ import annotations

import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from physicsai_test_support import API, H


def test_health_public(client):
    r = client.get(f"{API}/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_cookie_introspection_active(client, fake_dashboard):
    client.cookies.set("analysis_canvas_session", "tok-power")
    r = client.get(f"{API}/me")
    client.cookies.clear()
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "u-power" and body["roles"] == {"p-1": "power"}
    call = fake_dashboard.calls[-1]
    assert call.url.path == "/api/auth/me"
    assert call.headers["authorization"] == "Bearer tok-power"
    assert call.headers.get("x-request-id")


def test_invalid_roles_ignored(client):
    r = client.get(f"{API}/me", headers=H("tok-nonmember"))
    assert r.json()["roles"] == {"p-2": "power"}


@pytest.mark.parametrize(
    "token,mode,status,code",
    [
        (None, "ok", 401, "AUTHENTICATION_REQUIRED"),
        ("tok-unknown", "ok", 401, "AUTHENTICATION_REQUIRED"),
        ("tok-pending", "ok", 403, "ACCOUNT_NOT_ACTIVE"),
        ("tok-suspended", "ok", 403, "ACCOUNT_NOT_ACTIVE"),
        ("tok-power", "503", 503, "DASHBOARD_AUTH_UNAVAILABLE"),
        ("tok-power", "timeout", 503, "DASHBOARD_UNREACHABLE"),
        ("tok-power", "badjson", 503, "DASHBOARD_UNREACHABLE"),
        ("tok-power", "500", 503, "DASHBOARD_UNREACHABLE"),
    ],
)
def test_introspection_mapping(client, fake_dashboard, token, mode, status, code):
    fake_dashboard.mode = mode
    r = client.get(f"{API}/me", headers=H(token) if token else {})
    assert r.status_code == status
    assert r.json()["detail"]["code"] == code


def test_cache_ttl_and_failures_not_cached(engine, loaded_config, fake_dashboard):
    from physicsai_api.context import build_context
    from physicsai_api.main import create_app

    now = [1000.0]
    ctx = build_context(loaded_config, engine, transport=httpx.MockTransport(fake_dashboard.handler), clock=lambda: now[0])
    with TestClient(create_app(ctx), base_url="http://127.0.0.1") as c:
        assert c.get(f"{API}/me", headers=H("tok-power")).status_code == 200
        assert c.get(f"{API}/me", headers=H("tok-power")).status_code == 200
        assert fake_dashboard.me_calls() == 1
        now[0] += 29
        c.get(f"{API}/me", headers=H("tok-power"))
        assert fake_dashboard.me_calls() == 1
        now[0] += 2
        c.get(f"{API}/me", headers=H("tok-power"))
        assert fake_dashboard.me_calls() == 2
        # 실패는 캐시하지 않음
        fake_dashboard.mode = "503"
        assert c.get(f"{API}/me", headers=H("tok-general")).status_code == 503
        fake_dashboard.mode = "ok"
        assert c.get(f"{API}/me", headers=H("tok-general")).status_code == 200


def test_token_not_logged_or_stored(client, engine, caplog):
    from sqlalchemy import text

    caplog.set_level(logging.DEBUG)
    secret = "tok-power"
    client.get(f"{API}/me", headers=H(secret))
    client.post(f"{API}/studies", headers=H(secret, write=True), json={"project_id": "p-1", "folder_name": "Tok1", "title": "t"})
    assert secret not in caplog.text
    with engine.connect() as c:
        for table in ("audit_events", "studies", "notifications"):
            dump = str(c.execute(text(f"select * from {table}")).all())
            assert secret not in dump


def test_csrf_header_required(client):
    r = client.post(f"{API}/studies", headers=H("tok-power"), json={"project_id": "p-1", "folder_name": "X1", "title": "x"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "CSRF_HEADER_REQUIRED"


def test_projects_proxy(client):
    r = client.get(f"{API}/projects", headers=H("tok-general"))
    assert r.status_code == 200
    assert r.json() == [{"id": "p-1", "name": "쿠션", "product_name": "Phone"}, {"id": "p-2", "name": "브래킷", "product_name": "TV"}]


@pytest.mark.parametrize("profile,host,ok", [("dev", "127.0.0.1", True), ("prod", "127.0.0.1", False), ("dev", "0.0.0.0", False)])
def test_dev_static_startup_guard(engine, settings_dict, profile, host, ok):
    from physicsai_api.context import build_context
    from physicsai_api.main import StartupRefused, create_app
    from physicsai_core.config import load_config_dict

    d = dict(settings_dict)
    d["auth"] = {**d["auth"], "mode": "dev_static"}
    d["profile"] = profile
    lc = load_config_dict(d, environ={})
    if not ok:
        with pytest.raises(StartupRefused):
            create_app(build_context(lc, engine), bind_host=host)
        if profile == "prod":
            assert "auth.mode" in lc.error_keys()
    else:
        app = create_app(build_context(lc, engine), bind_host=host)
        with TestClient(app, base_url="http://127.0.0.1") as c:
            assert c.get(f"{API}/me").json()["user_id"] == "dev-admin"
