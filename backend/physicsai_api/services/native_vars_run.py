"""실행(⑥ 내장 최적화·④ 일괄 예측)의 변수 정의 확정(native-vars.md §4·§6.2·§6.3, v0.2.8 Altair 확장 altair-vars.md §5.2): 세트 정의 + 요청
`vars{add,exclude}` → 유효 변수 스냅숏 + `ps'`(기존 함수에 넘길 세트 사본) + 경고·안내.

- 세트 정의는 바꾸지 않는다(D4). 스냅숏 `vars`는 실행 기록(`settings.vars`·`source_meta.vars`)에 그대로 남는다.
- Altair 전체 tpl 세트는 Native 단일 baseline과 같은 규칙(풀 = tpl 선언, feasible·ref_locked 없음, `free_range = True` — 세트 범위 밖도 경고만).
  부분 tpl 세트에 `vars`가 오면 problem `TPL_SCOPE_PARTIAL`(그 밖 동작은 무변경 — 스냅숏·경고 없음, 범위 = 세트 범위).
- 다중 baseline 세트: 편집은 problem `NATIVE_VARS_MULTI_UNSUPPORTED`, 범위 경고 전환(NV-7)만 적용(학습 범위는 비교하지 않음).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from physicsai_core.geometry import baselines as bl
from physicsai_core.geometry import native_vars as nv

from ..context import AppContext
from .geometry_gate import engine_of
from . import template_vars as tv
from .native_vars_api import MULTI_MESSAGE, read_revision
from .native_vars_train import identities_of, train_for
from .param_set_native_api import set_path


@dataclass
class Resolved:
    ps: dict[str, Any]                       # 기존 함수에 넘길 세트(Native 단일 = parameters가 유효 변수 행)
    vars: dict[str, Any] | None = None       # 기록할 스냅숏(Native 단일 baseline만)
    warn_vars: dict[str, Any] | None = None  # 경고 계산용(스냅숏 또는 다중 baseline 대용)
    notes: list[dict[str, str]] = field(default_factory=list)       # TRAIN_RANGE_*·VARS_FROM_DOE 안내
    problems: list[dict[str, Any]] = field(default_factory=list)    # {code?, field, message}(code 없으면 호출부 기본 코드)
    pool: list[dict[str, Any]] = field(default_factory=list)
    free_range: bool = False                 # 범위 규칙 = 막지 않고 경고만(Native 전부, Altair 전체 tpl) — `_bounds(native=…)`·추가 검증


def edit_of(vars_req: Any) -> tuple[list[str], list[str]]:
    """요청 `vars`(VarsEdit·dict·None) → (add, exclude)."""
    if vars_req is None:
        return [], []
    get = vars_req.get if isinstance(vars_req, dict) else lambda k: getattr(vars_req, k, None)
    return list(get("add") or []), list(get("exclude") or [])


def _multi_pseudo(ps: dict[str, Any]) -> dict[str, Any]:
    """다중 baseline 세트의 경고용 변수 문서: feasible = baseline별 feasible(없으면 행 범위)의 합집합. 스냅숏으로 기록하지 않는다."""
    rows = []
    for r in ps.get("parameters") or []:
        lo: list[float] = []
        hi: list[float] = []
        for info in (r.get("baselines") or {}).values() if isinstance(r.get("baselines"), dict) else []:
            if not isinstance(info, dict):
                continue
            fe = info.get("feasible") or {"min": info.get("min"), "max": info.get("max")}
            a, b = nv.finite_num(fe.get("min")), nv.finite_num(fe.get("max"))
            if a is not None:
                lo.append(a)
            if b is not None:
                hi.append(b)
        rows.append({**r, "origin": "set", "train": None,
                     "feasible": {"min": min(lo) if lo else None, "max": max(hi) if hi else None, "source": None} if lo or hi else None})
    return {"schema_version": nv.SCHEMA_VERSION, "set_revision": 0, "edited": False, "variables": rows, "excluded": [], "train_source": None}


def resolve(ctx: AppContext, conn: Any, study: dict[str, Any], ps: dict[str, Any], model: dict[str, Any] | None,
            vars_req: Any, *, doe_names: list[str] | None = None) -> Resolved:
    """`doe_names`: ④ 일괄 `train_doe` — 유효 변수 = DOE 헤더 이름(세트 정의와 달라도 됨, 풀 ⊆ 이어야)."""
    add, exclude = edit_of(vars_req)
    alt = engine_of(ps) != "native"
    if alt and tv.tpl_scope(set_path(ctx, ps)) != tv.SCOPE_FULL:  # 부분 tpl(옛 것): 변경 없음 + 편집 요청은 재생성 안내
        out = Resolved(ps=ps)
        if add or exclude:
            out.problems.append({"code": tv.PARTIAL_REASON, "field": "vars", "message": tv.PARTIAL_MESSAGE})
        return out
    S = set_path(ctx, ps)
    if not alt and bl.is_multi(S):
        out = Resolved(ps=ps, warn_vars=_multi_pseudo(ps), notes=[{"code": nv.NOTE_UNKNOWN, "message": nv.MULTI_UNKNOWN_MESSAGE}],
                       free_range=True)
        if add or exclude:
            out.problems.append({"code": "NATIVE_VARS_MULTI_UNSUPPORTED", "field": "vars", "message": MULTI_MESSAGE})
        return out
    entries, _sha = tv.pool_for(ctx, ps, S)
    rows = list(ps["parameters"])
    set_names = [str(r["name"]) for r in rows]
    out = Resolved(ps=ps, pool=entries, free_range=True)
    if doe_names is not None:
        known = set(set_names) | {e["name"] for e in entries}
        bad = [n for n in doe_names if n not in known]
        out.problems += [{"code": "RANGE_INVALID", "field": "source", "message": f"① DOE 변수 '{n}'은 이 템플릿의 {'변수' if alt else '형상 변수'}가 아닙니다"}
                         for n in bad]
        add = [n for n in dict.fromkeys(doe_names) if n not in set_names and n in known]
        exclude = [n for n in set_names if n not in doe_names]
        out.notes.append({"code": "VARS_FROM_DOE", "message": "① DOE의 변수 구성을 그대로 씁니다"})
    train, src, notes = train_for(ctx, conn, study, model, identities_of(entries, rows), "altair" if alt else "native")
    out.notes += notes
    doc, probs = nv.effective(rows, entries, add=add, exclude=exclude, train=train, set_revision=read_revision(S), train_source=src)
    out.problems += [{"field": p["field"], "message": p["message"], "name": p["name"]} for p in probs]
    out.vars = out.warn_vars = doc
    out.ps = nv.apply(ps, doc)
    return out
