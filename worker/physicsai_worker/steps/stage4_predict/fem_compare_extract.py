"""④ FEM_VERIFY step 7 FV_EXTRACT(응답·범례, 예측 쪽 재사용 또는 사본 h3d 추출)와 작업 공용 도우미 — fem_compare에서 재노출."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file
from physicsai_core.stage4_predict import responses as resp_mod

from ...limiter.base import LimiterError
from ...signals import StepSkipped
from ..response_tcl import extract_requests, single_h3d
from . import capture as cap
from .fem_compare_calc import compare_rows, fem_datatype, legend_name
from .fem_verify import attempt_dir, predict_job, row

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
