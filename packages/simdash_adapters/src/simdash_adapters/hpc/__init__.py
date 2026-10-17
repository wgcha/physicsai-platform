"""HPC(PBS·SCX) 작업 게이트웨이."""

from .adapter import AdapterHpcGateway
from .command import CommandHpcGateway, render_argv, validate_command_config
from .config import CommandConfig, HpcDefaults
from .factory import make_gateway
from .none import NoneHpcGateway
from .scx import ScxConfig, ScxHpcGateway, ScxRadiossRequest, ScxSubmitOutcome, read_secret_file, validate_scx_config
from .scx_client import ScxRelayClient, parse_relay_url
from .types import HpcAvailability, HpcGatewayError, HpcJobGateway, HpcState, HpcStatus, HpcSubmitResult, HpcSubmitSpec

__all__ = [
    "HpcState", "HpcAvailability", "HpcSubmitSpec", "HpcSubmitResult", "HpcStatus", "HpcGatewayError", "HpcJobGateway",
    "CommandConfig", "HpcDefaults", "validate_command_config", "render_argv", "CommandHpcGateway",
    "NoneHpcGateway", "AdapterHpcGateway", "make_gateway",
    # scx(phase3 §16) — 패키지 최상위 공개 API(`simdash_adapters.__all__`)는 바꾸지 않고 하위 패키지에서만 노출
    "ScxConfig", "ScxHpcGateway", "ScxRadiossRequest", "ScxSubmitOutcome", "read_secret_file", "validate_scx_config",
    "ScxRelayClient", "parse_relay_url",
]
