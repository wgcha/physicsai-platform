"""step 핸들러 등록부: (job_type, step_key) → handler(ctx). 단계별 패키지(stageN_*, Study 관리 stage0_manage)의 HANDLERS를 합친다."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import analysis, asm_match, stage0_manage, stage1_train_data, stage2_curation, stage3_model, stage4_predict, stage5_optimize

HANDLERS: dict[tuple[str, str], Callable[[Any], None]] = {}
for _mod in (stage3_model, stage4_predict, stage1_train_data, stage2_curation, stage5_optimize, stage0_manage, analysis, asm_match):
    HANDLERS.update(_mod.HANDLERS)
