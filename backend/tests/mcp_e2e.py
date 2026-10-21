"""MCP E2E 시험 공용(V-MCP-15·16·17): 시험 uvicorn(127.0.0.1 임시 포트) + SDK 클라이언트(Streamable HTTP·stdio) + 감사 행 조회."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
import httpx2
import pytest
import uvicorn
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import text

from physicsai_test_support import API, REPO, H

MCP_PATH = "/physicsai/mcp"


@dataclass
class Live:
    base: str  # http://127.0.0.1:<port>
    server: uvicorn.Server
    thread: threading.Thread

    @property
    def api(self) -> str:
        return f"{self.base}{API}"

    @property
    def mcp_url(self) -> str:
        return f"{self.base}{MCP_PATH}"

    @property
    def platform_url(self) -> str:
        return f"{self.base}/physicsai"

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(15)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def live(app_ctx):
    from physicsai_api.main import create_app

    app = create_app(app_ctx)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    end = time.time() + 20
    while not server.started and time.time() < end:
        time.sleep(0.02)
    assert server.started, "시험 서버가 기동하지 않았습니다"
    lv = Live(f"http://127.0.0.1:{port}", server, th)
    yield lv
    lv.stop()


def issue_live(lv: Live, session: str = "tok-power", scope: str = "run", name: str = "llm", **kw: Any) -> tuple[str, dict[str, Any]]:
    r = httpx.post(f"{lv.api}/me/api-tokens", headers=H(session, write=True), json={"name": name, "scope": scope, **kw})
    assert r.status_code == 201, r.text
    return r.json()["token"], r.json()["api_token"]


def http_mcp(lv: Live, token: str, **client_kw: Any) -> Client:
    hc = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30)
    return Client(streamable_http_client(lv.mcp_url, http_client=hc), **client_kw)


def stdio_params(lv: Live, token: str | None = None, *, token_file: str | None = None, extra_env: dict[str, str] | None = None) -> StdioServerParameters:
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(REPO / "backend"), "PYTHONUNBUFFERED": "1",
           "PHYSICSAI_MCP_URL": lv.platform_url}
    if token:
        env["PHYSICSAI_MCP_TOKEN"] = token
    if token_file:
        env["PHYSICSAI_MCP_TOKEN_FILE"] = token_file
    env.update(extra_env or {})
    return StdioServerParameters(command=sys.executable, args=["-m", "physicsai_mcp.stdio"], env=env)


def payload(result: Any) -> Any:
    """도구 결과 → JSON(structuredContent 우선, 없으면 text)."""
    if getattr(result, "structured_content", None) is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


def audit_rows(engine, **where: Any) -> list[dict[str, Any]]:
    q = "SELECT operation_id, tool, method, route, status_code, result_code, token_prefix, api_token_id FROM api_audit"
    if where:
        q += " WHERE " + " AND ".join(f"{k} = :{k}" for k in where)
    with engine.connect() as c:
        return [dict(r._mapping) for r in c.execute(text(q + " ORDER BY occurred_at, id"), where)]


def wait_audit(engine, count: int, timeout: float = 5.0, **where: Any) -> list[dict[str, Any]]:
    """감사 행은 응답 뒤 별도 트랜잭션으로 쓰인다 — 기대 개수가 될 때까지 잠깐 기다린다(초과하면 그대로 돌려줘 호출부가 실패시킨다)."""
    end = time.time() + timeout
    rows = audit_rows(engine, **where)
    while len(rows) < count and time.time() < end:
        time.sleep(0.05)
        rows = audit_rows(engine, **where)
    time.sleep(0.15)  # 초과 기록(중복 행)이 있으면 드러나도록 짧게 더 본다
    return audit_rows(engine, **where)


def generated_tools() -> dict[str, dict[str, Any]]:
    from physicsai_api.mcp.glossary import GENERATED_DIR

    doc = json.loads((GENERATED_DIR / "tools.mcp.json").read_text(encoding="utf-8"))
    return {t["name"]: t for t in doc["tools"]}


RANK = {"read": 0, "run": 1, "admin": 2}


def expected_visible(scope: str) -> set[str]:
    return {n for n, t in generated_tools().items() if RANK[t["annotations"]["x-risk"]] <= RANK[scope]}
