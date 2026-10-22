"""조합 행·결과 모양과 공용 도우미(문제 코드·run 이름·배치 폴더 이름·반영값 행) — matrix에서 재노출."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..stage4_predict import nearest

PROBLEM_CODES = (
    "TABLE_HEADER", "TABLE_VALUE", "TEXT_TOO_LARGE", "TOO_MANY_ROWS", "TOO_FEW_ROWS", "RANGE_INVALID", "DOE_PARAM_MISMATCH",
    "COUNT_NOT_POW2", "CONTINUE_INVALID", "SEQUENCE_MISMATCH", "LEVELS_INVALID", "DESIGN_UNSUPPORTED", "GENERATOR_UNAVAILABLE", "VAR_RANGE_INVALID",
    "TABLE_OUT_OF_RANGE",
)
NOTE_CODES = ("FIXED_EXCLUDED", "FULL_FACTORIAL_USED", "BBD_PAIRWISE", "DUPLICATE_ROWS", "SEQUENCE_CONTINUED", "INFLUENCE_TOO_FEW")
NEW_KINDS = ("lhs_opt", "sobol", "fullfact", "fracfact", "pb", "bbd", "ccd")
MAX_PROBLEMS = 100  # 행 오류는 이 개수까지만 모은다(화면 회색 줄)
DOE_COLUMN = "doe"  # 표의 선택 열(무시)
RUN_KEY_RE = re.compile(r"run__([0-9]+)")  # fullmatch 전용, ASCII 숫자만(D3-53)


class BatchShapeError(ValueError):
    """source 모양 오류(kind·필드 형식). API는 422 INVALID_PARAMS로 바꾼다."""


@dataclass(frozen=True)
class BatchRow:
    """조합 1행 — predict_batch_runs 행·미리보기 행과 같은 모양."""

    doe_no: int
    run_key: str
    values: dict[str, float]
    applied_values: dict[str, float]
    out_of_range: list[str]

    def as_dict(self) -> dict[str, Any]:
        """미리보기 응답·batch.json 행."""
        return {"doe_no": self.doe_no, "run_key": self.run_key, "values": dict(self.values),
                "applied_values": dict(self.applied_values), "out_of_range": list(self.out_of_range)}


@dataclass
class BatchMatrix:
    """조합 계산 결과. problems가 있으면 작업 생성은 422 BATCH_SOURCE_INVALID."""

    source_kind: str  # LHS | LHS_OPT | SOBOL | HALTON | RANDOM | FULLFACT | FRACFACT | PB | BBD | CCD | TABLE | TRAIN_DOE
    rows: list[BatchRow] = field(default_factory=list)
    problems: list[dict[str, Any]] = field(default_factory=list)
    source_meta: dict[str, Any] = field(default_factory=dict)
    notes: list[dict[str, str]] = field(default_factory=list)  # 막지 않는 안내({code, message}, §20.9)

    @property
    def ok(self) -> bool:
        """문제 없음 + 행 1개 이상."""
        return not self.problems and bool(self.rows)


def run_key_for(doe_no: int) -> str:
    """doe_no → run 폴더 이름 `run__00001`(① hstbatch와 같은 5자리)."""
    return f"run__{int(doe_no):05d}"


def doe_no_of(run_key: str) -> int | None:
    """`run__00014` → 14. 형식이 다르면 None."""
    m = RUN_KEY_RE.fullmatch(run_key) if isinstance(run_key, str) else None
    return int(m.group(1)) if m and int(m.group(1)) >= 1 else None


def batch_label(batch_no: int) -> str:
    """batch_no → 표시·폴더 이름 `B-003`."""
    return f"B-{int(batch_no):03d}"


def batch_dir_rel(dir_name: str, batch_no: int) -> str:
    """Study 기준 배치 폴더 `04_batch/B-003`(predict_batch.dir_name)."""
    return f"{dir_name}/{batch_label(batch_no)}"


def input_rel_for(run_key: str, input_kind: str, simlab_mesh_name: str) -> str:
    """배치 폴더 기준 하위 예측 입력: assembly `run__N/m_3`, mesh_only `run__N/m_1/<simlab_mesh_name>`."""
    return f"{run_key}/m_3" if input_kind == "assembly" else f"{run_key}/m_1/{simlab_mesh_name}"


def _problem(out: list[dict[str, Any]], code: str, message: str, row: int | None = None) -> None:
    if len(out) >= MAX_PROBLEMS:
        return
    p: dict[str, Any] = {"code": code, "message": message}
    if row is not None:
        p["row"] = row
    out.append(p)


def _finite(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, str):
        try:
            f = float(v.strip())
        except ValueError:
            return None
    else:
        return None
    return f if math.isfinite(f) else None


def _make_row(doe_no: int, run_key: str, values: dict[str, float], parameters: Sequence[Mapping[str, Any]],
              tpl_params: Sequence[Mapping[str, Any]], rounding: str,
              oor_parameters: Sequence[Mapping[str, Any]] | None = None) -> BatchRow:
    """oor_parameters: `out_of_range` 판정 기준 `[{name, min, max}]`(None = 세트 범위, Native 일괄은 학습 범위 — native-vars.md §5.3)."""
    applied = nearest.applied_values(list(tpl_params), values, rounding)  # type: ignore[arg-type]
    basis = parameters if oor_parameters is None else oor_parameters
    oor = [o["name"] for o in nearest.out_of_range(list(basis), values)]  # type: ignore[arg-type]
    return BatchRow(doe_no, run_key, dict(values), applied, oor)
