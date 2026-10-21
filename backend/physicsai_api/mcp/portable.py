"""이식 가능 스키마 변환기(mcp.md §9.2, MR-16): openapi 스키마 → Claude·Codex·Gemini 공통 부분집합.

규칙(바꿀 수 없으면 `SpecError` — 메시지에 operation·필드):
- 허용 키워드: type(단일 문자열)·description·properties·required·items·enum(문자열만)·minimum·maximum·minItems·maxItems·minLength·maxLength·nullable
- `$ref` 인라인(순환이면 실패), title·default·examples·example·format·pattern·additionalProperties·patternProperties·const·exclusive*는 제거하고
  기본값·형식·패턴은 description 끝 `(기본 …, 형식 …)`로 옮긴다.
- anyOf/oneOf/allOf 금지: `X | None` = X + nullable, 단일 allOf(`$ref` + 설명)는 병합, 그 밖은 실패.
- properties가 없는 object(자유 객체)는 최상위 인자에서만 `<이름>_json` 문자열로 바꾼다(호출부가 처리), 중첩이면 실패.
"""

from __future__ import annotations

import copy
from typing import Any

ALLOWED = ("type", "description", "properties", "required", "items", "enum", "minimum", "maximum", "minItems", "maxItems",
           "minLength", "maxLength", "nullable")
MOVE_TO_DESC = ("default", "format", "pattern", "const")  # description 끝으로 옮기는 키
DROP = ("title", "examples", "example", "additionalProperties", "patternProperties", "exclusiveMinimum", "exclusiveMaximum",
        "readOnly", "writeOnly", "deprecated")
TYPES = ("object", "string", "number", "integer", "boolean", "array")
ARG_DESC_MAX = 200
JSON_ARG_NOTE = "JSON 객체 텍스트(64 KiB 이하)"


class SpecError(RuntimeError):
    pass


def _label(k: str) -> str:
    return {"default": "기본", "format": "형식", "pattern": "패턴", "const": "고정값"}[k]


def deref(node: dict[str, Any], comps: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        return comps[ref.rsplit("/", 1)[1]]
    return node


def is_free_object(node: dict[str, Any], comps: dict[str, Any]) -> bool:
    """properties가 없는(자유 형식) object — 최상위 인자면 `<이름>_json` 문자열 대상."""
    n = _merge_single(node, comps, [])
    return n.get("type") == "object" and not n.get("properties")


def _merge_single(node: dict[str, Any], comps: dict[str, Any], stack: list[str]) -> dict[str, Any]:
    """$ref 인라인 + 단일 allOf 병합(바깥 description 우선)."""
    node = dict(node)
    ref = node.pop("$ref", None)
    base: dict[str, Any] = {}
    if isinstance(ref, str):
        name = ref.rsplit("/", 1)[-1]
        if name in stack:
            raise SpecError(f"순환 $ref: {' → '.join([*stack, name])}")
        base = _merge_single(comps[name], comps, [*stack, name])
    allof = node.pop("allOf", None)
    if allof:
        if len(allof) != 1:
            raise SpecError("allOf는 항목 1개일 때만 병합할 수 있습니다")
        inner = _merge_single(allof[0], comps, stack)
        base = {**base, **inner}
    return {**base, **node}


def convert(schema: dict[str, Any], comps: dict[str, Any], where: str, *, stack: tuple[str, ...] = ()) -> dict[str, Any]:
    """openapi 스키마 한 노드 → 이식 가능 스키마(재귀)."""
    node = _merge_single(schema, comps, list(stack))
    nullable = bool(node.pop("nullable", False))
    for comb in ("anyOf", "oneOf"):
        if comb in node:
            alts = node.pop(comb)
            non_null = [a for a in alts if not (isinstance(a, dict) and a.get("type") == "null")]
            if len(non_null) == len(alts) - 1 and len(non_null) == 1:  # X | None
                nullable = True
                node = {**_merge_single(non_null[0], comps, list(stack)), **{k: v for k, v in node.items()}}
            else:
                raise SpecError(f"{where}: {comb}는 `X | None` 형태만 허용됩니다(단순화하거나 x-mcp exclude)")
    if "allOf" in node:
        raise SpecError(f"{where}: allOf 금지")
    typ = node.get("type")
    if isinstance(typ, list):
        non_null_t = [t for t in typ if t != "null"]
        if len(non_null_t) != 1:
            raise SpecError(f"{where}: type 배열 {typ}")
        nullable = nullable or len(non_null_t) != len(typ)
        typ = non_null_t[0]
    if typ is None and "enum" in node:
        typ = "string"
    if typ not in TYPES:
        raise SpecError(f"{where}: 지원하지 않는 type {typ!r}")
    out: dict[str, Any] = {"type": typ}
    notes: list[str] = []
    for k in MOVE_TO_DESC:
        if k in node and node[k] is not None:
            notes.append(f"{_label(k)} {node[k]}")
    for k in ("exclusiveMinimum", "exclusiveMaximum"):
        if k in node and isinstance(node[k], (int, float)) and not isinstance(node[k], bool):
            notes.append(f"{'초과' if k == 'exclusiveMinimum' else '미만'} {node[k]}")
    if "enum" in node:
        vals = node["enum"]
        if not all(isinstance(v, str) for v in vals):
            raise SpecError(f"{where}: enum은 문자열만 허용됩니다({vals})")
        out["enum"] = list(vals)
    for k in ("minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength"):
        if k in node:
            out[k] = node[k]
    unknown = [k for k in node if k not in ALLOWED and k not in MOVE_TO_DESC and k not in DROP
               and k not in ("anyOf", "oneOf", "allOf", "$ref") and not k.startswith("x-")]
    if unknown:
        raise SpecError(f"{where}: 지원하지 않는 키워드 {unknown}")
    if typ == "object":
        props = node.get("properties") or {}
        if not props:
            raise SpecError(f"{where}: properties가 없는 object — 최상위 인자는 *_json 문자열, 중첩은 모델을 단순화하세요")
        out["properties"] = {name: convert(ps, comps, f"{where}.{name}", stack=stack) for name, ps in props.items()}
        req = [r for r in node.get("required") or [] if r in props]
        if req:
            out["required"] = sorted(req)
    elif typ == "array":
        if "items" not in node:
            raise SpecError(f"{where}: array에 items가 없습니다")
        out["items"] = convert(node["items"], comps, f"{where}[]", stack=stack)
    desc = str(node.get("description") or "").strip()
    if notes:
        desc = f"{desc} ({', '.join(notes)})".strip()
    if desc:
        out["description"] = desc
    if nullable:
        out["nullable"] = True
    return out


def convert_arg(name: str, schema: dict[str, Any], comps: dict[str, Any], where: str) -> tuple[str, dict[str, Any], bool]:
    """최상위 인자 하나 → (인자 이름, 스키마, json 문자열로 바꿨는지). 설명 필수·≤ 200자."""
    node = _merge_single(schema, comps, [])
    if node.get("type") == "object" and not node.get("properties"):
        desc = str(node.get("description") or "").strip()
        if not desc:
            raise SpecError(f"{where}.{name}: description이 없습니다")
        out = {"type": "string", "description": f"{desc} — {JSON_ARG_NOTE}"}
        _check_desc(f"{where}.{name}_json", out["description"])
        return f"{name}_json", out, True
    out = convert(schema, comps, f"{where}.{name}")
    if not out.get("description"):
        raise SpecError(f"{where}.{name}: description이 없습니다")
    _check_desc(f"{where}.{name}", out["description"])
    return name, out, False


def _check_desc(where: str, desc: str) -> None:
    if len(desc) > ARG_DESC_MAX:
        raise SpecError(f"{where}: 인자 설명이 {ARG_DESC_MAX}자를 넘습니다({len(desc)}자) — 줄이세요")


def clone(obj: Any) -> Any:
    return copy.deepcopy(obj)
