"""step 핸들러 등록부: (job_type, step_key) → handler(ctx)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import curation, dataset, evaluate, model_register, optimize, package, predict, spdm_import, train, verify

HANDLERS: dict[tuple[str, str], Callable[[Any], None]] = {}
for _mod in (dataset, package, model_register, evaluate, predict, verify, train, curation, spdm_import, optimize):
    HANDLERS.update(_mod.HANDLERS)
