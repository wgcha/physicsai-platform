"""④ 일괄 예측 입력 생성 PREDICT_BATCH(phase3 §14.5 S9) — step 자리표시.

P0(스키마·job_type 등록)에서는 등록부 일치만 맞춘다. 실제 처리(BP_PREP·BP_GEN `run_parallel`·BP_ENQUEUE)는 Impl-Worker P1이
이 파일을 채운다. API가 아직 PREDICT_BATCH 생성을 받지 않으므로 실행될 일은 없다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from physicsai_core.errors import StepFailure

_NOT_READY = "일괄 예측 입력 생성은 아직 이 워커에서 지원하지 않습니다(플랫폼 업데이트 필요)"


def _not_implemented(ctx: Any) -> None:
    """P1 구현 전 자리표시: 항상 INTERNAL_ERROR."""
    raise StepFailure("INTERNAL_ERROR", _NOT_READY)


HANDLERS: dict[tuple[str, str], Callable[[Any], None]] = {
    ("PREDICT_BATCH", "BP_PREP"): _not_implemented,
    ("PREDICT_BATCH", "BP_GEN"): _not_implemented,
    ("PREDICT_BATCH", "BP_ENQUEUE"): _not_implemented,
}
