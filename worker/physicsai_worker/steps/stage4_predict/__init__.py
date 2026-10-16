"""④ 예측 step: PREDICT, PREDICT_VERIFY, PREDICT_BATCH(phase3 §14.5)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import batch, predict, verify

HANDLERS: dict[tuple[str, str], Callable[[Any], None]] = {}
for _mod in (predict, verify, batch):
    HANDLERS.update(_mod.HANDLERS)
