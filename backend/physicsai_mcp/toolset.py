"""도구 집합(mcp.md §20.1·§20.3): 생성 스펙(`tools.mcp.json`)의 `x-http`로 도구 호출을 백엔드 HTTP 요청으로 바꾸고, 응답을 도구 결과로 되돌린다.

두 전송(HTTP 마운트·stdio) 공용. **권한 판단 없음** — 범위·허용 목록·역할·confirm·호출 제한·감사는 전부 백엔드가 하고, 여기서는 인자 모양(이름·필수·JSON 문자열)만
확인한다. 로그에는 도구 이름·상태·소요 시간만 남긴다(인자 값·결과 본문·Authorization 없음).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import quote

import anyio

from . import resources, sdk_adapter
from .backend_client import BackendClient, BackendTimeout, BackendUnreachable

log = logging.getLogger("physicsai_mcp")

DEFAULT_MAX_RESULT_BYTES = 65536
DEFAULT_CALL_TIMEOUT_S = 60.0
MAX_JSON_ARG_BYTES = 65536  # `*_json` 문자열 인자 상한(스키마 설명의 "64 KiB 이하")
BODY_METHODS = ("POST", "PUT", "PATCH")


@dataclass(frozen=True)
class CallCtx:
    """한 호출의 요청자 정보. `bearer`는 백엔드로 그대로 전달할 토큰(보관·로그하지 않는다), `scope`는 `tools/list` 표시 필터용."""

    bearer: str | None
    client_ip: str | None = None
    scope: str | None = None
    transport: str = "http"


@dataclass(frozen=True)
class ToolOutcome:
    is_error: bool
    data: Any
    status: int | None = None

    @property
    def text(self) -> str:
        return json.dumps(self.data, ensure_ascii=False)


@dataclass(frozen=True)
class ResourceOutcome:
    ok: bool
    text: str = ""
    mime: str = resources.MIME
    code: int | None = None
    message: str = ""


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]
    risk: str
    confirm: str
    version: int
    deprecated: bool
    method: str
    path: str
    args: dict[str, str]
    json_fields: dict[str, str]

    @property
    def required(self) -> list[str]:
        return list(self.input_schema.get("required") or [])

    def as_listing(self) -> dict[str, Any]:
        """SDK 중립 도구 항목(생성 파일 값 그대로 — 이름·설명·입력 스키마)."""
        return {"name": self.name, "description": self.description, "inputSchema": self.input_schema,
                "readOnlyHint": self.risk == "read", "destructiveHint": self.risk != "read",
                "meta": {"x-risk": self.risk, "x-confirm": self.confirm, "x-version": self.version, "x-deprecated": self.deprecated}}


def parse_tools(doc: Mapping[str, Any]) -> dict[str, ToolDef]:
    out: dict[str, ToolDef] = {}
    for t in doc.get("tools") or []:
        ann = t.get("annotations") or {}
        xh = t.get("x-http") or {}
        out[t["name"]] = ToolDef(
            name=t["name"], description=t.get("description") or "", input_schema=dict(t.get("inputSchema") or {"type": "object", "properties": {}}),
            risk=str(ann.get("x-risk") or "read"), confirm=str(ann.get("x-confirm") or "never"), version=int(ann.get("x-version") or 1),
            deprecated=bool(ann.get("x-deprecated")), method=str(xh.get("method") or "GET").upper(), path=str(xh.get("path") or ""),
            args=dict(xh.get("args") or {}), json_fields=dict(xh.get("json_string_fields") or {}))
    return out


def _error(status: int | None, code: str, message: str, hint: str | None = None, **extra: Any) -> ToolOutcome:
    data: dict[str, Any] = {"status": status, "code": code, "message": message}
    if hint:
        data["hint"] = hint
    data.update({k: v for k, v in extra.items() if v is not None})
    return ToolOutcome(True, data, status)


def _scalar(v: Any) -> str | None:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float, str)):
        return str(v)
    return None


class Toolset:
    """생성 스펙 문서 하나 + 위임 클라이언트. `visible`(문서의 최상위 키)이 있으면 `tools/list`는 그 이름만 보인다(호출은 모든 도구가 가능 — 거부는 백엔드)."""

    def __init__(self, doc: Mapping[str, Any], client: BackendClient, *, hints: Mapping[str, str] | None = None,
                 call_timeout_s: float = DEFAULT_CALL_TIMEOUT_S, max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES) -> None:
        self.tools = parse_tools(doc)
        visible = doc.get("visible")
        self.visible: set[str] | None = set(visible) if isinstance(visible, list) else None
        self.client = client
        self.hints = dict(hints or {})
        self.call_timeout_s = call_timeout_s
        self.max_result_bytes = max_result_bytes

    # ---- 도구 목록 -----------------------------------------------------------------------------------

    def list_tools(self) -> list[dict[str, Any]]:
        return [t.as_listing() for n, t in sorted(self.tools.items()) if self.visible is None or n in self.visible]

    # ---- 도구 호출 -----------------------------------------------------------------------------------

    def _build(self, tool: ToolDef, arguments: Mapping[str, Any]) -> tuple[str, dict[str, str], Any] | ToolOutcome:
        unknown = sorted(set(arguments) - set(tool.args))
        if unknown:
            return _error(None, "INVALID_ARGUMENTS", f"알 수 없는 인자: {', '.join(unknown)}", f"허용 인자: {', '.join(sorted(tool.args)) or '(없음)'}")
        missing = [r for r in tool.required if arguments.get(r) is None]
        if missing:
            return _error(None, "INVALID_ARGUMENTS", f"필수 인자 누락: {', '.join(missing)}")
        path = tool.path
        query: dict[str, str] = {}
        body: dict[str, Any] = {}
        for name, where in tool.args.items():
            v = arguments.get(name)
            if v is None:
                continue
            if where == "path":
                s = _scalar(v)
                if s is None:
                    return _error(None, "INVALID_ARGUMENTS", f"인자 {name}은 문자열·숫자여야 합니다")
                path = path.replace("{" + name + "}", quote(s, safe=""))
            elif where == "query":
                s = _scalar(v)
                if s is None:
                    return _error(None, "INVALID_ARGUMENTS", f"인자 {name}은 문자열·숫자·불리언이어야 합니다")
                query[name] = s
            elif name in tool.json_fields:
                if not isinstance(v, str):
                    return _error(None, "PARAMS_JSON_INVALID", f"인자 {name}은 JSON 객체 텍스트(문자열)여야 합니다")
                if len(v.encode("utf-8")) > MAX_JSON_ARG_BYTES:
                    return _error(None, "PARAMS_JSON_INVALID", f"인자 {name}이 64 KiB를 넘습니다")
                try:
                    parsed = json.loads(v)
                except ValueError:
                    return _error(None, "PARAMS_JSON_INVALID", f"인자 {name}이 올바른 JSON이 아닙니다")
                if not isinstance(parsed, dict):
                    return _error(None, "PARAMS_JSON_INVALID", f"인자 {name}은 JSON 객체여야 합니다")
                body[tool.json_fields[name]] = parsed
            else:
                body[name] = v
        if "{" in path:
            return _error(None, "INVALID_ARGUMENTS", "경로 인자가 모두 채워지지 않았습니다")
        has_body = tool.method in BODY_METHODS and any(w == "body" for w in tool.args.values())
        return path, query, (body if has_body else None)

    def _http_error(self, status: int, body: Any, headers: Mapping[str, str]) -> ToolOutcome:
        detail = body.get("detail") if isinstance(body, dict) else None
        code = message = None
        extra: dict[str, Any] = {}
        if isinstance(detail, dict):
            code, message = detail.get("code"), detail.get("message")
            errs = detail.get("errors")
            if isinstance(errs, list):
                extra["errors"] = errs[:20]
            for k in ("required", "token_prefix"):
                if detail.get(k) is not None:
                    extra[k] = detail[k]
        elif isinstance(detail, str):
            message = detail
        code = str(code) if code else f"HTTP_{status}"
        message = str(message) if message else "요청이 거부되었습니다"
        retry = None
        if status == 429:
            try:
                retry = int(headers.get("retry-after", ""))
            except ValueError:
                retry = None
        return _error(status, code, message, self.hints.get(code), retry_after_s=retry, **extra)

    async def call(self, ctx: CallCtx, name: str, arguments: Mapping[str, Any] | None) -> ToolOutcome:
        t0 = time.monotonic()
        outcome = await self._call(ctx, name, arguments or {})
        log.info("tool=%s status=%s error=%s ms=%d", name if name in self.tools else "?", outcome.status, outcome.is_error,
                 int((time.monotonic() - t0) * 1000))
        return outcome

    async def _call(self, ctx: CallCtx, name: str, arguments: Mapping[str, Any]) -> ToolOutcome:
        tool = self.tools.get(name)
        if tool is None:
            return _error(None, "UNKNOWN_TOOL", f"알 수 없는 도구입니다: {name[:64]}")
        built = self._build(tool, arguments)
        if isinstance(built, ToolOutcome):
            return built
        path, query, body = built
        try:
            with anyio.fail_after(self.call_timeout_s):
                resp = await self.client.request(tool.method, path, query=query, json=body, bearer=ctx.bearer, client_ip=ctx.client_ip)
        except (TimeoutError, BackendTimeout):
            return _error(None, "BACKEND_TIMEOUT", f"백엔드 응답이 {self.call_timeout_s:g}초 안에 오지 않았습니다")
        except BackendUnreachable:
            return _error(None, "SERVER_UNREACHABLE", "백엔드 서버에 연결할 수 없습니다", "PHYSICSAI_MCP_URL과 사내망 접속을 확인하세요")
        if resp.status >= 400 or resp.status < 200:
            return self._http_error(resp.status, resp.body, resp.headers)
        data = resp.body if resp.body is not None else {}
        out = ToolOutcome(False, data, resp.status)
        if len(out.text.encode("utf-8")) > self.max_result_bytes:
            return _error(None, "RESULT_TOO_LARGE", f"결과가 {self.max_result_bytes} 바이트를 넘습니다", "top_n·limit을 줄이세요")
        return out

    # ---- 리소스 --------------------------------------------------------------------------------------

    @staticmethod
    def list_resources() -> list[dict[str, str]]:
        return [{"uri": r.uri, "name": r.name, "description": r.description, "mime": resources.MIME} for r in resources.STATIC]

    @staticmethod
    def list_templates() -> list[dict[str, str]]:
        return [{"uri_template": r.uri_template, "name": r.name, "description": r.description, "mime": resources.MIME}
                for r in resources.TEMPLATES]

    async def read_resource(self, ctx: CallCtx, uri: str) -> ResourceOutcome:
        target = resources.resolve(uri)
        if target is None:
            return ResourceOutcome(False, code=sdk_adapter.RESOURCE_NOT_FOUND, message="알 수 없는 리소스입니다")
        path, query = target
        try:
            with anyio.fail_after(self.call_timeout_s):
                resp = await self.client.request("GET", path, query=query, bearer=ctx.bearer, client_ip=ctx.client_ip)
        except (TimeoutError, BackendTimeout):
            return ResourceOutcome(False, code=sdk_adapter.INTERNAL_ERROR, message="BACKEND_TIMEOUT")
        except BackendUnreachable:
            return ResourceOutcome(False, code=sdk_adapter.INTERNAL_ERROR, message="SERVER_UNREACHABLE")
        if resp.status >= 400:
            e = self._http_error(resp.status, resp.body, resp.headers).data
            return ResourceOutcome(False, code=sdk_adapter.INVALID_PARAMS if resp.status < 500 else sdk_adapter.INTERNAL_ERROR,
                                   message=f"{e.get('code')}: {e.get('message')}")
        text = json.dumps(resp.body, ensure_ascii=False)
        if len(text.encode("utf-8")) > self.max_result_bytes:
            return ResourceOutcome(False, code=sdk_adapter.INTERNAL_ERROR, message="RESULT_TOO_LARGE")
        return ResourceOutcome(True, text=text)


class ToolService:
    """SDK 서버에 등록되는 핸들러 묶음. `source(ctx)`가 호출자(스코프)에 맞는 `Toolset`을 준다(stdio는 고정 하나)."""

    def __init__(self, source: Callable[[CallCtx], Toolset]) -> None:
        self.source = source

    def list_tools(self, ctx: CallCtx) -> list[dict[str, Any]]:
        return self.source(ctx).list_tools()

    async def call_tool(self, ctx: CallCtx, name: str, arguments: Mapping[str, Any] | None) -> ToolOutcome:
        return await self.source(ctx).call(ctx, name, arguments)

    def list_resources(self, ctx: CallCtx) -> list[dict[str, str]]:
        return self.source(ctx).list_resources()

    def list_templates(self, ctx: CallCtx) -> list[dict[str, str]]:
        return self.source(ctx).list_templates()

    async def read_resource(self, ctx: CallCtx, uri: str) -> ResourceOutcome:
        return await self.source(ctx).read_resource(ctx, uri)


def build_server(service: ToolService, *, version: str, static_ctx: CallCtx | None = None, name: str = "physicsai",
                 instructions: str | None = None) -> Any:
    """SDK 저수준 `Server`에 `tools/list`·`tools/call`·`resources/*`를 등록해 돌려준다. `static_ctx`가 있으면(stdio) 모든 호출이 그 토큰을 쓴다."""
    return sdk_adapter.new_server(service, name=name, version=version, instructions=instructions, static_ctx=static_ctx, ctx_type=CallCtx)
