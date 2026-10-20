"""④ 조립 FEM 검증 컨투어·커브·표(CSV) — fem_verify에서 재노출."""

from __future__ import annotations

import csv
import io
import json
import math
import os
from typing import Any

from physicsai_core.db.repositories import contour_media as media_repo
from physicsai_core.db.repositories import fem_verifications as fv_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.paths import resolve_in_study
from physicsai_core.stage4_predict import contour_capture as cc

from ..auth import Principal
from ..context import AppContext
from .common import study_root
from .contour_capture import file_out
from .fem_verify_plan import CSV_HEADER, MAX_CURVE_POINTS
from .fem_verify_view import _attempt_dir, _require
from .predict_batches import downsample

# ---- 컨투어·커브·표 --------------------------------------------------------------------------------


def media(ctx: AppContext, principal: Principal, fid: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        row = _require(conn, fid)
        study = studies_repo.require(conn, row["study_id"])
        job = jobs_repo.get_job(conn, row["job_id"]) if row.get("job_id") else None
        res = (job or {}).get("result") or {}
        m = res.get("media") if isinstance(res.get("media"), dict) else {}
        ids = [x for side in ("pred", "fem") for it in (m.get(side) or []) for x in (it.get("image_artifact_id"),
                                                                                       it.get("video_artifact_id"))]
        arts = media_repo.artifacts_by_ids(conn, ids)
    sroot = study_root(ctx, study)
    by: dict[str, dict[str, Any]] = {}
    for side in ("pred", "fem"):
        for it in m.get(side) or []:
            img = arts.get(it.get("image_artifact_id") or "")
            if img is None or not os.path.isfile(resolve_in_study(sroot, img["rel_path"])):
                continue
            vid = arts.get(it.get("video_artifact_id") or "")
            v = it.get("view")
            by.setdefault(v, {"view": v, "label": cc.VIEW_LABELS.get(v, v), "pred": None, "fem": None})[side] = {
                "image": file_out(img), "video": file_out(vid) if vid else None,
                "video_error": it.get("video_error") if not vid else None}
    items = [by[v] for v in sorted(by, key=lambda x: cc.VIEWS.index(x) if x in cc.VIEWS else len(cc.VIEWS))]
    cmp_ = res.get("compare") or {}
    ms = (cmp_.get("media") or {})
    status = "NONE" if not m else ("OK" if ms.get("pred_status") == "OK" and ms.get("fem_status") == "OK" else
                                   ms.get("fem_status") or ms.get("pred_status") or "NONE")
    return {"status": status, "display": m.get("display"), "legend": cmp_.get("legend"), "items": items}


def _load_series(path: str, name: str | None, max_bytes: int) -> tuple[list[str], dict[str, Any] | None]:
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > max_bytes:
            return [], None
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return [], None
    series = [x for x in (data or {}).get("series") or [] if isinstance(x, dict) and isinstance(x.get("name"), str)]
    pick = next((x for x in series if x["name"] == name), None) if name is not None else None
    return [x["name"] for x in series], pick


def _xy(sr: dict[str, Any] | None, max_points: int) -> tuple[dict[str, Any] | None, bool]:
    if sr is None:
        return None, False
    xs, ys = sr.get("x"), sr.get("y")
    ok = (isinstance(xs, list) and isinstance(ys, list) and len(xs) == len(ys) and xs
          and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in xs + ys))
    if not ok:
        return None, False
    x2, y2, d = downsample([float(v) for v in xs], [float(v) for v in ys], max_points)
    return {"x": x2, "y": y2}, d


def curves(ctx: AppContext, principal: Principal, fid: str, name: str | None, max_points: int) -> dict[str, Any]:
    max_points = max(2, min(int(max_points), MAX_CURVE_POINTS))
    with ctx.engine.connect() as conn:
        row = _require(conn, fid)
        study = studies_repo.require(conn, row["study_id"])
        job = jobs_repo.get_job(conn, row["job_id"]) if row.get("job_id") else None
        pj = jobs_repo.get_job(conn, row["predict_job_id"]) if row.get("predict_job_id") else None
        proot = jobs_repo.root_job_id(conn, pj) if pj else None
    res = (job or {}).get("result") or {}
    cv = (res.get("compare") or {}).get("curve") or {}
    pairs = [p for p in cv.get("pairs") or [] if isinstance(p, dict)]
    names = [p["pred"] for p in pairs if isinstance(p.get("pred"), str)]
    pick = name if name is not None else (names[0] if names else None)
    pair = next((p for p in pairs if p.get("pred") == pick), None)
    sroot = study_root(ctx, study)
    cap = ctx.settings.ui.max_artifact_bytes
    pred = fem = None
    down = False
    if pair is not None and proot:
        _n, sr = _load_series(resolve_in_study(sroot, f"04_predict/{proot}/curve.json"), pair["pred"], cap)
        pred, d1 = _xy(sr, max_points)
        a_rel = _attempt_dir(row, job)
        _n, sr2 = _load_series(resolve_in_study(sroot, f"{a_rel}/curves/fem_curve.json"), pair.get("fem"), cap) if a_rel else ([], None)
        fem, d2 = _xy(sr2, max_points)
        down = d1 or d2
    return {"names": names, "name": pick, "pred": pred, "fem": fem, "downsampled": down}


def _num(v: Any) -> str:
    return "" if v is None else repr(float(v))


def table_csv(ctx: AppContext, principal: Principal, fid: str) -> tuple[bytes, str]:
    with ctx.engine.connect() as conn:
        row = _require(conn, fid)
        job = jobs_repo.get_job(conn, row["job_id"]) if row.get("job_id") else None
    rows = ((((job or {}).get("result") or {}).get("compare") or {}).get("responses") or [])
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_HEADER)
    for r in rows:
        w.writerow([r.get("name") or "", r.get("unit") or "", r.get("stat") or "",
                    *(_num(r.get(k)) for k in CSV_HEADER[3:])])
    return ("﻿" + buf.getvalue()).encode("utf-8"), f"{fv_repo.label(row['fv_no'])}_responses.csv"
