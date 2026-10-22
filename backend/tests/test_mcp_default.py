"""mcp.md V-MCP-1: mcp 키 없는 설정(기본 꺼짐) = 기존 동작 불변."""

from __future__ import annotations

from mcp_helpers import T
from physicsai_test_support import API, H


# ---- V-MCP-1: mcp 키 없는 설정 = 기존 동작 -----------------------------------------------------------


def test_v_mcp_1_default_off(client, fake_dashboard):
    fake = "pai_abcdefgh_" + "A" * 43
    r = client.get(f"{API}/me", headers=T(fake))
    assert r.status_code == 401 and r.json()["detail"]["code"] == "AUTHENTICATION_REQUIRED"
    assert fake_dashboard.me_calls() == 0  # 대시보드로 보내지 않는다
    for path in ("/mcp/job-kinds", "/mcp/system", "/me/api-tokens", "/mcp/glossary", "/mcp/tools", "/mcp/ping", "/mcp/connection"):
        r = client.get(f"{API}{path}", headers=H("tok-power"))
        assert r.status_code == 404 and r.json()["detail"]["code"] == "MCP_DISABLED", path
    r = client.post(f"{API}/mcp/jobs/plan", headers=H("tok-power", write=True), json={"kind": "predict", "study_id": "x"})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "MCP_DISABLED"
    # 세션 요청·CSRF 동작 동일
    assert client.get(f"{API}/me", headers=H("tok-power")).json()["user_id"] == "u-power"
    r = client.post(f"{API}/studies", headers=H("tok-power"), json={"project_id": "p-1", "folder_name": "S1", "title": "t"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "CSRF_HEADER_REQUIRED"
    assert client.get(f"{API}/status", headers=H("tok-power")).json()["features"]["mcp"] == {"enabled": False, "missing": ["mcp.enabled"]}


def test_v_mcp_1_config_defaults():
    from physicsai_core.config import load_config_dict

    lc = load_config_dict({}, environ={})
    m = lc.settings.mcp
    assert m.enabled is False and m.denied_job_kinds == ["solve_pbs"] and m.token.snapshot_max_age_days == 30 and m.token.max_expiry_days == 30 and m.token.default_expiry_days == 30
    assert m.confirm_ttl_s == 600 and m.rate_limit.requests_per_min == 60 and m.summary.max_bytes == 8192
    assert m.server.http_enabled is True and m.server.call_timeout_s == 60 and m.server.max_result_bytes == 65536
    bad = load_config_dict({"mcp": {"confirm_ttl_s": 5, "audit": {"retention_days": 1}, "token": {"max_expiry_days": 31},
                                    "server": {"call_timeout_s": 0}}}, environ={})
    assert {"mcp.confirm_ttl_s", "mcp.audit.retention_days", "mcp.token.max_expiry_days", "mcp.server.call_timeout_s"} <= set(bad.error_keys())
    bad = load_config_dict({"mcp": {"token": {"snapshot_max_age_days": 31, "default_expiry_days": 31}}}, environ={})
    assert {"mcp.token.snapshot_max_age_days", "mcp.token.default_expiry_days"} <= set(bad.error_keys())
