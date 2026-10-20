"""④ FEM_VERIFY step 7~10(phase3 §21.3.6 S16): FV_EXTRACT(응답·범례) · FV_CURVE(T01 커브) · FV_CAPTURE(컨투어 두 쪽) ·
FV_COMPARE(compare.json·responses_fem.csv·검증 행 요약).

- 응답: §14.6 원본 MinMax TCL 재사용. 요청 = 템플릿 응답 정의 + 범례 줄 `__FV_LEGEND`(fixed면 생략). FEM datatype =
  요청 fem.field > fem_verify.field_map > 원래. 예측 쪽은 P의 RESPONSES.txt를 재사용(요청 같을 때)하거나 사본 h3d로 추출 —
  예측 폴더에는 쓰지 않는다.
- 도구 실패는 경고(RESPONSE_EXTRACT_FAILED·FEM_CURVE_FAILED·CAPTURE_FAILED)이고 값은 비운다. 작업은 성공 유지.
300줄 분할(R-B): 공용 계산(순수)은 `fem_compare_calc`, FV_EXTRACT는 `fem_compare_extract`(여기서 재노출).
"""

from __future__ import annotations

import json
import os
from typing import Any

from physicsai_core.db.repositories import curations as cur_repo
from physicsai_core.db.repositories import fem_verifications as fv_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json, write_text
from physicsai_core.stage2_curation import curation as cu
from physicsai_core.stage4_predict import responses as resp_mod
from physicsai_core.stage4_predict.xydata import parse_xydata

from ...limiter.base import LimiterError
from ...signals import StepSkipped
from . import capture as cap
from .fem_verify import attempt_dir, row
from ..response_tcl import single_h3d
from .fem_compare_calc import (  # noqa: F401 - 기존 경로 재노출
    LEGEND, MAX_SUMMARY_NAMES, _CATCH, legend_name, fem_datatype, compare_rows, worst_of, legend_union, pair_curves,
)
from .fem_compare_extract import _ctx_objs, _display, fv_extract  # noqa: F401 - 기존 경로 재노출


# ---- 8 FV_CURVE --------------------------------------------------------------------------------------


def curve_definitions(ctx: Any, pj: dict[str, Any]) -> list[dict[str, str]] | None:
    """① 모델 데이터셋 → 데이터셋 작업 params.curation_id → 그 큐레이션 작업(CU_T01_CURVES) params.curves
    ② 없으면 Study 최신 성공 CU_T01_CURVES params.curves ③ 없음 = None."""
    mid = (pj.get("result") or {}).get("model_id") or (pj.get("params") or {}).get("model_id")
    with ctx.ex.engine.connect() as conn:
        m = models_repo.get(conn, mid) if mid else None
        if m and m.get("dataset_id"):
            from physicsai_core.db.repositories import datasets as ds_repo

            d = ds_repo.get(conn, m["dataset_id"])
            dj = jobs_repo.get_job(conn, d["job_id"]) if d and d.get("job_id") else None
            cid = ((dj or {}).get("params") or {}).get("curation_id")
            cur = cur_repo.get_curation(conn, cid) if cid else None
            cj = jobs_repo.get_job(conn, cur["job_id"]) if cur else None
            curves = ((cj or {}).get("params") or {}).get("curves") if cj and cj["job_type"] == "CU_T01_CURVES" else None
            if curves:
                return list(curves)
        rows = jobs_repo.list_with_study_title(conn, study_id=ctx.study["id"], states=["SUCCEEDED"], created_by=None,
                                               job_type="CU_T01_CURVES", limit=1, offset=0)
    if rows and (rows[0].get("params") or {}).get("curves"):
        return list(rows[0]["params"]["curves"])
    return None


def _read_curve_json(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) and isinstance(data.get("series"), list) else None
    except (OSError, ValueError):
        return None


def _skip_curve(ctx: Any, reason: str) -> None:
    ctx.patch_result({"fv_curve": {"status": "SKIPPED", "message": reason, "pairs": [], "unmatched_pred": [], "unmatched_fem": []}})
    raise StepSkipped(reason)


def fv_curve(ctx: Any) -> None:
    _r, pj, root, _ps = _ctx_objs(ctx)
    A = attempt_dir(ctx)
    curves = curve_definitions(ctx, pj)
    if not curves:
        _skip_curve(ctx, "커브 정의 없음 — 커브 비교 생략")
    tcl = ctx.settings.resources.curate_hg_tcl
    if not tcl or not os.path.isfile(tcl) or ctx.settings.commands.t01_curve_export is None:
        _skip_curve(ctx, "커브 추출 미구성(resources.curate_hg_tcl·commands.t01_curve_export) — 커브 비교 생략")
    res_dir = os.path.join(A, "result")
    t01 = sorted(n for n in os.listdir(res_dir) if n.upper().endswith("T01") and os.path.isfile(os.path.join(res_dir, n)))
    if len(t01) != 1:
        ctx.add_warning("FEM_CURVE_T01", f"회수 폴더 T01이 정확히 1개가 아닙니다({len(t01)}개) — 커브 비교 생략")
        _skip_curve(ctx, f"T01 {len(t01)}개 — 커브 비교 생략")
    C = os.path.join(A, "curves")
    out = os.path.join(C, "fem_curve.json")
    cfg = os.path.join(C, "INPUT_CURATE_CURVE.json")
    data = cu.curve_input_json(curves, [(os.path.join(res_dir, t01[0]), "fem")], C)
    data["jobs"][0]["outputFile"] = out.replace("\\", "/")
    ctx.backup([p for p in (out, cfg) if os.path.lexists(p)])
    write_json(cfg, data)
    try:
        ctx.run_local("t01_curve_export", {"curate_tcl": tcl, "config_json": cfg}, cwd=C, check_log_errors=False)
    except (StepFailure, LimiterError) as exc:
        ctx.add_warning("FEM_CURVE_FAILED", f"FEM 커브 추출 실패({exc.code}): {exc.message}"[:480])
        ctx.patch_result({"fv_curve": {"status": "FAILED", "message": exc.message[:300], "pairs": [], "unmatched_pred": [],
                                       "unmatched_fem": []}})
        return
    fem_data = _read_curve_json(out) if os.path.isfile(out) else None
    if fem_data is None and os.path.isfile(out):  # JSON이 아니면 xydata로 해석해 fem_curve.json으로
        raw = os.path.join(C, "fem_curve.xy")
        if os.path.lexists(raw):
            ctx.backup([raw])
        os.replace(out, raw)
        fem_data = parse_xydata(raw, display_name=t01[0])
        write_json(out, fem_data)
    if fem_data is None:
        ctx.add_warning("FEM_CURVE_FAILED", "FEM 커브 파일이 만들어지지 않았습니다")
        ctx.patch_result({"fv_curve": {"status": "FAILED", "message": "출력 없음", "pairs": [], "unmatched_pred": [],
                                       "unmatched_fem": []}})
        return
    pred = _read_curve_json(ctx.abs(f"04_predict/{root}/curve.json")) or {"series": []}
    pn = [x["name"] for x in pred["series"] if isinstance(x, dict) and isinstance(x.get("name"), str)]
    fn = [x["name"] for x in fem_data.get("series") or [] if isinstance(x, dict) and isinstance(x.get("name"), str)]
    pairs, up, uf = pair_curves(pn, fn)
    ctx.patch_result({"fv_curve": {"status": "OK", "message": None, "pairs": pairs, "unmatched_pred": up, "unmatched_fem": uf}})


# ---- 9 FV_CAPTURE ------------------------------------------------------------------------------------


def _side(ctx: Any, *, h3d: str | None, media_dir: str, display: dict[str, Any], views: list[str], fid: str,
          side: str) -> tuple[str, list[dict[str, Any]], str | None]:
    if not h3d:
        return "FAILED", [], "h3d 없음"
    try:
        out = cap.run_capture(ctx, h3d=h3d, media_dir=media_dir, display=display, views=views,
                              extra_meta={"side": side, "fv_id": fid})
    except _CATCH as exc:
        return "FAILED", [], (getattr(exc, "message", None) or str(exc))[:300]
    return cap._status(out), out["media"], out.get("message")


def fv_capture(ctx: Any) -> None:
    r, pj, _root, _ps = _ctx_objs(ctx)
    A = attempt_dir(ctx)
    s = ctx.settings
    reason = cap.not_configured(ctx)
    if reason:
        ctx.patch_result({"media": {}, "fv_capture": {"pred_status": "SKIPPED", "fem_status": "SKIPPED",
                                                       "legend": {"mode": "auto", "min": None, "max": None, "source": None,
                                                                  "note": reason}}})
        raise StepSkipped(reason)
    opts = r.get("options") or {}
    fem = opts.get("fem") or {}
    disp = _display(ctx, r, pj)
    views = list(disp["views"])
    ex = ctx.result().get("fv_extract") or {}
    lg = disp.get("legend") or {}
    if lg.get("mode") == "fixed":
        legend = {"mode": "fixed", "min": lg.get("min"), "max": lg.get("max"), "source": "request", "note": None}
    else:
        u = legend_union(tuple(ex.get("legend_pred") or (None, None)), tuple(ex.get("legend_fem") or (None, None)))  # type: ignore[arg-type]
        if u is not None:
            legend = {"mode": "fixed", "min": u[0], "max": u[1], "source": "minmax", "note": None}
            disp["legend"] = {"mode": "fixed", "min": u[0], "max": u[1]}
        else:
            legend = {"mode": "auto", "min": None, "max": None, "source": None,
                      "note": "범례를 맞추지 못했습니다 — 이미지마다 자동 범례(범례 min·max를 읽지 못함)"}
    pred_h3d = (pj.get("result") or {}).get("pred_h3d_rel")
    p_status, p_media, p_msg = _side(ctx, h3d=ctx.abs(pred_h3d) if pred_h3d else None,
                                     media_dir=os.path.join(A, "media", "pred"), display=dict(disp), views=views, fid=r["id"],
                                     side="pred")
    fh3d, _names = single_h3d(os.path.join(A, "result"))
    comps = fem.get("comps")
    if comps is None and r.get("template_kind") == "mesh_only" and s.fem_verify.auto_isolate_cushion:
        comps = ctx.result().get("cushion_part_ids") or None
    fdisp = {**disp, "field": fem_datatype(s, str(disp.get("field") or ""), fem),
             "component": fem.get("component") if fem.get("component") is not None else disp.get("component", ""),
             "comps": list(comps) if comps is not None else list(disp.get("comps") or [])}
    f_status, f_media, f_msg = _side(ctx, h3d=fh3d, media_dir=os.path.join(A, "media", "fem"), display=fdisp, views=views,
                                     fid=r["id"], side="fem")
    for side, st, msg in (("예측", p_status, p_msg), ("FEM", f_status, f_msg)):
        if st != "OK":
            ctx.add_warning("CAPTURE_FAILED", f"컨투어 캡처 실패({side}): {msg or st}"[:300])
    ctx.patch_result({"media": {"pred": p_media, "fem": f_media, "display": disp, "fem_display": fdisp},
                      "fv_capture": {"pred_status": p_status, "fem_status": f_status, "legend": legend}})


# ---- 10 FV_COMPARE -----------------------------------------------------------------------------------


def _warnings_count(ctx: Any) -> int:
    with ctx.ex.engine.connect() as conn:
        j = jobs_repo.get_job(conn, ctx.ex.job_id) or {}
    return len(j.get("warnings") or [])


def fv_compare(ctx: Any) -> None:
    r = row(ctx)
    A = attempt_dir(ctx)
    res = ctx.result()
    ex = res.get("fv_extract") or {}
    cv = res.get("fv_curve") or {"status": "SKIPPED", "message": "커브 비교 안 함", "pairs": []}
    fc = res.get("fv_capture") or {"pred_status": "SKIPPED", "fem_status": "SKIPPED",
                                   "legend": {"mode": "auto", "min": None, "max": None, "source": None, "note": None}}
    rows = list(ex.get("rows") or [])
    mx, worst = worst_of(rows)
    names = [p["pred"] for p in cv.get("pairs") or []]
    compare = {"responses": rows, "max_abs_diff_pct": mx, "worst": worst, "legend": fc["legend"],
               "curve": {"status": cv["status"], "message": cv.get("message"), "names": names, "pairs": cv.get("pairs") or [],
                         "unmatched_pred": cv.get("unmatched_pred") or [], "unmatched_fem": cv.get("unmatched_fem") or []},
               "media": {"pred_status": fc["pred_status"], "fem_status": fc["fem_status"]}}
    cj = os.path.join(A, "compare.json")
    csvp = os.path.join(A, "responses_fem.csv")
    ctx.backup([p for p in (cj, csvp) if os.path.lexists(p)])
    write_json(cj, compare)
    write_text(csvp, resp_mod.name_value_csv_text({x["name"]: x.get("fem_value") for x in rows}))
    ctx.add_output(cj)
    ctx.add_output(csvp)
    lg = fc["legend"]
    summary = {"attempt": int(res.get("attempt") or 0),
               "responses": [{k: x.get(k) for k in ("name", "unit", "stat", "pred_value", "fem_value", "diff_pct")} for x in rows],
               "max_abs_diff_pct": mx, "worst": worst,
               "curve": {"status": cv["status"], "matched": len(names), "names": names[:MAX_SUMMARY_NAMES]},
               "media": {"pred_status": fc["pred_status"], "fem_status": fc["fem_status"],
                         "legend": {k: lg.get(k) for k in ("mode", "min", "max", "source")}},
               "warnings_count": _warnings_count(ctx)}
    ctx.ex.db(lambda c: fv_repo.set_row(c, r["id"], summary=summary))
    ctx.patch_result({"compare": compare})


HANDLERS = {
    ("FEM_VERIFY", "FV_EXTRACT"): fv_extract,
    ("FEM_VERIFY", "FV_CURVE"): fv_curve,
    ("FEM_VERIFY", "FV_CAPTURE"): fv_capture,
    ("FEM_VERIFY", "FV_COMPARE"): fv_compare,
}
