"""①-3 TD_DOE_GEN native — lhs 밖 표본 방식(doe-methods.md DM-C2·§5.1). doe_native·doe_native_set의 DG_PREP이 호출한다.

- 단일 baseline: `doe_platform.build`(= `build_matrix`, API check와 같은 코드)의 `applied_values` 행을 `doe_matrix.csv`로 쓰고
  `train_does.sampling = {kind, input, meta}`(meta = 방식별 S15 meta)를 채운다.
- 다중 baseline: 층화(baseline별 개수 차 ≤ 1, 층 seed = seed + 층 번호)는 그대로 두고 층 안 생성기만 바꾼다(`sampling.layer_gen`).
lhs·표본표 재사용(train_doe)·옛 입력(sampling 없음)은 여기로 오지 않는다 — 기존 코드 그대로(DM-C8).
"""

from __future__ import annotations

from typing import Any

from physicsai_core.errors import StepFailure
from physicsai_core.sampling import qmc
from physicsai_core.sampling.layer_gen import layer_generator
from physicsai_core.stage1_train_data import doe_platform


def method_sampling(p: dict[str, Any]) -> dict[str, Any] | None:
    """작업 params.sampling이 lhs 밖 표본 방식이면 그 dict, 아니면 None(기존 분기)."""
    sp = p.get("sampling")
    if isinstance(sp, dict) and sp.get("kind") not in (None, "lhs", "train_doe"):
        return sp
    return None


def single_matrix(ctx: Any, sp: dict[str, Any], inputs: tuple[list[dict[str, Any]], list[dict[str, Any]]]
                  ) -> tuple[list[tuple[int, str, dict[str, float]]], dict[str, Any]]:
    """단일 baseline 표본 → ([(doe_no, run_key, 반영값)], train_does.sampling 기록). 문제가 있으면 StepFailure(INPUT_INVALID)."""
    plan = doe_platform.build(sp, {}, ctx.settings, inputs=inputs)
    if plan.problems or not plan.rows:
        p0 = (plan.problems or [{"message": "표본이 없습니다"}])[0]
        raise StepFailure("INPUT_INVALID", f"표본을 만들 수 없습니다: {p0['message']}")
    for n in plan.notes:
        ctx.add_warning(n["code"], n["message"])
    ctx.log(f"표본 방식 {plan.label}: run {len(plan.rows)}개")
    return [(r.doe_no, r.run_key, dict(r.applied_values)) for r in plan.rows], plan.sampling_record(with_meta=True)


def multi_generator(sp: dict[str, Any]) -> Any:
    """다중 baseline 층 안 생성기(kind별). halton의 scipy 불가는 StepFailure로."""
    kind, inp = doe_platform.normalize(sp)
    return layer_generator(kind, inp.get("criterion") or "maximin"), kind, inp


def multi_record(kind: str, inp: dict[str, Any], per: dict[str, int]) -> dict[str, Any]:
    """다중 baseline `train_does.sampling` 기록: meta = {count, seed, (criterion), (scramble·generator), layers = baseline별 run 수}."""
    meta: dict[str, Any] = {"count": inp["count"], "seed": inp["seed"], "layers": dict(per)}
    if kind == "lhs_opt":
        meta["criterion"] = inp.get("criterion") or "maximin"
    if kind == "halton":
        meta["scramble"] = True
        try:
            meta["generator"] = qmc.generator_label()
        except qmc.GeneratorUnavailable as exc:
            raise StepFailure("INPUT_INVALID", f"표본을 만들 수 없습니다: {exc}") from None
    return {"kind": kind, "input": dict(inp), "meta": meta}
