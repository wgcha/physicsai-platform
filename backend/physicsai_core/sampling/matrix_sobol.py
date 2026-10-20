"""S15 Sobol 조합 행과 이어서 추가(continue_from, §20.5.3) 검사 — matrix에서 재노출."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from . import designs, qmc
from .matrix_designs import (
    _Design,
    _design_vars,
    _int_arg,
    _RawRows,
    _rows_from,
    _unsupported,
)
from .matrix_rows import BatchShapeError, _finite, _problem

SOBOL_MAX_SEED = 4_294_967_295
SEQUENCE_TOL = 1e-9  # 이어서 추가 대조: |차| ≤ 1e-9·(hi−lo)


def _is_pow2_count(n: int, max_runs: int) -> bool:
    return n >= 4 and n & (n - 1) == 0 and n <= max_runs


def _span(r: Any) -> bool:
    lo = _finite(r[0]) if isinstance(r, (list, tuple)) and len(r) == 2 else None
    hi = _finite(r[1]) if isinstance(r, (list, tuple)) and len(r) == 2 else None
    return lo is not None and hi is not None and lo < hi


def _continue_check(cb: Mapping[str, Any] | None, source: Mapping[str, Any], param_set_id: str | None,
                    parameters: Sequence[Mapping[str, Any]]) -> tuple[str | None, Mapping[str, Any] | None]:
    """이어서 추가 조건(§20.5.3) → (문제 문구 또는 None, 이전 배치 meta)."""
    if not cb or cb.get("missing"):
        return "이어서 추가할 이전 배치를 찾을 수 없습니다", None
    if cb.get("source_kind") != "SOBOL":
        return "Sobol 배치가 아닙니다", None
    if param_set_id is None or cb.get("param_set_id") != param_set_id:
        return "다른 템플릿의 배치입니다", None
    meta = cb.get("source_meta") or {}
    prev_active, prev_ranges = meta.get("active"), meta.get("ranges")
    names = [str(p["name"]) for p in parameters]
    if (not isinstance(prev_active, list) or not isinstance(prev_ranges, Mapping)
            or [n for n in names if n in prev_ranges and _span(prev_ranges[n])] != prev_active):
        return "변수 구성이 다릅니다", None
    if source.get("seed") is not None or source.get("ranges") not in (None, {}):
        return "이어서 추가는 이전 배치의 시드·범위를 그대로 씁니다", None
    return None, meta


def _matches_previous(dsn: _Design, old_u: Sequence[Sequence[float]], runs: Sequence[Mapping[str, Any]], count: int) -> bool:
    """이전 배치 구간을 다시 만든 값이 저장된 run 값과 |차| ≤ 1e-9·(hi−lo)인지."""
    by_no = {int(r["doe_no"]): r.get("values") or {} for r in runs if "doe_no" in r}
    if len(old_u) != count or len(by_no) != count:
        return False
    for i, row in enumerate(old_u, start=1):
        stored = by_no.get(i)
        if not stored:
            return False
        for j, n in enumerate(dsn.active):
            lo, hi = dsn.bounds[n]
            v = _finite(stored.get(n))
            if v is None or abs(v - designs.unit_to_value(row[j], lo, hi)) > SEQUENCE_TOL * (hi - lo):
                return False
    return True


def _sobol(source: Mapping[str, Any], parameters: Sequence[Mapping[str, Any]], max_runs: int,
           problems: list[dict[str, Any]], continue_batch: Mapping[str, Any] | None, param_set_id: str | None
           ) -> tuple[_RawRows, dict[str, Any], list[dict[str, str]], _Design]:
    count = _int_arg(source, "count")
    if count is None:
        raise BatchShapeError("source.count는 정수여야 합니다")
    cont = source.get("continue_from")
    if cont is not None and (not isinstance(cont, str) or not cont or len(cont) > 64):
        raise BatchShapeError("source.continue_from은 배치 id(64자 이하) 또는 null이어야 합니다")
    seed = _int_arg(source, "seed")
    if seed is not None and not 0 <= seed <= SOBOL_MAX_SEED:
        raise BatchShapeError(f"source.seed는 0~{SOBOL_MAX_SEED}입니다")
    pow2 = _is_pow2_count(count, max_runs)
    if not pow2:
        _problem(problems, "COUNT_NOT_POW2", "Sobol은 run 수가 2의 거듭제곱이어야 합니다(4·8·16·32·64·128)")
    prev: Mapping[str, Any] | None = None
    if cont is not None:
        why, prev = _continue_check(continue_batch, source, param_set_id, parameters)
        if why:
            _problem(problems, "CONTINUE_INVALID", why)
            return [], {"count": count, "continue_from": None}, [], _design_vars(None, parameters, [])
        ranges = {n: prev["ranges"][n] for n in prev["active"]}  # type: ignore[index]
        seed = int(prev.get("seed", 1))  # type: ignore[union-attr]
    else:
        ranges = source.get("ranges")
        seed = 1 if seed is None else seed
    dsn = _design_vars(ranges, parameters, problems)
    meta: dict[str, Any] = {"count": count, "seed": seed, "scramble": True, "offset": 0, "continue_from": None,
                            **dsn.base_meta()}
    if pow2:
        meta["m"] = count.bit_length() - 1
    if dsn.k == 0 and not problems:
        _unsupported(problems, "범위가 있는 변수가 없습니다")
    if problems:
        return [], meta, [], dsn
    notes: list[dict[str, str]] = []
    offset = 0
    try:
        if prev is not None and continue_batch is not None:
            p_off, p_cnt = int(prev.get("offset", 0)), int(prev.get("count", 0))
            offset = p_off + p_cnt
            if offset % count != 0:
                _problem(problems, "CONTINUE_INVALID",
                         f"이어서 추가할 run 수는 {offset}을 나누어떨어지게 하는 2의 거듭제곱이어야 합니다(권장 {offset & -offset})")
                return [], meta, [], dsn
            old_u, _gen = qmc.sobol_unit(dsn.k, p_cnt, seed, p_off)
            if not _matches_previous(dsn, old_u, continue_batch.get("runs") or [], p_cnt):
                _problem(problems, "SEQUENCE_MISMATCH",
                         "이전 배치를 같은 수열로 다시 만들 수 없습니다(계산 라이브러리 버전 차이) — 새 Sobol 배치로 시작하세요")
                return [], meta, [], dsn
            label = str(continue_batch.get("label") or "")
            total = offset + count
            notes.append({"code": "SEQUENCE_CONTINUED",
                          "message": f"{label}과 합치면 {total}개" + ("(균형 유지)" if total & (total - 1) == 0 else "(합계는 균형 아님)")})
            meta["continue_from"] = {"batch_id": continue_batch.get("id"), "label": label}
        u, gen = qmc.sobol_unit(dsn.k, count, seed, offset)
    except qmc.GeneratorUnavailable as exc:
        _problem(problems, "GENERATOR_UNAVAILABLE", str(exc))
        return [], meta, [], dsn
    meta["offset"] = offset
    meta["generator"] = gen
    meta["quality"] = designs.quality(u)
    return _rows_from(dsn, u, designs.unit_to_value), meta, notes, dsn
