"""옛 경로 재노출(R-B): ④ 일괄 예측(DOE) 조합 계산은 공용 `physicsai_core.sampling.matrix`(+ matrix_rows·matrix_basic·
matrix_designs·matrix_sobol)로 옮겼다. 기존 import(`stage4_predict.batch_matrix.build_matrix` 등)는 그대로 쓴다.
"""

from __future__ import annotations

from ..sampling.matrix import (  # noqa: F401 - 기존 경로 재노출
    DOE_COLUMN,
    LEVEL_MAX,
    LEVEL_MIN,
    MAX_PROBLEMS,
    NEW_KINDS,
    NOTE_CODES,
    PROBLEM_CODES,
    RUN_KEY_RE,
    SEQUENCE_TOL,
    SOBOL_MAX_SEED,
    SOURCE_KINDS,
    BatchMatrix,
    BatchRow,
    BatchShapeError,
    batch_dir_rel,
    batch_label,
    build_matrix,
    build_matrix_for,
    doe_no_of,
    input_rel_for,
    lhs_values,
    run_key_for,
    samples_csv_text,
)
