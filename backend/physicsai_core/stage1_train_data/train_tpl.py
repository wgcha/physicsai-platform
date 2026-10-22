"""①-2 tpl 생성(phase2 §6.3, altair-vars.md §3). 원본 update_parameter_file(1_CREATE_TRAINING_DATA/FUNC/1_create_tpl_file.py:127-193)을
우리 코드로 재구현한다. 정규식·marker는 설정(train_data.*)에서 읽는다.

차이(계약): anchor가 없으면 오류(가정 A-4), 행별 형식.
- v0.2.7까지: 사용하지 않는 파라미터는 두 블록 모두에서 뺐다(가정 A-5, 부분 tpl).
- v0.2.8(altair-vars.md AV-1): ①-1 표의 유효한 모든 행을 선언한다(전체 tpl). 사용 행 = DOE 범위, 미사용 행 = min = max = 공칭 고정,
  parameter 블록 뒤에 범위 표지 줄(AV-3). 행에 `used` 키가 없으면 사용으로 본다(= v0.2.7 호출, 표지·미사용 처리 없음).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import train_params as tp
from ..tpl_render import (  # noqa: F401 - scope_of·scope_of_file·SCOPE_LINE는 이 모듈 속성으로도 쓴다
    PARAM_DECL_RE,
    PARAM_LINE_RE,
    SCOPE_LINE,
    VALID_FMT_RE,
    VAR_REF_RE,
    format_value,
    parse_declarations,
    parse_tpl,
    scope_of,
    scope_of_file,
)

ANCHOR = '<Parameters Value="">'
SCOPE_LINE_RE = re.compile(r"(?m)^[ \t]*#[ \t]*physicsai-tpl[^\n]*\n?")
NOMINAL_LOSS_TOL = 1e-9  # AV-6: fmt % 공칭을 다시 읽은 값이 공칭과 다른 정도(상대, × max(1, |공칭|))

NOTE_SKIPPED = "TPL_PARAM_SKIPPED"
NOTE_FORMAT_LOSS = "TPL_NOMINAL_FORMAT_LOSS"


class TplTemplateInvalid(ValueError):
    def __init__(self, problems: list[dict[str, str]]) -> None:
        super().__init__("; ".join(p["message"] for p in problems))
        self.problems = problems


def num_text(v: float | int) -> str:
    """정수값 실수는 "3", 그 외 repr(float) 최단 표기("2.85")."""
    f = float(v)
    if f.is_integer():
        return str(int(f))
    return repr(f)


@dataclass(frozen=True)
class TplRules:
    marker: str
    prt_regex: str
    parameter_line_regex: str
    paramitem_line_regex: str

    @classmethod
    def from_settings(cls, td: Any) -> TplRules:
        return cls(td.tpl_marker, td.tpl_prt_regex, td.tpl_parameter_line_regex, td.tpl_paramitem_line_regex)


# ---- 범위 표지 ------------------------------------------------------------------------------------


# scope_of·scope_of_file·SCOPE_LINE은 공용 `physicsai_core.tpl_render`(④ 세트 검증기도 쓴다 — 단계 패키지 간 import 금지)


# ---- 생성 -----------------------------------------------------------------------------------------


def nominal_lost(fmt: str, nominal: float) -> bool:
    """AV-6: 미사용 행의 `fmt % 공칭`이 공칭을 잃는지(예: 정수 형식 %3i에 공칭 2.85)."""
    try:
        back = float(format_value(fmt, nominal))
    except (ValueError, OverflowError, TypeError):
        return True
    return abs(back - float(nominal)) > NOMINAL_LOSS_TOL * max(1.0, abs(float(nominal)))


@dataclass
class TplBuild:
    text: str
    declared: list[dict[str, Any]] = field(default_factory=list)  # 선언·참조된 행(표 순서, var_1…)
    literal: list[dict[str, Any]] = field(default_factory=list)  # AV-6 리터럴 Value로 쓴 미사용 행(선언·참조 없음)


def generate_ex(template_text: str, params: Sequence[Mapping[str, Any]], cad_file_name: str, rules: TplRules, *,
                full: bool = False) -> TplBuild:
    """params = 표 순서의 행 [{name, nominal, min, max, format, used?}]. `used`가 False인 행은 min = max = 공칭으로 선언한다.
    `full=True`면 parameter 블록 뒤에 범위 표지 줄을 쓴다. 실패 시 TplTemplateInvalid."""
    text = template_text.lstrip("﻿\r\n\t ")  # :130-132
    text = re.sub(rules.prt_regex, lambda _m: f'dir_file_prt = r"./{cad_file_name}"', text)  # :135-139
    declared: list[dict[str, Any]] = []
    literal: list[dict[str, Any]] = []
    for p in params:
        if not p.get("used", True) and nominal_lost(p["format"], p["nominal"]):
            literal.append(dict(p))
        else:
            declared.append(dict(p))
    var_of = {p["name"]: f"var_{i}" for i, p in enumerate(declared, start=1)}

    def bounds(p: Mapping[str, Any]) -> tuple[Any, Any]:
        return (p["min"], p["max"]) if p.get("used", True) else (p["nominal"], p["nominal"])

    parameter_block = "\n".join(
        f'{{parameter({var_of[p["name"]]}, "{p["name"]}", {num_text(p["nominal"])}, {num_text(bounds(p)[0])}, {num_text(bounds(p)[1])})}}'
        for p in declared
    )
    text = re.sub(rules.parameter_line_regex, "", text)  # :153-157
    pos = text.find(rules.marker)  # :159-162
    if pos == -1:
        raise TplTemplateInvalid([{"code": "TPL_MARKER_MISSING", "message": "tpl 템플릿에서 marker 줄을 찾지 못했습니다"}])
    text = parameter_block + "\n" + (SCOPE_LINE + "\n" if full else "") + text[pos:]
    literal_names = {p["name"] for p in literal}

    def new_value(p: Mapping[str, Any]) -> str:
        if p["name"] in literal_names:
            return num_text(p["nominal"])  # AV-6: 변수 참조 없이 원래 Value 문자열 그대로
        return f'{{{var_of[p["name"]]}, {p["format"]}}}'

    paramitem_block = "\n".join(
        f'   <paramitem Name="{p["name"]}" NewValue="{new_value(p)}" Value="{num_text(p["nominal"])}"/>' for p in params
    )
    text = re.sub(rules.paramitem_line_regex, "", text)  # :177-181
    if ANCHOR not in text:
        raise TplTemplateInvalid([{"code": "TPL_ANCHOR_MISSING", "message": f"tpl 템플릿에 {ANCHOR} 가 없습니다"}])
    text = text.replace(ANCHOR, ANCHOR + "\n" + paramitem_block)  # :183-186
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)  # :188
    return TplBuild(text, declared, literal)


def generate(template_text: str, params: list[dict[str, Any]], cad_file_name: str, rules: TplRules, *, full: bool = False) -> str:
    """`generate_ex`의 텍스트만(v0.2.7 호환 — `used` 키가 없는 사용 행 목록이면 v0.2.7과 같은 결과)."""
    return generate_ex(template_text, params, cad_file_name, rules, full=full).text


def validate_generated(text: str, params: list[dict[str, Any]]) -> list[dict[str, str]]:
    """생성 tpl이 1차 §15.4 검증기(파라미터 이름 집합 일치, {VAR, FMT} 형식)를 통과하는지.
    params = tpl에 선언한 행(전체 tpl이면 `TplBuild.declared` — AV-2·AV-6 제외분 뺀 것)."""
    problems: list[dict[str, str]] = []
    decl, refs = parse_tpl(text)
    if set(decl.values()) != {p["name"] for p in params}:
        problems.append({"code": "PARAM_TPL_MISMATCH", "message": "tpl의 parameter 이름 집합이 사용 파라미터와 다릅니다"})
    for r in refs:
        if not VALID_FMT_RE.match(r["format"]):
            problems.append({"code": "TPL_FORMAT_INVALID", "message": f"tpl 형식 '{r['format']}'을 쓸 수 없습니다"})
        if r["var"] not in decl:
            problems.append({"code": "TPL_VAR_UNDEFINED", "message": f"tpl 변수 '{r['var']}'가 parameter로 정의되지 않았습니다"})
    return problems


def tpl_params_snapshot(params: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """tpl 선언 행 기록(`train_setups.tpl_params`·`param_sets.tpl_params`). 모양은 v0.2.7 `{var, name, format}`에 전체 tpl 행이면
    `used`·`table_min`·`table_max`(①-1 표 값 — 미사용 행의 ④ 기본 범위 출처, AV-4)·`unit`을 더한다.
    `used` 키가 없는 행(v0.2.7 호출)은 옛 모양 그대로."""
    out: list[dict[str, Any]] = []
    for i, p in enumerate(params, start=1):
        row: dict[str, Any] = {"var": f"var_{i}", "name": p["name"], "format": p["format"]}
        if "used" in p:
            row.update({"used": bool(p["used"]), "table_min": p.get("min"), "table_max": p.get("max"), "unit": p.get("unit") or ""})
        out.append(row)
    return out


def is_full_snapshot(tpl_params: Sequence[Mapping[str, Any]] | None) -> bool:
    """스냅숏 행에 `used` 키가 있으면 전체 tpl 기록(없으면 부분 tpl = 모두 사용, AV-4)."""
    return bool(tpl_params) and any("used" in r for r in tpl_params or [])


def plan_rows(parameters: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """①-1 표 → (tpl에 넣을 행(유효한 모든 행, 표 순서, `used` = 사용 체크), 유효하지 않아 뺀 미사용 행 이름).
    유효하지 않은 **사용** 행은 호출부가 먼저 거른다(422)."""
    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    for p in parameters:
        q = tp.with_validity(dict(p))
        if q["valid"]:
            rows.append({"name": q["name"], "nominal": q["nominal"], "min": q["min"], "max": q["max"], "format": q["format"],
                         "unit": q.get("unit") or "", "used": bool(q.get("use"))})
        elif not q.get("use"):
            skipped.append(str(q["name"]))
    return rows, skipped


def declared_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """`plan_rows` 행 중 tpl에 선언되는 행(AV-6 리터럴 행 제외) — `generate_ex(...).declared`와 같다."""
    return [dict(p) for p in rows if p.get("used", True) or not nominal_lost(p["format"], p["nominal"])]


def expected_snapshot(parameters: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """현재 ①-1 표로 지금 tpl을 생성했다면 남을 `tpl_params` 기록(stale 판정용)."""
    return tpl_params_snapshot(declared_rows(plan_rows(parameters)[0]))


def summary_of(parameters: Sequence[Mapping[str, Any]] | None, tpl_params: Sequence[Mapping[str, Any]] | None,
               warnings: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    """`tpl_summary` {total, used, skipped, format_loss, scope}: 저장된 tpl 기록에서 계산(전체 tpl이면 `warnings`의 note 이름 사용)."""
    snap = list(tpl_params or [])
    notes = {w.get("code"): [str(n) for n in (w.get("names") or [])] for w in (warnings or [])}
    full = is_full_snapshot(snap)
    format_loss = notes.get(NOTE_FORMAT_LOSS, []) if full else []
    return {"total": len(snap) + len(format_loss), "used": sum(1 for r in snap if r.get("used", True)),
            "skipped": notes.get(NOTE_SKIPPED, []) if full else [], "format_loss": format_loss,
            "scope": "full" if full else "partial"}


# ---- 렌더 도우미·뷰 ---------------------------------------------------------------------------------


def fill_nominal(decl: Iterable[Mapping[str, Any]], values: Mapping[str, float]) -> dict[str, float]:
    """값 ∪ {선언됐지만 값이 없는 파라미터: 공칭}(AV-5·§5.2). `decl` = `tpl_render.parse_declarations(text)` 결과."""
    out = dict(values)
    for d in decl:
        if d["name"] not in out and d.get("nominal") is not None:
            out[d["name"]] = d["nominal"]
    return out


def used_view(full_text: str, used_names: Iterable[str], nominal_by_name: Mapping[str, float] | None = None) -> str:
    """전체 tpl의 사용 뷰(AV-7): 미사용 선언 줄 제거, 그 변수 참조 `{var_i, fmt}`를 `fmt % 공칭` 문자로 치환, 표지 줄 제거,
    남은 변수는 var_1…으로 다시 번호(v0.2.7 생성 tpl과 선언·참조가 같다). 공칭 = nominal_by_name, 없으면 선언의 공칭."""
    used = set(used_names)
    decls = parse_declarations(full_text)
    keep = [d for d in decls if d["name"] in used]
    drop = {d["var"]: d for d in decls if d["name"] not in used}
    new_var = {d["var"]: f"var_{i}" for i, d in enumerate(keep, start=1)}
    nominal: dict[str, float] = {}
    for d in drop.values():
        n = (nominal_by_name or {}).get(d["name"], d["nominal"])
        if n is None:
            raise TplTemplateInvalid([{"code": "TPL_VIEW_NOMINAL_MISSING", "message": f"선언 '{d['name']}'의 공칭을 알 수 없습니다"}])
        nominal[d["var"]] = float(n)

    text = SCOPE_LINE_RE.sub("", full_text)

    def decl_line(m: re.Match[str]) -> str:
        dm = PARAM_DECL_RE.search(m.group(0))
        if dm is None:
            return m.group(0)
        var = dm.group(1)
        if var in drop:
            return ""
        nv = new_var.get(var)
        if nv is None or nv == var:
            return m.group(0)
        a, b = dm.span(1)
        line = m.group(0)
        return line[:a] + nv + line[b:]

    text = PARAM_LINE_RE.sub(decl_line, text)

    def ref(m: re.Match[str]) -> str:
        var, fmt = m.group(1), m.group(2)
        if var in drop:
            return format_value(fmt, nominal[var])
        nv = new_var.get(var)
        return m.group(0) if nv is None else f"{{{nv}, {fmt}}}"

    return VAR_REF_RE.sub(ref, text)
