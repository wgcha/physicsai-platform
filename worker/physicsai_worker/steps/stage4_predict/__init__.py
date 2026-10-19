"""④ 예측 step: PREDICT, PREDICT_VERIFY, PREDICT_BATCH(phase3 §14.5), FEM_VERIFY(phase3 §21.3.5 S16)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import batch, capture, fem_compare, fem_verify, predict, verify

HANDLERS: dict[tuple[str, str], Callable[[Any], None]] = {}
for _mod in (predict, verify, batch, capture, fem_verify, fem_compare):
    HANDLERS.update(_mod.HANDLERS)
