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
# 선언 전체(이름·공칭·하한·상한 인자 포함) — 전체 tpl(altair-vars.md AV-1)의 공칭·고정 판정에 쓴다
PARAM_DECL_FULL_RE = re.compile(
    r'\{\s*parameter\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"([^"]+)"\s*,\s*([^,()]+?)\s*,\s*([^,()]+?)\s*,\s*([^,()]+?)\s*\)\s*\}')

# 전체 tpl 범위 표지(altair-vars.md AV-3): 이 줄이 있는 tpl = 전체 tpl, 없으면 부분 tpl(옛 것·사용자 수작업)
SCOPE_LINE = "# physicsai-tpl scope=full v=1"
SCOPE_RE = re.compile(r"(?m)^[ \t]*#[ \t]*physicsai-tpl[ \t]+scope=full[ \t]+v=\d+[ \t]*\r?$")
SCOPE_HEAD_BYTES = 65536  # 표지 줄은 parameter 블록 바로 뒤(파일 앞부분) — 파일 앞쪽만 읽어 판정


def scope_of(text: str) -> str:
    """"full"(표지 줄 있음) | "partial"."""
    return "full" if SCOPE_RE.search(text.lstrip("\ufeff")) else "partial"


def scope_of_file(path: str) -> str | None:
    """tpl 파일 앞부분만 읽어 범위 판정. 파일이 없거나 읽을 수 없으면 None."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(SCOPE_HEAD_BYTES)
    except OSError:
        return None
    return scope_of(head.decode("utf-8", errors="ignore"))


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


def parse_declarations(text: str) -> list[dict[str, Any]]:
    """선언 순서대로 [{var, name, nominal, min, max}](숫자가 아니면 None). 인자 형식이 다른 선언은 nominal·min·max = None."""
    text = text.lstrip("﻿")
    out: list[dict[str, Any]] = []
    full = {m.group(1): m for m in PARAM_DECL_FULL_RE.finditer(text)}
    for m in PARAM_DECL_RE.finditer(text):
        fm = full.get(m.group(1))
        nums: list[float | None] = [None, None, None]
        if fm is not None:
            for i in range(3):
                try:
                    f = float(fm.group(3 + i))
                except ValueError:
                    continue
                nums[i] = f if f == f and abs(f) != float("inf") else None
        out.append({"var": m.group(1), "name": m.group(2), "nominal": nums[0], "min": nums[1], "max": nums[2]})
    return out


def format_value(fmt: str, v: float) -> str:
    """`{VAR, FMT}` 자리에 들어가는 문자열(`render_tpl`과 같은 규칙 — 정수 형식(i·d)은 int(v))."""
    if not VALID_FMT_RE.match(fmt):
        raise StepFailure("INPUT_INVALID", f"tpl 형식 '{fmt}'을 쓸 수 없습니다")
    return fmt % (int(v) if fmt[-1] in "id" else v)


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
        return format_value(fmt, v)

    out = VAR_REF_RE.sub(sub, body)
    leftover = re.search(r"\{\s*var_[A-Za-z0-9_]*\b[^}]*\}", out)
    if leftover:
        raise StepFailure("INPUT_INVALID", f"정의되지 않은 변수 참조가 남았습니다: {leftover.group(0)}")
    return out
