"""④ 단일 예측 step: PREDICT, PREDICT_VERIFY."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import predict, verify

HANDLERS: dict[tuple[str, str], Callable[[Any], None]] = {}
for _mod in (predict, verify,):
    HANDLERS.update(_mod.HANDLERS)
