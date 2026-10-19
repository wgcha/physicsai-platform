"""④ FEM_VERIFY step 7~10(phase3 §21.3.6 S16): FV_EXTRACT(응답·범례) · FV_CURVE(T01 커브) · FV_CAPTURE(컨투어 두 쪽) ·
FV_COMPARE(compare.json·responses_fem.csv·검증 행 요약).

- 응답: §14.6 원본 MinMax TCL 재사용. 요청 = 템플릿 응답 정의 + 범례 줄 `__FV_LEGEND`(fixed면 생략). FEM datatype =
  요청 fem.field > fem_verify.field_map > 원래. 예측 쪽은 P의 RESPONSES.txt를 재사용(요청 같을 때)하거나 사본 h3d로 추출 —
  예측 폴더에는 쓰지 않는다.
- 도구 실패는 경고(RESPONSE_EXTRACT_FAILED·FEM_CURVE_FAILED·CAPTURE_FAILED)이고 값은 비운다. 작업은 성공 유지.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import replace
from typing import Any

from physicsai_core.db.repositories import curations as cur_repo
from physicsai_core.db.repositories import fem_verifications as fv_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.errors import DomainError, StepFailure
from physicsai_core.fileutil import copy_file, write_json, write_text
from physicsai_core.stage2_curation import curation as cu
from physicsai_core.stage4_predict import responses as resp_mod
from physicsai_core.stage4_predict.xydata import parse_xydata

from ...limiter.base import LimiterError
from ...signals import StepSkipped
from . import capture as cap
from .fem_verify import attempt_dir, predict_job, row
from ..response_tcl import extract_requests, single_h3d

LEGEND = "__FV_LEGEND"
MAX_SUMMARY_NAMES = 20
_CATCH = (StepFailure, DomainError, LimiterError, OSError)
_WS = re.compile(r"\s+")


# ---- 공용 계산(순수) ----------------------------------------------------------------------------------


def legend_name(responses: list[dict[str, Any]]) -> str:
    """예약 이름 `__FV_LEGEND`, 같은 이름의 사용자 응답이 있으면 `__FV_LEGEND2`(…3)."""
    names = {str(r.get("name") or "") for r in responses}
    if LEGEND not in names:
        return LEGEND
    i = 2
    while f"{LEGEND}{i}" in names:
        i += 1
    return f"{LEGEND}{i}"


def fem_datatype(settings: Any, datatype: str, fem: dict[str, Any] | None) -> str:
    f = (fem or {}).get("field")
    if f:
        return str(f)
    return settings.fem_verify.field_map.get(datatype, datatype)


def _diff(pred: float | None, fem: float | None, zero_tol: float) -> tuple[float | None, float | None, str | None]:
    if pred is None or fem is None:
        return None, None, None
    d = pred - fem
    if abs(fem) <= zero_tol:
        return d, None, "기준값 0"
    return d, d / abs(fem) * 100.0, None


def compare_rows(reqs: list[resp_mod.H3dRequest], units: dict[str, str], pred: resp_mod.ParsedResponses | None,
                 fem: resp_mod.ParsedResponses | None, zero_tol: float) -> list[dict[str, Any]]:
    """응답마다 MIN·MAX·판정값(stat) 비교 행 1개(MIN·MAX 차이도 같은 식)."""
    out = []
    empty = resp_mod.ParsedResponses()
    for q in reqs:
        p, f = pred or empty, fem or empty
        pmin, pmax = p.values.get(f"{q.name}_MIN"), p.values.get(f"{q.name}_MAX")
        fmin, fmax = f.values.get(f"{q.name}_MIN"), f.values.get(f"{q.name}_MAX")
        pv, _ = resp_mod.apply_stat(q, p)
        fv, _ = resp_mod.apply_stat(q, f)
        d, dp, note = _diff(pv, fv, zero_tol)
        dmin, dpmin, _n1 = _diff(pmin, fmin, zero_tol)
        dmax, dpmax, _n2 = _diff(pmax, fmax, zero_tol)
        out.append({"name": q.name, "unit": units.get(q.name, ""), "stat": q.stat, "pred_min": pmin, "pred_max": pmax,
                    "fem_min": fmin, "fem_max": fmax, "pred_value": pv, "fem_value": fv, "diff": d, "diff_pct": dp,
                    "min_diff": dmin, "min_diff_pct": dpmin, "max_diff": dmax, "max_diff_pct": dpmax, "note": note})
    return out


def worst_of(rows: list[dict[str, Any]]) -> tuple[float | None, str | None]:
    best: tuple[float | None, str | None] = (None, None)
    for r in rows:
        v = r.get("diff_pct")
        if isinstance(v, (int, float)) and math.isfinite(v) and (best[0] is None or abs(v) > best[0]):
            best = (abs(v), r["name"])
    return best


def legend_union(pred: tuple[float | None, float | None], fem: tuple[float | None, float | None]) -> tuple[float, float] | None:
    vals = [*pred, *fem]
    if any(v is None or not math.isfinite(v) for v in vals):
        return None
    lo, hi = min(pred[0], fem[0]), max(pred[1], fem[1])  # type: ignore[type-var]
    return (lo, hi) if lo < hi else None


def _norm(name: str) -> str:
    return _WS.sub("", name).casefold()


def pair_curves(pred_names: list[str], fem_names: list[str]) -> tuple[list[dict[str, str]], list[str], list[str]]:
    """이름 짝(정확히 같음 → 대소문자·공백 무시). (짝, 짝 없는 예측, 짝 없는 FEM)."""
    pairs: list[dict[str, str]] = []
    left_f = list(fem_names)
    left_p = []
    for p in pred_names:
        if p in left_f:
            pairs.append({"pred": p, "fem": p})
            left_f.remove(p)
        else:
            left_p.append(p)
    still = []
    for p in left_p:
        m = next((f for f in left_f if _norm(f) == _norm(p)), None)
        if m is not None:
            pairs.append({"pred": p, "fem": m})
            left_f.remove(m)
        else:
            still.append(p)
    return pairs, still, left_f


# ---- 공용(작업) ---------------------------------------------------------------------------------------


def _ctx_objs(ctx: Any) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any] | None]:
    r = row(ctx)
    pj, root = predict_job(ctx, r)
    psid = (pj.get("result") or {}).get("param_set_id") or (pj.get("params") or {}).get("param_set_id")
    with ctx.ex.engine.connect() as conn:
        ps = ps_repo.get(conn, psid) if psid else None
    return r, pj, root, ps


def _display(ctx: Any, r: dict[str, Any], pj: dict[str, Any]) -> dict[str, Any]:
    disp, _src = cap.display_for(ctx, pj, (r.get("options") or {}).get("display"))
    return disp


# ---- 7 FV_EXTRACT ------------------------------------------------------------------------------------


def _pred_reuse(ctx: Any, root: str, reqs: list[resp_mod.H3dRequest]) -> resp_mod.ParsedResponses | None:
    """P/RESULT의 RESPONSES.txt + 같은 요청의 H3D_REQUESTS.txt면 그 값(읽기만)."""
    d = ctx.abs(f"04_predict/{root}/RESULT")
    try:
        with open(os.path.join(d, resp_mod.REQUESTS_FILE), encoding="utf-8") as fh:
            old = [ln.strip() for ln in fh if ln.strip() and not ln.strip().startswith("#")]
    except OSError:
        return None
    if old != [q.line() for q in reqs]:
        return None
    return resp_mod.read_responses(d)


def _merge(a: resp_mod.ParsedResponses | None, b: resp_mod.ParsedResponses | None) -> resp_mod.ParsedResponses | None:
    if a is None and b is None:
        return None
    out = resp_mod.ParsedResponses()
    for x in (a, b):
        if x is not None:
            out.values.update(x.values)
            out.failures.update(x.failures)
    return out


def _extract_pred(ctx: Any, A: str, pj: dict[str, Any], root: str, reqs: list[resp_mod.H3dRequest],
                  legend_req: resp_mod.H3dRequest | None) -> resp_mod.ParsedResponses | None:
    reused = _pred_reuse(ctx, root, reqs) if reqs else None
    todo = ([legend_req] if legend_req else []) if reused is not None else [*reqs, *([legend_req] if legend_req else [])]
    if not todo:
        return reused
    rel = (pj.get("result") or {}).get("pred_h3d_rel")
    src = ctx.abs(rel) if rel else None
    if not src or not os.path.isfile(src):
        ctx.add_warning("RESPONSE_EXTRACT_FAILED", "예측 h3d가 없어 예측 쪽 응답을 다시 추출하지 못했습니다")
        return reused
    limit = ctx.settings.fem_verify.max_pred_h3d_copy_bytes
    if os.path.getsize(src) > limit:
        ctx.add_warning("PRED_H3D_TOO_LARGE", f"예측 h3d가 사본 상한(fem_verify.max_pred_h3d_copy_bytes)을 넘어 추출하지 않았습니다: "
                                              f"{os.path.getsize(src)} B")
        return reused
    d = os.path.join(A, "extract", "pred")
    dst = os.path.join(d, os.path.basename(src))
    if os.path.lexists(dst):
        ctx.backup([dst])
    copy_file(src, dst, checkpoint=ctx.checkpoint)
    try:
        got = extract_requests(ctx, todo, d, dst)
    except (StepFailure, LimiterError) as exc:
        ctx.add_warning("RESPONSE_EXTRACT_FAILED", f"예측 응답 추출 실패({exc.code}): {exc.message}"[:480])
        return reused
    return _merge(reused, got)


def fv_extract(ctx: Any) -> None:
    r, pj, root, ps = _ctx_objs(ctx)
    A = attempt_dir(ctx)
    s = ctx.settings
    opts = r.get("options") or {}
    fem = opts.get("fem")
    responses = list((ps or {}).get("responses") or [])
    disp = _display(ctx, r, pj)
    fixed = (disp.get("legend") or {}).get("mode") == "fixed"
    reqs, _skipped = resp_mod.build_requests(responses)
    if not reqs and fixed:
        ctx.patch_result({"fv_extract": {"rows": [], "legend_pred": [None, None], "legend_fem": [None, None]}})
        raise StepSkipped("응답 정의 없음·범례 고정")
    res_dir = os.path.join(A, "result")
    h3d, names = single_h3d(res_dir)
    if not names:
        raise StepFailure("OUTPUT_MISSING", "회수한 FEM h3d가 없습니다")
    lname = legend_name(responses)
    legend_pred = legend_fem = None
    if not fixed:
        legend_pred = resp_mod.H3dRequest(lname, s.fem_verify.legend_subcase, str(disp.get("field") or ""),
                                          str(disp.get("component") or ""), "", "MAX")
        legend_fem = replace(legend_pred, datatype=fem_datatype(s, legend_pred.datatype, fem),
                             component=str((fem or {}).get("component") if (fem or {}).get("component") is not None
                                           else legend_pred.component))
    fem_reqs = [replace(q, datatype=fem_datatype(s, q.datatype, fem)) for q in reqs]
    fem_parsed = None
    if h3d is None:
        ctx.add_warning("RESP_H3D_AMBIGUOUS", f"FEM 응답 추출: 회수 폴더 h3d가 정확히 1개가 아닙니다({len(names)}개) — FEM 값을 비웁니다")
    else:
        try:
            fem_parsed = extract_requests(ctx, [*fem_reqs, *([legend_fem] if legend_fem else [])], res_dir, h3d)
        except (StepFailure, LimiterError) as exc:
            ctx.add_warning("RESPONSE_EXTRACT_FAILED", f"FEM 응답 추출 실패({exc.code}): {exc.message}"[:480])
    pred_parsed = _extract_pred(ctx, A, pj, root, reqs, legend_pred)
    units = {str(x.get("name")): str(x.get("unit") or "") for x in responses}
    rows = compare_rows(reqs, units, pred_parsed, fem_parsed, s.fem_verify.zero_tol)
    if reqs and r.get("template_kind") == "mesh_only":
        ctx.add_warning("FEM_RESPONSE_WHOLE_MODEL", "FEM 응답은 조립 전체 모델의 최솟값·최댓값입니다(쿠션만 한정 불가) — 컨투어를 함께 보세요")

    def mm(p: resp_mod.ParsedResponses | None) -> list[float | None]:
        if p is None or legend_pred is None:
            return [None, None]
        return [p.values.get(f"{lname}_MIN"), p.values.get(f"{lname}_MAX")]

    ctx.patch_result({"fv_extract": {"rows": rows, "legend_pred": mm(pred_parsed), "legend_fem": mm(fem_parsed),
                                     "legend_name": lname if legend_pred else None}})


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
