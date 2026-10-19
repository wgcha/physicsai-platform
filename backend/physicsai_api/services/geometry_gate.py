"""native 형상 엔진 공통 검사(geometry-engine.md §7.1·§7.4·§7.7): 사용 가능 여부 409, 옵션 422, 엔진 불일치 409."""

from __future__ import annotations

from typing import Any

from physicsai_core.errors import DomainError
from physicsai_core.features import geometry_native_missing
from physicsai_core.geometry.options import effective_options, normalize_override


def require_native_available(settings: Any) -> None:
    """409 GEOM_NATIVE_UNAVAILABLE: 명령 템플릿이 비었거나 paicad 실행 파일이 없다(missing 목록 포함)."""
    tmpl, res = geometry_native_missing(settings)
    if tmpl or res:
        raise DomainError("GEOM_NATIVE_UNAVAILABLE", "native 형상 엔진을 쓸 수 없습니다 — 관리자 설정이 필요합니다", status=409,
                          missing=tmpl + res)


def validate_geom_options(settings: Any, raw: dict[str, Any] | None) -> dict[str, Any]:
    """세트별 덮어쓰기 검증 → 정규화된 덮어쓰기. 범위·형식 위반은 422 GEOM_OPTIONS_INVALID(problems)."""
    over, probs = normalize_override(raw)
    _opts, p2 = effective_options(settings.geometry.defaults, over)
    probs = probs + [p for p in p2 if p not in probs]
    if probs:
        raise DomainError("GEOM_OPTIONS_INVALID", "형상 옵션 값이 올바르지 않습니다", status=422, problems=probs)
    return over


def engine_of(row: dict[str, Any] | None) -> str:
    return (row or {}).get("engine") or "altair"


def check_engine_match(ps: dict[str, Any], model: dict[str, Any]) -> list[dict[str, str]]:
    """세트·모델 형상 엔진 불일치 409 ENGINE_MISMATCH(§7.7). 모델 엔진이 NULL(모름)인 native 세트 조합은 ENGINE_UNKNOWN 경고."""
    pe, me = engine_of(ps), model.get("engine")
    if me is not None and me != pe:
        raise DomainError("ENGINE_MISMATCH", f"모델의 학습 데이터 형상 엔진({me})과 파라미터 세트({pe})가 다릅니다 — 같은 엔진으로 맞춰 주세요",
                          status=409, model_engine=me, param_set_engine=pe)
    if me is None and pe == "native":
        return [{"code": "ENGINE_UNKNOWN", "message": "모델의 학습 데이터 형상 엔진을 알 수 없어 확인하지 못했습니다"}]
    return []


def native_set_gate(ctx: Any, ps: dict[str, Any]) -> None:
    """native 세트로 형상을 만드는 작업의 사전조건: paicad 사용 가능(409 GEOM_NATIVE_UNAVAILABLE) + 준비본 READY(409 GEOM_PREP_STALE)."""
    from . import param_set_native_api as nat

    require_native_available(ctx.settings)
    state = nat.prep_state_of(ctx, ps)
    if state is not None and state.status != "READY":
        raise DomainError("GEOM_PREP_STALE", state.reason or "형상 준비본이 유효하지 않습니다 — 형상 준비를 다시 하세요", status=409,
                          prep_status=state.status, param_set_id=ps["id"])
    bad = nat.baseline_prep_problems(ctx, ps)  # 4B: 준비본 유효성은 baseline별(§7.3.8)
    if bad:
        bid, why = bad[0]
        raise DomainError("GEOM_PREP_STALE", f"baseline {bid}: {why}", status=409, prep_status="STALE", param_set_id=ps["id"],
                          baseline_id=bid)


def require_map_confirmed(ctx: Any, ps: dict[str, Any]) -> None:
    """4B 확정 게이트(§7.3.8): param_map.json이 있는 세트에서 형상을 만드는 run 생성(①-3 DOE·④ 일괄 생성)은 confirmed일 때만.
    단일 baseline 세트·단건 예측은 대상 아님. 미확정 → 409 PARAM_MAP_UNCONFIRMED(미결정 행 수)."""
    from physicsai_core.geometry import baselines as bl

    from . import param_set_native_api as nat

    if engine_of(ps) != "native":
        return
    S = nat.set_path(ctx, ps)
    try:
        pm = bl.load(S, ctx.settings.geometry.max_report_bytes)
    except bl.MapError as exc:
        raise DomainError(exc.code, exc.message, status=422, problems=exc.problems) from None
    if pm is not None and pm.get("status") != "confirmed":
        n = bl.undecided_count(pm)
        raise DomainError("PARAM_MAP_UNCONFIRMED", f"다중 baseline 매칭표가 확정되지 않았습니다(미결정 행 {n}개) — 매칭표를 확인해 확정하세요",
                          status=409, param_set_id=ps["id"], undecided_rows=n, unresolved_rows=bl.unresolved(pm))
