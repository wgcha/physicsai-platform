"""단계 간 공용 이름 규칙(①·④가 함께 쓰는 파라미터·run 이름 정규식, tpl 파일 이름)."""

from __future__ import annotations

import re
import unicodedata

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
RUN_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
TPL_NAME = "simlab_parametered_mesh.tpl"
TPL_FULL_NAME = "simlab_parametered_mesh.full.tpl"  # 레거시 hstbatch ① DOE 폴더의 전체 tpl 원본(altair-vars.md AV-7)
LABEL_MAX = 120
# 표시 이름에 쓸 수 없는 문자 범주(D3-50): 제어(Cc: NUL·줄바꿈·탭)·서식(Cf: U+202E 등 양방향 제어·영폭 문자)·
# 대리(Cs)·줄/문단 구분자(Zl·Zp). 화면·감사 로그·파일 이름 표시에서 글자 순서를 속이거나 줄을 끊지 못하게 한다.
_LABEL_BAD_CATS = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})


def label_problem(text: str) -> str | None:
    """표시 이름(label) 검사. 문제 없으면 None, 있으면 한국어 사유."""
    bad = sorted({f"U+{ord(c):04X}" for c in text if unicodedata.category(c) in _LABEL_BAD_CATS})
    if bad:
        return "표시 이름에 제어문자·양방향 제어 문자를 쓸 수 없습니다(" + " ".join(bad[:5]) + ")"
    return None
