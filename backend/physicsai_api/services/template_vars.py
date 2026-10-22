"""템플릿 변수 풀의 엔진 분기(altair-vars.md §5.1): Native = 피처 파일의 그룹 대표(`native_vars_api.set_pool`, 현행 규칙),
Altair = tpl 선언 행(`native_vars.altair_pool`). 그 밖의 변수 정의 API·실행 규칙은 엔진 무관으로 같은 코드를 쓴다.

범위 표지(AV-3): 세트 폴더 tpl에 `# physicsai-tpl scope=full v=1` 줄이 있으면 전체 tpl(변수 정의 편집 가능), 없으면 부분 tpl(옛 것·수작업).
"""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.fileutil import sha256_file
from physicsai_core.geometry import native_vars as nv
from physicsai_core.naming import TPL_NAME
from physicsai_core.stage1_train_data import train_tpl
from physicsai_core.tpl_render import parse_declarations

from ..context import AppContext
from .geometry_gate import engine_of

SCOPE_FULL = "full"
SCOPE_PARTIAL = "partial"
PARTIAL_REASON = "TPL_SCOPE_PARTIAL"
PARTIAL_MESSAGE = "옛 tpl(사용 파라미터만) — ①-2에서 tpl을 다시 생성해 새 템플릿으로 등록하세요"


def is_altair(p: dict[str, Any] | None) -> bool:
    return engine_of(p) != "native"


def tpl_scope(S: str) -> str | None:
    """Altair 세트 폴더의 tpl 범위(full | partial). tpl 파일이 없으면 None."""
    return train_tpl.scope_of_file(os.path.join(S, TPL_NAME))


def altair_pool(ctx: AppContext, p: dict[str, Any], S: str) -> tuple[list[dict[str, Any]], str | None]:
    """(Altair 풀, tpl 파일 sha256). tpl이 없거나 읽을 수 없으면 ([], None)."""
    path = os.path.join(S, TPL_NAME)
    try:
        with open(path, encoding="utf-8-sig") as fh:
            text = fh.read()
        sha: str | None = sha256_file(path)
    except (OSError, UnicodeDecodeError):
        return [], None
    return nv.altair_pool(parse_declarations(text), p.get("tpl_params") or [], p.get("parameters") or []), sha


def pool_for(ctx: AppContext, p: dict[str, Any], S: str) -> tuple[list[dict[str, Any]], str | None]:
    """엔진별 변수 풀과 풀 출처 해시(Native = 피처 파일, Altair = tpl)."""
    if is_altair(p):
        return altair_pool(ctx, p, S)
    from .native_vars_api import set_pool

    return set_pool(ctx, S)


def engine_label(p: dict[str, Any] | None) -> str:
    return "altair" if is_altair(p) else "native"
