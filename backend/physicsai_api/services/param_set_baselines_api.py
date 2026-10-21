"""단계 4B 다중 baseline API 서비스(geometry-engine.md §4.10·§7.3.8·§11.4).

- baseline 추가(202, PARAM_SET_NATIVE mode add_baseline)·삭제(폴더는 `_backup`)·단일로 되돌리기(disable).
- 매칭표 조회·행별 decision 저장(PUT, proposed·signature 불변, 확정 상태면 draft로)·확정(confirm).
- 확정 시 파라미터 표 = 공통 이름 행(baseline별 대응 `baselines` 포함) + 쉘 두께 행. draft 동안 표는 바꾸지 않는다(DOE·일괄 생성은
  409 PARAM_MAP_UNCONFIRMED — 게이트는 `geometry_gate.require_map_confirmed`).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import study_manage as sm_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.fileutil import write_json_atomic
from physicsai_core.geometry import baselines as bl
from physicsai_core.geometry import shell as sh
from physicsai_core.geometry.prep import prep_state
from physicsai_core.geometry.reports import ReportError, read_report
from physicsai_core.paths import backup_existing, backup_stamp, resolve_in_study

from ..auth import Principal
from ..context import AppContext
from . import jobs as jobs_svc
from .common import audit, param_set_out, require_power, study_root


def _ctx_set(ctx: AppContext, conn: Any, ps_id: str) -> tuple[dict[str, Any], str, str]:
    """(세트 행, S, Study 루트). native가 아니면 409."""
    p = ps_repo.get(conn, ps_id)
    if p is None:
        raise DomainError("NOT_FOUND", "파라미터 세트를 찾을 수 없습니다", status=404)
    if (p.get("engine") or "altair") != "native":
        raise DomainError("ENGINE_MISMATCH", "다중 baseline은 Native 형상 엔진 세트에서만 씁니다", status=409)
    root = study_root(ctx, studies_repo.require(conn, p["study_id"]))
    return p, resolve_in_study(root, p["stored_rel"]), root


def _load(ctx: AppContext, S: str, *, required: bool = True) -> dict[str, Any] | None:
    try:
        pm = bl.load(S, ctx.settings.geometry.max_report_bytes)
    except bl.MapError as exc:
        raise DomainError(exc.code, exc.message, status=422, problems=exc.problems) from None
    if pm is None and required:
        raise DomainError("NOT_MULTI_BASELINE", "다중 baseline 세트가 아닙니다 — baseline을 먼저 추가하세요", status=409)
    return pm


def _not_busy(conn: Any, p: dict[str, Any]) -> None:
    if sm_repo.has_active_of_type(conn, p["study_id"], "PARAM_SET_NATIVE"):
        raise DomainError("PARAM_SET_BUSY", "형상 준비 작업이 진행 중입니다 — 끝난 뒤 다시 시도하세요", status=409)


def require_writable(conn: Any, principal: Principal, p: dict[str, Any]) -> None:
    """세트 내용 변경 권한: 프로젝트 power 이상 + Study ACTIVE(patch_param_set과 같은 규칙)."""
    st = studies_repo.require(conn, p["study_id"])
    require_power(principal, st["project_id"])
    if st["status"] != "ACTIVE":
        raise DomainError("STUDY_ARCHIVED", "보관된 Study입니다", status=409)


def _ps_out(ctx: AppContext, conn: Any, ps_id: str) -> dict[str, Any]:
    from .param_set_native_api import enrich

    row = ps_repo.get(conn, ps_id)
    return enrich(ctx, row, param_set_out(row))  # type: ignore[arg-type]


# ------------------------------------------------------------------ 응답 보강(ParamSet.baselines)
def baselines_info(ctx: AppContext, p: dict[str, Any], S: str, opts: dict[str, Any]) -> tuple[list[dict[str, Any]], str] | None:
    """다중 baseline 세트면 ([BaselineInfo…], 매칭표 상태), 아니면 None. 준비본 유효성은 baseline별(§7.3.8)."""
    s = ctx.settings
    try:
        pm = bl.load(S, s.geometry.max_report_bytes)
    except bl.MapError:
        return None
    if pm is None:
        return None
    out = []
    for b in bl.baseline_ids(pm):
        try:
            root = bl.baseline_root(S, pm, b)
        except bl.MapError:
            continue
        st = prep_state(root, step_exts=s.geometry.step_extensions, mesh_include_name=s.predict.mesh_include_name,
                        renum_csv_name=s.predict.renum_csv_name, opts=opts)
        label = p.get("label") if root == S else None
        try:
            label = read_report(os.path.join(root, bl.BASELINE_JSON), s.geometry.max_report_bytes).get("label") if root != S else label
        except ReportError:
            pass
        out.append({"id": b, "rel": bl.baseline_rel(pm, b), "label": label, "prep_status": st.status, "prep_reason": st.reason,
                    "feature_count": len(bl.rep_features_at(root, s.geometry.max_report_bytes))})
    return out, str(pm.get("status"))


def prep_problems(ctx: AppContext, p: dict[str, Any], S: str, opts: dict[str, Any]) -> list[tuple[str, str]]:
    """다중 baseline 세트의 추가 baseline 중 READY가 아닌 것 [(id, 사유)] — 작업 생성 409 GEOM_PREP_STALE(§7.3.8)."""
    info = baselines_info(ctx, p, S, opts)
    if info is None:
        return []
    return [(b["id"], b["prep_reason"] or b["prep_status"]) for b in info[0] if b["rel"] != "." and b["prep_status"] != "READY"]


# ------------------------------------------------------------------ baseline 추가·삭제·끄기
def add_baseline(ctx: AppContext, principal: Principal, ps_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    if getattr(body, "extract_filter", None) is not None:
        from .param_set_native_api import raise_filter_fixed

        raise_filter_fixed()  # extract-filter.md §6.7: 새 baseline은 기준 baseline 조건을 승계(요청으로 받지 않음)
    with ctx.engine.connect() as conn:
        p, _S, _root = _ctx_set(ctx, conn, ps_id)
    params = {"mode": "add_baseline", "param_set_id": ps_id,
              "baseline": {"id": body.id, "path": body.path, "choice": body.choice or {}, "label": body.label},
              "usage": body.usage, "split_param": body.split_param}
    job = jobs_svc.create_job(ctx, principal, p["study_id"], "PARAM_SET_NATIVE", params, rid, ip)
    return {"job_id": job["id"]}


def remap(ctx: AppContext, principal: Principal, ps_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        p, _S, _root = _ctx_set(ctx, conn, ps_id)
    job = jobs_svc.create_job(ctx, principal, p["study_id"], "PARAM_SET_NATIVE",
                              {"mode": "remap", "param_set_id": ps_id, "usage": body.usage, "split_param": body.split_param}, rid, ip)
    return {"job_id": job["id"]}


def delete_baseline(ctx: AppContext, principal: Principal, ps_id: str, bid: str, rid: str, ip: str | None) -> dict[str, Any]:
    """추가 baseline 삭제(폴더 `_backup`, 매칭표 draft). 첫 baseline·마지막 추가 baseline은 409(→ disable로 단일로)."""
    with ctx.engine.begin() as conn:
        p, S, root = _ctx_set(ctx, conn, ps_id)
        require_writable(conn, principal, p)
        _not_busy(conn, p)
        pm = _load(ctx, S)
        ids = bl.baseline_ids(pm)  # type: ignore[arg-type]
        if bid not in ids:
            raise DomainError("NOT_FOUND", f"baseline {bid}이(가) 없습니다", status=404)
        if bl.baseline_rel(pm, bid) in (".", ""):  # type: ignore[arg-type]
            raise DomainError("BASELINE_BASE", "첫 baseline(세트 자신)은 삭제할 수 없습니다 — 단일로 되돌리려면 disable을 쓰세요", status=409)
        if len(ids) <= 2:
            raise DomainError("BASELINE_LAST", "baseline이 2개뿐이라 삭제할 수 없습니다 — 단일로 되돌리려면 disable을 쓰세요", status=409)
        new = bl.drop_baseline(pm, bid)  # type: ignore[arg-type]
        backup_existing(root, [bl.baseline_root(S, pm, bid), bl.map_path(S)], "baseline_delete", backup_stamp())  # type: ignore[arg-type]
        write_json_atomic(bl.map_path(S), new)
        audit(conn, principal, "PARAM_SET_BASELINE_DELETE", "param_set", ps_id, {"baseline": bid}, rid, ip)
        return _ps_out(ctx, conn, ps_id)


def disable(ctx: AppContext, principal: Principal, ps_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    """단일 baseline으로 되돌림: `baselines/`·`param_map.json`을 `_backup`으로, 파라미터 표 = 다중 전환 전 표 + 쉘 두께 행."""
    with ctx.engine.begin() as conn:
        p, S, root = _ctx_set(ctx, conn, ps_id)
        require_writable(conn, principal, p)
        _not_busy(conn, p)
        _load(ctx, S)
        single = os.path.join(S, *bl.SINGLE_PARAMS.split("/"))
        geo = sh.geometry_rows(p["parameters"])
        try:
            geo = [r for r in read_report(single, ctx.settings.geometry.max_report_bytes).get("parameters") or [] if isinstance(r, dict)]
        except ReportError:
            pass
        rows = sh.merge_rows(sh.geometry_rows(geo), sh.prop_rows(p["parameters"]))
        backup_existing(root, [bl.map_path(S), os.path.join(S, bl.BASELINES_DIR)], "baseline_disable", backup_stamp())
        write_json_atomic(os.path.join(S, "parameters.json"), {"schema_version": 1, "unit_system": p.get("unit_system") or "mm-ton-s",
                                                                "parameters": rows})
        ps_repo.set_values(conn, ps_id, parameters=rows)
        audit(conn, principal, "PARAM_SET_BASELINE_DISABLE", "param_set", ps_id, {}, rid, ip)
        return _ps_out(ctx, conn, ps_id)


# ------------------------------------------------------------------ 매칭표
def map_out(pm: dict[str, Any]) -> dict[str, Any]:
    left = set(bl.unresolved(pm))
    rows = []
    for r in pm.get("common") or []:
        if isinstance(r, dict):
            rows.append({**r, "requires_decision": str(r.get("row_id")) in left})
    return {**{k: pm.get(k) for k in ("status", "usage", "confirmed_by", "confirmed_at", "engine_version", "discrete", "range_split",
                                      "map_options")},
            "baselines": [{"id": b.get("id"), "rel": b.get("rel")} for b in pm.get("baselines") or [] if isinstance(b, dict)],
            "common": rows, "warnings": [w for w in pm.get("warnings") or [] if isinstance(w, dict) and w.get("code")],
            "unresolved_rows": sorted(left, key=lambda x: [r.get("row_id") for r in rows].index(x)),
            "undecided_count": bl.undecided_count(pm), "variables": bl.display_names(pm)}


def get_map(ctx: AppContext, ps_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        _p, S, _root = _ctx_set(ctx, conn, ps_id)
    return map_out(_load(ctx, S))  # type: ignore[arg-type]


def _known(ctx: AppContext, S: str, pm: dict[str, Any]) -> dict[str, set[str]]:
    feats, _rows = bl.read_baselines(S, pm, ctx.settings.geometry.max_report_bytes)
    return bl.known_names(feats)


def put_map(ctx: AppContext, principal: Principal, ps_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        p, S, root = _ctx_set(ctx, conn, ps_id)
        require_writable(conn, principal, p)
        _not_busy(conn, p)
        pm = _load(ctx, S)
        try:
            new = bl.put_decisions(pm, [x.model_dump(exclude_none=False) for x in body.decisions], _known(ctx, S, pm))  # type: ignore[arg-type]
        except bl.MapError as exc:
            raise DomainError(exc.code, exc.message, status=422, problems=exc.problems) from None
        backup_existing(root, [bl.map_path(S)], "param_map", backup_stamp())
        write_json_atomic(bl.map_path(S), new)
        audit(conn, principal, "PARAM_SET_MAP_UPDATE", "param_set", ps_id,
              {"rows": [x.row_id for x in body.decisions][:50], "was": pm.get("status")}, rid, ip)  # type: ignore[union-attr]
    return map_out(new)


def confirm_map(ctx: AppContext, principal: Principal, ps_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    """확정(§7.3.8): check·needs_review 행 미결정 → 422 GEOM_INPUT_INVALID, 나머지 미결정 = accept. 파라미터 표 갱신."""
    s = ctx.settings
    with ctx.engine.begin() as conn:
        p, S, root = _ctx_set(ctx, conn, ps_id)
        require_writable(conn, principal, p)
        _not_busy(conn, p)
        pm = _load(ctx, S)
        feats, prow = bl.read_baselines(S, pm, s.geometry.max_report_bytes)  # type: ignore[arg-type]
        try:
            new = bl.confirm(pm, principal.user_id, datetime.now(timezone.utc).isoformat(), bl.known_names(feats))  # type: ignore[arg-type]
            common = bl.parameter_rows(new, feats, prow)
        except bl.MapError as exc:
            raise DomainError(exc.code, exc.message, status=422, problems=exc.problems) from None
        gaps = bl.range_gaps(new, common)
        warns = [w for w in new.get("warnings") or [] if isinstance(w, dict) and w.get("code") != "BASELINE_RANGE_GAP"]
        new["warnings"] = warns + [{"code": "BASELINE_RANGE_GAP", "row_id": None,
                                    "message": f"인접 baseline의 모핑 가능 범위 사이에 틈이 있습니다({g}) — 그 구간 샘플은 스킵됩니다"} for g in gaps]
        rows = sh.merge_rows(common, sh.prop_rows(p["parameters"]))
        single = os.path.join(S, *bl.SINGLE_PARAMS.split("/"))
        if not os.path.isfile(single):  # 이전 버전 폴더 보호: 단일 표가 없으면 지금 표의 형상 행을 둔다
            os.makedirs(os.path.dirname(single), exist_ok=True)
            write_json_atomic(single, {"schema_version": 1, "parameters": sh.geometry_rows(p["parameters"])})
        backup_existing(root, [bl.map_path(S)], "param_map", backup_stamp())
        write_json_atomic(bl.map_path(S), new)
        write_json_atomic(os.path.join(S, "parameters.json"), {"schema_version": 1, "unit_system": p.get("unit_system") or "mm-ton-s",
                                                                "parameters": rows})
        ps_repo.set_values(conn, ps_id, parameters=rows)
        audit(conn, principal, "PARAM_SET_MAP_CONFIRM", "param_set", ps_id,
              {"variables": [r["name"] for r in common], "baselines": bl.baseline_ids(new)}, rid, ip)
    return map_out(new)
