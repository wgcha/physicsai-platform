"""① 학습 DOE 플랫폼 생성 표본(phase3 §23.4·§23.5 S18, D3-66) — 순수 함수, I/O 없음.

표본 = S15 `batch_matrix.build_matrix`(④ 일괄 예측과 같은 결정적 코드) 10 kind(+ DM-C3 halton·random) + `table`(①-2 범위 안 CSV,
doe-methods.md DM-C3·§4.1) + `train_doe`. 범위는 ①-2 표(사용 행)의 min·max이고, `ranges`·`continue_from`은 받지 않는다. 반영값(applied_values) = tpl 정수 형식만 `predict.integer_rounding`.

- `check`(API, 동기): run 수·문제·안내만. `lhs_opt`는 같은 count·seed의 `lhs`로 대신 검증한다(최적화 반복이 무거워서, G5).
- `build`(워커 DG_PREP): 실제 행. 결정적이라 check의 run 수 = build 행 수(V3-S18-1).
상한 = `train_data.platform_max_runs`(문구에 그 값이 나온다).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..sampling import registry
from ..sampling.matrix import BatchRow, BatchShapeError, build_matrix
from ..sampling.matrix_rows import _problem
from . import train_params as tp
from .train_tpl import tpl_params_snapshot

REUSE_KIND = "train_doe"  # equiv-check.md Q1: 다른 DOE의 표본표 재사용(run 이름 유지) — 호출부가 samples를 넘긴다
TABLE_KIND = "table"  # DM-C3: ①의 표 붙여넣기 / CSV(JSON 본문 문자열, 값은 ①-2 범위 안)
# lhs_opt, sobol, halton, lhs, random, fullfact, fracfact, pb, bbd, ccd, table, train_doe(= registry.SITE_KINDS["train_platform"])
KINDS = registry.PLATFORM_KINDS + (TABLE_KIND, REUSE_KIND)
# kind별 허용 입력 키(정규화 순서)와 기본값 — API 스키마(TrainSampling)와 같은 규칙
_DEFAULTS: dict[str, dict[str, Any]] = {
    "lhs": {"count": None, "seed": 1},
    "lhs_opt": {"count": None, "seed": 1, "criterion": "maximin"},
    "sobol": {"count": None, "seed": 1},
    "halton": {"count": None, "seed": 1},
    "random": {"count": None, "seed": 1},
    "fullfact": {"levels": {}},
    "fracfact": {"resolution": 5},
    "pb": {},
    "bbd": {},
    "ccd": {"alpha": "face"},
    "table": {"text": None},
    "train_doe": {"doe_id": None},
}


@dataclass
class PlatformPlan:
    """표본 계산 결과(check·build 공용 모양)."""

    kind: str
    doe_type: str  # LHS_OPT …(④ source_kind와 같은 글자)
    label: str  # §20.4 표시 이름
    desc_id: str  # td_<kind>
    input: dict[str, Any]  # 정규화한 입력(kind 제외) = train_does.options
    rows: list[BatchRow] = field(default_factory=list)
    problems: list[dict[str, Any]] = field(default_factory=list)
    notes: list[dict[str, str]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def run_count(self) -> int:
        return len(self.rows)

    @property
    def ok(self) -> bool:
        return not self.problems and bool(self.rows)

    def stored_input(self) -> dict[str, Any]:
        """DB(train_does.options·sampling.input)에 남길 입력(`stored_input` 함수 참고)."""
        return stored_input(self.kind, self.input, self.run_count)

    def sampling_record(self, *, with_meta: bool) -> dict[str, Any]:
        """train_does.sampling = {kind, input, meta}. API 단계(check)는 meta = null(워커 DG_PREP이 채움)."""
        return {"kind": self.kind, "input": self.stored_input(), "meta": dict(self.meta) if with_meta else None}


def stored_input(kind: str, inp: Mapping[str, Any], run_count: int) -> dict[str, Any]:
    """DB(train_does.options·sampling.input)에 남길 입력. 표(table)는 본문을 빼고 행 수만 — 표 본문은 작업 params에만 둔다(④가 표 본문을
    저장하지 않는 원칙과 같음, 응답 `options` 비대화 방지)."""
    return {"row_count": int(run_count)} if kind == TABLE_KIND else dict(inp)


def normalize(sampling: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """sampling(kind + 필드) → (kind, 정규화 입력). 모르는 kind·금지 키·모르는 키 → BatchShapeError."""
    if not isinstance(sampling, Mapping):
        raise BatchShapeError("sampling은 객체여야 합니다")
    kind = sampling.get("kind")
    if kind not in KINDS:
        raise BatchShapeError("sampling.kind는 " + " | ".join(KINDS) + " 중 하나입니다")
    defaults = _DEFAULTS[kind]
    extra = [k for k in sampling if k != "kind" and k not in defaults]
    if extra:
        raise BatchShapeError(f"sampling.{extra[0]}는 '{kind}' 방식에서 쓸 수 없습니다")
    out: dict[str, Any] = {}
    for k, dv in defaults.items():
        v = sampling.get(k)
        out[k] = (dict(dv) if isinstance(dv, dict) else dv) if v is None else (dict(v) if isinstance(v, Mapping) else v)
    if kind in ("lhs", "lhs_opt", "sobol", "halton", "random") and out["count"] is None:
        raise BatchShapeError("sampling.count는 정수여야 합니다")
    if kind == TABLE_KIND and not isinstance(out["text"], str):
        raise BatchShapeError("sampling.text(표 내용, 첫 줄 = 파라미터 이름 헤더)가 필요합니다")
    if kind == REUSE_KIND and not isinstance(out["doe_id"], str):
        raise BatchShapeError("sampling.doe_id(표본표를 재사용할 DOE)가 필요합니다")
    return kind, out


def design_inputs(setup: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """①-2 표(train_setups) → (parameters = 사용 행 {name, min, max, nominal, format}, tpl_params = {var, name, format}).
    tpl_params는 tpl 생성 기록(없으면 사용 행으로 다시 만든 같은 모양) — 정수 형식(%Ni/%Nd)이 applied_values 반올림 대상.
    전체 tpl(altair-vars.md AV-5)의 미사용 행 기록은 뺀다 — 표본·반올림 입력이 v0.2.7과 같다(① DOE 불변)."""
    used = tp.used(list(setup.get("parameters") or []))
    params = [{"name": str(p["name"]), "min": float(p["min"]), "max": float(p["max"]),
               "nominal": p.get("nominal"), "format": p.get("format")} for p in used]
    names = {p["name"] for p in params}
    tpl_params = [t for t in (setup.get("tpl_params") or tpl_params_snapshot(used)) if t.get("name") in names]
    return params, tpl_params


def design_inputs_native(setup: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """①-1 Native 추출 기준 표(①-2 사용 행) → (parameters, tpl_params = []). Native는 tpl이 없고 ①-2 `format`("%3i" 등)은 추출 기본값일 뿐이라
    정수 반올림을 적용하지 않는다(반영값 = 설계 값, Native lhs와 같다 — doe-methods.md §4.3)."""
    return design_inputs(setup)[0], []


def _plan(kind: str, inp: dict[str, Any], matrix: Any) -> PlatformPlan:
    doe_type, label, _d = registry.method_info(kind)
    return PlatformPlan(kind, doe_type, label, registry.platform_desc_id(kind), inp, list(matrix.rows), list(matrix.problems),
                        list(matrix.notes), dict(matrix.source_meta))


Samples = tuple[list[str], list[dict[str, Any]]]  # (samples.csv 헤더, 행) — `doe_samples.read_samples_csv` 결과


Inputs = tuple[list[dict[str, Any]], list[dict[str, Any]]]  # (parameters, tpl_params) — `design_inputs`·`design_inputs_from_params` 결과


def _matrix(source: dict[str, Any], setup: Mapping[str, Any], settings: Any, samples: Samples | None = None,
            inputs: Inputs | None = None) -> Any:
    params, tpl_params = inputs if inputs is not None else design_inputs(setup)
    return build_matrix(source, parameters=params, tpl_params=tpl_params, max_runs=int(settings.train_data.platform_max_runs),
                        table_max_bytes=int(settings.predict_batch.table_max_bytes),
                        integer_rounding=settings.predict.integer_rounding,
                        samples_header=samples[0] if samples else None, samples=samples[1] if samples else None)


def _table_range_problems(plan: PlatformPlan, rows: list[BatchRow], inputs: list[dict[str, Any]]) -> None:
    """DM-C3·Q1: ①의 표는 값이 ①-2(세트) 학습 범위 min~max 밖이면 TABLE_OUT_OF_RANGE(행별, 상한 MAX_PROBLEMS까지)."""
    by_name = {str(p["name"]): p for p in inputs}
    for r in rows:
        for n in r.out_of_range:
            p = by_name[n]
            _problem(plan.problems, "TABLE_OUT_OF_RANGE",
                     f"'{n}' 값 {r.values[n]:g}가 학습 범위 {float(p['min']):g}~{float(p['max']):g} 밖입니다", r.doe_no)


def _finish(kind: str, inp: dict[str, Any], matrix: Any, settings: Any, inputs: Inputs | None, setup: Mapping[str, Any]) -> PlatformPlan:
    plan = _plan(kind, inp, matrix)
    if kind == TABLE_KIND and not plan.problems:  # ①의 표: 행 2개 이상·학습 범위 안(④ table은 1행·범위 밖 허용 — 그대로)
        if len(plan.rows) < 2:
            _problem(plan.problems, "TOO_FEW_ROWS", f"행은 2개 이상이어야 합니다(현재 {len(plan.rows)}개)")
        else:
            _table_range_problems(plan, plan.rows, (inputs if inputs is not None else design_inputs(setup))[0])
    return plan


def check(sampling: Mapping[str, Any], setup: Mapping[str, Any], settings: Any, *, samples: Samples | None = None,
          inputs: Inputs | None = None) -> PlatformPlan:
    """API 검증(동기): lhs_opt는 {kind: lhs, count, seed}로 대신(같은 run 수·같은 count·seed 오류). rows는 run 수 계산용.
    train_doe(표본표 재사용)는 호출부가 원본 DOE samples.csv를 읽어 `samples`로 넘긴다. `inputs` = 표 입력을 호출부가 정한 경우
    (Native 세트 기준 DOE는 `design_inputs_from_params`), 생략 = ①-2 표(`design_inputs(setup)`)."""
    kind, inp = normalize(sampling)
    source: dict[str, Any] = {"kind": "lhs", "count": inp["count"], "seed": inp["seed"]} if kind == "lhs_opt" \
        else {"kind": kind, **inp}
    plan = _finish(kind, inp, _matrix(source, setup, settings, samples, inputs), settings, inputs, setup)
    if kind == "lhs_opt":  # 대체 검증이라 meta·안내 중 lhs 고유 내용은 버리고 run 수·문제만 남긴다
        plan.meta = {}
    return plan


def build(sampling: Mapping[str, Any], setup: Mapping[str, Any], settings: Any, *, samples: Samples | None = None,
          inputs: Inputs | None = None) -> PlatformPlan:
    """워커 DG_PREP: 실제 표본 행(doe_no 1.., run_key run__00001.. — train_doe는 원본 run 이름 그대로). meta = §20.5 각 방식 meta(+ quality)."""
    kind, inp = normalize(sampling)
    return _finish(kind, inp, _matrix({"kind": kind, **inp}, setup, settings, samples, inputs), settings, inputs, setup)


def design_inputs_from_params(params: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """native 세트 파라미터 표(param_sets.parameters) → design_inputs와 같은 모양(세트 기준 DOE의 표본표 재사용용)."""
    out = [{"name": str(p["name"]), "min": float(p["min"]), "max": float(p["max"]), "nominal": p.get("nominal"), "format": p.get("format")}
           for p in params if p.get("min") is not None and p.get("max") is not None]
    return out, [{"var": f"var_{i + 1}", "name": p["name"], "format": p.get("format")} for i, p in enumerate(out)]
