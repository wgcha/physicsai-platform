"""시험 공용 상수(REPO·FAKE_TOOLS·IS_WINDOWS·LIMITER)와 backend·worker import 경로 등록."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FAKE_TOOLS = Path(__file__).resolve().parent / "fake_tools"
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "worker"))

IS_WINDOWS = os.name == "nt"
# 시험 설정의 제한기: Linux는 posix, Windows는 실제 Job Object
LIMITER = "windows_job" if IS_WINDOWS else "posix"
