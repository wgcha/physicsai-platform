"""mcp.md §23.4 `GET /mcp/connection`(MR-C3, V-MCP-24·26 API 쪽): 주소 출처(config|guess)·api_base·세션 전용(토큰 403)·꺼짐 404·x-mcp 제외."""

from __future__ import annotations

import contextlib

import pytest

from mcp_helpers import T, enable, issue
from physicsai_test_support import API, H

URL = "https://ai.example.test/physicsai/mcp"
KEYS = {"enabled", "http_enabled", "url", "url_source", "api_base", "stdio_hint"}


@pytest.fixture()
def settings_dict(settings_dict):
    return enable(settings_dict)  # mcp.enabled=true, public_url 없음(짐작)


@contextlib.contextmanager
def _peer(app_ctx, host: str):
    """요청 상대(peer) 주소를 정한 TestClient — 프록시 헤더 신뢰 규칙 시험용."""
    from fastapi.testclient import TestClient

    from physicsai_api.main import create_app

    with TestClient(create_app(app_ctx), base_url="http://127.0.0.1", client=(host, 50000)) as c:
        yield c


def _get(c, headers: dict[str, str] | None = None):
    return c.get(f"{API}/mcp/connection", headers={**H("tok-power"), **(headers or {})})


def test_connection_guess_from_request_origin(client):
    r = _get(client, {"host": "ai.example.test:8443"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j) == KEYS
    assert (j["enabled"], j["http_enabled"], j["url_source"]) == (True, True, "guess")
    assert j["url"] == "http://ai.example.test:8443/physicsai/mcp" and j["api_base"] == "http://ai.example.test:8443/physicsai"
    sh = j["stdio_hint"]
    assert sh["command"] == "physicsai-mcp"
    assert sh["command_path"] is None or sh["command_path"].endswith(("physicsai-mcp", "physicsai-mcp.exe"))
    assert "wheels" in sh["install"] and "Node.js" in sh["install"] and "mcp-remote" in sh["install"]
    assert "pai_" not in r.text  # 토큰 값은 응답에 없다


def test_connection_forwarded_headers_only_from_loopback_peer(app_ctx):
    fwd = {"x-forwarded-proto": "https", "x-forwarded-host": "ai.example.test", "host": "internal:8100"}
    with _peer(app_ctx, "10.1.2.3") as c:  # 직접 붙은 외부 상대의 헤더는 믿지 않는다(주소 위조 방지)
        j = _get(c, fwd).json()
        assert j["url"] == "http://internal:8100/physicsai/mcp" and j["url_source"] == "guess"
    with _peer(app_ctx, "127.0.0.1") as c:  # 같은 PC의 리버스 프록시
        j = _get(c, fwd).json()
        assert j["url"] == "https://ai.example.test/physicsai/mcp" and j["api_base"] == "https://ai.example.test/physicsai"
        bad = _get(c, {"x-forwarded-host": "evil.test/x?y", "x-forwarded-proto": "ftp", "host": "internal:8100"}).json()
        assert bad["url"] == "http://internal:8100/physicsai/mcp"  # 모양이 이상하면 직접 연결 값으로


class TestConfigured:
    @pytest.fixture()
    def settings_dict(self, settings_dict):
        settings_dict["mcp"]["public_url"] = URL + "/"
        return settings_dict

    def test_config_value_wins_over_request(self, client):
        j = _get(client, {"host": "other.test"}).json()
        assert (j["url"], j["url_source"], j["api_base"]) == (URL, "config", "https://ai.example.test/physicsai")


class TestHttpOff:
    @pytest.fixture()
    def settings_dict(self, settings_dict):
        settings_dict["mcp"]["server"] = {"http_enabled": False}
        return settings_dict

    def test_http_enabled_false_is_reported(self, client):
        j = _get(client).json()
        assert j["enabled"] is True and j["http_enabled"] is False


def test_connection_session_only_token_403(client):
    plain, _ = issue(client, scope="run", name="all")
    r = client.get(f"{API}/mcp/connection", headers=T(plain))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "SESSION_REQUIRED"
    assert client.get(f"{API}/mcp/connection").status_code == 401  # 로그인 필요


def test_connection_not_in_tool_specs(client):
    """x-mcp exclude: 도구 스펙(생성본·서버 응답) 어디에도 없다 — 웹 세션 전용 안내라 AI 도구로 노출하지 않는다."""
    plain, _ = issue(client, scope="run", name="all")
    r = client.get(f"{API}/mcp/tools", headers=T(plain))
    assert r.status_code == 200 and "mcp_connection" not in {t["name"] for t in r.json()["tools"]}
    oa = client.get(f"{API}/mcp/tools?format=openai", headers=T(plain)).json()
    assert "mcp_connection" not in {(t.get("function") or t)["name"] for t in (oa if isinstance(oa, list) else oa["tools"])}


class TestDisabled:
    @pytest.fixture()
    def settings_dict(self, settings_dict):
        settings_dict["mcp"] = {"enabled": False}
        return settings_dict

    def test_disabled_is_404_mcp_disabled(self, client):
        r = _get(client)
        assert r.status_code == 404 and r.json()["detail"]["code"] == "MCP_DISABLED"
