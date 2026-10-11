"""command 모드 HPC 게이트웨이(§12.3) 호환층. 정의는 `simdash_adapters.hpc.command`(phase3.md §6.4).

기존 시그니처 유지: `CommandHpcGateway(hpc, env_factory=None)`, `validate_command_config(hpc)` — `hpc`는 설정 `hpc` 절.
"""

from __future__ import annotations

import logging
from typing import Any

from simdash_adapters.hpc import command as _pkg
from simdash_adapters.hpc.command import (  # noqa: F401 (재노출)
    FORBIDDEN_EXT,
    JOB_NAME_RE,
    PATH_RE,
    PLACEHOLDERS,
    QUEUE_RE,
    VALID_STATES,
    WALLTIME_RE,
)
from simdash_adapters.hpc.config import CommandConfig, HpcDefaults
from simdash_adapters.transfer.paths import map_path  # noqa: F401 (재노출)

from .gateway import COMMAND_LOGGER

log = logging.getLogger(COMMAND_LOGGER)


def validate_command_config(hpc: Any) -> list[str]:
    return _pkg.validate_command_config(CommandConfig.from_obj(hpc.command))


class CommandHpcGateway(_pkg.CommandHpcGateway):
    def __init__(self, hpc: Any, env_factory: Any = None) -> None:
        self.hpc = hpc
        super().__init__(CommandConfig.from_obj(hpc.command), HpcDefaults.from_obj(hpc.defaults),
                         env_factory=env_factory, logger=log)
