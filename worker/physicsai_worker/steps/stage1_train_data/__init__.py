"""① 학습데이터 생성 step(phase2 §6.2, §6.4~§6.6.1): TD_EXTRACT_PARAMS, TD_DOE_GEN, TD_SOLVE, TD_RESULT_IMPORT, TD_RESP_EXTRACT."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import doe_gen, extract, resp_extract, result_import, solve

HANDLERS: dict[tuple[str, str], Callable[[Any], None]] = {}
for _mod in (extract, doe_gen, solve, result_import, resp_extract,):
    HANDLERS.update(_mod.HANDLERS)
