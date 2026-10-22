"""표본 행 계산 공용 진입점(phase3 §23.4 S18): ④ 일괄 예측(DOE) 조합 계산(phase3 §14.5 S9) — 미리보기·작업 생성·워커와
① 플랫폼 DOE(`stage1_train_data.doe_platform`)가 같은 결과를 쓴다(순수 함수, I/O 없음). 옛 경로
`stage4_predict.batch_matrix`는 재노출만 한다(R-B). 행·결과 모양은 `matrix_rows`, lhs·표·① DOE는 `matrix_basic`,
S15 설계는 `matrix_designs`·`matrix_sobol`.

source.kind:
- `lhs`: `count`(2~max_runs)·`seed`(정수, 기본 1)·`ranges{name:[lo,hi]}`(생략 = 세트 min·max). `random.Random(seed)`로
  파라미터마다(세트 순서) ① 층 순열 `perm = shuffle(range(n))` ② run i마다 `u = random()` →
  값 = `lo + (perm[i] + u)/n·(hi−lo)`. 층마다 정확히 1개. 학습 범위 밖 허용(`out_of_range`).
- `table`: 붙여넣기·CSV 텍스트. 구분자 탭(첫 줄에 탭이 있으면)/쉼표 자동, BOM 허용, 첫 줄 헤더 = 파라미터 이름 전부(순서 무관,
  선택 열 `doe`는 무시), 데이터 행 1~max_runs, doe_no = 행 순서 1..
- `train_doe`: ① DOE `samples.csv` 행(`doe_samples.read_samples_csv` 결과). 파라미터 이름 집합 = 템플릿 이름 집합,
  doe_no = run 번호(`run__00014` → 14), run_key = ① run 이름 그대로.

S15(phase3 §20, D3-63) 새 kind 7개 — 순서·알고리즘은 `physicsai_core/sampling/`(결정적):
- `lhs_opt`(count·seed·ranges·criterion maximin|corr), `sobol`(count=2^m·seed·ranges·continue_from), `fullfact`(levels·ranges),
  `fracfact`(resolution 4|5·ranges), `pb`(ranges), `bbd`(ranges), `ccd`(alpha face|inscribed·ranges).
  고정 변수(세트 min = max)는 설계에서 빼고 고정값을 쓴다. 막지 않는 안내는 `BatchMatrix.notes`({code,message}).

반영값(`applied_values`) = `predict.integer_rounding`으로 tpl 정수 형식 파라미터만 반올림(`nearest.applied_values`).
문제는 예외 대신 `BatchMatrix.problems`({code,message,row?})로 모은다 — code ∈ PROBLEM_CODES.
모양 오류(kind 모름·필드 형식)는 `BatchShapeError`(API 422 INVALID_PARAMS).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from typing import Any

from ..stage4_predict import nearest
from .registry import SOURCE_KINDS  # API kind → DB source_kind (10개)
from .matrix_rows import (  # noqa: F401 - 기존 경로 재노출
    PROBLEM_CODES,
    NOTE_CODES,
    NEW_KINDS,
    MAX_PROBLEMS,
    DOE_COLUMN,
    RUN_KEY_RE,
    BatchShapeError,
    BatchRow,
    BatchMatrix,
    run_key_for,
    doe_no_of,
    batch_label,
    batch_dir_rel,
    input_rel_for,
    _make_row,
    _problem,
)
from .matrix_basic import lhs_values, _lhs, _table, _train_doe  # noqa: F401 - 기존 경로 재노출
from .matrix_designs import (  # noqa: F401 - 기존 경로 재노출
    _RawRows,
    LEVEL_MIN,
    LEVEL_MAX,
    _Design,
    _design_vars,
    _unsupported,
    _lhs_opt,
    _fullfact,
    _fracfact,
    _pb,
    _bbd,
    _ccd,
)
from .matrix_sobol import SOBOL_MAX_SEED, SEQUENCE_TOL, _sobol  # noqa: F401 - 기존 경로 재노출
from .matrix_more import HALTON_MAX_SEED, _halton, _random  # noqa: F401 - DM-C3 새 방식


def _new_kind(kind: str, source: Mapping[str, Any], parameters: Sequence[Mapping[str, Any]],
              tpl_params: Sequence[Mapping[str, Any]], max_runs: int, integer_rounding: str,
              problems: list[dict[str, Any]], continue_batch: Mapping[str, Any] | None, param_set_id: str | None
              ) -> tuple[_RawRows, dict[str, Any], list[dict[str, str]], _Design]:
    if kind == "sobol":
        return _sobol(source, parameters, max_runs, problems, continue_batch, param_set_id)
    dsn = _design_vars(source.get("ranges"), parameters, problems)
    if problems:
        return [], dsn.base_meta(), [], dsn
    if dsn.k == 0:
        _unsupported(problems, "범위가 있는 변수가 없습니다")
        return [], dsn.base_meta(), [], dsn
    if kind == "lhs_opt":
        raw, meta, notes = _lhs_opt(source, dsn, max_runs, problems)
    elif kind == "halton":
        raw, meta, notes = _halton(source, dsn, max_runs, problems)
    elif kind == "random":
        raw, meta, notes = _random(source, dsn, max_runs, problems)
    elif kind == "fullfact":
        raw, meta, notes = _fullfact(source, dsn, tpl_params, integer_rounding, max_runs, problems)
    elif kind == "fracfact":
        raw, meta, notes = _fracfact(source, dsn, max_runs, problems)
    elif kind == "pb":
        raw, meta, notes = _pb(dsn, max_runs, problems)
    elif kind == "bbd":
        raw, meta, notes = _bbd(dsn, max_runs, problems)
    else:
        raw, meta, notes = _ccd(source, dsn, max_runs, problems)
    return raw, meta, notes, dsn


def _all_notes(dsn: _Design, kind_notes: list[dict[str, str]], rows: Sequence[BatchRow], names: Sequence[str]
               ) -> list[dict[str, str]]:
    """안내 순서(§20.9): 고정 변수 제외 → 방식별 → 정수 반올림 중복 → 영향도 run 부족."""
    notes: list[dict[str, str]] = []
    if dsn.fixed:
        notes.append({"code": "FIXED_EXCLUDED", "message": f"고정 변수 {'·'.join(dsn.fixed)}는 설계에서 빼고 고정값을 씁니다"})
    notes.extend(kind_notes)
    if rows:
        dups = len(rows) - len({tuple(r.applied_values[n] for n in names) for r in rows})
        if dups:
            notes.append({"code": "DUPLICATE_ROWS", "message": f"정수 반올림 뒤 같은 조합이 {dups}개 있습니다 — 같은 예측이 반복됩니다"})
        need = max(5, len(names) + 2)
        if len(rows) < need:
            notes.append({"code": "INFLUENCE_TOO_FEW", "message": f"run이 {need}개보다 적어 ⑤ 영향도는 계산되지 않습니다"})
    return notes


# ---- 공용 진입점 -----------------------------------------------------------------------------------


def build_matrix(
    source: Mapping[str, Any],
    *,
    parameters: Sequence[Mapping[str, Any]],
    tpl_params: Sequence[Mapping[str, Any]],
    max_runs: int,
    table_max_bytes: int,
    integer_rounding: str = "half_up",
    samples_header: Sequence[str] | None = None,
    samples: Sequence[Mapping[str, Any]] | None = None,
    continue_batch: Mapping[str, Any] | None = None,
    param_set_id: str | None = None,
    oor_parameters: Sequence[Mapping[str, Any]] | None = None,
) -> BatchMatrix:
    """템플릿(param_sets.parameters·tpl_params) + source → 조합 행(doe_no 순). train_doe는 samples(header, rows)를 넘긴다.

    sobol 이어서 추가(`continue_from`)는 호출부가 이전 배치를 읽어 `continue_batch`로 넘긴다:
    `{id, label, source_kind, param_set_id, source_meta, runs:[{doe_no, values}]}`(없거나 다른 Study면 `{"missing": True}`).
    """
    if not isinstance(source, Mapping):
        raise BatchShapeError("source는 객체여야 합니다")
    kind = source.get("kind")
    if kind not in SOURCE_KINDS:
        raise BatchShapeError("source.kind는 " + " | ".join(SOURCE_KINDS) + " 중 하나입니다")
    names = [str(p["name"]) for p in parameters]
    problems: list[dict[str, Any]] = []
    notes: list[dict[str, str]] = []
    dsn: _Design | None = None
    if kind == "lhs":
        raw, meta = _lhs(source, parameters, max_runs, problems)
    elif kind == "table":
        raw, meta = _table(source, names, max_runs, table_max_bytes, problems)
    elif kind == "train_doe":
        raw, meta = _train_doe(source, names, samples_header, samples, max_runs, problems)
    else:
        raw, meta, notes, dsn = _new_kind(kind, source, parameters, tpl_params, max_runs, integer_rounding, problems,
                                          continue_batch, param_set_id)
    ranges = source.get("ranges")
    if isinstance(ranges, Mapping):  # altair-vars.md §5.1: 정수(%i) 파라미터의 비정수 범위 — PUT variables·⑥과 같은 공용 검사
        for n in nearest.integer_range_violations(ranges, list(tpl_params)):
            _problem(problems, nearest.INT_RANGE_CODE, f"'{n}' {nearest.INT_RANGE_MESSAGE}")
    rows = [_make_row(no, rk, v, parameters, tpl_params, integer_rounding, oor_parameters) for no, rk, v in raw]
    if dsn is not None:
        notes = _all_notes(dsn, notes, rows, names)
    return BatchMatrix(SOURCE_KINDS[kind], rows, problems, meta, notes)


def build_matrix_for(source: Mapping[str, Any], param_set: Mapping[str, Any], settings: Any, *,
                     samples_header: Sequence[str] | None = None,
                     samples: Sequence[Mapping[str, Any]] | None = None,
                     continue_batch: Mapping[str, Any] | None = None,
                     oor_parameters: Sequence[Mapping[str, Any]] | None = None) -> BatchMatrix:
    """param_sets 행 + 설정(predict_batch·predict.integer_rounding)으로 build_matrix(미리보기·작업 생성·워커 공용)."""
    return build_matrix(
        source, parameters=param_set["parameters"], tpl_params=param_set.get("tpl_params") or [],
        max_runs=settings.predict_batch.max_runs, table_max_bytes=settings.predict_batch.table_max_bytes,
        integer_rounding=settings.predict.integer_rounding, samples_header=samples_header, samples=samples,
        continue_batch=continue_batch, param_set_id=param_set.get("id"), oor_parameters=oor_parameters,
    )


def samples_csv_text(names: Sequence[str], rows: Sequence[BatchRow]) -> str:
    """배치 폴더 samples.csv(`doe_no,run_key,<파라미터…>` 반영값) — 폴더 ↔ 번호 ↔ 값(§14.3)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["doe_no", "run_key", *names])
    for r in rows:
        w.writerow([r.doe_no, r.run_key, *[repr(float(r.applied_values[n])) for n in names]])
    return buf.getvalue()
