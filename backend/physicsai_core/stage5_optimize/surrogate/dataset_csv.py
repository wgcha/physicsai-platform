"""⑤ dataset.csv 쓰기·읽기와 지표 표시 이름 — dataset에서 재노출."""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from typing import Any

from .dataset_model import Point, Problem, finite, is_feasible

CURVE_LABELS = {"max": "커브 최대값", "min": "커브 최소값", "absmax": "커브 |최대|"}


def metric_label(metric: str, series: str | None = None) -> str:
    """지표 id → 표시 이름: `resp:CornerStress_MAX` → `CornerStress_MAX`, `curve:max` → `커브 최대값(계열)`, `perf:X` → `X`."""
    kind, _, key = metric.partition(":")
    if kind == "curve":
        base = CURVE_LABELS.get(key, metric)
        return f"{base}({series})" if series else base
    return key or metric


def _num(v: Any) -> str:
    f = finite(v)
    return "" if f is None else repr(f)


def _obj_cols(problem: Problem) -> list[str]:
    return ["objective"] if not problem.multi else [f"objective_{i}" for i in range(1, problem.m + 1)]


def _obs_cols(problem: Problem) -> list[str]:
    return [f"obs:{metric_label(o.metric, o.series)}" for o in problem.observe]


def _with_reason(problem: Problem) -> bool:
    return problem.multi or bool(problem.observe)


def dataset_csv(points: Sequence[Point], problem: Problem, *, predicted: Mapping[tuple[int, int], float] | None = None,
                with_feasible: bool = False, bom: bool = False, crlf: bool = False) -> str:
    """iter·batch·doe_no·run_key·<변수>·objective(다목적 objective_1..m)·<제약>·(obs:<관찰>·reason)·(predicted·feasible)·state.
    단일 목적·관찰 없음은 S13 열 그대로(§22.4.3)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n" if crlf else "\n")
    cons = [c.key for c in problem.constraints]
    head = ["iter", "batch", "doe_no", "run_key", *problem.names, *_obj_cols(problem), *cons, *_obs_cols(problem)]
    if _with_reason(problem):
        head.append("reason")
    if with_feasible:
        head += ["predicted", "feasible"]
    w.writerow([*head, "state"])
    for p in points:
        objs = list(p.objectives or [p.objective])[: problem.m]
        objs += [None] * (problem.m - len(objs))
        row: list[Any] = [p.iter_no, p.batch_label, p.doe_no, p.run_key, *[_num(p.values.get(n)) for n in problem.names],
                          *[_num(v) for v in objs], *[_num(v) for v in p.constraints],
                          *[_num(p.observed.get(o.key)) for o in problem.observe]]
        if _with_reason(problem):
            row.append(next(iter(p.reasons.values()), ""))
        if with_feasible:
            pv = (predicted or {}).get((p.iter_no, p.doe_no))
            feas = "" if not p.valid else ("true" if is_feasible(p.constraints, problem.constraints) else "false")
            row += [_num(pv), feas]
        w.writerow([*row, p.state])
    text = buf.getvalue()
    return ("\ufeff" + text) if bom else text


def read_dataset_csv(text: str, problem: Problem) -> list[Point]:
    """dataset_csv 결과를 다시 Point로(워커 step 사이 전달)."""
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    head = rows[0]
    idx = {h: i for i, h in enumerate(head)}
    obj_cols = _obj_cols(problem)
    obs_cols = _obs_cols(problem)
    out = []
    for r in rows[1:]:
        if not r:
            continue

        def f(name: str) -> float | None:
            s = r[idx[name]] if name in idx else ""
            return float(s) if s != "" else None

        vals = {n: v for n in problem.names if (v := f(n)) is not None}
        objs = [f(c) for c in obj_cols]
        reason = r[idx["reason"]] if "reason" in idx else ""
        out.append(Point(int(r[idx["iter"]]), r[idx["batch"]], int(r[idx["doe_no"]]), r[idx["run_key"]], vals,
                         objs[0], [f(c.key) for c in problem.constraints], r[idx["state"]], objectives=objs,
                         observed={o.key: f(col) for o, col in zip(problem.observe, obs_cols)},
                         reasons={"": reason} if reason else {}))
    return out
