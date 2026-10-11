"""사내 어댑터 자리(§12.1) 호환층(정의: `simdash_adapters.hpc.adapter`). 어댑터 패키지를 import하지 않는다.

예전 모듈 공개 이름(값 형식·`_MSG` 포함)을 그대로 재노출한다.
"""

from simdash_adapters.hpc.adapter import _MSG, AdapterHpcGateway  # noqa: F401
from simdash_adapters.hpc.types import HpcAvailability, HpcGatewayError, HpcStatus, HpcSubmitResult, HpcSubmitSpec  # noqa: F401
