"""설정 검사 — phase3 §18.9 surrogate_opt 정수 키 범위·폴더 이름 — validate에서 재노출."""

from __future__ import annotations

import re

from .schema import (
    ConfigIssue,
    Settings,
)

# phase3 §18.9: surrogate_opt 정수 키 범위
SURROGATE_OPT_RANGES: dict[str, tuple[int, int]] = {
    "max_variables": (1, 50), "max_iterations": (1, 50), "max_candidates": (1, 50), "default_iterations": (1, 50),
    "default_candidates": (1, 50), "gp_restarts": (1, 64), "de_maxiter": (1, 10000), "de_popsize": (2, 200),
    "fit_timeout_s": (10, 86400), "blas_threads": (1, 256),
    # S17 §22.11
    "max_objectives": (1, 3), "max_observe": (0, 50), "max_extra_points": (1, 50), "mo_lattice_h2": (2, 20),
    "mo_lattice_h3": (2, 20), "mo_de_maxiter": (1, 10000), "mo_gp_restarts": (1, 64),
}
_SO_DIR_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{0,63}(/[A-Za-z0-9][A-Za-z0-9_\-]{0,63}){0,3}")


def _validate_surrogate_opt(s: Settings, issues: list[ConfigIssue]) -> None:
    so = s.surrogate_opt
    for k, (lo, hi) in SURROGATE_OPT_RANGES.items():
        if not lo <= getattr(so, k) <= hi:
            issues.append(ConfigIssue(f"surrogate_opt.{k}", f"{lo}~{hi}"))
    if so.default_iterations > so.max_iterations:
        issues.append(ConfigIssue("surrogate_opt.default_iterations", "max_iterations 이하"))
    if so.default_candidates > so.max_candidates:
        issues.append(ConfigIssue("surrogate_opt.default_candidates", "max_candidates 이하"))
    if not 0.0 < so.default_tol_rel < 1.0:
        issues.append(ConfigIssue("surrogate_opt.default_tol_rel", "0 초과 1 미만"))
    if so.default_surrogate not in ("gp", "rbf"):
        issues.append(ConfigIssue("surrogate_opt.default_surrogate", "gp | rbf"))
    if not 0.0 <= so.mo_rho <= 1.0:
        issues.append(ConfigIssue("surrogate_opt.mo_rho", "0~1"))
    if not 0.0 <= so.mo_hvi_share_m3 <= 1.0:
        issues.append(ConfigIssue("surrogate_opt.mo_hvi_share_m3", "0~1"))
    if not 0.0 <= so.mo_front_prox_m3 <= 50.0:
        issues.append(ConfigIssue("surrogate_opt.mo_front_prox_m3", "0~50"))
    if not 0.01 <= so.mo_ref_offset <= 1.0:
        issues.append(ConfigIssue("surrogate_opt.mo_ref_offset", "0.01~1"))
    from ..stage5_optimize.surrogate.algo import config_issues  # opt-native §9

    for k, rng in config_issues(so):
        issues.append(ConfigIssue(f"surrogate_opt.{k}", rng))
    if not _SO_DIR_RE.fullmatch(so.dir_name) or so.dir_name.split("/")[0].casefold() in ("_platform", "_backup"):
        issues.append(ConfigIssue("surrogate_opt.dir_name", "Study 기준 상대 폴더(영숫자·_·-, '/' 구분, 4단계 이내)"))
