"""④ 템플릿 응답 정의 검증(phase3 §14.6 S9) — `PUT /param-sets/{id}/responses`.

형식 = 원본 ⑤ `OPTIMIZE.responses`의 H3D 부분(phase2 §6.12 RESPONSES 규칙): 행 `{name, unit, spec}`,
spec `{source:"H3D", subcase(≥1 정수), datatype, component, layer, stat(MAX|MIN|ABSMAX)}`. goal·bound 없음, XYDATA는 후속.
component는 layer와 같은 **선택 항목**(D3-54): 없으면 "", 있으면 문자열(⑤ 결과 이름 필드 문자 규칙·`|` 금지·200자) —
PhysicsAI 예측 h3d 응력 `CornerStress`처럼 성분 없는 결과. 요청 줄에는 빈 필드(`NAME|1|CornerStress||`)로 쓴다.
spec이 null인 행 = 추출 정의 없음(이름·단위만 — 실측 `resp:` 열 이름을 유지할 때).
요청 파일(`H3D_REQUESTS.txt`) 작성·`RESPONSES.txt` 파싱은 워커 공용 `responses.py`가 이 정규화 형식을 읽는다.

단계 간 import 금지(test_layering 규칙 5)라 ⑤ `stage5_optimize.optimize`의 규칙을 같은 값으로 둔다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")  # ⑤ RESPONSES name 규칙(최대 64자) — fullmatch 전용(D3-53)
NAME_MAX = 64
FIELD_RE = re.compile(r"[\w \-./():+]*")  # ⑤ 결과 이름 필드 허용 문자(변경 메모 C16)
FIELD_MAX = 200
UNIT_MAX = 40
STATS = ("MAX", "MIN", "ABSMAX")
SOURCES = ("H3D",)
MAX_RESPONSES = 100
SPEC_KEYS = frozenset({"source", "subcase", "datatype", "component", "layer", "stat"})
ROW_KEYS = frozenset({"name", "unit", "spec"})


def _problem(out: list[dict[str, Any]], i: int | None, code: str, message: str) -> None:
    item: dict[str, Any] = {"code": code, "message": message}
    if i is not None:
        item["row"] = i
    out.append(item)


def _check_field(out: list[dict[str, Any]], i: int, key: str, v: Any, *, required: bool) -> None:
    if not isinstance(v, str):
        _problem(out, i, "RESPONSE_INVALID", f"{key}는 문자열이어야 합니다")
    elif required and not v:
        _problem(out, i, "RESPONSE_INVALID", f"{key}가 필요합니다")
    elif "|" in v:
        _problem(out, i, "RESPONSE_INVALID", "'|' 문자는 사용할 수 없습니다")
    elif not FIELD_RE.fullmatch(v) or len(v) > FIELD_MAX:
        _problem(out, i, "RESPONSE_INVALID", f"{key}에 허용되지 않는 문자가 있습니다(영숫자·공백·_ - . / ( ) : + 만)")


def _spec(out: list[dict[str, Any]], i: int, spec: Any) -> dict[str, Any] | None:
    if spec is None:
        return None
    if not isinstance(spec, dict):
        _problem(out, i, "RESPONSE_INVALID", "spec은 객체여야 합니다")
        return None
    unknown = sorted(set(spec) - SPEC_KEYS)
    if unknown:
        _problem(out, i, "RESPONSE_INVALID", f"spec에 알 수 없는 키: {unknown}")
    if spec.get("source") not in SOURCES:
        _problem(out, i, "RESPONSE_INVALID", "source는 H3D만 쓸 수 있습니다(XYDATA는 후속)")
    sc = spec.get("subcase")
    if isinstance(sc, bool) or not isinstance(sc, int) or sc < 1:
        _problem(out, i, "RESPONSE_INVALID", "subcase는 1 이상 정수")
    component = spec.get("component", "")  # D3-54: 선택 항목(layer와 같은 규칙)
    layer = spec.get("layer", "")
    _check_field(out, i, "datatype", spec.get("datatype"), required=True)
    _check_field(out, i, "component", component, required=False)
    _check_field(out, i, "layer", layer, required=False)
    if spec.get("stat") not in STATS:
        _problem(out, i, "RESPONSE_INVALID", "stat은 MAX | MIN | ABSMAX")
    return {"source": spec.get("source"), "subcase": sc, "datatype": spec.get("datatype"),
            "component": component, "layer": layer, "stat": spec.get("stat")}


def validate_response_defs(rows: Any, *, measured: Iterable[str] = ()) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """검증 + 정규화 → (행 `{name, unit, spec|None}`, problems `{code, message, row?}`).

    code: `RESPONSE_INVALID`(형식) | `RESPONSE_IN_USE`(samples.csv 실측 `resp:` 열 이름을 뺌 — 호출부가 422 코드로 쓴다).
    """
    problems: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        _problem(problems, None, "RESPONSE_INVALID", "responses는 배열이어야 합니다")
        return [], problems
    if len(rows) > MAX_RESPONSES:
        _problem(problems, None, "RESPONSE_INVALID", f"응답은 최대 {MAX_RESPONSES}개입니다")
        return [], problems
    seen: set[str] = set()
    kept = list(measured)
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            _problem(problems, i, "RESPONSE_INVALID", "행 형식 오류")
            continue
        unknown = sorted(set(r) - ROW_KEYS)
        if unknown:
            _problem(problems, i, "RESPONSE_INVALID", f"알 수 없는 키: {unknown}")
        name = r.get("name")
        legacy = isinstance(name, str) and name in kept  # 등록 때 이미 있던 실측 열 이름(§15.4 규칙)은 그대로 둔다
        if not isinstance(name, str) or (not legacy and not NAME_RE.fullmatch(name)) or len(name) > NAME_MAX:
            _problem(problems, i, "RESPONSE_INVALID", "name은 영문으로 시작하고 영문/숫자/_ 만(최대 64자)")
        elif name.casefold() in seen:
            _problem(problems, i, "RESPONSE_INVALID", f"이미 있는 name입니다(대소문자 무시): {name}")
        else:
            seen.add(name.casefold())
        unit = r.get("unit", "")
        if unit is None:
            unit = ""
        if not isinstance(unit, str) or len(unit) > UNIT_MAX or "|" in unit or any(ord(ch) < 32 for ch in unit):
            _problem(problems, i, "RESPONSE_INVALID", f"unit은 {UNIT_MAX}자 이내 문자열('|'·제어문자 제외)")
        out.append({"name": name, "unit": unit if isinstance(unit, str) else "", "spec": _spec(problems, i, r.get("spec"))})
    if not problems:
        names = {x["name"] for x in out}
        for m in kept:
            if m not in names:
                _problem(problems, None, "RESPONSE_IN_USE",
                         f"'{m}'는 샘플 표(samples.csv)의 실측 열이라 지울 수 없습니다")
    return out, problems
