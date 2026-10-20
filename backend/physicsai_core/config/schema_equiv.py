"""설정 스키마 — ⑤ 해석 등가성 판정 절 `equiv_check`(equiv-check.md §5.3). 기본값·시스템 기본 레시피(§3.2)는 이 파일 한 곳.

시스템 기본 레시피는 "제안값"(읽기 전용)이다 — 판정 실행에는 사용자가 선택·확인한 레시피(복제본 또는 adhoc)를 쓴다.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Any

from pydantic import Field

from ._model import _M

if TYPE_CHECKING:
    from .schema import ConfigIssue, Settings

_DIR_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{0,63}")

SYSTEM_RECIPE_KEY = "sys:default"
SYSTEM_RECIPE_NAME = "시스템 기본(제안값)"


def default_system_recipe() -> dict[str, Any]:
    """equiv-check.md §3.2 — source는 비어 있고(연결 필요) 실행 화면에서 성능 정의를 연결한다. 응력·접촉력은 참고(제안)."""
    def scalar(mid: str, label: str, rel: float, required: bool) -> dict[str, Any]:
        return {"id": mid, "label": label, "kind": "scalar", "source": None,
                "tol": {"rel_pct": rel, "abs": None}, "required": required}

    return {
        "schema_version": 1,
        "metrics": [
            scalar("accel_peak", "가속도 피크", 5.0, True),
            scalar("cushion_deform", "쿠션 최대 변형", 5.0, True),
            scalar("ie_max", "내부 에너지 최대", 5.0, True),
            scalar("ke_max", "운동 에너지 최대", 5.0, True),
            scalar("stress_peak", "응력 피크", 10.0, False),
            scalar("contact_peak", "접촉력 피크", 10.0, False),
            {"id": "accel_corr", "label": "가속도 곡선 상관", "kind": "curve_corr",
             "source": {"type": "curve", "series": None, "t01": None}, "tol": {"corr_min": 0.95}, "required": True},
            {"id": "volume_diff", "label": "쿠션 부피 차", "kind": "mesh_volume",
             "source": {"type": "mesh_volume", "parts": "cushion", "origin": "mesh"}, "tol": {"rel_pct": 0.1, "abs": None},
             "required": True},
        ],
        "pair_rule": {"mode": "all"},
        "verdict_rule": "required_all",
    }


class EquivCheckCfg(_M):
    enabled: bool = True
    dir_name: str = "05_equiv"
    max_pairs: int = 200
    max_metrics: int = 20
    max_active: int = 2
    curve_points: int = 1000
    curve_min_overlap: float = 0.9
    zero_tol: float = 1.0e-12
    param_match_rel_tol: float = 1.0e-6
    max_extract_copy_bytes: int = 21474836480  # 20 GiB
    system_version: int = 1
    system_recipe: dict[str, Any] = Field(default_factory=default_system_recipe)
    snapshot_max_bytes: int = 65536  # DB summary·recipe_snapshot 상한(V-EQ-9, 64 KiB)


def validate_equiv_check(s: Settings, issues: list[ConfigIssue]) -> None:
    from ..equiv.recipes import validate_definition
    from ..paths import ALL_OUTPUT_DIRS
    from .schema import ConfigIssue as issue

    e = s.equiv_check
    reserved = {d.casefold() for d in ALL_OUTPUT_DIRS} | {"_platform", "01_train", "02_import", "02_curated",
                                                          s.predict_batch.dir_name.casefold(), s.fem_verify.dir_name.casefold()}
    if not _DIR_RE.fullmatch(e.dir_name) or e.dir_name.casefold() in reserved:
        issues.append(issue("equiv_check.dir_name", "Study 직계 폴더 이름(영숫자·_·-, 64자 이내), 다른 산출 폴더와 다른 이름"))
    for k, lo, hi in (("max_pairs", 1, 5000), ("max_metrics", 1, 100), ("max_active", 1, 20), ("curve_points", 10, 100000),
                      ("system_version", 1, 1000000), ("snapshot_max_bytes", 4096, 1048576),
                      ("max_extract_copy_bytes", 1048576, 1099511627776)):
        if not lo <= getattr(e, k) <= hi:
            issues.append(issue(f"equiv_check.{k}", f"{lo}~{hi}"))
    if not (math.isfinite(e.curve_min_overlap) and 0 < e.curve_min_overlap <= 1):
        issues.append(issue("equiv_check.curve_min_overlap", "0 초과 1 이하"))
    if not (math.isfinite(e.zero_tol) and 0 <= e.zero_tol <= 1):
        issues.append(issue("equiv_check.zero_tol", "0~1"))
    if not (math.isfinite(e.param_match_rel_tol) and 0 <= e.param_match_rel_tol <= 1):
        issues.append(issue("equiv_check.param_match_rel_tol", "0~1"))
    probs = validate_definition(e.system_recipe, max_metrics=e.max_metrics, allow_unbound=True)
    if probs:
        issues.append(issue("equiv_check.system_recipe", "; ".join(f"{p['code']}: {p['message']}" for p in probs[:3])))
