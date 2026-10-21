"""PhysicsAI MCP 서버(docs/contracts/mcp.md §20): 공식 MCP SDK 위의 얇은 래퍼.

권한 판단 없음 — 모든 도구 호출은 같은 Bearer로 백엔드 HTTP API를 부르고, 범위·허용 목록·역할·confirm·호출 제한·감사는 백엔드가 한다.
레이어(test_layering 규칙 8): 이 패키지는 physicsai_api·physicsai_core·physicsai_worker를 import하지 않는다(필요한 것은 주입).
SDK(`mcp`) import는 `sdk_adapter.py` 한 파일에만 둔다.
"""

from __future__ import annotations

from importlib import metadata


def package_version() -> str:
    """설치된 플랫폼 wheel 버전(없으면 `0+unknown`). 코어 `__version__`을 import하지 않으려고 메타데이터를 읽는다."""
    try:
        return metadata.version("physicsai-platform")
    except metadata.PackageNotFoundError:
        return "0+unknown"


def sdk_package_version() -> str:
    """설치된 `mcp` SDK 버전(SDK 모듈을 import하지 않고 메타데이터만 읽는다 — `--version`이 가볍게 끝나도록)."""
    try:
        return metadata.version("mcp")
    except metadata.PackageNotFoundError:
        return "not-installed"
