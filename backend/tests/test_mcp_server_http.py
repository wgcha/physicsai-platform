"""mcp.md V-MCP-15(HTTP E2E: SDK 클라이언트 streamable_http)·V-MCP-17(거부·감사·로그) — 시험 uvicorn + PostgreSQL."""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from mcp.shared.exceptions import MCPError

from mcp_e2e import (MCP_PATH, audit_rows, expected_visible, generated_tools, http_mcp, issue_live, live,  # noqa: F401 - fixture
                     payload, wait_audit)
from mcp_helpers import enable, import_root, install_test_kinds, shift_clock  # noqa: F401 - fixture
from physicsai_test_support import H

pytestmark = pytest.mark.timeout(120)


@pytest.fixture()
def settings_dict(settings_dict):
    return enable(settings_dict)


def _study(lv, name="S1"):
    r = httpx.post(f"{lv.api}/studies", headers=H("tok-power", write=True), json={"project_id": "p-1", "folder_name": name, "title": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.anyio
async def test_v_mcp_15_tools_list_and_read_calls(live):
    gen = generated_tools()
    read, rinfo = issue_live(live, scope="read", name="ro")
    run, _ = issue_live(live, scope="run", name="rw")
    async with http_mcp(live, read) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert set(tools) == expected_visible("read") and "run_job" not in tools and "cancel_job" not in tools
        for name, t in tools.items():  # 이름·스키마 = 생성 파일
            assert t.input_schema == gen[name]["inputSchema"], name
            assert t.description == gen[name]["description"]
        ping = payload(await c.call_tool("ping", {}))
        assert ping["ok"] is True and ping["token"]["prefix"] == rinfo["token_prefix"] and ping["token"]["scope"] == "read"
        me = payload(await c.call_tool("whoami", {}))
        assert me["user_id"] == "u-power"
        sid = _study(live)
        s = payload(await c.call_tool("get_summary", {"entity": "study", "id": sid}))
        assert s["entity"] == "study" and s["id"] == sid
        # 리소스: 용어집·작업 종류
        res = (await c.list_resources()).resources
        assert {"physicsai://glossary", "physicsai://job-kinds"} <= {str(r.uri) for r in res}
        tmpl = (await c.list_resource_templates()).resource_templates
        assert {"physicsai://glossary/{section}", "physicsai://job-kinds/{kind}"} <= {t.uri_template for t in tmpl}
        g = await c.read_resource("physicsai://glossary")
        body = json.loads(g.contents[0].text)
        assert "feature_abbr" in body and "job_kinds" in body and g.contents[0].mime_type == "application/json"
        sec = json.loads((await c.read_resource("physicsai://glossary/feature_abbr")).contents[0].text)
        assert "feature_abbr" in sec and "job_kinds" not in sec
        with pytest.raises(MCPError):
            await c.read_resource("physicsai://nope")
        with pytest.raises(MCPError):
            await c.read_resource("physicsai://glossary/not_a_section")
    async with http_mcp(live, run) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert names == expected_visible("run") and {"run_job", "cancel_job", "plan_job"} <= names


@pytest.mark.anyio
async def test_v_mcp_15_run_flow_plan_confirm_run_status(live, monkeypatch, import_root):
    calls = install_test_kinds(monkeypatch, import_root)
    sid = _study(live)
    run, _ = issue_live(live, scope="run")
    async with http_mcp(live, run) as c:
        kinds = payload(await c.call_tool("list_job_kinds", {}))
        assert {"test_heavy", "test_light"} <= {k["kind"] for k in kinds}
        desc = payload(await c.call_tool("describe_job_kind", {"kind": "test_heavy"}))
        assert desc["kind"] == "test_heavy"
        plan = payload(await c.call_tool("plan_job", {"kind": "test_heavy", "study_id": sid, "params_json": json.dumps({"n": 2})}))
        assert plan["valid"] is True and plan["confirm_token"].startswith("pcf_") and plan["runs"] == 2
        out = await c.call_tool("run_job", {"kind": "test_heavy", "study_id": sid, "params_json": json.dumps({"n": 2}),
                                            "confirm_token": plan["confirm_token"]})
        assert out.is_error is False
        job = payload(out)
        assert job["job_id"] and calls["create"] == [(sid, 2)]
        st = payload(await c.call_tool("job_status", {"job_id": job["job_id"]}))
        assert st["job_id"] == job["job_id"] and st["state"]
        jobs = payload(await c.call_tool("list_jobs", {"study_id": sid}))
        assert job["job_id"] in json.dumps(jobs)
        # 같은 confirm_token 재사용 불가(1회용) — 백엔드 409 그대로
        again = await c.call_tool("run_job", {"kind": "test_heavy", "study_id": sid, "params_json": json.dumps({"n": 2}),
                                              "confirm_token": plan["confirm_token"]})
        assert again.is_error and payload(again)["code"] == "CONFIRM_INVALID" and payload(again)["status"] == 409
        canc = await c.call_tool("cancel_job", {"job_id": job["job_id"]})
        assert canc.is_error is False


@pytest.mark.anyio
async def test_v_mcp_15_bearer_failures_and_disabled(live, engine):
    tok, info = issue_live(live, scope="read")
    r = httpx.post(live.mcp_url, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Bearer") and r.json()["code"] == "AUTHENTICATION_REQUIRED"
    r = httpx.post(live.mcp_url, headers=H("tok-power"), json={"jsonrpc": "2.0", "id": 1, "method": "ping"})  # 세션 토큰은 안 됨
    assert r.status_code == 401 and r.json()["code"] == "API_TOKEN_INVALID" and "WWW-Authenticate" in r.headers
    r = httpx.post(live.mcp_url, headers={"Authorization": "Bearer pai_abcdefgh_" + "A" * 43}, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "API_TOKEN_INVALID"
    # 폐기 토큰
    rv = httpx.delete(f"{live.api}/me/api-tokens/{info['id']}", headers=H("tok-power", write=True))
    assert rv.status_code == 204, rv.text
    r = httpx.post(live.mcp_url, headers={"Authorization": f"Bearer {tok}"}, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401 and r.json()["code"] == "API_TOKEN_REVOKED"
    # 거부는 api_audit 거부 행(접두만, 원문 없음)
    rows = [x for x in audit_rows(engine) if x["route"] == MCP_PATH]
    assert {x["result_code"] for x in rows} == {"API_TOKEN_INVALID", "API_TOKEN_REVOKED"} and all(x["status_code"] == 401 for x in rows)
    assert all(tok not in str(x) for x in rows)
    # 슬래시 끝 경로도 같은 마운트(리다이렉트 없이)
    r = httpx.post(live.mcp_url + "/", json={}, follow_redirects=False)
    assert r.status_code == 401


@pytest.mark.anyio
async def test_v_mcp_15_http_transport_disabled_404(app_ctx, settings_dict, tmp_path):
    """mcp.enabled=true라도 mcp.server.http_enabled=false면 404, mcp.enabled=false(기본)도 404 — openapi에는 나타나지 않는다."""
    from fastapi.testclient import TestClient

    from physicsai_api.main import create_app
    from physicsai_core.config import load_config_dict
    from physicsai_api.context import build_context

    for mcp in ({"enabled": True, "server": {"http_enabled": False}}, {"enabled": False}):
        sd = dict(settings_dict)
        sd["mcp"] = mcp
        lc = load_config_dict(sd, environ={})
        assert lc.ok, lc.error_keys()
        ctx = build_context(lc, app_ctx.engine)
        with TestClient(create_app(ctx), base_url="http://127.0.0.1") as c:
            r = c.post(MCP_PATH, json={})
            body = r.json()
            assert r.status_code == 404 and body["detail"]["code"] == "MCP_DISABLED"
            # mcp.md MR-C2 ②: 마운트 오류 본문 = {code, message, detail:{code, message}}(최상위는 MCP 클라이언트용)
            assert body["code"] == "MCP_DISABLED" and body["message"] and body["message"] == body["detail"]["message"]
            assert set(body) == {"code", "message", "detail"} and set(body["detail"]) == {"code", "message"}
            assert MCP_PATH not in c.get("/physicsai/api/openapi.json").json()["paths"]


def _raw(live, token, method="ping"):
    return httpx.post(live.mcp_url, headers={"Authorization": f"Bearer {token}"}, json={"jsonrpc": "2.0", "id": 1, "method": method})


def test_v_mcp_15_expired_and_stale_rejected_at_mount(live, engine, monkeypatch):
    tok, _ = issue_live(live, scope="read", expires_in_days=5)
    assert _raw(live, tok).status_code != 401
    shift_clock(monkeypatch, days=6)
    r = _raw(live, tok)
    assert r.status_code == 401 and r.json()["code"] == "API_TOKEN_EXPIRED" and r.headers["www-authenticate"].startswith("Bearer")
    assert [x["result_code"] for x in audit_rows(engine, route=MCP_PATH)] == ["API_TOKEN_EXPIRED"]


@pytest.mark.anyio
async def test_v_mcp_17_rejections_forwarded_and_audited(live, engine, caplog, monkeypatch, import_root):
    install_test_kinds(monkeypatch, import_root)
    sid = _study(live)
    read, rinfo = issue_live(live, scope="read", name="ro")
    run, tinfo = issue_live(live, scope="run", name="rw")
    caplog.set_level(logging.DEBUG)
    secret = "SENTINEL-PARAM-VALUE-7731"
    async with http_mcp(live, read) as c:
        await c.call_tool("ping", {})
        r = await c.call_tool("run_job", {"kind": "test_heavy", "study_id": sid, "params_json": json.dumps({"n": 1, "note": secret})})
        d = payload(r)
        assert r.is_error is True and d["status"] == 403 and d["code"] == "API_TOKEN_SCOPE"  # HTTP 403 그대로 전달
    async with http_mcp(live, run) as c:
        r = await c.call_tool("run_job", {"kind": "test_heavy", "study_id": sid, "params_json": json.dumps({"n": 1})})
        d = payload(r)
        assert r.is_error is True and d["status"] == 428 and d["code"] == "CONFIRM_REQUIRED" and "plan_job" in d["hint"]
        r = await c.call_tool("run_job", {"kind": "test_heavy", "study_id": sid, "params_json": "{not json"})
        assert r.is_error and payload(r)["code"] == "PARAMS_JSON_INVALID"  # 백엔드까지 가지 않는 인자 오류
        r = await c.call_tool("run_job", {"kind": "test_heavy"})
        assert r.is_error and payload(r)["code"] == "INVALID_ARGUMENTS"
        r = await c.call_tool("no_such_tool", {})
        assert r.is_error and payload(r)["code"] == "UNKNOWN_TOOL"
        pl = await c.call_tool("plan_job", {"kind": "test_heavy", "study_id": sid, "params_json": json.dumps({"n": 1})})
        assert pl.is_error is False
    # api_audit: 도구 호출마다 백엔드 요청 1행(initialize·tools/list·로컬 인자 오류는 없음) — MCP 계층 직접 기록 없음
    rows = [x for x in wait_audit(engine, 3) if x["route"] != MCP_PATH]
    ops = [(x["operation_id"], x["status_code"], x["result_code"], x["api_token_id"]) for x in rows]
    assert ops == [("run_job", 403, "API_TOKEN_SCOPE", rinfo["id"]), ("run_job", 428, "CONFIRM_REQUIRED", tinfo["id"]),
                   ("plan_job", 200, None, tinfo["id"])], ops
    assert all(x["tool"] in ("run_job", "plan_job") for x in rows)
    # 로그: 도구 이름·상태만 — 토큰·인자 값·Authorization 없음
    logs = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("physicsai_mcp"))
    assert "tool=run_job" in logs and "tool=ping" in logs
    server_side = [r for r in caplog.records if r.name.startswith(("physicsai_mcp", "physicsai_api", "httpx", "mcp.server", "uvicorn"))
                   and not r.name.startswith("physicsai_api.audit.test")]
    everything = "\n".join(f"{r.name} {r.getMessage()}" for r in server_side)
    assert "physicsai_mcp" in everything
    for forbidden in (read, run, secret, "Bearer pai_", "pcf_", sid):
        assert forbidden not in everything, forbidden


@pytest.fixture()
def reads_settings(settings_dict):
    return enable(settings_dict, audit={"record_reads": True}, rate_limit={"requests_per_min": 4})


@pytest.mark.anyio
async def test_v_mcp_17_one_audit_row_per_call_and_rate_limit(reads_settings, live, engine):
    tok, info = issue_live(live, scope="read")
    async with http_mcp(live, tok) as c:
        await c.list_tools()  # API 호출 아님 — 감사 대상 아님
        await c.call_tool("ping", {})
        await c.call_tool("whoami", {})
        await c.call_tool("list_job_kinds", {})
        assert [x["tool"] for x in wait_audit(engine, 3, api_token_id=info["id"])] == ["ping", "whoami", "list_job_kinds"]
        r = await c.call_tool("system_status", {})  # 4번째(분당 4회) — 통과
        assert r.is_error is False
        r = await c.call_tool("ping", {})  # 5번째 — 429 전달
        d = payload(r)
        assert r.is_error is True and d["status"] == 429 and d["code"] == "RATE_LIMITED" and d["retry_after_s"] >= 1 and d["hint"]
    last = wait_audit(engine, 6, api_token_id=info["id"])[-1]
    assert last["status_code"] == 429 and last["tool"] == "ping"


@pytest.fixture()
def stale_settings(settings_dict):
    return enable(settings_dict, token={"snapshot_max_age_days": 10})


def test_v_mcp_15_stale_snapshot_rejected_at_mount(stale_settings, live, monkeypatch, engine):
    tok, _ = issue_live(live, scope="read")
    shift_clock(monkeypatch, days=11)
    r = _raw(live, tok)
    assert r.status_code == 401 and r.json()["code"] == "API_TOKEN_STALE" and r.headers["www-authenticate"].startswith("Bearer")
    assert [x["result_code"] for x in audit_rows(engine, route=MCP_PATH)] == ["API_TOKEN_STALE"]


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_v_mcp_15_handshake_eras(live, mode):
    """SDK 2.x 클라이언트의 두 접속 방식(2026-07-28 요청 단위·이전 initialize 핸드셰이크) 모두 stateless 서버에서 동작."""
    tok, _ = issue_live(live, scope="read")
    async with http_mcp(live, tok, mode=mode) as c:
        assert {t.name for t in (await c.list_tools()).tools} == expected_visible("read")
        assert payload(await c.call_tool("ping", {}))["ok"] is True


def test_v_mcp_15_raw_jsonrpc_like_curl(live):
    """SDK 없이 JSON-RPC를 직접 보내도 된다(initialize → tools/list). stateless라 세션 헤더 없음, GET(독립 SSE)은 405."""
    tok, _ = issue_live(live, scope="read")
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "curl", "version": "0"}}}
    r = httpx.post(live.mcp_url, headers=h, json=init)
    assert r.status_code == 200 and "mcp-session-id" not in r.headers
    res = r.json()["result"]
    assert res["serverInfo"]["name"] == "physicsai" and "tools" in res["capabilities"] and "resources" in res["capabilities"]
    r = httpx.post(live.mcp_url, headers={**h, "MCP-Protocol-Version": "2025-06-18"}, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert {t["name"] for t in r.json()["result"]["tools"]} == expected_visible("read")
    assert httpx.get(live.mcp_url, headers=h).status_code == 405
