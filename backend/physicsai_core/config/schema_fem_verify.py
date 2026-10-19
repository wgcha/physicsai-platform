"""설정 스키마 — ④ 조립 FEM 검증 절 `fem_verify`(phase3 §21.3.10 S16). 기본값은 이 파일 한 곳."""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

from pydantic import Field

from ._model import _M

if TYPE_CHECKING:
    from .schema import ConfigIssue, Settings

# §15.3과 같은 문자 규칙(64자, " { } [ ] $ \ ; | ·제어문자 금지)
_FIELD_FORBIDDEN = re.compile(r'["{}\[\]$\;|]|[\x00-\x1f\x7f]')
_DIR_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{0,63}")


class FemVerifyCfg(_M):
    enabled: bool = True
    dir_name: str = "04_verify"
    max_active: int = 4  # Study당 진행 중(WAITING_PREDICT·RUNNING) 상한, 1~20
    field_map: dict[str, str] = Field(default_factory=dict)  # 예측 h3d 결과 이름 → FEM h3d 결과 이름(E4-14-F2)
    legend_subcase: int = 1
    auto_isolate_cushion: bool = True  # mesh_only면 FEM 컨투어를 include의 /PART id로 격리(E4-14-F3)
    zero_tol: float = 1.0e-12
    max_assem_files: int = 500
    max_assem_bytes: int = 2147483648
    include_scan_max_bytes: int = 16777216
    max_pred_h3d_copy_bytes: int = 4294967296


def field_text_problem(v: str) -> bool:
    return not v.strip() or len(v) > 64 or bool(_FIELD_FORBIDDEN.search(v))


def validate_fem_verify(s: Settings, issues: list[ConfigIssue]) -> None:
    from ..paths import ALL_OUTPUT_DIRS
    from .schema import ConfigIssue as issue

    f = s.fem_verify
    reserved = {d.casefold() for d in ALL_OUTPUT_DIRS} | {"_platform", "01_train", "02_import", "02_curated",
                                                          s.predict_batch.dir_name.casefold()}
    if not _DIR_RE.fullmatch(f.dir_name) or f.dir_name.casefold() in reserved:
        issues.append(issue("fem_verify.dir_name", "Study 직계 폴더 이름(영숫자·_·-, 64자 이내), 다른 산출 폴더와 다른 이름"))
    if not 1 <= f.max_active <= 20:
        issues.append(issue("fem_verify.max_active", "1~20"))
    if any(field_text_problem(k) or field_text_problem(v) for k, v in f.field_map.items()) or len(f.field_map) > 100:
        issues.append(issue("fem_verify.field_map", '키·값 1~64자, 따옴표·괄호·$·\\·;·|·제어문자 없음(최대 100쌍)'))
    if not 1 <= f.legend_subcase <= 100000:
        issues.append(issue("fem_verify.legend_subcase", "1 이상"))
    if not (math.isfinite(f.zero_tol) and 0 <= f.zero_tol <= 1):
        issues.append(issue("fem_verify.zero_tol", "0~1"))
    for k, lo, hi in (("max_assem_files", 1, 100000), ("max_assem_bytes", 1048576, 1099511627776),
                      ("include_scan_max_bytes", 1024, 1073741824), ("max_pred_h3d_copy_bytes", 1048576, 1099511627776)):
        if not lo <= getattr(f, k) <= hi:
            issues.append(issue(f"fem_verify.{k}", f"{lo}~{hi}"))
