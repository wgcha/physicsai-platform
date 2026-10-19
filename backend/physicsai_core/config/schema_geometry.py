"""설정 스키마 — native 형상 엔진 절 `geometry`(geometry-engine.md §7.1)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ._model import _M

GEOMETRY_ENGINES = ("altair", "native")
GEOMETRY_TIMEOUT_KEYS = ("extract", "tag", "update", "morph", "check", "run")


def _timeouts() -> dict[str, float | None]:
    return {"extract": 1800, "tag": 1800, "update": 600, "morph": 1800, "check": 1800, "run": 3600}


def _env() -> dict[str, str]:
    return {"OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4", "PAICAD_THREADS": "4"}


class GeometryCfg(_M):
    engine: str = "altair"  # altair | native — 새 파라미터 세트·①-1 추출·①-3 DOE의 기본 엔진
    paicad_path: str = ""  # 빈 값 = 워커 Python 폴더의 Scripts\paicad.exe(Windows)·bin/paicad(그 외)
    step_extensions: list[str] = Field(default_factory=lambda: [".step", ".stp"])
    max_report_bytes: int = 4194304
    progress_regex: str = r"^PAICAD PROGRESS (?P<pct>[0-9.]+) (?P<msg>.*)$"
    timeout_s: dict[str, float | None] = Field(default_factory=_timeouts)
    env: dict[str, str] = Field(default_factory=_env)
    defaults: dict[str, Any] = Field(default_factory=dict)  # §4.9 options.json 기본값 덮어쓰기(코드 기본값 위에 깊은 병합)
