"""⑤ 최적화 step: OPTIMIZE."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import optimize

HANDLERS: dict[tuple[str, str], Callable[[Any], None]] = {}
for _mod in (optimize,):
    HANDLERS.update(_mod.HANDLERS)
