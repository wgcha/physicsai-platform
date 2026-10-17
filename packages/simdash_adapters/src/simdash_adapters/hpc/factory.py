"""게이트웨이 팩터리: 모드 문자열 → 인스턴스. 알 수 없는 모드는 none(플랫폼 현행 규칙)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from .types import HpcJobGateway


def make_gateway(mode: str, command: Any = None, defaults: Any = None,
                 env_factory: Callable[[], Mapping[str, str]] | None = None,
                 logger: logging.Logger | None = None, *, scx: Any = None, scx_secret_path: str | None = None,
                 on_secret: Callable[[str], None] | None = None) -> HpcJobGateway:
    if mode == "command":
        from .command import CommandHpcGateway

        if command is None or defaults is None:
            raise ValueError("command 모드에는 command·defaults 설정이 필요합니다")
        return CommandHpcGateway(command, defaults, env_factory=env_factory, logger=logger)
    if mode == "adapter":
        from .adapter import AdapterHpcGateway

        return AdapterHpcGateway()
    if mode == "scx":
        from .scx import ScxHpcGateway

        if scx is None:
            raise ValueError("scx 모드에는 scx 설정이 필요합니다")
        return ScxHpcGateway(scx, scx_secret_path, logger=logger, on_secret=on_secret)
    from .none import NoneHpcGateway

    return NoneHpcGateway()
