"""HpcJobGateway 프로토콜과 팩터리(§12.2). API는 availability()만 호출한다.

정의는 `simdash_adapters.hpc`(phase3.md §6, R3-8). 이 모듈은 재노출 호환층이며 설정 읽기·자식 환경(`child_env`)은 플랫폼 몫이다.
"""

from __future__ import annotations

import logging
from typing import Any

from simdash_adapters.hpc.config import CommandConfig, HpcDefaults
from simdash_adapters.hpc.factory import make_gateway
from simdash_adapters.hpc.types import (  # noqa: F401 (재노출)
    HpcAvailability,
    HpcGatewayError,
    HpcJobGateway,
    HpcState,
    HpcStatus,
    HpcSubmitResult,
    HpcSubmitSpec,
)

COMMAND_LOGGER = "physicsai_core.hpc.command"  # 운영 로그 이름 불변
SCX_LOGGER = "physicsai_core.hpc.scx"


def scx_secret_path(settings: Any) -> str:
    """scx relay 비밀 파일 경로: `hpc.scx.secret_file` 또는 `<런타임>/secrets/scx_relay_key`(phase3 §16.8)."""
    from ..config.runtime import default_scx_secret_path

    return settings.hpc.scx.secret_file or default_scx_secret_path()


def get_hpc_gateway(settings: Any) -> HpcJobGateway:
    mode = settings.hpc.gateway
    if mode == "command":
        from ..childenv import child_env

        patterns = [*settings.worker.env_passthrough, "PBS_*"]
        deny = [settings.database.url_env]
        return make_gateway("command", CommandConfig.from_obj(settings.hpc.command), HpcDefaults.from_obj(settings.hpc.defaults),
                            env_factory=lambda: child_env(patterns, deny_names=deny), logger=logging.getLogger(COMMAND_LOGGER))
    if mode == "scx":
        from simdash_adapters.hpc.scx import ScxConfig

        from ..masking import register_secret_value

        return make_gateway("scx", scx=ScxConfig.from_obj(settings.hpc.scx), scx_secret_path=scx_secret_path(settings),
                            logger=logging.getLogger(SCX_LOGGER), on_secret=register_secret_value)
    return make_gateway(mode)
