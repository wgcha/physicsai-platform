"""④ 일괄 예측 하위 입력 검사(altair·native 공용, geometry-engine.md GE-C14).

하위 PREDICT(prepared)가 PR_PREP에서 다시 하는 검사(`prepared_input.check_path`·`plan_copy`)를 생성 단계에서 먼저 해서
실패를 생성 실패로 남긴다. batch.py(altair)·batch_native.py(native)가 같은 함수를 쓴다.
"""

from __future__ import annotations

from typing import Any

from physicsai_core.errors import StepFailure
from physicsai_core.paths import PathError
from physicsai_core.stage4_predict import prepared_input


def check_child_input(settings: Any, input_path: str) -> None:
    """하위 PREDICT(prepared)가 PR_PREP에서 다시 하는 검사를 먼저(실패면 생성 실패로)."""
    try:
        cp = prepared_input.check_path(input_path, settings)
    except PathError as exc:
        raise StepFailure("INPUT_INVALID", f"생성된 입력을 예측 입력으로 쓸 수 없습니다: {exc.message}") from None
    plan = prepared_input.plan_copy(cp.path, settings)
    if plan.problems:
        p0 = plan.problems[0]
        raise StepFailure(p0["code"] if p0["code"] == "STARTER_COUNT" else "INPUT_INVALID", p0["message"])
