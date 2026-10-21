"""공식 MCP Python SDK(`mcp`) 접점 — SDK import는 이 파일에만 둔다(mcp.md §20.1·§18: SDK 버전 변화 흡수, `mcp==2.3.0` 고정).

- `new_server`: 저수준 `Server`에 도구·리소스 핸들러를 등록(도구는 생성 스펙에서 동적).
- `handle_http`: 요청 하나를 stateless + JSON 응답 Streamable HTTP로 처리(요청마다 세션 관리자를 새로 만들어 앱 수명주기와 무관).
- `run_stdio`: 표준입출력 전송.
핸들러는 SDK 중립 `ToolService`(toolset.py)에 위임한다 — 여기에는 권한·범위 판단이 없다.
"""

from __future__ import annotations

from typing import Any

import mcp_types as mt
from mcp.server.lowlevel.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import MCPError

INVALID_PARAMS: int = mt.INVALID_PARAMS
INTERNAL_ERROR: int = mt.INTERNAL_ERROR
RESOURCE_NOT_FOUND = -32002  # MCP 사양: resource not found

SCOPE_KEY = "physicsai.mcp"  # ASGI scope에 http_app이 심는 요청별 정보({bearer, scope, client_ip})


def sdk_version() -> str:
    from importlib import metadata

    return metadata.version("mcp")


def _ctx_of(rctx: Any, static_ctx: Any, ctx_type: Any) -> Any:
    if static_ctx is not None:
        return static_ctx
    req = getattr(rctx, "request", None)
    info = (getattr(req, "scope", None) or {}).get(SCOPE_KEY) or {}
    return ctx_type(bearer=info.get("bearer"), client_ip=info.get("client_ip"), scope=info.get("scope"), transport="http")


def new_server(service: Any, *, name: str, version: str, instructions: str | None, static_ctx: Any, ctx_type: Any) -> Server:
    async def on_list_tools(rctx: Any, params: Any) -> mt.ListToolsResult:
        tools = [
            mt.Tool(name=t["name"], description=t["description"], input_schema=t["inputSchema"],
                    annotations=mt.ToolAnnotations(read_only_hint=t["readOnlyHint"], destructive_hint=t["destructiveHint"]), meta=t["meta"])
            for t in service.list_tools(_ctx_of(rctx, static_ctx, ctx_type))
        ]
        return mt.ListToolsResult(tools=tools)

    async def on_call_tool(rctx: Any, params: mt.CallToolRequestParams) -> mt.CallToolResult:
        out = await service.call_tool(_ctx_of(rctx, static_ctx, ctx_type), params.name, params.arguments)
        return mt.CallToolResult(content=[mt.TextContent(text=out.text)], is_error=out.is_error,
                                 structured_content=out.data if isinstance(out.data, dict) else None)

    async def on_list_resources(rctx: Any, params: Any) -> mt.ListResourcesResult:
        items = service.list_resources(_ctx_of(rctx, static_ctx, ctx_type))
        return mt.ListResourcesResult(resources=[mt.Resource(name=r["name"], uri=r["uri"], description=r["description"], mime_type=r["mime"])
                                                 for r in items])

    async def on_list_templates(rctx: Any, params: Any) -> mt.ListResourceTemplatesResult:
        items = service.list_templates(_ctx_of(rctx, static_ctx, ctx_type))
        return mt.ListResourceTemplatesResult(resource_templates=[
            mt.ResourceTemplate(name=r["name"], uri_template=r["uri_template"], description=r["description"], mime_type=r["mime"]) for r in items])

    async def on_read_resource(rctx: Any, params: mt.ReadResourceRequestParams) -> mt.ReadResourceResult:
        out = await service.read_resource(_ctx_of(rctx, static_ctx, ctx_type), str(params.uri))
        if not out.ok:
            raise MCPError(out.code if out.code is not None else INTERNAL_ERROR, out.message)
        return mt.ReadResourceResult(contents=[mt.TextResourceContents(uri=str(params.uri), mime_type=out.mime, text=out.text)])

    return Server(name, version=version, instructions=instructions, on_list_tools=on_list_tools, on_call_tool=on_call_tool,
                  on_list_resources=on_list_resources, on_list_resource_templates=on_list_templates, on_read_resource=on_read_resource)


async def handle_http(server: Server, scope: Any, receive: Any, send: Any) -> None:
    """요청 하나를 stateless·JSON 응답으로 처리. 세션 관리자를 요청마다 만들고(`run()`은 인스턴스당 1회) 응답이 끝나면 닫는다."""
    manager = StreamableHTTPSessionManager(app=server, json_response=True, stateless=True)
    async with manager.run():
        await manager.handle_request(scope, receive, send)


async def run_stdio(server: Server) -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
