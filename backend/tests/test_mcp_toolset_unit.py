"""physicsai_mcp.toolset·resources·stdio 설정 단위 시험(백엔드 없이 가짜 클라이언트) + 같은 프로세스 ASGI 위임이 백엔드 판정을 그대로 전달하는지."""

from __future__ import annotations

import asyncio
import json

import pytest

from mcp_helpers import enable, issue  # noqa: F401
from physicsai_mcp import resources
from physicsai_mcp.backend_client import AsgiBackendClient, BackendResponse, BackendTimeout, BackendUnreachable
from physicsai_mcp.stdio import StartupError, load_config
from physicsai_mcp.toolset import CallCtx, Toolset
from physicsai_test_support import API, H

CTX = CallCtx(bearer="pai_xxxxxxxx_secret", client_ip="10.0.0.5")


def _tool(name, method, path, args, schema, json_fields=None, risk="read"):
    xh = {"method": method, "path": path, "operationId": name, "args": args}
    if json_fields:
        xh["json_string_fields"] = json_fields
    return {"name": name, "description": f"{name} desc", "inputSchema": schema,
            "annotations": {"x-risk": risk, "x-confirm": "never", "x-version": 1, "x-deprecated": False}, "x-http": xh}


def _doc(visible=None):
    d = {"tools": [
        _tool("get_item", "GET", "/api/items/{item_id}", {"item_id": "path", "top_n": "query", "flag": "query"},
              {"type": "object", "properties": {"item_id": {"type": "string"}, "top_n": {"type": "integer"}, "flag": {"type": "boolean"}},
               "required": ["item_id"]}),
        _tool("make_item", "POST", "/api/items", {"name": "body", "params_json": "body", "note": "body"},
              {"type": "object", "properties": {"name": {"type": "string"}, "params_json": {"type": "string"}, "note": {"type": "string"}},
               "required": ["name"]}, {"params_json": "params"}, risk="run"),
        _tool("drop_item", "POST", "/api/items/{item_id}/drop", {"item_id": "path"},
              {"type": "object", "properties": {"item_id": {"type": "string"}}, "required": ["item_id"]}, risk="run"),
    ]}
    if visible is not None:
        d["visible"] = visible
    return d


class Fake:
    def __init__(self, resp=None, exc=None, delay=0.0):
        self.calls, self.resp, self.exc, self.delay = [], resp or BackendResponse(200, {"ok": True}), exc, delay

    async def request(self, method, path, *, query=None, json=None, bearer=None, client_ip=None):  # noqa: A002
        self.calls.append({"method": method, "path": path, "query": dict(query or {}), "json": json, "bearer": bearer, "ip": client_ip})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.resp


def run(coro):
    return asyncio.run(coro)


def test_argument_mapping_path_query_body_and_json_fields():
    f = Fake()
    ts = Toolset(_doc(), f)
    r = run(ts.call(CTX, "get_item", {"item_id": "a/b c", "top_n": 5, "flag": True}))
    assert not r.is_error and f.calls[0] == {"method": "GET", "path": "/api/items/a%2Fb%20c", "query": {"top_n": "5", "flag": "true"},
                                             "json": None, "bearer": CTX.bearer, "ip": "10.0.0.5"}
    r = run(ts.call(CTX, "make_item", {"name": "n", "params_json": json.dumps({"k": [1, 2]}), "note": None}))
    assert f.calls[1]["json"] == {"name": "n", "params": {"k": [1, 2]}} and f.calls[1]["method"] == "POST"
    run(ts.call(CTX, "drop_item", {"item_id": "j1"}))
    assert f.calls[2]["json"] is None and f.calls[2]["path"] == "/api/items/j1/drop"  # 본문 인자 없는 POST는 본문 없음


@pytest.mark.parametrize("name,args,code_part", [
    ("get_item", {}, "필수 인자 누락"),
    ("get_item", {"item_id": "x", "bogus": 1}, "알 수 없는 인자"),
    ("get_item", {"item_id": {"a": 1}}, "문자열·숫자"),
    ("get_item", {"item_id": "x", "top_n": [1]}, "문자열·숫자·불리언"),
    ("make_item", {"name": "n", "params_json": "{bad"}, "올바른 JSON이 아닙니다"),
    ("make_item", {"name": "n", "params_json": "[1]"}, "JSON 객체여야"),
    ("make_item", {"name": "n", "params_json": 5}, "문자열"),
    ("make_item", {"name": "n", "params_json": json.dumps({"x": "A" * 70000})}, "64 KiB"),
    ("nope", {}, "알 수 없는 도구"),
])
def test_local_argument_errors_never_reach_backend(name, args, code_part):
    f = Fake()
    r = run(Toolset(_doc(), f).call(CTX, name, args))
    assert r.is_error and code_part in r.data["message"] and r.data["code"] in ("INVALID_ARGUMENTS", "PARAMS_JSON_INVALID", "UNKNOWN_TOOL")
    assert (r.data["code"] == "PARAMS_JSON_INVALID") == ("params_json" in args and name == "make_item") and f.calls == []


def test_http_error_mapping_hint_retry_after_and_422_errors():
    hints = {"CONFIRM_REQUIRED": "plan_job을 먼저"}
    body = {"detail": {"code": "CONFIRM_REQUIRED", "message": "확인 필요", "plan_with": "plan_job"}}
    r = run(Toolset(_doc(), Fake(BackendResponse(428, body)), hints=hints).call(CTX, "get_item", {"item_id": "x"}))
    assert r.is_error and r.data == {"status": 428, "code": "CONFIRM_REQUIRED", "message": "확인 필요", "hint": "plan_job을 먼저"}
    r = run(Toolset(_doc(), Fake(BackendResponse(429, {"detail": {"code": "RATE_LIMITED", "message": "m"}}, {"retry-after": "7"}))).call(
        CTX, "get_item", {"item_id": "x"}))
    assert r.data["retry_after_s"] == 7 and r.data["status"] == 429 and "hint" not in r.data
    errs = [{"loc": ["body", "n"], "msg": "bad"}]
    r = run(Toolset(_doc(), Fake(BackendResponse(422, {"detail": {"code": "INVALID_PARAMS", "message": "m", "errors": errs}}))).call(
        CTX, "get_item", {"item_id": "x"}))
    assert r.data["errors"] == errs
    r = run(Toolset(_doc(), Fake(BackendResponse(500, "boom"))).call(CTX, "get_item", {"item_id": "x"}))
    assert r.is_error and r.data["code"] == "HTTP_500" and r.data["status"] == 500
    r = run(Toolset(_doc(), Fake(BackendResponse(401, {"detail": "no"}))).call(CTX, "get_item", {"item_id": "x"}))
    assert r.data["code"] == "HTTP_401" and r.data["message"] == "no"


def test_unreachable_timeout_and_result_too_large():
    r = run(Toolset(_doc(), Fake(exc=BackendUnreachable("ConnectError"))).call(CTX, "get_item", {"item_id": "x"}))
    assert r.is_error and r.data["code"] == "SERVER_UNREACHABLE" and r.data["status"] is None
    r = run(Toolset(_doc(), Fake(exc=BackendTimeout("ReadTimeout"))).call(CTX, "get_item", {"item_id": "x"}))
    assert r.data["code"] == "BACKEND_TIMEOUT"
    r = run(Toolset(_doc(), Fake(delay=1.0), call_timeout_s=0.05).call(CTX, "get_item", {"item_id": "x"}))
    assert r.data["code"] == "BACKEND_TIMEOUT"
    big = BackendResponse(200, {"rows": ["x" * 100] * 50})
    r = run(Toolset(_doc(), Fake(big), max_result_bytes=1000).call(CTX, "get_item", {"item_id": "x"}))
    assert r.is_error and r.data["code"] == "RESULT_TOO_LARGE" and "top_n" in r.data["hint"]
    ok = run(Toolset(_doc(), Fake(big), max_result_bytes=100000).call(CTX, "get_item", {"item_id": "x"}))
    assert not ok.is_error and json.loads(ok.text) == big.body


def test_visible_filter_only_affects_listing_not_calls():
    f = Fake()
    ts = Toolset(_doc(visible=["get_item"]), f)
    assert [t["name"] for t in ts.list_tools()] == ["get_item"]
    assert not run(ts.call(CTX, "make_item", {"name": "n"})).is_error and len(f.calls) == 1  # 호출 거부는 백엔드가 한다
    assert [t["name"] for t in Toolset(_doc(), f).list_tools()] == ["drop_item", "get_item", "make_item"]
    t = ts.list_tools()[0]
    assert t["readOnlyHint"] is True and t["meta"]["x-risk"] == "read" and t["inputSchema"]["required"] == ["item_id"]


def test_resource_table():
    assert resources.resolve("physicsai://glossary") == ("/api/mcp/glossary", {})
    assert resources.resolve("physicsai://glossary/feature_abbr") == ("/api/mcp/glossary", {"section": "feature_abbr"})
    assert resources.resolve("physicsai://job-kinds") == ("/api/mcp/job-kinds", {})
    assert resources.resolve("physicsai://job-kinds/predict") == ("/api/mcp/job-kinds/predict", {})
    for bad in ("physicsai://job-kinds/../x", "physicsai://glossary/a b", "physicsai://x", "http://glossary", "physicsai://glossary/"):
        assert resources.resolve(bad) is None, bad
    ts = Toolset(_doc(), Fake(BackendResponse(404, {"detail": {"code": "JOB_KIND_UNKNOWN", "message": "m"}})))
    o = run(ts.read_resource(CTX, "physicsai://job-kinds/zzz"))
    assert not o.ok and "JOB_KIND_UNKNOWN" in o.message
    assert not run(ts.read_resource(CTX, "physicsai://nope")).ok


def test_stdio_config_rules(tmp_path):
    tf = tmp_path / "t"
    tf.write_text("\n  pai_aaaaaaaa_bbb \nignored\n", encoding="utf-8")
    base = {"PHYSICSAI_MCP_URL": "http://h/physicsai/"}
    c = load_config({**base, "PHYSICSAI_MCP_TOKEN_FILE": str(tf)})
    assert c.token == "pai_aaaaaaaa_bbb" and c.url == "http://h/physicsai" and c.timeout_s == 60.0 and c.ca_bundle is None
    c = load_config({**base, "PHYSICSAI_MCP_TOKEN": "pai_direct", "PHYSICSAI_MCP_TOKEN_FILE": str(tf), "PHYSICSAI_MCP_TIMEOUT_S": "5",
                     "PHYSICSAI_MCP_CA_BUNDLE": "/ca.pem"})
    assert c.token == "pai_direct" and c.timeout_s == 5.0 and c.ca_bundle == "/ca.pem"  # TOKEN 우선
    empty = tmp_path / "e"
    empty.write_text(" \n", encoding="utf-8")
    for env in ({}, {"PHYSICSAI_MCP_URL": "ftp://x", "PHYSICSAI_MCP_TOKEN": "pai_x"}, {**base}, {**base, "PHYSICSAI_MCP_TOKEN_FILE": str(empty)},
                {**base, "PHYSICSAI_MCP_TOKEN": "nope"}, {**base, "PHYSICSAI_MCP_TOKEN": "pai_x", "PHYSICSAI_MCP_TIMEOUT_S": "0"},
                {**base, "PHYSICSAI_MCP_TOKEN": "pai_x", "PHYSICSAI_MCP_TIMEOUT_S": "99999"}):
        with pytest.raises(StartupError):
            load_config(env)


@pytest.fixture()
def settings_dict(settings_dict):
    return enable(settings_dict)


def test_asgi_delegation_forwards_backend_decisions_unchanged(app_ctx, client):
    """같은 프로세스 ASGI 위임: 백엔드가 허용하지 않은 operation(토큰에 열리지 않음)·세션 전용·범위 부족을 MCP 계층이 판정 없이 그대로 전달한다."""
    plain, _ = issue(client, scope="read")
    asgi = AsgiBackendClient(client.app, timeout_s=20)
    doc = {"tools": [_tool("peek_notifications", "GET", "/api/notifications", {}, {"type": "object", "properties": {}}),
                     _tool("list_my_tokens", "GET", "/api/me/api-tokens", {}, {"type": "object", "properties": {}}),
                     _tool("whoami", "GET", "/api/me", {}, {"type": "object", "properties": {}}),
                     _tool("sneaky_plan", "POST", "/api/mcp/jobs/plan", {"kind": "body"}, {"type": "object", "properties": {"kind": {"type": "string"}},
                                                                                         "required": ["kind"]}, risk="read")]}
    ts = Toolset(doc, asgi)
    ctx = CallCtx(bearer=plain, client_ip="203.0.113.9")

    async def go():
        return [await ts.call(ctx, n, a) for n, a in (("peek_notifications", {}), ("list_my_tokens", {}), ("whoami", {}), ("sneaky_plan", {"kind": "zzz"}))]

    notif, mine, me, plan = asyncio.run(go())
    assert notif.is_error and notif.data["status"] == 403 and notif.data["code"] == "API_TOKEN_OPERATION_NOT_ALLOWED"
    assert mine.is_error and mine.data["status"] == 403 and mine.data["code"] == "SESSION_REQUIRED"
    assert not me.is_error and me.data["user_id"] == "u-power"
    assert plan.is_error and plan.data["status"] == 422 and plan.data["code"] == "INVALID_PARAMS" and plan.data["errors"][0]["loc"] == ["body", "study_id"]
    # 원 요청자 주소가 감사에 남는다
    from sqlalchemy import text

    with app_ctx.engine.connect() as c:
        ips = {r[0] for r in c.execute(text("SELECT client_ip FROM api_audit"))}
    assert ips == {"203.0.113.9"}
