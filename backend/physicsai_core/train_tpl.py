"""①-2 tpl 생성(phase2 §6.3). 원본 update_parameter_file(1_CREATE_TRAINING_DATA/FUNC/1_create_tpl_file.py:127-193)을
우리 코드로 재구현한다. 정규식·marker는 설정(train_data.*)에서 읽는다.

차이(계약): 사용하지 않는 파라미터는 두 블록 모두에서 뺀다(가정 A-5), anchor가 없으면 오류(가정 A-4), 행별 형식.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .tpl_render import VALID_FMT_RE, parse_tpl

ANCHOR = '<Parameters Value="">'


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


def generate(template_text: str, params: list[dict[str, Any]], cad_file_name: str, rules: TplRules) -> str:
    """params = 사용 파라미터(표 순서) [{name, nominal, min, max, format}]. 실패 시 TplTemplateInvalid."""
    text = template_text.lstrip("﻿\r\n\t ")  # :130-132
    text = re.sub(rules.prt_regex, lambda _m: f'dir_file_prt = r"./{cad_file_name}"', text)  # :135-139
    parameter_block = "\n".join(
        f'{{parameter(var_{i}, "{p["name"]}", {num_text(p["nominal"])}, {num_text(p["min"])}, {num_text(p["max"])})}}'
        for i, p in enumerate(params, start=1)
    )
    text = re.sub(rules.parameter_line_regex, "", text)  # :153-157
    pos = text.find(rules.marker)  # :159-162
    if pos == -1:
        raise TplTemplateInvalid([{"code": "TPL_MARKER_MISSING", "message": "tpl 템플릿에서 marker 줄을 찾지 못했습니다"}])
    text = parameter_block + "\n" + text[pos:]
    paramitem_block = "\n".join(
        f'   <paramitem Name="{p["name"]}" NewValue="{{var_{i}, {p["format"]}}}" Value="{num_text(p["nominal"])}"/>'
        for i, p in enumerate(params, start=1)
    )
    text = re.sub(rules.paramitem_line_regex, "", text)  # :177-181
    if ANCHOR not in text:
        raise TplTemplateInvalid([{"code": "TPL_ANCHOR_MISSING", "message": f"tpl 템플릿에 {ANCHOR} 가 없습니다"}])
    text = text.replace(ANCHOR, ANCHOR + "\n" + paramitem_block)  # :183-186
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)  # :188
    return text


def validate_generated(text: str, params: list[dict[str, Any]]) -> list[dict[str, str]]:
    """생성 tpl이 1차 §15.4 검증기(파라미터 이름 집합 일치, {VAR, FMT} 형식)를 통과하는지."""
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


def tpl_params_snapshot(params: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"var": f"var_{i}", "name": p["name"], "format": p["format"]} for i, p in enumerate(params, start=1)]
