"""도구 스펙 생성(mcp.md §9): openapi `x-mcp.tool` operation → MCP tool JSON·OpenAI function JSON·용어집·작업 종류 스키마.

결정적: 키 정렬·ensure_ascii=False·indent 2·끝 줄바꿈, 시각·경로 미포함. CLI는 `scripts/gen_tool_specs.py`.
입력 스키마는 이식 가능 부분집합(§9.2, `portable.py`) — Claude·Codex·Gemini 공통, MCP와 OpenAI 형식이 같은 스키마를 쓴다.
호환 검사(§9 MR-12): 같은 이름 도구에서 인자 제거·타입 변경·새 필수 인자, 비deprecated 도구 삭제 → 실패(새 이름 `<tool>_v2`).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import portable
from .glossary import GENERATED_DIR
from .portable import SpecError

FILES = ("tools.mcp.json", "tools.openai.json", "glossary.json", "job_kinds.json")
TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
ARG_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
MAX_TOOLS = 40
TOOL_DESC_MAX = 300
API_PREFIX = "/physicsai"  # x-http.path는 이 접두를 뗀 `/api/...`(stdio 실행기가 PHYSICSAI_MCP_URL 뒤에 붙인다)


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def tool_operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    out = []
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if isinstance(op, dict) and isinstance(op.get("x-mcp"), dict) and op["x-mcp"].get("tool"):
                out.append((path, method, op))
    names = [op["x-mcp"]["tool"] for _, _, op in out]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise SpecError(f"도구 이름 중복: {dup}")
    return sorted(out, key=lambda x: x[2]["x-mcp"]["tool"])


def _tool_description(x: dict[str, Any], where: str) -> str:
    en, ko = str(x.get("summary_en") or "").strip(), str(x.get("summary_ko") or "").strip()
    if not en or not ko:
        raise SpecError(f"{where}: x-mcp.summary_en·summary_ko가 모두 필요합니다")
    desc = f"{en} / {ko}"
    if len(desc) > TOOL_DESC_MAX:
        raise SpecError(f"{where}: 도구 설명이 {TOOL_DESC_MAX}자를 넘습니다({len(desc)}자)")
    return desc


def input_schema(spec: dict[str, Any], op: dict[str, Any], where: str) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    """경로·쿼리·본문 인자를 한 객체로 평탄화 → (이식 가능 inputSchema, 인자→위치, json 문자열 인자→본문 필드). 이름 충돌은 생성 실패."""
    comps = spec.get("components", {}).get("schemas", {})
    props: dict[str, Any] = {}
    required: list[str] = []
    where_of: dict[str, str] = {}
    json_fields: dict[str, str] = {}

    def add(raw_name: str, schema: dict[str, Any], loc: str, req: bool) -> None:
        name, ps, as_json = portable.convert_arg(raw_name, schema, comps, where)
        if not ARG_NAME_RE.fullmatch(name):
            raise SpecError(f"{where}: 인자 이름 {name!r}이 ^[a-zA-Z_][a-zA-Z0-9_]{{0,63}}$를 어깁니다")
        if name in props:
            raise SpecError(f"{where}: 인자 이름 충돌 {name}({where_of[name]}·{loc})")
        props[name] = ps
        where_of[name] = loc
        if as_json:
            json_fields[name] = raw_name
        if req:
            required.append(name)

    for prm in op.get("parameters") or []:
        if prm.get("in") not in ("path", "query"):
            continue
        sch = dict(prm.get("schema") or {})
        if prm.get("description") and not sch.get("description"):
            sch["description"] = prm["description"]
        add(prm["name"], sch, prm["in"], bool(prm.get("required")))
    body = (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema")
    if body:
        b = portable._merge_single(body, comps, [])
        for name, ps in (b.get("properties") or {}).items():
            add(name, ps, "body", name in (b.get("required") or []))
    out: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        out["required"] = sorted(required)
    return out, where_of, json_fields


def build(spec: dict[str, Any], glossary: dict[str, Any], job_kinds: dict[str, Any]) -> dict[str, str]:
    tools_mcp, tools_oai = [], []
    ops = tool_operations(spec)
    if len(ops) > MAX_TOOLS:
        raise SpecError(f"도구가 {MAX_TOOLS}개를 넘습니다({len(ops)}) — 굵은 도구 소수 원칙")
    for path, method, op in ops:
        x = op["x-mcp"]
        name = x["tool"]
        where = f"{method.upper()} {path} (도구 {name})"
        if not TOOL_NAME_RE.fullmatch(name):
            raise SpecError(f"{where}: 도구 이름이 ^[a-zA-Z0-9_-]{{1,64}}$를 어깁니다")
        schema, args_in, json_fields = input_schema(spec, op, where)
        desc = _tool_description(x, where)
        risk = x.get("risk", "read")
        rel = path[len(API_PREFIX):] if path.startswith(API_PREFIX) else path
        xhttp: dict[str, Any] = {"method": method.upper(), "path": rel, "operationId": op.get("operationId"), "args": args_in}
        if json_fields:
            xhttp["json_string_fields"] = json_fields
        tools_mcp.append({
            "name": name, "description": desc, "inputSchema": schema,
            "annotations": {"readOnlyHint": risk == "read", "destructiveHint": risk != "read", "x-risk": risk,
                            "x-confirm": x.get("confirm", "never"), "x-version": x.get("version", 1),
                            "x-deprecated": bool(x.get("deprecated"))},
            "x-http": xhttp,
        })
        tools_oai.append({"type": "function", "function": {"name": name, "description": desc, "parameters": schema, "strict": False}})
    mcp_doc = {"schema_version": 1, "generated_from": f"openapi {spec.get('info', {}).get('version', '')}".strip(), "tools": tools_mcp}
    return {"tools.mcp.json": dumps(mcp_doc), "tools.openai.json": dumps(tools_oai), "glossary.json": dumps(glossary),
            "job_kinds.json": dumps(job_kinds)}


def job_kinds_doc() -> dict[str, Any]:
    from .job_kinds import JOB_KINDS

    return {"schema_version": 1, "kinds": {k.kind: {"version": k.version, "cost": k.cost, "params_schema": k.params_model.model_json_schema()}
                                           for k in sorted(JOB_KINDS.values(), key=lambda x: x.kind)}}


def generate() -> dict[str, str]:
    from ..export_openapi import build_openapi
    from . import glossary as g

    spec = build_openapi()
    gen = g.extract(spec)
    return build(spec, gen, job_kinds_doc())


# ---- 호환 검사 ----------------------------------------------------------------------------------------


def _type_sig(ps: dict[str, Any]) -> str:
    if "$ref" in ps:
        return "ref:" + str(ps["$ref"]).rsplit("/", 1)[-1]
    if "anyOf" in ps:
        return "|".join(sorted(_type_sig(x) for x in ps["anyOf"]))
    t = ps.get("type")
    return ",".join(sorted(t)) if isinstance(t, list) else str(t)


def _compat_schema(label: str, old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    probs = []
    op, np_ = old.get("properties") or {}, new.get("properties") or {}
    for name in sorted(op):
        if name not in np_:
            probs.append(f"{label}: 인자 제거·이름 변경 {name}")
        elif _type_sig(op[name]) != _type_sig(np_[name]):
            probs.append(f"{label}: 인자 타입 변경 {name}({_type_sig(op[name])} → {_type_sig(np_[name])})")
    for name in sorted(set(new.get("required") or []) - set(old.get("required") or [])):
        probs.append(f"{label}: 새 필수 인자 {name}")
    return probs


def compat_problems(old_mcp: dict[str, Any], new_mcp: dict[str, Any], old_kinds: dict[str, Any] | None = None,
                    new_kinds: dict[str, Any] | None = None) -> list[str]:
    """깨지는 변경 목록(비면 통과). 깨지는 변경은 새 이름(`<tool>_v2`·새 kind)으로, 옛 도구는 deprecated로 1 릴리스 유지."""
    probs: list[str] = []
    old_t = {t["name"]: t for t in old_mcp.get("tools") or []}
    new_t = {t["name"]: t for t in new_mcp.get("tools") or []}
    for name, ot in sorted(old_t.items()):
        nt = new_t.get(name)
        if nt is None:
            if not (ot.get("annotations") or {}).get("x-deprecated"):
                probs.append(f"도구 {name} 삭제 — 먼저 deprecated로 1 릴리스 유지하세요")
            continue
        probs += _compat_schema(f"도구 {name}", ot.get("inputSchema") or {}, nt.get("inputSchema") or {})
    ok, nk = (old_kinds or {}).get("kinds") or {}, (new_kinds or {}).get("kinds") or {}
    for name, o in sorted(ok.items()):
        n = nk.get(name)
        if n is None:
            probs.append(f"작업 종류 {name} 삭제 — 새 이름을 쓰고 옛 종류는 1 릴리스 유지하세요")
            continue
        probs += _compat_schema(f"작업 종류 {name}", o.get("params_schema") or {}, n.get("params_schema") or {})
    return probs


def read_disk(out_dir: Path = GENERATED_DIR) -> dict[str, str | None]:
    return {f: (out_dir / f).read_text(encoding="utf-8") if (out_dir / f).is_file() else None for f in FILES}
