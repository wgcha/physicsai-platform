"""웹 "AI 연결(MCP)" 페이지 연결 안내(mcp.md §23.4, MR-C3): 서버 주소·전송·stdio 실행기. 세션 전용 — 토큰 요청은 라우트 x-mcp(session_only)가 403.

주소는 서버가 준다: 설정 `mcp.public_url`이 있으면 그 값(`config`), 없으면 요청 origin + `/physicsai/mcp` 짐작(`guess`).
짐작에 쓰는 `X-Forwarded-Proto`·`X-Forwarded-Host`는 요청 상대가 loopback(같은 PC의 리버스 프록시)일 때만 믿는다.
비밀값(토큰·경로 밖 정보)은 응답에 없다.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from fastapi import Request

from ..context import AppContext
from ..mcp.http_mount import MOUNT_PATH
from .api_tokens import require_enabled

STDIO_COMMAND = "physicsai-mcp"
LOOPBACK = ("127.0.0.1", "::1")
HOST_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_:[]")
INSTALL_HINT = ("Node.js를 쓸 수 없는 PC(대안): 관리자에게 오프라인 묶음 wheels를 받아 `pip install --no-index --find-links <wheels> physicsai-platform`(Python 3.12) — "
                "이 실행기는 Node.js 불필요, 기본 방식(npx mcp-remote 브리지)은 Node.js 필요")


def _first(value: str | None) -> str:
    return (value or "").split(",")[0].strip()


def _host_ok(host: str) -> bool:
    return 0 < len(host) <= 255 and all(c in HOST_CHARS for c in host)


def guess_origin(request: Request) -> str:
    """요청 origin(scheme://host[:port]). 프록시 헤더는 loopback 상대일 때만, 모양이 이상하면 직접 연결 값으로 되돌린다."""
    peer = request.client.host if request.client else ""
    trusted = peer in LOOPBACK
    scheme = _first(request.headers.get("x-forwarded-proto")) if trusted else ""
    host = _first(request.headers.get("x-forwarded-host")) if trusted else ""
    if scheme not in ("http", "https"):
        scheme = request.url.scheme if request.url.scheme in ("http", "https") else "http"
    if not _host_ok(host):
        host = _first(request.headers.get("host"))
    if not _host_ok(host):
        host = request.url.netloc if _host_ok(request.url.netloc) else "localhost"
    return f"{scheme}://{host}"


def command_path() -> str | None:
    """서버 venv의 실행기 경로(`sys.prefix` 기준, 없으면 None)."""
    rel = ("Scripts", f"{STDIO_COMMAND}.exe") if os.name == "nt" else ("bin", STDIO_COMMAND)
    p = os.path.join(sys.prefix, *rel)
    return p if os.path.isfile(p) else None


def connection(ctx: AppContext, request: Request) -> dict[str, Any]:
    require_enabled(ctx)  # 꺼짐이면 404 MCP_DISABLED(기존 /mcp/* 규칙)
    m = ctx.settings.mcp
    if m.public_url:
        url, source = m.public_url.rstrip("/"), "config"
    else:
        url, source = guess_origin(request) + MOUNT_PATH, "guess"
    return {"enabled": True, "http_enabled": bool(m.server.http_enabled), "url": url, "url_source": source,
            "api_base": url[: -len("/mcp")] if url.endswith("/mcp") else url,
            "stdio_hint": {"command": STDIO_COMMAND, "command_path": command_path(), "install": INSTALL_HINT}}
