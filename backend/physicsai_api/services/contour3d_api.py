"""결과 3D 컨투어 API(geometry-view.md §13.5·§13.6): 열 때 생성 — 캐시 적중 200 즉시, 아니면 202 + CONTOUR_3D(CPU 대기열) 작업.
권한(contour3d-default C3D-6): 캐시 적중(200)·진행 중 공유(202)는 로그인 사용자(member 이상), 새로 생성할 때만 power 이상.

원본: PREDICT_H3D = 성공한 PREDICT(`source_ref.job_id`, result.pred_h3d_rel), SOLVER_H3D = 조립 FEM 검증 결과(`fem_verification_id`,
최신 시도 `a<n>/result`의 h3d 1개) 또는 Study 기준 `.h3d` 상대 경로(`h3d_rel`, ① run 결과 등). 표시 값 생략 = 기존 컨투어 표시 설정
결정 순서(phase3 §15 resolve_display). 캐시 = 서버측 `<study>/_cache/contour3d/`(미리보기와 같은 housekeeping·보관 규칙).
대기 안내(§13.6): 응답 `progress` = 단계(대기·H3D 읽기·형상·프레임 변환·완료·실패)·진행률·경과·예상 시간·취소 가능 여부.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from physicsai_core.config.schema_capture import effective_extract_tcl
from physicsai_core.contour3d.settings import cache_key, clean_unit, limits_of, message_ko, normalize_comps, tcl_hash
from physicsai_core.db.repositories import artifacts as artifacts_repo
from physicsai_core.db.repositories import geom_view as gv_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.features import contour3d_missing
from physicsai_core.path_links import is_link_or_reparse
from physicsai_core.paths import resolve_in_study, to_rel
from physicsai_core.stage4_predict import contour_capture as cc
from physicsai_core.stage4_predict import input_kind as ik

from ..auth import Principal
from ..context import AppContext
from .common import audit, require_power, study_root
from .job_params.study_manage import study_gate

PHASE_LABEL = {"waiting": "대기", "reading_h3d": "H3D 읽기", "geometry": "형상", "frames": "프레임 변환", "done": "완료",
               "failed": "실패", "canceled": "취소", "expired": "정리됨(다시 만들기)"}


def _single_h3d(folder: str) -> str | None:
    try:
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith(".h3d") and os.path.isfile(os.path.join(folder, n)))
    except OSError:
        return None
    return os.path.join(folder, names[0]) if len(names) == 1 else None


def _resolve(ctx: AppContext, conn: Any, kind: str, ref: dict[str, str]) -> tuple[dict[str, Any], str, str, dict[str, Any] | None,
                                                                                 dict[str, Any] | None, bool]:
    """(study, h3d 절대경로, source_id, 표시 설정 param_set, 원본 예측 params display, 쿠션 입력 예측 여부).
    쿠션 입력 예측 h3d는 부품 이름(comps)을 적용하지 않는다(C3F-13 — 쿠션 하나뿐이라 줄일 부품이 없다)."""
    missing = DomainError("PREREQUISITE_MISSING", "결과 h3d를 찾을 수 없습니다", status=409, missing=["H3D"])
    if kind == "PREDICT_H3D":
        jid = ref.get("job_id")
        j = jobs_repo.get_job(conn, jid) if jid else None
        if j is None or j["job_type"] != "PREDICT":
            raise DomainError("INPUT_INVALID", "예측 작업을 찾을 수 없습니다", status=422, errors=[{"loc": ["source_ref", "job_id"], "msg": "not found"}])
        st = studies_repo.require(conn, j["study_id"])
        rel = (j.get("result") or {}).get("pred_h3d_rel")
        if j["state"] != "SUCCEEDED" or not rel:
            raise missing
        psid = (j.get("params") or {}).get("param_set_id")
        ps = ps_repo.get(conn, psid) if psid else None
        cushion = ik.of_run(j.get("params"), j.get("result"), (ps or {}).get("input_kind")) == ik.CUSHION
        return st, resolve_in_study(study_root(ctx, st), rel), f"job:{j['id']}", ps, (j.get("params") or {}).get("display"), cushion
    if ref.get("fem_verification_id"):
        from physicsai_core.db.repositories import fem_verifications as fv_repo

        fv = fv_repo.get(conn, ref["fem_verification_id"])
        if fv is None:
            raise DomainError("INPUT_INVALID", "FEM 검증을 찾을 수 없습니다", status=422,
                              errors=[{"loc": ["source_ref", "fem_verification_id"], "msg": "not found"}])
        st = studies_repo.require(conn, fv["study_id"])
        A = resolve_in_study(study_root(ctx, st), f"{fv['dir_rel'].rstrip('/')}/a{int(fv.get('attempt_no') or 0)}/result")
        h3d = _single_h3d(A)
        if h3d is None:
            raise missing
        ps = ps_repo.get(conn, fv["param_set_id"]) if fv.get("param_set_id") else None
        return st, h3d, f"fv:{fv['id']}:a{fv.get('attempt_no')}", ps, None, False  # FEM 검증은 쿠션 입력도 재조립 결과
    rel, sid = ref.get("h3d_rel"), ref.get("study_id")
    if not rel or not sid or not rel.lower().endswith(".h3d"):
        raise DomainError("INPUT_INVALID", "source_ref는 fem_verification_id 또는 {study_id, h3d_rel}(.h3d)이어야 합니다", status=422,
                          errors=[{"loc": ["source_ref"], "msg": "invalid"}])
    st = studies_repo.require(conn, sid)
    return st, resolve_in_study(study_root(ctx, st), rel), f"rel:{rel}", None, None, False


def _display(ctx: AppContext, ps: dict[str, Any] | None, job_display: dict[str, Any] | None, body: Any, cushion: bool = False
             ) -> dict[str, Any]:
    """최종 표시 값 {field, component, avgmode, unit, comps}. comps = 표시 설정의 부품 이름(최대 50), 쿠션 입력 예측이면 늘 `[]`(§9.5)."""
    over = body.display.model_dump(exclude_none=True) if body.display is not None else None
    d, _src = cc.resolve_display(ctx.settings.capture, ps, job_display, over)
    comps = [] if cushion else normalize_comps(d.get("comps"))[:cc.MAX_COMPS]
    return {"field": str(d.get("field") or ""), "component": str(d.get("component") or ""), "avgmode": str(d.get("avgmode") or ""),
            "unit": clean_unit(d.get("unit")), "comps": comps}


def _estimate(conn: Any, source_kind: str) -> float | None:
    vals = [float(t["total_s"]) for t in gv_repo.recent_timings(conn, source_kind) if isinstance(t.get("total_s"), (int, float))]
    return round(sum(vals) / len(vals), 1) if vals else None


def phase_of(row_status: str, job_state: str | None, step_key: str | None, step_pct: float | None) -> str:
    """진행 단계(§13.6 대기 안내): 행 종료 상태 우선, 실행 중이면 step으로 — C3_PREP·C3_EXTRACT = H3D 읽기,
    C3_CONVERT 30% 미만 = 형상(외부 면·GLB), 그 뒤·C3_REGISTER = 프레임 변환."""
    done = {"DONE": "done", "FAILED": "failed", "CANCELED": "canceled", "EXPIRED": "expired"}
    if row_status in done:
        return done[row_status]
    if job_state in (None, "QUEUED"):
        return "waiting"
    if step_key == "C3_CONVERT":
        return "geometry" if step_pct is None or step_pct < 30 else "frames"
    if step_key == "C3_REGISTER":
        return "frames"
    return "reading_h3d"


def progress_of(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    st = row["status"]
    job = jobs_repo.get_job(conn, row["job_id"]) if row.get("job_id") else None
    step_key, pct, sp = None, None, None
    if job is not None:
        pct = job.get("progress_pct")
        if job["state"] == "RUNNING":
            steps = {s["step_no"]: s for s in jobs_repo.get_steps(conn, job["id"])}
            cur = steps.get(job.get("current_step_no") or 0)
            step_key = cur["step_key"] if cur else None
            sp = (cur or {}).get("progress_pct")
    phase = phase_of(st, job["state"] if job else None, step_key, sp)
    elapsed = None
    if job is not None and job.get("started_at") is not None:
        end = job.get("finished_at") or datetime.now(timezone.utc)
        elapsed = round((end - job["started_at"]).total_seconds(), 1)
    return {"phase": phase, "phase_label": PHASE_LABEL[phase], "step_key": step_key, "percent": pct,
            "label": (job or {}).get("progress_label"), "elapsed_s": elapsed, "estimate_s": _estimate(conn, row["source_kind"]),
            "can_cancel": st in ("QUEUED", "RUNNING")}


def _fail_reason(ctx: AppContext | None, conn: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    """결과 FAIL(작업 성공 + 캐시된 결정적 실패) 대체 사유(계약 §12): code·message_ko와, FAIL manifest의 `limits`에서 읽은 수치
    (노드 수·상한, 형상·프레임 크기·상한)와 상세 `message`. manifest를 못 읽으면(예전 행·파일 정리) 수치는 null이고 code·message_ko만 있다.
    kind = nodes | glb | frames | field | other — 화면이 문구를 고르는 기준."""
    if row.get("result_status") != "FAIL":
        return None
    code = row.get("code")
    man: dict[str, Any] = {}
    if ctx is not None and row.get("manifest_artifact_id"):
        a = artifacts_repo.get(conn, row["manifest_artifact_id"])
        if a is not None:
            from physicsai_core.geometry.view import read_json

            st = studies_repo.require(conn, row["study_id"])
            man = read_json(resolve_in_study(study_root(ctx, st), a["rel_path"])) or {}
    lim = man.get("limits") if isinstance(man.get("limits"), dict) else {}
    num = lambda k: lim.get(k) if isinstance(lim.get(k), (int, float)) and not isinstance(lim.get(k), bool) else None  # noqa: E731
    kind = "field" if code == "CONTOUR3D_FIELD_EMPTY" else "other"
    if code == "CONTOUR3D_TOO_LARGE":
        if num("nodes") is not None and num("max_nodes") is not None and num("nodes") > num("max_nodes"):
            kind = "nodes"
        elif num("glb_bytes") is not None and num("max_glb_bytes") is not None and num("glb_bytes") > num("max_glb_bytes"):
            kind = "glb"
        elif num("max_bin_bytes") is not None:
            kind = "frames"
    disp = row.get("display") or {}
    return {"kind": kind, "code": code, "message_ko": message_ko(code), "detail": str(man.get("message") or "")[:300] or None,
            "nodes": num("nodes") if num("nodes") is not None else row.get("nodes"), "max_nodes": num("max_nodes"),
            "glb_bytes": num("glb_bytes"), "max_glb_bytes": num("max_glb_bytes"),
            "bin_bytes": num("bin_bytes"), "max_bin_bytes": num("max_bin_bytes"),
            "field": disp.get("field") or None, "comps_applicable": bool(disp.get("comps_applicable", True))}


def out(conn: Any, row: dict[str, Any], cache_hit: bool = False, ctx: AppContext | None = None) -> dict[str, Any]:
    """응답. 변위·LOD 산출물 id는 같은 작업의 artifacts에서 kind로 찾는다(캐시 행에 열 없음, §5.6). `retryable`·`reason`은 화면의
    [다시] 버튼·대체 사유 한 줄용(§10·§12): [다시]는 작업 FAILED·CANCELED에만, 결과 FAIL(DONE)은 사유만 보이고 다시 만들지 않는다."""
    extra = {"disp_artifact_id": None, "lod_artifact_id": None}
    if row["status"] == "DONE" and row.get("result_status") == "OK" and row.get("job_id"):
        kinds = {a["kind"]: a["id"] for a in artifacts_repo.list_for_job(conn, row["job_id"])}
        extra = {"disp_artifact_id": kinds.get("CONTOUR3D_DISP"), "lod_artifact_id": kinds.get("CONTOUR3D_LOD")}
    return {"id": row["id"], "job_id": row.get("job_id"), "status": row["status"], "cache_hit": cache_hit,
            "source_kind": row["source_kind"], "source_ref": row.get("source_ref") or {}, "display": row.get("display"),
            "result_status": row.get("result_status"), "code": row.get("code"), "message_ko": message_ko(row.get("code")),
            "frames": row.get("frames"), "nodes": row.get("nodes"), "bytes": row.get("bytes"),
            "glb_artifact_id": row.get("glb_artifact_id"), "frames_artifact_id": row.get("frames_artifact_id"),
            "manifest_artifact_id": row.get("manifest_artifact_id"), **extra, "timing": row.get("timing"),
            "progress": progress_of(conn, row), "retryable": row["status"] in ("FAILED", "CANCELED"),
            "reason": _fail_reason(ctx, conn, row), "created_at": row.get("created_at"), "finished_at": row.get("finished_at")}


def create(ctx: AppContext, principal: Principal, body: Any, rid: str, ip: str | None) -> tuple[dict[str, Any], int]:
    s = ctx.settings
    t, r = contour3d_missing(s)
    if t or r:
        raise DomainError("CONTOUR3D_NOT_CONFIGURED", message_ko("CONTOUR3D_NOT_CONFIGURED") or "", status=409, missing=t + r)
    with ctx.engine.connect() as conn:
        st0, h3d, source_id, ps, jdisp, cushion = _resolve(ctx, conn, body.source_kind, dict(body.source_ref))
    root = study_root(ctx, st0)
    if not os.path.isfile(h3d) or is_link_or_reparse(h3d):
        raise DomainError("PREREQUISITE_MISSING", "결과 h3d 파일이 없습니다", status=409, missing=["H3D"])
    disp = _display(ctx, ps, jdisp, body, cushion)
    stt = os.stat(h3d)
    c3 = s.contour3d
    key = cache_key(source_kind=body.source_kind, source_id=source_id, h3d_size=stt.st_size, h3d_mtime_ns=stt.st_mtime_ns, display=disp,
                    max_frames=c3.max_frames, include_disp=c3.include_disp, comps=disp["comps"], limits=limits_of(c3),
                    lod_min_nodes=c3.lod_min_nodes, lod_target_vertices=c3.lod_target_vertices, meshopt=c3.meshopt,
                    extract_tcl=tcl_hash(effective_extract_tcl(s)))
    cid = str(uuid.uuid4())
    with ctx.engine.begin() as conn:
        study = studies_repo.require(conn, st0["id"], for_update=True)
        study_gate(conn, study, "CONTOUR_3D")
        row = gv_repo.live_by_key(conn, gv_repo.CONTOURS, key, for_update=True)
        if row is not None and row["status"] == "DONE":
            gv_repo.touch(conn, gv_repo.CONTOURS, row["id"])
            return out(conn, row, cache_hit=True, ctx=ctx), 200
        if row is not None:  # 진행 중(QUEUED·RUNNING) — 새 작업 없이 같은 행 공유(member도 허용)
            return out(conn, row, ctx=ctx), 202
        require_power(principal, st0["project_id"])  # 새 생성만 power(C3D-6, 403 시 작업·행 0건)
        if gv_repo.active_count(conn, gv_repo.CONTOURS, principal.user_id) >= s.geometry.view.max_queued_per_user:
            raise DomainError("PREVIEW_BUSY", "3D 컨투어 생성이 많이 대기 중입니다 — 잠시 후 다시 시도하세요", status=429,
                              limit=s.geometry.view.max_queued_per_user)
        h3d_rel = to_rel(root, h3d)
        params = {"contour_id": cid, "source_kind": body.source_kind, "source_ref": dict(body.source_ref), "display": disp,
                  "h3d_rel": h3d_rel, "cache_key": key, "max_frames": s.contour3d.max_frames, "include_disp": s.contour3d.include_disp}
        job = jobs_repo.insert_job(conn, study=study, job_type="CONTOUR_3D", params=params, user_id=principal.user_id,
                                   user_name=principal.display_name)
        row = gv_repo.insert(conn, gv_repo.CONTOURS, {"id": cid, "study_id": study["id"], "cache_key": key, "job_id": job["id"],
                                                      "created_by": principal.user_id, "status": "QUEUED", "source_kind": body.source_kind,
                                                      "source_ref": {**dict(body.source_ref), "h3d_name": os.path.basename(h3d)},
                                                      "display": {"field": disp["field"], "dcomp": disp["component"],
                                                                  "avgmode": disp["avgmode"], "unit": disp["unit"],
                                                                  "comps": disp["comps"], "comps_applicable": not cushion}})
        audit(conn, principal, "CONTOUR3D_CREATE", "job", job["id"], {"contour_id": cid, "source_kind": body.source_kind}, rid, ip)
        return out(conn, row, ctx=ctx), 202


def get(ctx: AppContext, cid: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        row = gv_repo.get(conn, gv_repo.CONTOURS, cid)
        if row is None:
            raise DomainError("NOT_FOUND", "3D 컨투어를 찾을 수 없습니다", status=404)
        return out(conn, row, ctx=ctx)


def cancel(ctx: AppContext, principal: Principal, cid: str, rid: str, ip: str | None) -> dict[str, Any]:
    """대기 안내 화면 [취소](§13.6): 작업 취소 → CANCELED(캐시 안 함). 끝난 행은 409."""
    with ctx.engine.begin() as conn:
        row = gv_repo.get(conn, gv_repo.CONTOURS, cid)
        if row is None:
            raise DomainError("NOT_FOUND", "3D 컨투어를 찾을 수 없습니다", status=404)
        st = studies_repo.require(conn, row["study_id"])
        require_power(principal, st["project_id"])
        if row["status"] not in ("QUEUED", "RUNNING") or not row.get("job_id"):
            raise DomainError("JOB_TERMINAL", "이미 끝난 3D 컨투어 생성입니다", status=409)
        jobs_repo.request_cancel(conn, row["job_id"], principal.user_id)
        audit(conn, principal, "CONTOUR3D_CANCEL", "job", row["job_id"], {"contour_id": cid}, rid, ip)
        return out(conn, gv_repo.get(conn, gv_repo.CONTOURS, cid), ctx=ctx)  # type: ignore[arg-type]
