"""simdash_adapters — HPC(PBS) 게이트웨이와 회수 경로 해석 공통 어댑터(phase3.md §6).

표준 라이브러리만 쓴다. 공개 API는 `__all__`뿐이며 그 밖의 이름은 비공개다.
마스킹하지 않는다: 게이트웨이 오류 메시지·`raw_stdout`은 원문이므로 저장·로그 전에 호출자가 마스킹한다.
사용자 문구는 한국어(사내 전용).
"""

from .hpc import (
    AdapterHpcGateway,
    CommandConfig,
    CommandHpcGateway,
    HpcAvailability,
    HpcDefaults,
    HpcGatewayError,
    HpcJobGateway,
    HpcState,
    HpcStatus,
    HpcSubmitResult,
    HpcSubmitSpec,
    NoneHpcGateway,
    make_gateway,
    render_argv,
    validate_command_config,
)
from .pathstr import fwd, is_abs_path_str
from .transfer import PathMapEntry, TransferConfig, map_path, resolve_collect_dirs

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "HpcState", "HpcAvailability", "HpcSubmitSpec", "HpcSubmitResult", "HpcStatus", "HpcGatewayError", "HpcJobGateway",
    "CommandConfig", "HpcDefaults", "validate_command_config", "render_argv", "CommandHpcGateway",
    "NoneHpcGateway", "AdapterHpcGateway", "make_gateway",
    "PathMapEntry", "TransferConfig", "map_path", "resolve_collect_dirs",
    "fwd", "is_abs_path_str",
]
