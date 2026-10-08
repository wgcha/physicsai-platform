"""① 파라미터 표(phase2 §5.1.1, §6.2 TX_PARSE, §6.3 저장 검증).

- XML 파싱은 원본 get_model_parameters(1_CREATE_TRAINING_DATA/FUNC/1_create_tpl_file.py:99-125) 재구현:
  루트 아래 Model/Parameter의 Name·Value 텍스트, 값에서 'mm'·'MM' 제거 후 strip.
- 크기 상한 + DOCTYPE·ENTITY 거부 후 xml.etree.ElementTree로 파싱(phase2 §15.3).
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from typing import Any

from .errors import StepFailure
from .param_sets import NAME_RE

FORMAT_RE = re.compile(r"^%[-0-9.]*[idfeEgG]$")
MAX_RAW = 64
MAX_UNIT = 16


def read_extracted_xml(path: str, max_bytes: int) -> list[tuple[str, str]]:
    """(name, value) 목록. 원본처럼 'mm'·'MM' 제거·strip. 위반 시 StepFailure(INPUT_INVALID)."""
    import os

    size = os.path.getsize(path)
    if size > max_bytes:
        raise StepFailure("INPUT_INVALID", f"추출 XML이 상한({max_bytes} bytes)을 넘습니다: {size} bytes")
    with open(path, "rb") as fh:
        data = fh.read()
    _reject_dtd(data)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise StepFailure("INPUT_INVALID", f"추출 XML 형식 오류: {exc}") from None
    model = root.find("Model")
    out: list[tuple[str, str]] = []
    if model is None:
        return out
    for param in model.findall("Parameter"):
        n, v = param.find("Name"), param.find("Value")
        if n is None or v is None:
            continue
        name = (n.text or "").strip()
        value = (v.text or "").strip()
        out.append((name, value.replace("mm", "").replace("MM", "").strip()))
    return out


class _DtdFound(Exception):
    pass


def _reject_dtd(data: bytes) -> None:
    """파서(expat) 수준에서 DOCTYPE·ENTITY 선언을 거부한다 — 인코딩(UTF-8/16·BOM·XML 선언)과 무관(phase2 §15.3).

    expat이 모르는 인코딩(UTF-32 등)은 형식 오류로 거부된다.
    """
    from xml.parsers import expat

    def found(*_a: Any) -> None:
        raise _DtdFound()

    p = expat.ParserCreate()
    p.StartDoctypeDeclHandler = found
    p.EntityDeclHandler = found
    p.UnparsedEntityDeclHandler = found
    p.ExternalEntityRefHandler = found
    p.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        p.Parse(data, True)
    except _DtdFound:
        raise StepFailure("INPUT_INVALID", "추출 XML에 DOCTYPE·ENTITY 선언이 있어 거부했습니다") from None
    except expat.ExpatError as exc:
        raise StepFailure("INPUT_INVALID", f"추출 XML 형식 오류: {exc}") from None


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def default_range(nominal: float, ratio: float) -> tuple[float, float]:
    """원본 GUI(1_gui_create_tpl_file.py:295-302) ±ratio, round 4자리. 음수 공칭도 min ≤ max가 되게 정렬."""
    a, b = round(nominal * (1 - ratio), 4), round(nominal * (1 + ratio), 4)
    return (min(a, b), max(a, b))


def problems_of(p: dict[str, Any]) -> list[str]:
    """행 문제 코드 목록(서버 계산 valid·problems)."""
    probs: list[str] = []
    if not NAME_RE.match(p.get("name") or ""):
        probs.append("NAME_INVALID")
    nom, lo, hi = p.get("nominal"), p.get("min"), p.get("max")
    if nom is None:
        probs.append("NOMINAL_NOT_NUMBER")
    if lo is None or hi is None:
        probs.append("RANGE_NOT_NUMBER")
    elif not lo < hi:
        probs.append("RANGE_INVALID")
    elif nom is not None and not lo <= nom <= hi:
        probs.append("NOMINAL_OUT_OF_RANGE")
    if not FORMAT_RE.match(p.get("format") or ""):
        probs.append("FORMAT_INVALID")
    return probs


def with_validity(p: dict[str, Any]) -> dict[str, Any]:
    q = dict(p)
    q["problems"] = problems_of(q)
    q["valid"] = not q["problems"]
    return q


def build_from_extracted(pairs: list[tuple[str, str]], ratio: float, default_format: str) -> list[dict[str, Any]]:
    out = []
    for name, raw in pairs:
        nom = _num(raw)
        lo, hi = default_range(nom, ratio) if nom is not None else (None, None)
        row = {"name": name, "raw_nominal": raw[:MAX_RAW], "nominal": nom, "min": lo, "max": hi, "use": True,
               "format": default_format, "unit": ""}
        row = with_validity(row)
        row["use"] = row["valid"]
        out.append(row)
    return out


MESSAGES = {
    "NAME_INVALID": "파라미터 이름이 규칙(^[A-Za-z_][A-Za-z0-9_]{0,63}$)에 맞지 않습니다",
    "NOMINAL_NOT_NUMBER": "공칭값이 숫자가 아닙니다",
    "RANGE_NOT_NUMBER": "하한·상한이 숫자가 아닙니다",
    "RANGE_INVALID": "하한 < 상한 이어야 합니다",
    "NOMINAL_OUT_OF_RANGE": "하한 ≤ 공칭 ≤ 상한 이어야 합니다",
    "FORMAT_INVALID": "형식은 %[-0-9.]*[idfeEgG] 이어야 합니다(예 %3i, %8.4f)",
}


def apply_update(current: list[dict[str, Any]], updates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """PUT /train/params(phase2 §6.3): 이름으로 대응, min·max·use·format·unit만 변경. (새 표, problems)."""
    problems: list[dict[str, str]] = []
    by_name = {p["name"]: p for p in current}
    names_upd = [u["name"] for u in updates]
    if len(set(names_upd)) != len(names_upd):
        problems.append({"name": "", "code": "DUPLICATE", "message": "같은 이름의 행이 여러 개입니다"})
    unknown = [n for n in names_upd if n not in by_name]
    missing = [n for n in by_name if n not in names_upd]
    for n in unknown:
        problems.append({"name": n, "code": "UNKNOWN", "message": "추출되지 않은 파라미터입니다"})
    for n in missing:
        problems.append({"name": n, "code": "MISSING_ROW", "message": "모든 행을 보내야 합니다"})
    if problems:
        return current, problems
    upd = {u["name"]: u for u in updates}
    new: list[dict[str, Any]] = []
    for p in current:
        u = upd[p["name"]]
        row = dict(p)
        row["min"] = _num(u.get("min"))
        row["max"] = _num(u.get("max"))
        row["use"] = bool(u.get("use"))
        if u.get("format") is not None:
            row["format"] = str(u["format"])
        if u.get("unit") is not None:
            row["unit"] = str(u["unit"])[:MAX_UNIT]
        row = with_validity(row)
        new.append(row)
        if row["use"]:
            for code in row["problems"]:
                problems.append({"name": row["name"], "code": code, "message": MESSAGES.get(code, code)})
    if not any(r["use"] for r in new):
        problems.append({"name": "", "code": "NO_PARAMETER_USED", "message": "사용할 파라미터가 1개 이상 필요합니다"})
    return new, problems


def used(params: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in params if p.get("use")]


def integer_format_warnings(params: list[dict[str, Any]]) -> list[dict[str, str]]:
    """정수 형식(i/d)인데 min·max·nominal 중 비정수가 있으면 경고(U23)."""
    names = []
    for p in used(params):
        fmt = p.get("format") or ""
        if fmt[-1:] in ("i", "d"):
            vals = [p.get("nominal"), p.get("min"), p.get("max")]
            if any(v is not None and float(v) != int(float(v)) for v in vals):
                names.append(p["name"])
    if not names:
        return []
    return [{"code": "TPL_INTEGER_FORMAT",
             "message": f"정수 형식(%3i)이라 HyperStudy 샘플 값이 정수로 반영됩니다: {', '.join(names)}"}]


def definition_key(params: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """tpl에 영향을 주는 사용 행 정의(표 변경 감지용)."""
    return [(p["name"], p.get("nominal"), p.get("min"), p.get("max"), p.get("format")) for p in used(params)]


class RunDirMatcher:
    """①-5 결과 폴더 이름 → DOE run_key(phase2 §6.6, 변경 메모 C13).

    대소문자 무시는 run_key 그룹에만 적용한다: 정확 일치가 아니면 IGNORECASE로 맞춘 뒤 그룹 부분을 DOE run_key로
    바꾼 이름이 대소문자 구분 정규식에도 맞아야 한다(접두·접미부는 정확히).
    """

    def __init__(self, pattern: str, run_keys: set[str] | None) -> None:
        self.rx = re.compile(pattern)
        self.rx_i = re.compile(pattern, re.IGNORECASE)
        self.by_lower = {k.lower(): k for k in run_keys} if run_keys is not None else None

    def match(self, name: str) -> str | None:
        m = self.rx.match(name)
        if m:
            rk = m.group("run_key")
            if self.by_lower is None:
                return rk
            if rk in self.by_lower.values():
                return rk
        m = self.rx_i.match(name)
        if not m:
            return None
        got = m.group("run_key")
        key = self.by_lower.get(got.lower()) if self.by_lower is not None else got.lower()
        if key is None:
            return None
        s, e = m.span("run_key")
        cand = name[:s] + key + name[e:]
        m2 = self.rx.match(cand)
        return key if m2 and m2.group("run_key") == key else None
