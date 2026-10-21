"""mcp.md V-MCP-2(토큰 수명)·V-MCP-3(범위·허용 목록·스냅숏)·V-MCP-11(호출 제한)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from mcp_helpers import T, enable, issue, shift_clock
from physicsai_test_support import API, USERS, H


# ---- V-MCP-2: 토큰 수명 ------------------------------------------------------------------------------


@pytest.fixture()
def settings_dict(settings_dict):
    return enable(settings_dict, token={"snapshot_max_age_days": 10})  # stale 시험용(기본 30 = 만료와 같은 시점, MR-13)


def test_v_mcp_2_token_lifecycle(client, engine, monkeypatch, fake_dashboard):
    plain, tok = issue(client, scope="read")
    assert plain.startswith("pai_") and len(plain) == 56 and tok["token_prefix"] == plain[:12]
    lst = client.get(f"{API}/me/api-tokens", headers=H("tok-power")).json()
    assert [t["id"] for t in lst] == [tok["id"]] and lst[0]["status"] == "active"
    assert plain not in str(lst) and "token_hash" not in lst[0] and "token" not in lst[0]
    with engine.connect() as c:
        dump = " ".join(r[0] for r in c.execute(text(
            "SELECT row_to_json(t)::text FROM api_tokens t UNION ALL SELECT row_to_json(a)::text FROM audit_events a")))
    assert plain not in dump and plain[12:] not in dump and "API_TOKEN_CREATE" in dump
    calls0 = fake_dashboard.me_calls()
    r = client.get(f"{API}/me", headers=T(plain))
    assert r.status_code == 200 and r.json()["user_id"] == "u-power"
    assert fake_dashboard.me_calls() == calls0  # 토큰은 대시보드로 보내지 않음
    # 형식 오류·모르는 토큰
    for bad in ("pai_short", plain[:-1] + ("A" if plain[-1] != "A" else "B")):
        r = client.get(f"{API}/me", headers=T(bad))
        assert r.status_code == 401 and r.json()["detail"]["code"] == "API_TOKEN_INVALID"
        assert bad not in r.text
    # stale(스냅숏 11일 경과 > 설정 10) → 만료(31일) 순
    shift_clock(monkeypatch, days=11)
    r = client.get(f"{API}/me", headers=T(plain))
    assert r.status_code == 401 and r.json()["detail"]["code"] == "API_TOKEN_STALE"
    shift_clock(monkeypatch, days=31)
    r = client.get(f"{API}/me", headers=T(plain))
    assert r.json()["detail"]["code"] == "API_TOKEN_EXPIRED"
    monkeypatch.undo()
    # 폐기(멱등) → 401 REVOKED
    assert client.delete(f"{API}/me/api-tokens/{tok['id']}", headers=H("tok-power", write=True)).status_code == 204
    assert client.delete(f"{API}/me/api-tokens/{tok['id']}", headers=H("tok-power", write=True)).status_code == 204
    r = client.get(f"{API}/me", headers=T(plain))
    assert r.status_code == 401 and r.json()["detail"]["code"] == "API_TOKEN_REVOKED"
    assert client.delete(f"{API}/me/api-tokens/{tok['id']}", headers=H("tok-power2", write=True)).status_code == 404


def test_v_mcp_2_limits_and_session_only(client):
    for i in range(5):
        issue(client, scope="read", name=f"t{i}")
    r = client.post(f"{API}/me/api-tokens", headers=H("tok-power", write=True), json={"name": "t9", "scope": "read"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "API_TOKEN_LIMIT"
    plain, _ = issue(client, session="tok-power2", scope="read", name="t0")
    r = client.post(f"{API}/me/api-tokens", headers=H("tok-power2", write=True), json={"name": "t0", "scope": "read"})
    assert r.json()["detail"]["code"] == "API_TOKEN_NAME_EXISTS"
    r = client.post(f"{API}/me/api-tokens", headers=H("tok-power2", write=True), json={"name": "x", "scope": "read",
                                                                                     "expires_in_days": 31})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "API_TOKEN_EXPIRY_TOO_LONG"
    r = client.post(f"{API}/me/api-tokens", headers=H("tok-power2", write=True), json={"name": "x", "scope": "read",
                                                                                     "expires_in_days": 0})
    assert r.status_code == 422
    for method, path in (("get", "/me/api-tokens"), ("post", "/me/api-tokens"), ("get", "/admin/api-tokens")):
        r = getattr(client, method)(f"{API}{path}", headers=T(plain), **({"json": {"name": "y", "scope": "read"}} if method == "post" else {}))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "SESSION_REQUIRED", path


# ---- V-MCP-3: 범위·허용 목록·스냅숏 ------------------------------------------------------------------


def test_v_mcp_3_scope_and_allow_list(client, monkeypatch):
    r = client.post(f"{API}/me/api-tokens", headers=H("tok-general", write=True), json={"name": "a", "scope": "run"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "API_TOKEN_SCOPE"
    r = client.post(f"{API}/me/api-tokens", headers=H("tok-power", write=True), json={"name": "a", "scope": "admin"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "API_TOKEN_SCOPE"
    read, _ = issue(client, scope="read", name="r")
    r = client.post(f"{API}/mcp/jobs", headers=T(read), json={"kind": "predict", "study_id": "x", "params": {}})
    assert r.status_code == 403 and r.json()["detail"] == {"code": "API_TOKEN_SCOPE", "message": r.json()["detail"]["message"],
                                                           "required": "run"}
    r = client.get(f"{API}/queue", headers=T(read))  # x-mcp 없는 기존 operation
    assert r.status_code == 403 and r.json()["detail"]["code"] == "API_TOKEN_OPERATION_NOT_ALLOWED"
    r = client.get(f"{API}/mcp/audit", headers=T(read))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "API_TOKEN_SCOPE"
    assert client.get(f"{API}/studies", headers=T(read)).status_code == 200
    assert client.get(f"{API}/mcp/tools?format=openai", headers=T(read)).status_code == 200  # 제외 + token_risk read
    adm, _ = issue(client, session="tok-admin", scope="admin", name="adm")
    assert client.get(f"{API}/mcp/audit", headers=T(adm)).status_code == 200
    assert client.get(f"{API}/mcp/audit", headers=H("tok-power")).json()["detail"]["code"] == "PERMISSION_DENIED"


def test_v_mcp_3_snapshot_refresh_and_admin_revoke(client, monkeypatch):
    run, _ = issue(client, scope="run", name="r")
    sid = client.post(f"{API}/studies", headers=H("tok-power", write=True),
                      json={"project_id": "p-1", "folder_name": "S1", "title": "t"}).json()["id"]
    assert client.get(f"{API}/me", headers=T(run)).json()["roles"] == {"p-1": "power"}
    monkeypatch.setitem(USERS, "tok-power-demoted", {**USERS["tok-power"], "memberships": [{"project_id": "p-1", "role": "general"}]})
    assert client.get(f"{API}/me", headers=H("tok-power-demoted")).status_code == 200  # 웹 로그인 → 스냅숏 갱신
    assert client.get(f"{API}/me", headers=T(run)).json()["roles"] == {"p-1": "general"}
    r = client.post(f"{API}/mcp/jobs", headers=T(run), json={"kind": "predict", "study_id": sid, "params": {"values": {"a": 1.0}}})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "PERMISSION_DENIED"
    adm, atok = issue(client, session="tok-admin", scope="admin", name="adm")
    monkeypatch.setitem(USERS, "tok-admin-demoted", {**USERS["tok-admin"], "is_global_admin": False})
    client.get(f"{API}/me", headers=H("tok-admin-demoted"))
    r = client.get(f"{API}/me", headers=T(adm))
    assert r.status_code == 401 and r.json()["detail"]["code"] == "API_TOKEN_REVOKED"
    lst = client.get(f"{API}/admin/api-tokens?user_id=u-admin", headers=H("tok-admin")).json()
    assert lst[0]["revoked_by"] == "system:role_change"


def test_admin_revoke_api(client):
    plain, tok = issue(client, scope="read")
    r = client.post(f"{API}/admin/api-tokens/{tok['id']}/revoke", headers=H("tok-admin", write=True))
    assert r.status_code == 200 and r.json()["status"] == "revoked" and r.json()["username"] == "power"
    assert client.get(f"{API}/me", headers=T(plain)).json()["detail"]["code"] == "API_TOKEN_REVOKED"
    assert client.post(f"{API}/admin/api-tokens/{tok['id']}/revoke", headers=H("tok-power", write=True)).status_code == 403


# ---- V-MCP-11: 호출 제한 ------------------------------------------------------------------------------


def test_v_mcp_11_requests_per_minute(client):
    plain, _ = issue(client, scope="read")
    for _ in range(60):
        assert client.get(f"{API}/me", headers=T(plain)).status_code == 200
    r = client.get(f"{API}/me", headers=T(plain))
    assert r.status_code == 429 and r.json()["detail"]["code"] == "RATE_LIMITED" and int(r.headers["Retry-After"]) >= 1
    for _ in range(70):  # 세션 무제한
        assert client.get(f"{API}/me", headers=H("tok-power")).status_code == 200
