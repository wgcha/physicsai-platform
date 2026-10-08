"""SimLab tpl 렌더(§8.9 TPL_RENDER).

`{parameter(VAR, "NAME", …)}` 줄 제거, 본문의 `{VAR, FMT}`를 `FMT % 값`으로 치환(정수 형식은 반영값).
"""

from __future__ import annotations

import re
from typing import Any

from .errors import StepFailure

PARAM_DECL_RE = re.compile(r'\{\s*parameter\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"([^"]+)"[^)]*\)\s*\}')
PARAM_LINE_RE = re.compile(r"(?m)^[^\n]*\{\s*parameter\(.*?\)\s*\}[^\n]*\n?")
VAR_REF_RE = re.compile(r"\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*(%[-0-9.]*[A-Za-z])\s*\}")
VALID_FMT_RE = re.compile(r"^%[-0-9.]*[idfeEgG]$")


def parse_tpl(text: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    """(var → 파라미터 이름, [{var, name, format}])."""
    text = text.lstrip("﻿")
    decl = {m.group(1): m.group(2) for m in PARAM_DECL_RE.finditer(text)}
    body = PARAM_LINE_RE.sub("", text)
    refs: list[dict[str, str]] = []
    seen = set()
    for m in VAR_REF_RE.finditer(body):
        var, fmt = m.group(1), m.group(2)
        if (var, fmt) in seen:
            continue
        seen.add((var, fmt))
        refs.append({"var": var, "name": decl.get(var, ""), "format": fmt})
    return decl, refs


def render_tpl(text: str, values_by_name: dict[str, float], applied_by_name: dict[str, float]) -> str:
    text = text.lstrip("﻿")
    decl = {m.group(1): m.group(2) for m in PARAM_DECL_RE.finditer(text)}
    body = PARAM_LINE_RE.sub("", text)

    def sub(m: re.Match[str]) -> str:
        var, fmt = m.group(1), m.group(2)
        name = decl.get(var)
        if name is None or name not in values_by_name:
            raise StepFailure("INPUT_INVALID", f"tpl 변수 '{var}'에 대응하는 파라미터 값이 없습니다")
        if not VALID_FMT_RE.match(fmt):
            raise StepFailure("INPUT_INVALID", f"tpl 형식 '{fmt}'을 쓸 수 없습니다")
        v: Any = applied_by_name.get(name, values_by_name[name])
        if fmt[-1] in "id":
            v = int(v)
        return fmt % v

    out = VAR_REF_RE.sub(sub, body)
    leftover = re.search(r"\{\s*var_[A-Za-z0-9_]*\b[^}]*\}", out)
    if leftover:
        raise StepFailure("INPUT_INVALID", f"정의되지 않은 변수 참조가 남았습니다: {leftover.group(0)}")
    return out
