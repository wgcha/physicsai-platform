"""⑤ 최적화 step: OPTIMIZE(원본 HyperStudy), SURROGATE_OPT(플랫폼 내장 대리모델, phase3 §18)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import optimize, surrogate

HANDLERS: dict[tuple[str, str], Callable[[Any], None]] = {}
for _mod in (optimize, surrogate):
    HANDLERS.update(_mod.HANDLERS)
