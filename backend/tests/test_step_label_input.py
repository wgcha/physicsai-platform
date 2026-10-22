"""step_label의 입력 종류별 덮어쓰기(input-kind.md §4.1): 쿠션이면 RAD_ASSEMBLE = "쿠션 입력 복사", 그 밖은 기존과 같다."""

from __future__ import annotations

from physicsai_core.job_types import STEP_LABELS, step_label


def test_step_label_cushion_overrides_only_rad_assemble():
    assert step_label("RAD_ASSEMBLE") == STEP_LABELS["RAD_ASSEMBLE"] == "입력 조립"
    assert step_label("RAD_ASSEMBLE", None, "assembly") == "입력 조립"
    for engine in (None, "altair", "native"):
        assert step_label("RAD_ASSEMBLE", engine, "cushion") == "쿠션 입력 복사"
        assert step_label("EDSPY_PREDICT", engine, "cushion") == "예측 실행"
    assert step_label("MESH", "native", "cushion") == "메시 모핑·검사" and step_label("MESH", "altair", "cushion") == "메싱"
    assert step_label(None, "native", "cushion") is None
