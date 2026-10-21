"""mcp.md V-MCP-14: 생성 파일의 도구 입력 스키마가 이식 가능 부분집합(§9.2 — Claude·Codex·Gemini 공통)인지 **생성기와 별도 구현**으로 다시 확인.

이 파일은 `physicsai_api.mcp.portable`(생성기 변환기)을 import하지 않는다 — 변환기 버그가 검사까지 통과시키지 않게 한다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from physicsai_test_support import REPO

GEN = REPO / "backend" / "physicsai_api" / "mcp" / "generated"
WHITELIST = {"type", "description", "properties", "required", "items", "enum", "minimum", "maximum", "minItems", "maxItems", "minLength",
             "maxLength", "nullable"}
TYPES = {"object", "string", "number", "integer", "boolean", "array"}
TOOL_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
ARG_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
RISKS = {"read", "run", "admin"}


def load(name: str) -> Any:
    return json.loads((GEN / name).read_text(encoding="utf-8"))


def problems(node: Any, where: str, *, top: bool = False) -> list[str]:
    """스키마 노드 하나(재귀) → 문제 목록."""
    out: list[str] = []
    if not isinstance(node, dict):
        return [f"{where}: 객체가 아님"]
    for k in node:
        if k not in WHITELIST:
            out.append(f"{where}: 허용되지 않는 키워드 {k}")
    t = node.get("type")
    if not isinstance(t, str) or t not in TYPES:
        out.append(f"{where}: type은 {sorted(TYPES)} 중 단일 문자열이어야 함({t!r})")
    if "enum" in node and (not isinstance(node["enum"], list) or not node["enum"] or not all(isinstance(v, str) for v in node["enum"])):
        out.append(f"{where}: enum은 비지 않은 문자열 목록이어야 함")
    if "nullable" in node and node["nullable"] is not True:
        out.append(f"{where}: nullable은 true만")
    for k in ("minimum", "maximum"):
        if k in node and (isinstance(node[k], bool) or not isinstance(node[k], (int, float))):
            out.append(f"{where}: {k}는 숫자")
    for k in ("minItems", "maxItems", "minLength", "maxLength"):
        if k in node and (isinstance(node[k], bool) or not isinstance(node[k], int) or node[k] < 0):
            out.append(f"{where}: {k}는 0 이상의 정수")
    if t == "object":
        props = node.get("properties")
        if not isinstance(props, dict) or (not props and not top):
            out.append(f"{where}: 중첩 object는 properties가 비면 안 됨(→ *_json 문자열)")
        for name, sub in (props or {}).items():
            if not ARG_RE.fullmatch(name):
                out.append(f"{where}.{name}: 인자 이름 규칙 위반")
            out += problems(sub, f"{where}.{name}")
        req = node.get("required", [])
        if not isinstance(req, list) or not set(req) <= set(props or {}):
            out.append(f"{where}: required가 properties에 없는 이름을 가리킴")
    else:
        if "properties" in node or "required" in node:
            out.append(f"{where}: object가 아닌데 properties·required가 있음")
    if t == "array":
        if "items" not in node:
            out.append(f"{where}: array에 items 없음")
        else:
            out += problems(node["items"], f"{where}[]")
    elif "items" in node:
        out.append(f"{where}: array가 아닌데 items가 있음")
    return out


def arg_description_problems(schema: dict[str, Any], where: str) -> list[str]:
    out = []
    for name, sub in (schema.get("properties") or {}).items():
        d = sub.get("description")
        if not isinstance(d, str) or not d.strip():
            out.append(f"{where}.{name}: description 없음")
        elif len(d) > 200:
            out.append(f"{where}.{name}: 인자 설명 {len(d)}자 > 200")
    return out


def test_mcp_tools_file_is_portable():
    doc = load("tools.mcp.json")
    tools = doc["tools"]
    assert doc["schema_version"] == 1 and 1 <= len(tools) <= 40
    names = [t["name"] for t in tools]
    assert names == sorted(names) and len(set(names)) == len(names)
    bad: list[str] = []
    for t in tools:
        n = t["name"]
        if not TOOL_RE.fullmatch(n):
            bad.append(f"{n}: 도구 이름 규칙 위반")
        d = t["description"]
        en, sep, ko = d.partition(" / ")
        if not sep or not en.strip() or not ko.strip() or len(d) > 300:
            bad.append(f"{n}: 설명은 '<영어> / <한국어>' ≤ 300자({len(d)}자)")
        s = t["inputSchema"]
        if s.get("type") != "object":
            bad.append(f"{n}: inputSchema 최상위는 object")
        bad += problems(s, f"{n}.inputSchema", top=True)
        bad += arg_description_problems(s, n)
        ann = t["annotations"]
        if ann.get("x-risk") not in RISKS or ann.get("readOnlyHint") != (ann["x-risk"] == "read") or "outputSchema" in t:
            bad.append(f"{n}: annotations·outputSchema 규칙 위반")
        xh = t["x-http"]
        path_args = set(re.findall(r"\{(\w+)\}", xh["path"]))
        declared = {a for a, w in xh["args"].items() if w == "path"}
        if path_args != declared or set(xh["args"]) != set(s["properties"]) or not set(xh["args"].values()) <= {"path", "query", "body"}:
            bad.append(f"{n}: x-http.args가 경로·입력 스키마와 다름")
        for a, body_key in (xh.get("json_string_fields") or {}).items():
            if s["properties"].get(a, {}).get("type") != "string" or not a.endswith("_json") or not body_key:
                bad.append(f"{n}: json_string_fields {a} 규칙 위반")
    assert bad == [], "\n".join(bad)


def test_openai_file_matches_mcp_file():
    mcp = {t["name"]: t for t in load("tools.mcp.json")["tools"]}
    oai = load("tools.openai.json")
    assert [f["function"]["name"] for f in oai] == sorted(mcp)
    bad: list[str] = []
    for f in oai:
        fn = f["function"]
        n = fn["name"]
        if f["type"] != "function" or fn.get("strict") is not False or set(fn) != {"name", "description", "parameters", "strict"}:
            bad.append(f"{n}: OpenAI 함수 형식 위반")
        if fn["parameters"] != mcp[n]["inputSchema"] or fn["description"] != mcp[n]["description"]:
            bad.append(f"{n}: MCP와 OpenAI의 스키마·설명이 다름(같은 이식 가능 스키마를 써야 함)")
        bad += problems(fn["parameters"], f"{n}.parameters", top=True)
    assert bad == [], "\n".join(bad)


def test_job_kinds_and_glossary_files_have_expected_shape():
    """job_kinds.json의 params_schema는 describe_job_kind 리소스(텍스트)용 — 도구 입력이 아니므로 화이트리스트 대상이 아니고 모양만 본다."""
    jk = load("job_kinds.json")
    assert jk["schema_version"] == 1 and jk["kinds"]
    for name, k in jk["kinds"].items():
        assert isinstance(k["version"], int) and k["cost"] in ("heavy", "light") and k["params_schema"]["type"] == "object", name
    g = load("glossary.json")
    assert g["schema_version"] == 1 and {"entities", "job_types", "job_kinds", "feature_abbr", "enums", "error_codes"} <= set(g)


@pytest.mark.parametrize("schema,expect", [
    ({"type": "object", "properties": {"a": {"type": "string", "format": "date"}}}, "허용되지 않는 키워드 format"),
    ({"type": "object", "properties": {"a": {"anyOf": [{"type": "string"}]}}}, "허용되지 않는 키워드 anyOf"),
    ({"type": "object", "properties": {"a": {"$ref": "#/x"}}}, "허용되지 않는 키워드 $ref"),
    ({"type": "object", "properties": {"a": {"type": ["string", "null"]}}}, "단일 문자열"),
    ({"type": "object", "properties": {"a": {"type": "string", "enum": [1, 2]}}}, "enum"),
    ({"type": "object", "properties": {"a": {"type": "object", "properties": {}}}}, "properties가 비면"),
    ({"type": "object", "properties": {"a": {"type": "array"}}}, "items 없음"),
    ({"type": "object", "properties": {"a": {"type": "string", "default": "x"}}}, "허용되지 않는 키워드 default"),
    ({"type": "object", "properties": {"1bad": {"type": "string"}}}, "인자 이름 규칙"),
    ({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["b"]}, "required"),
    ({"type": "object", "properties": {"a": {"type": "object", "properties": {"b": {"type": "string"}}, "additionalProperties": False}}},
     "허용되지 않는 키워드 additionalProperties"),
])
def test_checker_rejects_non_portable_schemas(schema, expect):
    """검사기 자체 시험: 비이식 스키마를 실제로 잡아낸다(통과만 하는 검사기 방지)."""
    assert any(expect in p for p in problems(schema, "x", top=True)), problems(schema, "x", top=True)


def test_checker_accepts_a_portable_schema():
    ok = {"type": "object", "required": ["a"], "properties": {
        "a": {"type": "string", "description": "d", "enum": ["x", "y"]}, "b": {"type": "integer", "minimum": 1, "maximum": 5, "nullable": True},
        "c": {"type": "array", "items": {"type": "number"}, "minItems": 1}}}
    assert problems(ok, "x", top=True) == []
