"""⑤ 플랫폼 내장 최적화 API(phase3 §18.6 S13): 미리보기·생성·목록·상세·runs.csv·일괄 취소·이어서 실행.

권한: 조회·미리보기 = 로그인(member), 생성·이어서 실행 = power, 취소 = power + (등록자 또는 전역 관리자).
생성은 한 트랜잭션(Study 행 FOR UPDATE, D3-25): opt 행 + 탐색 PREDICT_BATCH(새 DOE) 또는 반복 작업 1(재사용).
목적·제약 값은 공용 `run_metrics`(§17.3)로 계산한다 — API는 numpy를 불러오지 않는다(§18.2).
300줄 분할(R-B): 목록·상세·진행 문구·run CSV는 `surrogate_opts_view`(여기서 재노출).
"""

from __future__ import annotations

from typing import Any

from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import surrogate_opts as so_repo
from physicsai_core.errors import DomainError
from physicsai_core.stage4_predict.batch_matrix import build_matrix_for, lhs_values
from physicsai_core.stage5_optimize.surrogate import criteria

from ..auth import Principal
from ..context import AppContext
from .common import audit, require_config_ok, require_power
from .job_params.study_manage import study_gate
from .jobs import retry_locked
from .predict_batches import _estimate_min, retry_failed_locked
from .surrogate_opt_problem import MAX_CONSTRAINTS, require_feature  # noqa: F401 - 재노출(기존 import 경로)
from .surrogate_opt_problem import normalize as _normalize
from .surrogate_opts_view import (  # noqa: F401 - 기존 경로 재노출
    FAIL_TEXT, STOP_TEXT, _require_opt, list_opts, collect_runs, progress_text, _detail, get_opt, runs_csv,
)


def _invalid(problems: list[dict[str, Any]]) -> DomainError:
    return DomainError("SURROGATE_OPT_INVALID", "내장 최적화 설정이 올바르지 않습니다", status=422, problems=problems)


def preview(ctx: AppContext, study_id: str, body: Any) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        s = studies_repo.require(conn, study_id)
        n = _normalize(ctx, conn, s, body)
        st = n["settings"]
        none = st.get("verification") == "none"  # opt-native §8: 대리모델만 = 탐색 수만(재사용 0)
        total = n["explore_count"] + (0 if none else st["iterations"] * st["candidates"])
        est = _estimate_min(conn, study_id, total) if total else None
    return {"free_variables": n["free"], "integer_variables": [x for x in n["integer"] if x in n["free"]],
            "fixed": n["fixed"], "explore_count": n["explore_count"], "max_total_runs": total, "estimate_min": est,
            "objective_available": n["valid_points"] is None or n["valid_points"] > 0, "problems": n["problems"],
            "mode": st["mode"], "performances": n["performances"], "algorithm": st["algorithm"],
            "algo_options": st["algo_options"], "verification": st["verification"], "variables_kind": n["variables_kind"],
            "levels": st.get("levels")}


def create(ctx: AppContext, principal: Principal, study_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    cfg = ctx.settings
    with ctx.engine.begin() as conn:
        study = studies_repo.require(conn, study_id, for_update=True)
        require_power(principal, study["project_id"])
        require_config_ok(ctx)
        study_gate(conn, study, "SURROGATE_OPT")
        n = _normalize(ctx, conn, study, body)
        if n["criteria_missing"]:  # opt-native ON-C3: 사용자가 정하지 않은 기준은 채우지 않고 막는다
            raise DomainError(criteria.CODE, criteria.MESSAGE, status=422, missing=n["criteria_missing"],
                              problems=criteria.problems_of(n["criteria_missing"]))
        if n["problems"]:
            raise _invalid(n["problems"])
        if so_repo.active_for_study(conn, study_id) is not None:
            raise DomainError("SURROGATE_OPT_ACTIVE", "이 Study에 진행 중인 내장 최적화가 있습니다 — 끝나거나 취소한 뒤 시작하세요",
                              status=409)
        st = n["settings"]
        no = so_repo.next_opt_no(conn, study_id)
        oid = so_repo.new_opt_id()
        opt = so_repo.create_opt(
            conn, id=oid, study_id=study_id, opt_no=no, param_set_id=n["ps"]["id"], model_id=n["model"]["id"],
            input_kind=n["kind"], settings=st, status="EXPLORING" if n["reuse"] is None else "FITTING", iter_no=0,
            dir_rel=so_repo.opt_dir_rel(cfg.surrogate_opt.dir_name, no), created_by=principal.user_id,
            created_by_name=principal.display_name)
        if n["reuse"] is not None:
            so_repo.add_iter(conn, oid, 0, "REUSE", n["reuse"]["id"])
            job = so_repo.enqueue_round(conn, opt, 1)
        else:
            job, _b = _explore_batch(ctx, conn, opt, n)
        audit(conn, principal, "SURROGATE_OPT_CREATE", "surrogate_opt", oid, {"study_id": study_id, "job_id": job["id"]}, rid, ip)
        return _detail(ctx, conn, so_repo.get(conn, oid), principal)  # type: ignore[arg-type]


def _explore_batch(ctx: AppContext, conn: Any, opt: dict[str, Any], n: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """탐색 배치(새 DOE LHS): 범위(고정 변수는 lo = hi)로 batch_matrix와 같은 층화 LHS 값을 만들어 표 조합으로 검증·반영."""
    st = n["settings"]
    ex = st["explore"]
    if n.get("multi") is not None:  # opt-native §7: 다중 baseline = §7.3.8 층화 LHS(④ 다중 baseline 배치와 같은 경로)
        from physicsai_core.stage4_predict.batch_multi import build_multi_matrix, restrict

        levels = (st.get("levels") or {}).get("baseline")
        pm2, rows2 = restrict(n["multi"]["pm"], list(n["ps"]["parameters"]), levels, st["bounds"])
        mx = build_multi_matrix({"kind": "lhs", "count": ex["count"], "seed": ex["seed"]}, {**n["ps"], "parameters": rows2}, pm2,
                                ctx.settings)
        if mx.problems or not mx.rows:
            raise _invalid([{"code": "EXPLORE_TOO_FEW", "field": "explore", "message": str(mx.problems[:3])}])
        meta_m = {**mx.source_meta, "ranges": st["bounds"]}
        mx.source_meta = meta_m
        return so_repo.create_opt_batch(conn, opt=opt, iter_no=0, kind="EXPLORE", matrix=mx, source_meta=meta_m,
                                        batch_dir_name=ctx.settings.predict_batch.dir_name,
                                        simlab_mesh_name=ctx.settings.predict.simlab_mesh_name)
    names = [x for x in st["names"] if x in {str(p["name"]) for p in n["ps"]["parameters"]}]
    vals = lhs_values(names, {k: (v[0], v[1]) for k, v in st["bounds"].items()}, ex["count"], ex["seed"])
    text = "\n".join([",".join(names), *[",".join(repr(float(v[k])) for k in names) for v in vals]]) + "\n"
    matrix = build_matrix_for({"kind": "table", "text": text}, n["ps"], ctx.settings)
    if matrix.problems or not matrix.rows:
        raise _invalid([{"code": "EXPLORE_TOO_FEW", "field": "explore", "message": str(matrix.problems[:3])}])
    matrix.source_kind = "LHS"
    meta = {"count": ex["count"], "seed": ex["seed"], "ranges": st["bounds"]}
    matrix.source_meta = meta
    return so_repo.create_opt_batch(conn, opt=opt, iter_no=0, kind="EXPLORE", matrix=matrix, source_meta=meta,
                                    batch_dir_name=ctx.settings.predict_batch.dir_name,
                                    simlab_mesh_name=ctx.settings.predict.simlab_mesh_name)


# ---- 취소·이어서 실행 ----------------------------------------------------------------------------------


def cancel(ctx: AppContext, principal: Principal, opt_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        o = _require_opt(conn, opt_id, for_update=True)
        s = studies_repo.require(conn, o["study_id"])
        require_power(principal, s["project_id"])
        if not principal.is_global_admin and o["created_by"] != principal.user_id:
            raise DomainError("PERMISSION_DENIED", "내장 최적화 등록자 또는 관리자만 취소할 수 있습니다", status=403,
                              required="owner_or_global_admin")
        done = so_repo.cancel(conn, o, principal.user_id)
        audit(conn, principal, "SURROGATE_OPT_CANCEL", "surrogate_opt", o["id"], {"job_ids": done}, rid, ip)
        return _detail(ctx, conn, so_repo.get(conn, o["id"]), principal)  # type: ignore[arg-type]


def resume(ctx: AppContext, principal: Principal, opt_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    """FAILED만: 반복 작업 실패면 그 작업 재시도(on_retry가 opt FITTING), 배치 실패면 배치 실패만 다시(가드 우회)."""
    with ctx.engine.begin() as conn:
        o = _require_opt(conn, opt_id, for_update=True)
        study = studies_repo.require(conn, o["study_id"], for_update=True)
        require_power(principal, study["project_id"])
        require_config_ok(ctx)
        if o["status"] != "FAILED":
            raise DomainError("SURROGATE_OPT_NOT_RESUMABLE", "실패한 내장 최적화만 이어서 실행할 수 있습니다", status=409)
        if so_repo.active_for_study(conn, o["study_id"]) is not None:
            raise DomainError("SURROGATE_OPT_ACTIVE", "이 Study에 진행 중인 내장 최적화가 있습니다", status=409)
        out: dict[str, Any] = {"job_id": None, "batch_retry": None}
        if o["stop_reason"] == "BATCH_FAILED":
            it = so_repo.get_iter(conn, o["id"], o["iter_no"])
            b = pb_repo.get(conn, it["batch_id"], for_update=True) if it else None
            if b is None:
                raise DomainError("SURROGATE_OPT_NOT_RESUMABLE", "이어서 실행할 배치가 없습니다", status=409)
            out["batch_retry"] = retry_failed_locked(conn, principal, b, study, rid, ip)
            so_repo.set_opt(conn, o["id"], status="EXPLORING" if o["iter_no"] == 0 else "VERIFYING", stop_reason=None,
                            finished_at=None)
            # 하위만 다시 실행하면 배치는 PREDICTING으로 돌아가고, 끝나면 종료 훅이 다음 반복 작업을 넣는다
        else:
            old = jobs_repo.get_job(conn, o["current_job_id"]) if o["current_job_id"] else None
            if old is None:
                raise DomainError("SURROGATE_OPT_NOT_RESUMABLE", "이어서 실행할 반복 작업이 없습니다", status=409)
            # 반복 작업이 검증 배치를 등록한 뒤 실패했으면 다시 돌리지 않고 VERIFYING으로(배치 완료 훅이 이어 감)
            restored = so_repo.restore_verifying(conn, o, int((old.get("params") or {}).get("round") or 0))
            if restored is not None:
                out["job_id"] = restored["round_job_id"]
                out["batch_retry"] = {"restored_batch_id": restored["batch_id"]}
            else:
                out["job_id"] = retry_locked(conn, principal, old, 1, rid, ip)["id"]
        audit(conn, principal, "SURROGATE_OPT_RESUME", "surrogate_opt", o["id"], out, rid, ip)
        return out
