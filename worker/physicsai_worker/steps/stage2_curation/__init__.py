"""② 데이터 정리 step(phase2 §6.7~§6.10) + SPDM 가져오기: CU_H3D_PREVIEW, CU_H3D_CURATE, CU_T01_PREVIEW, CU_T01_CURVES, SPDM_IMPORT."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import h3d_curate, preview, spdm_import, t01_curves

HANDLERS: dict[tuple[str, str], Callable[[Any], None]] = {}
for _mod in (preview, h3d_curate, t01_curves, spdm_import,):
    HANDLERS.update(_mod.HANDLERS)
