"""표본 행 계산 공용 진입점(phase3 §23.4 S18): ④ 일괄 예측 `batch_matrix`(S15 build_matrix)를 ① 플랫폼 DOE도 쓴다.

단계 패키지는 다른 단계를 import하지 않는다(층 규칙 5) — ① `stage1_train_data.doe_platform`은 이 공용 모듈을 통해 쓴다.
구현은 `stage4_predict.batch_matrix` 한 곳(결정적·시험 완료 코드 재사용, 동작 동일).
"""

from __future__ import annotations

from ..stage4_predict.batch_matrix import BatchMatrix, BatchRow, BatchShapeError, build_matrix

__all__ = ["BatchMatrix", "BatchRow", "BatchShapeError", "build_matrix"]
