"""Study 관리(stage 0, phase3 §5) step: STUDY_STORAGE_SCAN, STUDY_CLEANUP."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import cleanup, storage_scan

HANDLERS: dict[tuple[str, str], Callable[[Any], None]] = {}
for _mod in (storage_scan, cleanup):
    HANDLERS.update(_mod.HANDLERS)
