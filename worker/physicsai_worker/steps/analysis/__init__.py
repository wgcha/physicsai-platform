"""⑤ 결과분석 step: EQ_CHECK(해석 등가성 판정, equiv-check.md §4.5)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import equiv_check

HANDLERS: dict[tuple[str, str], Callable[[Any], None]] = {}
HANDLERS.update(equiv_check.HANDLERS)
