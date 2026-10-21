"""mcp.md V-MCP-16(stdio E2E: SDK 클라이언트 stdio_client) — `python -m physicsai_mcp.stdio`를 환경변수로 띄워 V-MCP-15와 같은 시나리오."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError

from mcp_e2e import (audit_rows, expected_visible, free_port, generated_tools, issue_live, live,  # noqa: F401 - fixture
                     payload, stdio_params, wait_audit)
from mcp_helpers import enable, import_root, install_test_kinds  # noqa: F401 - fixture
from physicsai_test_support import REPO

pytestmark = pytest.mark.timeout(150)


@pytest.fixture()
def settings_dict(settings_dict):
    return enable(settings_dict)


def _study(lv, name="S1"):
    import httpx

    from physicsai_test_support import H

    r = httpx.post(f"{lv.api}/studies", headers=H("tok-power", write=True), json={"project_id": "p-1", "folder_name": name, "title": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    full = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(REPO / "backend"), **(env or {})}
    return subprocess.run([sys.executable, "-m", "physicsai_mcp.stdio", *args], env=full, capture_output=True, text=True, timeout=60, shell=False)


@pytest.mark.anyio
async def test_v_mcp_16_same_scenario_as_http(live, engine, monkeypatch, import_root, tmp_path):
    calls = install_test_kinds(monkeypatch, import_root)
    gen = generated_tools()
    sid = _study(live)
    read, rinfo = issue_live(live, scope="read", name="ro")
    run, tinfo = issue_live(live, scope="run", name="rw")
    # read 토큰(환경변수): 도구 목록 = HTTP와 같은 표시 규칙, 스키마 = 생성 파일
    async with Client(stdio_params(live, read)) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert set(tools) == expected_visible("read")
        for name, t in tools.items():
            assert t.input_schema == gen[name]["inputSchema"] and t.description == gen[name]["description"]
        ping = payload(await c.call_tool("ping", {}))
        assert ping["ok"] and ping["token"]["prefix"] == rinfo["token_prefix"] and ping["token"]["scope"] == "read"
        assert payload(await c.call_tool("whoami", {}))["user_id"] == "u-power"
        assert payload(await c.call_tool("get_summary", {"entity": "study", "id": sid}))["id"] == sid
        assert {"physicsai://glossary", "physicsai://job-kinds"} <= {str(r.uri) for r in (await c.list_resources()).resources}
        body = json.loads((await c.read_resource("physicsai://glossary")).contents[0].text)
        assert "feature_abbr" in body
        with pytest.raises(MCPError):
            await c.read_resource("physicsai://nope")
        # 숨긴 도구도 호출하면 백엔드가 거부(HTTP 403 그대로)
        r = await c.call_tool("run_job", {"kind": "test_heavy", "study_id": sid})
        assert r.is_error and payload(r)["status"] == 403 and payload(r)["code"] == "API_TOKEN_SCOPE"
    # run 토큰(토큰 파일): plan → confirm → run → status, 힌트
    tf = tmp_path / "token"
    tf.write_text("\n" + run + "\n", encoding="utf-8")
    async with Client(stdio_params(live, token_file=str(tf))) as c:
        assert {t.name for t in (await c.list_tools()).tools} == expected_visible("run")
        r = await c.call_tool("run_job", {"kind": "test_heavy", "study_id": sid, "params_json": json.dumps({"n": 2})})
        d = payload(r)
        assert r.is_error and d["status"] == 428 and d["code"] == "CONFIRM_REQUIRED" and "plan_job" in d["hint"]
        plan = payload(await c.call_tool("plan_job", {"kind": "test_heavy", "study_id": sid, "params_json": json.dumps({"n": 2})}))
        assert plan["confirm_token"].startswith("pcf_")
        out = await c.call_tool("run_job", {"kind": "test_heavy", "study_id": sid, "params_json": json.dumps({"n": 2}),
                                            "confirm_token": plan["confirm_token"]})
        assert out.is_error is False and calls["create"] == [(sid, 2)]
        job = payload(out)
        assert payload(await c.call_tool("job_status", {"job_id": job["job_id"]}))["job_id"] == job["job_id"]
    rows = wait_audit(engine, 4)
    assert [(x["tool"], x["status_code"]) for x in rows if x["tool"] in ("run_job", "plan_job")] == [
        ("run_job", 403), ("run_job", 428), ("plan_job", 200), ("run_job", 201)]
    assert {x["api_token_id"] for x in rows} <= {rinfo["id"], tinfo["id"]}


def test_v_mcp_16_start_failures_exit_2_without_token_in_output(live):
    token, info = issue_live(live, scope="read")
    p = _run_cli(env={"PHYSICSAI_MCP_URL": live.platform_url})
    assert p.returncode == 2 and "토큰이 없습니다" in p.stderr and p.stdout == ""
    p = _run_cli(env={"PHYSICSAI_MCP_TOKEN": token})
    assert p.returncode == 2 and "PHYSICSAI_MCP_URL" in p.stderr
    p = _run_cli(env={"PHYSICSAI_MCP_URL": live.platform_url, "PHYSICSAI_MCP_TOKEN_FILE": "/nonexistent/token-file"})
    assert p.returncode == 2 and "토큰 파일" in p.stderr
    p = _run_cli(env={"PHYSICSAI_MCP_URL": live.platform_url, "PHYSICSAI_MCP_TOKEN": "not-a-pai-token"})
    assert p.returncode == 2 and "pai_" in p.stderr and "not-a-pai-token" not in p.stderr
    fake = "pai_abcdefgh_" + "A" * 43
    p = _run_cli(env={"PHYSICSAI_MCP_URL": live.platform_url, "PHYSICSAI_MCP_TOKEN": fake})
    assert p.returncode == 2 and "거부" in p.stderr and "API_TOKEN_INVALID" in p.stderr and fake not in p.stderr + p.stdout
    p = _run_cli(env={"PHYSICSAI_MCP_URL": f"http://127.0.0.1:{free_port()}/physicsai", "PHYSICSAI_MCP_TOKEN": token})
    assert p.returncode == 2 and "접속할 수 없습니다" in p.stderr and token not in p.stderr + p.stdout
    p = _run_cli(env={"PHYSICSAI_MCP_URL": live.platform_url, "PHYSICSAI_MCP_TOKEN": token, "PHYSICSAI_MCP_TIMEOUT_S": "abc"})
    assert p.returncode == 2 and "PHYSICSAI_MCP_TIMEOUT_S" in p.stderr
    # 정상: --check는 ping 결과를 출력하고 0으로 종료(토큰 원문 출력 없음)
    p = _run_cli("--check", env={"PHYSICSAI_MCP_URL": live.platform_url, "PHYSICSAI_MCP_TOKEN": token})
    assert p.returncode == 0 and token not in p.stdout + p.stderr
    out = json.loads(p.stdout)
    assert out["ok"] is True and out["token"]["prefix"] == info["token_prefix"]


def test_v_mcp_16_version_and_no_platform_imports():
    p = _run_cli("--version")
    assert p.returncode == 0 and p.stdout.startswith("physicsai-mcp ") and "mcp 2.3.0" in p.stdout
    code = ("import sys, physicsai_mcp.stdio, physicsai_mcp.http_app\n"
            "bad=[m for m in sys.modules if m.split('.')[0] in ('physicsai_api','physicsai_core','physicsai_worker')]\n"
            "assert not bad, bad")
    p = subprocess.run([sys.executable, "-c", code], env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(REPO / "backend")},
                       capture_output=True, text=True, timeout=60, shell=False)
    assert p.returncode == 0, p.stderr


@pytest.mark.anyio
async def test_v_mcp_16_server_down_is_tool_error(live):
    token, _ = issue_live(live, scope="read")
    async with Client(stdio_params(live, token)) as c:
        assert payload(await c.call_tool("ping", {}))["ok"] is True
        live.stop()
        r = await c.call_tool("ping", {})
        d = payload(r)
        assert r.is_error is True and d["code"] == "SERVER_UNREACHABLE" and token not in json.dumps(d)
