"""④ 일괄 예측 응답 표(CSV)·커브 겹쳐보기(downsample) — predict_batches에서 재노출."""

from __future__ import annotations

import csv
import io
import json
import math
import os
from typing import Any

from physicsai_core.db.repositories import artifacts as artifacts_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.paths import resolve_in_study

from ..auth import Principal
from ..context import AppContext
from .common import study_root
from .predict_batches_info import MAX_CURVE_POINTS, _require_batch, get_batch


def _num(v: Any) -> str:
    return "" if v is None else repr(float(v))


def table_csv(ctx: AppContext, principal: Principal, batch_id: str) -> tuple[bytes, str]:
    """결과 표 CSV(UTF-8 BOM): doe_no,run_key,folder,<파라미터(반영값)>,<응답>,state."""
    d = get_batch(ctx, principal, batch_id)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    resp = [x["name"] for x in d["responses"]]
    w.writerow(["doe_no", "run_key", "folder", *d["parameters"], *resp, "state"])
    for r in d["rows"]:
        w.writerow([r["doe_no"], r["run_key"], r["folder"],
                    *[_num((r["applied_values"] or {}).get(n)) for n in d["parameters"]],
                    *[_num((r["responses"] or {}).get(n)) for n in resp], r["state"]])
    return ("﻿" + buf.getvalue()).encode("utf-8"), f"{d['label']}.csv"


# ---- 커브 겹쳐보기 --------------------------------------------------------------------------------


def downsample(x: list[float], y: list[float], max_points: int) -> tuple[list[float], list[float], bool]:
    """구간별 최소·최대 보존 다운샘플(점 ≤ max_points, 첫·끝 점 유지)."""
    n = len(x)
    if n <= max_points:
        return x, y, False
    buckets = max(1, (max_points - 2) // 2)
    keep = {0, n - 1}
    inner = n - 2
    for b in range(buckets):
        lo = 1 + b * inner // buckets
        hi = 1 + (b + 1) * inner // buckets
        if hi <= lo:
            continue
        seg = range(lo, hi)
        keep.add(min(seg, key=lambda i: y[i]))
        keep.add(max(seg, key=lambda i: y[i]))
    idx = sorted(keep)
    return [x[i] for i in idx], [y[i] for i in idx], True


def _curve_json(ctx: AppContext, study: dict[str, Any], conn: Any, job: dict[str, Any] | None) -> dict[str, Any] | None:
    aid = ((job or {}).get("result") or {}).get("curve_artifact_id")
    a = artifacts_repo.get(conn, aid) if isinstance(aid, str) else None
    if a is None:
        return None
    try:
        p = resolve_in_study(study_root(ctx, study), a["rel_path"])
        if os.path.getsize(p) > ctx.settings.ui.max_artifact_bytes:
            return None
        with open(p, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError, DomainError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("series"), list) else None


def _finite_list(v: Any) -> list[float] | None:
    if not isinstance(v, list):
        return None
    out = []
    for e in v:
        if isinstance(e, bool) or not isinstance(e, (int, float)) or not math.isfinite(e):
            return None
        out.append(float(e))
    return out


def curves(ctx: AppContext, batch_id: str, name: str | None, max_points: int) -> dict[str, Any]:
    """완료(SUCCEEDED) run의 curve.json에서 같은 이름 계열 1개씩(doe_no 순, run ≤ curve_max_runs, 점 ≤ max_points)."""
    max_points = max(2, min(int(max_points), MAX_CURVE_POINTS))
    cap = ctx.settings.predict_batch.curve_max_runs
    with ctx.engine.connect() as conn:
        b = _require_batch(conn, batch_id)
        s = studies_repo.require(conn, b["study_id"])
        done = [r for r in pb_repo.runs_with_jobs(conn, batch_id) if r["predict_job_id"] and r["job_state"] == "SUCCEEDED"]
        truncated = len(done) > cap
        loaded = [(r, _curve_json(ctx, s, conn, jobs_repo.get_job(conn, r["predict_job_id"]))) for r in done[:cap]]
    names: list[str] = []
    for _r, data in loaded:
        for sr in (data or {}).get("series") or []:
            n = sr.get("name") if isinstance(sr, dict) else None
            if isinstance(n, str) and n not in names:
                names.append(n)
    pick = name if name is not None else (names[0] if names else None)
    series, down = [], False
    for r, data in loaded:
        sr = next((x for x in (data or {}).get("series") or [] if isinstance(x, dict) and x.get("name") == pick), None)
        xs, ys = (_finite_list(sr.get("x")), _finite_list(sr.get("y"))) if sr else (None, None)
        if xs is None or ys is None or len(xs) != len(ys) or not xs:
            continue
        xs, ys, d = downsample(xs, ys, max_points)
        down = down or d
        series.append({"doe_no": r["doe_no"], "run_key": r["run_key"], "x": xs, "y": ys})
    return {"names": names, "name": pick, "truncated": truncated, "downsampled": down, "series": series}
