"""stdio 실행기 `physicsai-mcp`(mcp.md §20.1·§20.4): 클라이언트가 띄우는 MCP 서버. 모든 도구 호출은 같은 Bearer로 백엔드 HTTP API를 부른다.

환경변수: `PHYSICSAI_MCP_URL`(필수, 예 http://host/physicsai), `PHYSICSAI_MCP_TOKEN` 또는 `PHYSICSAI_MCP_TOKEN_FILE`(둘 다면 TOKEN 우선),
`PHYSICSAI_MCP_CA_BUNDLE`, `PHYSICSAI_MCP_TIMEOUT_S`(기본 60).
시작 실패(설정 누락·서버 거부·연결 실패)는 표준오류에 한국어 원인(토큰 값 없음) + 종료 코드 2. 표준출력은 MCP 프로토콜 전용이다.
옵션: `--version`(설치 확인), `--check`(ping 1회 후 종료).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import anyio

from . import package_version, sdk_package_version
from .backend_client import BackendResponse, BackendTimeout, BackendUnreachable, HttpBackendClient
from .toolset import CallCtx, Toolset, ToolService, build_server

ENV_URL = "PHYSICSAI_MCP_URL"
ENV_TOKEN = "PHYSICSAI_MCP_TOKEN"
ENV_TOKEN_FILE = "PHYSICSAI_MCP_TOKEN_FILE"
ENV_CA = "PHYSICSAI_MCP_CA_BUNDLE"
ENV_TIMEOUT = "PHYSICSAI_MCP_TIMEOUT_S"
DEFAULT_TIMEOUT_S = 60.0
EXIT_START_FAILED = 2

log = logging.getLogger("physicsai_mcp")


class StartupError(Exception):
    """시작 실패 — 메시지는 사용자에게 보이는 한국어 원인(토큰 값 없음)."""


@dataclass(frozen=True)
class StdioConfig:
    url: str
    token: str
    timeout_s: float
    ca_bundle: str | None


def _read_token(env: Mapping[str, str]) -> str:
    direct = (env.get(ENV_TOKEN) or "").strip()
    if direct:
        return direct
    path = (env.get(ENV_TOKEN_FILE) or "").strip()
    if not path:
        raise StartupError(f"토큰이 없습니다 — {ENV_TOKEN_FILE}(토큰 파일 경로, 권장) 또는 {ENV_TOKEN}을 설정하세요")
    try:
        text = Path(path).expanduser().read_text(encoding="utf-8")
    except OSError as e:
        raise StartupError(f"토큰 파일을 읽을 수 없습니다({ENV_TOKEN_FILE}): {type(e).__name__}") from e
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    raise StartupError(f"토큰 파일이 비어 있습니다({ENV_TOKEN_FILE})")


def load_config(env: Mapping[str, str]) -> StdioConfig:
    url = (env.get(ENV_URL) or "").strip().rstrip("/")
    if not url:
        raise StartupError(f"서버 주소가 없습니다 — {ENV_URL}(예: http://<대시보드 주소>/physicsai)을 설정하세요")
    if not url.startswith(("http://", "https://")):
        raise StartupError(f"{ENV_URL}은 http:// 또는 https://로 시작해야 합니다")
    token = _read_token(env)
    if not token.startswith("pai_"):
        raise StartupError("토큰이 pai_로 시작하지 않습니다 — 웹 화면의 '내 API 토큰'에서 발급한 값을 쓰세요")
    raw_t = (env.get(ENV_TIMEOUT) or "").strip()
    try:
        timeout_s = float(raw_t) if raw_t else DEFAULT_TIMEOUT_S
    except ValueError as e:
        raise StartupError(f"{ENV_TIMEOUT}은 숫자(초)여야 합니다") from e
    if not 1 <= timeout_s <= 3600:
        raise StartupError(f"{ENV_TIMEOUT}은 1~3600초여야 합니다")
    return StdioConfig(url=url, token=token, timeout_s=timeout_s, ca_bundle=(env.get(ENV_CA) or "").strip() or None)


def _explain(resp: BackendResponse, what: str) -> StartupError:
    detail = resp.body.get("detail") if isinstance(resp.body, dict) else None
    code = detail.get("code") if isinstance(detail, dict) else None
    suffix = f" [{code}]" if code else ""
    if resp.status == 401:
        return StartupError(f"서버가 토큰을 거부했습니다{suffix} — 만료·폐기되었으면 웹에서 새 토큰을 발급하세요")
    if resp.status == 404:
        return StartupError(f"{what} 경로가 없습니다{suffix} — 관리자가 MCP를 껐거나 {ENV_URL}이 틀렸습니다")
    return StartupError(f"{what} 실패(HTTP {resp.status}){suffix}")


async def _get(client: HttpBackendClient, path: str, token: str, what: str, query: Mapping[str, str] | None = None) -> BackendResponse:
    try:
        return await client.request("GET", path, query=query, bearer=token)
    except BackendTimeout as e:
        raise StartupError(f"{what}: 서버 응답 시간이 초과되었습니다({ENV_URL}·사내망 확인)") from e
    except BackendUnreachable as e:
        raise StartupError(f"{what}: 서버에 접속할 수 없습니다({ENV_URL}·사내망·인증서 확인)") from e


async def load_toolset(cfg: StdioConfig, client: HttpBackendClient) -> Toolset:
    """시작 때 도구 스펙 1회 로드(+ 오류 힌트, 실패해도 계속)."""
    resp = await _get(client, "/api/mcp/tools", cfg.token, "도구 목록 로드", {"format": "mcp", "visible": "true"})
    if resp.status != 200 or not isinstance(resp.body, dict):
        raise _explain(resp, "도구 목록 로드")
    hints: dict[str, str] = {}
    try:
        h = await client.request("GET", "/api/mcp/glossary", query={"section": "error_hints"}, bearer=cfg.token)
        if h.status == 200 and isinstance(h.body, dict) and isinstance(h.body.get("error_hints"), dict):
            hints = {str(k): str(v) for k, v in h.body["error_hints"].items()}
    except (BackendTimeout, BackendUnreachable):
        log.warning("오류 힌트를 불러오지 못했습니다(도구는 정상 동작)")
    return Toolset(resp.body, client, hints=hints, call_timeout_s=cfg.timeout_s)


async def check(cfg: StdioConfig, client: HttpBackendClient) -> dict[str, Any]:
    resp = await _get(client, "/api/mcp/ping", cfg.token, "연결 점검")
    if resp.status != 200 or not isinstance(resp.body, dict):
        raise _explain(resp, "연결 점검")
    return resp.body


async def _run(cfg: StdioConfig, do_check: bool) -> int:
    from . import sdk_adapter

    client = HttpBackendClient(cfg.url, timeout_s=cfg.timeout_s, ca_bundle=cfg.ca_bundle)
    try:
        if do_check:
            print(json.dumps(await check(cfg, client), ensure_ascii=False, default=str, indent=2))
            return 0
        toolset = await load_toolset(cfg, client)
    except StartupError as e:
        print(f"physicsai-mcp: {e}", file=sys.stderr)
        return EXIT_START_FAILED
    server = build_server(ToolService(lambda _ctx: toolset), version=package_version(),
                          static_ctx=CallCtx(bearer=cfg.token, scope=None, transport="stdio"))
    await sdk_adapter.run_stdio(server)
    return 0


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="physicsai-mcp", description="PhysicsAI MCP stdio 실행기(환경변수는 모듈 설명 참고)")
    parser.add_argument("--version", action="store_true", help="버전 출력 후 종료")
    parser.add_argument("--check", action="store_true", help="서버에 ping 1회 후 종료(연결·토큰 확인)")
    args = parser.parse_args(argv)
    if args.version:
        print(f"physicsai-mcp {package_version()} (mcp {sdk_package_version()})")
        return 0
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 요청 줄에 경로·쿼리 값이 들어간다(인자 값 로그 금지)
    try:
        cfg = load_config(os.environ if env is None else env)
    except StartupError as e:
        print(f"physicsai-mcp: {e}", file=sys.stderr)
        return EXIT_START_FAILED
    try:
        return anyio.run(_run, cfg, bool(args.check))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
