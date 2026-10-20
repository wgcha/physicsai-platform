"""쌍 매칭(equiv-check.md §4.2) — 순수 함수. run = {"name": str, "no": int|None, "params": {이름: 값}|None, "ok": bool}.

- by_name: 이름 정확 일치 → 대소문자 무시(casefold).
- by_params: 두 쪽 파라미터 이름 집합이 같을 때만. 연속 값은 상대 `rel_tol`(0이면 절대 1e-12) 이내, 정수·범주는 정확 일치.
  한 점에 여러 run이면 가장 작은 번호 1개.
- manual: [{a, b}] 목록(없는 이름은 problems PAIR_RUN_NOT_FOUND).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

MODES = ("by_name", "by_params", "manual")
ABS_TOL_WHEN_ZERO = 1e-12
_NO_RE = re.compile(r"(\d+)$")


@dataclass
class PairResult:
    pairs: list[tuple[str, str]] = field(default_factory=list)
    unmatched_a: list[str] = field(default_factory=list)
    unmatched_b: list[str] = field(default_factory=list)
    problems: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def run_no(run: Mapping[str, Any]) -> int:
    n = run.get("no")
    if isinstance(n, int) and not isinstance(n, bool):
        return n
    m = _NO_RE.search(str(run.get("name") or ""))
    return int(m.group(1)) if m else 1 << 30


def _names(runs: Sequence[Mapping[str, Any]]) -> list[str]:
    return [str(r["name"]) for r in runs]


def pair_by_name(a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]]) -> PairResult:
    res = PairResult()
    b_exact = {str(r["name"]): str(r["name"]) for r in b}
    b_fold: dict[str, str] = {}
    for r in sorted(b, key=run_no):
        b_fold.setdefault(str(r["name"]).casefold(), str(r["name"]))
    used: set[str] = set()
    for r in sorted(a, key=run_no):
        n = str(r["name"])
        m = b_exact.get(n)
        if m is None or m in used:
            m = b_fold.get(n.casefold())
        if m is None or m in used:
            res.unmatched_a.append(n)
            continue
        used.add(m)
        res.pairs.append((n, m))
    res.unmatched_b = [n for n in _names(b) if n not in used]
    return res


def _param_names(runs: Sequence[Mapping[str, Any]]) -> set[str]:
    out: set[str] = set()
    for r in runs:
        out |= set((r.get("params") or {}).keys())
    return out


def _same_value(x: Any, y: Any, integer: bool, rel_tol: float) -> bool:
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or isinstance(x, bool) or isinstance(y, bool):
        return x == y
    if not (math.isfinite(x) and math.isfinite(y)):
        return False
    if integer:
        return round(x) == round(y)
    if rel_tol <= 0:
        return abs(x - y) <= ABS_TOL_WHEN_ZERO
    return abs(x - y) <= rel_tol * max(abs(x), abs(y), ABS_TOL_WHEN_ZERO)


def pair_by_params(a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]], *, rel_tol: float,
                   integer_names: Sequence[str] = ()) -> PairResult:
    res = PairResult()
    na, nb = _param_names(a), _param_names(b)
    if na != nb:
        only_a, only_b = sorted(na - nb), sorted(nb - na)
        detail = "; ".join(x for x in (f"A에만: {', '.join(only_a)}" if only_a else "", f"B에만: {', '.join(only_b)}" if only_b else "") if x)
        res.problems.append({"code": "PARAM_SET_MISMATCH", "message": f"두 쪽 파라미터 이름 집합이 다릅니다({detail})",
                             "only_a": only_a, "only_b": only_b})
        res.unmatched_a, res.unmatched_b = _names(a), _names(b)
        return res
    names = sorted(na)
    ints = set(integer_names)
    used: set[str] = set()
    b_sorted = sorted(b, key=run_no)
    for r in sorted(a, key=run_no):
        pa = r.get("params") or {}
        hit = None
        for s in b_sorted:
            if str(s["name"]) in used:
                continue
            pb = s.get("params") or {}
            if all(_same_value(pa.get(n), pb.get(n), n in ints, rel_tol) for n in names):
                hit = str(s["name"])
                break
        if hit is None:
            res.unmatched_a.append(str(r["name"]))
        else:
            used.add(hit)
            res.pairs.append((str(r["name"]), hit))
    res.unmatched_b = [n for n in _names(b) if n not in used]
    return res


def pair_manual(pairs: Sequence[Mapping[str, Any]], a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]]) -> PairResult:
    res = PairResult()
    an, bn = set(_names(a)), set(_names(b))
    ua: set[str] = set()
    ub: set[str] = set()
    for p in pairs:
        x, y = str(p.get("a") or ""), str(p.get("b") or "")
        if x not in an or y not in bn:
            res.problems.append({"code": "PAIR_RUN_NOT_FOUND", "message": f"쌍 ({x}, {y})의 run을 찾을 수 없습니다"})
            continue
        if x in ua or y in ub:
            res.problems.append({"code": "PAIR_DUPLICATE", "message": f"run이 두 쌍에 들어 있습니다: {x if x in ua else y}"})
            continue
        ua.add(x)
        ub.add(y)
        res.pairs.append((x, y))
    res.unmatched_a = [n for n in _names(a) if n not in ua]
    res.unmatched_b = [n for n in _names(b) if n not in ub]
    return res


def match(mode: str, a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]], *, rel_tol: float,
          integer_names: Sequence[str] = (), manual: Sequence[Mapping[str, Any]] | None = None,
          max_pairs: int) -> PairResult:
    if mode == "by_name":
        res = pair_by_name(a, b)
    elif mode == "by_params":
        res = pair_by_params(a, b, rel_tol=rel_tol, integer_names=integer_names)
    elif mode == "manual":
        res = pair_manual(manual or [], a, b)
    else:
        return PairResult(problems=[{"code": "PAIRING_INVALID", "message": "쌍 방식은 by_name | by_params | manual 중 하나입니다"}])
    if res.problems:
        return res
    if not res.pairs:
        res.problems.append({"code": "NO_PAIRS", "message": "짝이 맞는 run이 없습니다"})
    elif len(res.pairs) > max_pairs:
        res.problems.append({"code": "PAIRS_RANGE", "message": f"쌍은 1~{max_pairs}개여야 합니다(현재 {len(res.pairs)}개)"})
    return res
