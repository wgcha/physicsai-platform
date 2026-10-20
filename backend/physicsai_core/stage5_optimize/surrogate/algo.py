"""⑥ 내장 최적화 알고리즘·검증 방식 설정 규칙(opt-native §6.1·§6.7·§8) — 표준 라이브러리만(API·워커·설정 검증 공용).

- algorithm: ego(기본, 생략 시) | ga(단일 목적) | nsga2(다목적 2·3).
- algo_options: pop_size·generations·crossover_prob·mutation_prob·eta_c·eta_m(null·생략 = 기본 — 설정 `surrogate_opt`의
  ga_*·nsga2_* 키, pop_size null = §6.7 식). 허용 범위 §6.7, pop_size × generations ≤ ga_max_evals.
- verification: loop(기본) | none(대리모델만, stop_reason SURROGATE_ONLY).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

ALGORITHMS = ("ego", "ga", "nsga2")
VERIFICATIONS = ("loop", "none")
OPTION_KEYS = ("pop_size", "generations", "crossover_prob", "mutation_prob", "eta_c", "eta_m")
ALGO_LABEL = {"ego": "EGO", "ga": "GA", "nsga2": "NSGA-II"}
STOP_SURROGATE_ONLY = "SURROGATE_ONLY"
POP_RANGE = (8, 1000)
GEN_RANGE = (1, 2000)
ETA_RANGE = (1.0, 100.0)


def settings_algorithm(settings: Mapping[str, Any]) -> str:
    """저장 settings의 알고리즘(키 없는 기존 행 = ego)."""
    a = settings.get("algorithm")
    return a if a in ALGORITHMS else "ego"


def settings_verification(settings: Mapping[str, Any]) -> str:
    v = settings.get("verification")
    return v if v in VERIFICATIONS else "loop"


NSGA2_MANY_OBJ = 3  # 목적 수가 이 값 이상이면 NSGA-II 기본 집단 하한을 NSGA2_MANY_OBJ_POP으로 올린다
NSGA2_MANY_OBJ_POP = 200  # 대리모델 위 탐색이라 계산 비용을 무시할 수 있다(DTLZ2 HV 비 0.90~0.91 — ON-C2)


def default_pop_size(algorithm: str, n_g: int, n_obj: int = 2) -> int:
    """§6.7: GA clamp(10·n_g, 40, 200) 짝수, NSGA-II clamp(⌈max(100, 10·n_g)/4⌉·4, 100, 400).

    NSGA-II 목적 수 ≥ 3이면 max(식, 200)(ON-C2). 200은 4의 배수이고 상한 400 이하다."""
    if algorithm == "ga":
        p = min(max(10 * n_g, 40), 200)
        return p + (p % 2)
    p = int(math.ceil(max(100, 10 * n_g) / 4.0) * 4)
    p = min(max(p, 100), 400)
    return max(p, NSGA2_MANY_OBJ_POP) if n_obj >= NSGA2_MANY_OBJ else p


def config_defaults(so: Any) -> dict[str, dict[str, Any]]:
    """`/status.surrogate_opt.algo_defaults`: 설정 기본값(pop_size·mutation_prob null = 변수 수로 정하는 식)."""
    return {
        "ga": {"pop_size": so.ga_pop_size, "generations": so.ga_generations, "crossover_prob": so.ga_crossover_prob,
               "mutation_prob": None, "eta_c": so.ga_eta_c, "eta_m": so.ga_eta_m},
        "nsga2": {"pop_size": so.nsga2_pop_size, "generations": so.nsga2_generations, "crossover_prob": so.ga_crossover_prob,
                  "mutation_prob": None, "eta_c": so.nsga2_eta_c, "eta_m": so.ga_eta_m},
    }


def resolve_options(algorithm: str, given: Mapping[str, Any] | None, n_g: int, so: Any, n_obj: int = 2) -> dict[str, Any]:
    """기본값을 채운 사용값(ego는 {}). mutation_prob null은 그대로 둔다(= 1/n_g, 실행 시 계산)."""
    if algorithm not in ("ga", "nsga2"):
        return {}
    base = config_defaults(so)[algorithm]
    out: dict[str, Any] = {}
    for k in OPTION_KEYS:
        v = (given or {}).get(k)
        out[k] = base[k] if v is None else v
    if out["pop_size"] is None:
        out["pop_size"] = default_pop_size(algorithm, max(n_g, 1), n_obj)
    out["pop_size"] = int(out["pop_size"])
    out["generations"] = int(out["generations"])
    for k in ("crossover_prob", "eta_c", "eta_m"):
        out[k] = float(out[k])
    if out["mutation_prob"] is not None:
        out["mutation_prob"] = float(out["mutation_prob"])
    return out


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def option_problems(algorithm: str, given: Mapping[str, Any] | None, n_g: int, so: Any, n_obj: int = 2) -> list[dict[str, Any]]:
    """algo_options 검사(§6.7·§8 ALGO_OPTIONS_INVALID) — [{code, field, message}]."""
    out: list[dict[str, Any]] = []

    def p(field: str, msg: str) -> None:
        out.append({"code": "ALGO_OPTIONS_INVALID", "field": f"algo_options.{field}" if field else "algo_options",
                    "message": msg})

    g = dict(given or {})
    unknown = [k for k in g if k not in OPTION_KEYS]
    if unknown:
        p("", f"알 수 없는 고급 옵션입니다: {', '.join(sorted(unknown))}")
    if algorithm == "ego":
        if any(v is not None for k, v in g.items() if k in OPTION_KEYS):
            p("", "EGO는 고급 옵션(집단 크기·세대 등)을 쓰지 않습니다")
        return out
    if algorithm not in ("ga", "nsga2"):
        return out
    ps = g.get("pop_size")
    if ps is not None:
        step = 4 if algorithm == "nsga2" else 2
        if not isinstance(ps, int) or isinstance(ps, bool) or not POP_RANGE[0] <= ps <= POP_RANGE[1] or ps % step:
            p("pop_size", f"집단 크기는 {POP_RANGE[0]}~{POP_RANGE[1]}의 {'4의 배수' if step == 4 else '짝수'}입니다")
    gen = g.get("generations")
    if gen is not None and (not isinstance(gen, int) or isinstance(gen, bool) or not GEN_RANGE[0] <= gen <= GEN_RANGE[1]):
        p("generations", f"세대 수는 {GEN_RANGE[0]}~{GEN_RANGE[1]}입니다")
    for k, label in (("crossover_prob", "교차 확률"), ("mutation_prob", "변이 확률")):
        v = g.get(k)
        if v is not None and (not _num(v) or not 0.0 <= float(v) <= 1.0):
            p(k, f"{label}은 0~1입니다")
    for k in ("eta_c", "eta_m"):
        v = g.get(k)
        if v is not None and (not _num(v) or not ETA_RANGE[0] <= float(v) <= ETA_RANGE[1]):
            p(k, f"{'η_c' if k == 'eta_c' else 'η_m'}는 1~100입니다")
    if not out:
        r = resolve_options(algorithm, g, n_g, so, n_obj)
        if r["pop_size"] * r["generations"] > so.ga_max_evals:
            p("", f"집단 크기 × 세대 수({r['pop_size']} × {r['generations']} = {r['pop_size'] * r['generations']})가 "
                  f"상한 {so.ga_max_evals}을 넘습니다")
    return out


def algorithm_problems(algorithm: Any, verification: Any, m: int) -> list[dict[str, Any]]:
    """algorithm·verification 값과 목적 수(§6.1) 검사."""
    out: list[dict[str, Any]] = []
    if algorithm not in ALGORITHMS:
        out.append({"code": "ALGORITHM_INVALID", "field": "algorithm",
                    "message": f"알고리즘은 {' · '.join(ALGORITHMS)} 중 하나입니다"})
    elif (algorithm == "ga" and m >= 2) or (algorithm == "nsga2" and m == 1):
        out.append({"code": "ALGORITHM_MISMATCH", "field": "algorithm",
                    "message": "GA는 단일 목적, NSGA-II는 다목적 전용입니다"})
    if verification not in VERIFICATIONS:
        out.append({"code": "VERIFICATION_INVALID", "field": "verification", "message": "검증 방식은 loop · none 중 하나입니다"})
    return out


def config_issues(so: Any) -> list[tuple[str, str]]:
    """설정 `surrogate_opt` 알고리즘 키 범위(§9) — [(키, 허용 범위)]."""
    out: list[tuple[str, str]] = []
    if so.default_algorithm not in ALGORITHMS:
        out.append(("default_algorithm", " | ".join(ALGORITHMS)))
    for k, step in (("ga_pop_size", 2), ("nsga2_pop_size", 4)):
        v = getattr(so, k)
        if v is not None and (not POP_RANGE[0] <= v <= POP_RANGE[1] or v % step):
            out.append((k, f"null 또는 {POP_RANGE[0]}~{POP_RANGE[1]}의 {'4의 배수' if step == 4 else '짝수'}"))
    for k in ("ga_generations", "nsga2_generations", "ga_stall_generations"):
        if not GEN_RANGE[0] <= getattr(so, k) <= GEN_RANGE[1]:
            out.append((k, f"{GEN_RANGE[0]}~{GEN_RANGE[1]}"))
    if not 0.0 <= so.ga_crossover_prob <= 1.0:
        out.append(("ga_crossover_prob", "0~1"))
    for k in ("ga_eta_c", "nsga2_eta_c", "ga_eta_m"):
        if not ETA_RANGE[0] <= getattr(so, k) <= ETA_RANGE[1]:
            out.append((k, "1~100"))
    if not 10 <= so.ga_archive_max <= 100000:
        out.append(("ga_archive_max", "10~100000"))
    if not 1000 <= so.ga_max_evals <= 10_000_000:
        out.append(("ga_max_evals", "1000~10000000"))
    if not 2 <= so.max_levels <= 64:
        out.append(("max_levels", "2~64"))
    for alg, pk, gk in (("ga", "ga_pop_size", "ga_generations"), ("nsga2", "nsga2_pop_size", "nsga2_generations")):
        pop = getattr(so, pk) or default_pop_size(alg, so.max_variables, NSGA2_MANY_OBJ)
        if pop * getattr(so, gk) > so.ga_max_evals:
            out.append((gk, f"{pk} × {gk} ≤ ga_max_evals"))
    return out
