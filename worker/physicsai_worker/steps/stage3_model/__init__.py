"""③ 데이터셋·모델 step: DATASET_CREATE, PACKAGE_EXPORT, MODEL_REGISTER, EVALUATE."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import data_health, dataset, evaluate, model_register, package

HANDLERS: dict[tuple[str, str], Callable[[Any], None]] = {}
for _mod in (dataset, data_health, package, model_register, evaluate,):
    HANDLERS.update(_mod.HANDLERS)
