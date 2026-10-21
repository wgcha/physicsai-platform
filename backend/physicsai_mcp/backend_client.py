"""위임 HTTP 클라이언트(mcp.md §20.1): 도구 호출을 백엔드 HTTP API 요청으로 보낸다. 구현 둘 — 네트워크(stdio용)·ASGI(같은 프로세스 앱, HTTP 마운트용).

토큰은 호출마다 인자로 받고 보관·로그하지 않는다. 응답 본문은 JSON이면 파싱, 아니면 잘라 낸 텍스트.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

import httpx

MAX_BODY_BYTES = 4 * 1024 * 1024  # 백엔드 응답 읽기 상한(도구 결과 상한은 toolset이 따로 건다)
INTERNAL_HOST = "mcp.internal"  # ASGI 클라이언트의 가짜 호스트(네트워크 아님)


class _QuietInternal(logging.Filter):
    """httpx가 INFO로 남기는 요청 줄("HTTP Request: POST <url>")에는 경로·쿼리 값이 들어간다 — 같은 프로세스 내부 호출은 로그에 남기지 않는다(인자 값 로그 금지)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args if isinstance(record.args, tuple) else ()
        return not any(INTERNAL_HOST in str(a) for a in args)


logging.getLogger("httpx").addFilter(_QuietInternal())


class BackendUnreachable(Exception):
    """연결 실패(서버 다운·주소 오류·TLS 오류)."""


class BackendTimeout(Exception):
    """시간 초과."""


@dataclass(frozen=True)
class BackendResponse:
    status: int
    body: Any
    headers: Mapping[str, str] = field(default_factory=dict)


class BackendClient(Protocol):
    async def request(self, method: str, path: str, *, query: Mapping[str, str] | None = None, json: Any = None,  # noqa: A002
                      bearer: str | None = None, client_ip: str | None = None) -> BackendResponse: ...


def _headers(bearer: str | None) -> dict[str, str]:
    h = {"Accept": "application/json"}
    if bearer:
        h["Authorization"] = f"Bearer {bearer}"
    return h


def _parse(resp: httpx.Response) -> BackendResponse:
    raw = resp.content[:MAX_BODY_BYTES]
    ctype = resp.headers.get("content-type", "")
    body: Any
    if raw and "json" in ctype:
        try:
            body = json.loads(raw)
        except ValueError:
            body = raw.decode("utf-8", "replace")[:2000]
    else:
        body = raw.decode("utf-8", "replace")[:2000] if raw else None
    return BackendResponse(resp.status_code, body, {k.lower(): v for k, v in resp.headers.items()})


class HttpBackendClient:
    """네트워크 클라이언트(stdio 실행기): `base_url`(예 http://host/physicsai) 뒤에 `/api/...`를 붙인다."""

    def __init__(self, base_url: str, *, timeout_s: float = 60.0, ca_bundle: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._verify: Any = ca_bundle if ca_bundle else True

    async def request(self, method: str, path: str, *, query: Mapping[str, str] | None = None, json: Any = None,  # noqa: A002
                      bearer: str | None = None, client_ip: str | None = None) -> BackendResponse:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s, verify=self._verify, follow_redirects=False) as c:
                resp = await c.request(method, self.base_url + path, params=dict(query or {}), json=json, headers=_headers(bearer))
        except httpx.TimeoutException as e:
            raise BackendTimeout(type(e).__name__) from e
        except (httpx.TransportError, OSError) as e:  # 메시지에 주소가 섞일 수 있어 종류만 전달
            raise BackendUnreachable(type(e).__name__) from e
        return _parse(resp)


class AsgiBackendClient:
    """같은 프로세스 앱을 ASGI로 직접 호출(HTTP 마운트). 앱의 미들웨어(감사·인증)를 그대로 탄다.

    `client_ip`가 있으면 ASGI scope의 client로 넘겨 감사 행에 원 요청자 주소가 남게 한다.
    """

    def __init__(self, app: Any, *, base_path: str = "/physicsai", timeout_s: float = 60.0) -> None:
        self.app = app
        self.base_path = base_path.rstrip("/")
        self.timeout_s = timeout_s

    async def request(self, method: str, path: str, *, query: Mapping[str, str] | None = None, json: Any = None,  # noqa: A002
                      bearer: str | None = None, client_ip: str | None = None) -> BackendResponse:
        transport = httpx.ASGITransport(app=self.app, raise_app_exceptions=False, client=(client_ip or "127.0.0.1", 0))
        try:
            async with httpx.AsyncClient(transport=transport, base_url=f"http://{INTERNAL_HOST}", timeout=self.timeout_s) as c:
                resp = await c.request(method, self.base_path + path, params=dict(query or {}), json=json, headers=_headers(bearer))
        except httpx.TimeoutException as e:
            raise BackendTimeout(type(e).__name__) from e
        except (httpx.TransportError, OSError) as e:
            raise BackendUnreachable(type(e).__name__) from e
        return _parse(resp)
