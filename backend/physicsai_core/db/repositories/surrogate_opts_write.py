"""⑤ 플랫폼 내장 최적화 저장소 갱신(opt·iter 행, 실패, 검증 배치 생성) — surrogate_opts에서 재노출."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.engine import Connection

from ...stage4_predict.batch_matrix import BatchMatrix, batch_dir_rel
from ..tables import studies, surrogate_opt_iters, surrogate_opts
from . import predict_batches as pb_repo
from .jobs import insert_job, row_dict
from .surrogate_opts_read import ACTIVE, get

# ---- 갱신 --------------------------------------------------------------------------------------


def create_opt(conn: Connection, **values: Any) -> dict[str, Any]:
    conn.execute(surrogate_opts.insert().values(**values))
    return get(conn, values["id"])  # type: ignore[return-value]


def set_opt(conn: Connection, opt_id: str, **values: Any) -> None:
    conn.execute(update(surrogate_opts).where(surrogate_opts.c.id == opt_id).values(**values))


def add_iter(conn: Connection, opt_id: str, iter_no: int, kind: str, batch_id: str, *, round_job_id: str | None = None,
             candidates: list[dict[str, Any]] | None = None, fit: dict[str, Any] | None = None) -> None:
    conn.execute(surrogate_opt_iters.insert().values(opt_id=opt_id, iter_no=iter_no, kind=kind, batch_id=batch_id,
                                                     round_job_id=round_job_id, candidates=candidates, fit=fit))


def set_iter(conn: Connection, opt_id: str, iter_no: int, **values: Any) -> None:
    conn.execute(update(surrogate_opt_iters).where(and_(
        surrogate_opt_iters.c.opt_id == opt_id, surrogate_opt_iters.c.iter_no == iter_no)).values(**values))


def fail(conn: Connection, opt_id: str, reason: str) -> bool:
    """진행 중이면 FAILED + 사유(이미 종료면 그대로). 바꿨으면 True."""
    r = conn.execute(update(surrogate_opts).where(and_(surrogate_opts.c.id == opt_id, surrogate_opts.c.status.in_(ACTIVE)))
                     .values(status="FAILED", stop_reason=reason[:32], finished_at=func.now()))
    return bool(r.rowcount)


def _study(conn: Connection, study_id: str) -> dict[str, Any]:
    return row_dict(conn.execute(select(studies).where(studies.c.id == study_id)).first())  # type: ignore[return-value]


def create_opt_batch(conn: Connection, *, opt: Mapping[str, Any], iter_no: int, kind: str, matrix: BatchMatrix,
                     source_meta: Mapping[str, Any], batch_dir_name: str, simlab_mesh_name: str,
                     round_job_id: str | None = None, candidates: list[dict[str, Any]] | None = None,
                     capture: bool | None = None, display: Mapping[str, Any] | None = None, extra: bool = False
                     ) -> tuple[dict[str, Any], dict[str, Any]]:
    """최적화 소유 PREDICT_BATCH 부모 작업(QUEUED) + 배치·run 행 + 반복 행(한 트랜잭션, 등록자 = opt 등록자).

    params는 §14 서버 저장 형식 + `surrogate_opt{id, opt_no, iter_no}`(§18.4), 캡처는 opt 설정(`capture.enabled`)."""
    study = _study(conn, opt["study_id"])
    s = opt["settings"]
    batch_no = pb_repo.next_batch_no(conn, study["id"])
    batch_id = pb_repo.new_batch_id()
    dir_rel = batch_dir_rel(batch_dir_name, batch_no)
    params = {
        "batch_id": batch_id, "batch_no": batch_no, "param_set_id": opt["param_set_id"], "model_id": opt["model_id"],
        "multi_execution": int(s["multi_execution"]), "template_kind": opt["input_kind"],
        "source": {"kind": "lhs" if matrix.source_kind == "LHS" else "table", **dict(source_meta)},
        "capture": {"enabled": bool(s.get("capture")) if capture is None else bool(capture)},
        "surrogate_opt": {"id": opt["id"], "opt_no": opt["opt_no"], "iter_no": iter_no, **({"extra": True} if extra else {})},
    }
    if display:  # D3-61 마무리 캡처: 기준안·최적안 같은 범례(fixed)
        params["display"] = dict(display)
    sv = s.get("vars") if isinstance(s.get("vars"), dict) else None
    if sv:  # native-vars.md §4.2: 소유 배치도 이 최적화의 변수 스냅숏을 기록(워커 bp_prep·조회는 스냅숏 우선)
        params["vars"] = sv
        matrix = dataclasses.replace(matrix, source_meta={**matrix.source_meta, "vars": sv})
    from .param_sets import get as _get_ps

    if (_get_ps(conn, opt["param_set_id"]) or {}).get("engine") == "native":  # geometry-engine.md §7.7: 워커가 엔진으로 분기
        params["engine"] = "native"
    result = {"batch_id": batch_id, "batch_no": batch_no, "run_count": len(matrix.rows), "dir_rel": dir_rel}
    job = insert_job(conn, study=study, job_type="PREDICT_BATCH", params=params, user_id=opt["created_by"],
                     user_name=opt["created_by_name"], result=result)
    batch = pb_repo.create_batch(
        conn, batch_id=batch_id, batch_no=batch_no, study_id=study["id"], job_id=job["id"], param_set_id=opt["param_set_id"],
        model_id=opt["model_id"], input_kind=opt["input_kind"], matrix=matrix, multi_execution=int(s["multi_execution"]),
        dir_rel=dir_rel, simlab_mesh_name=simlab_mesh_name, user_id=opt["created_by"], user_name=opt["created_by_name"],
    )
    add_iter(conn, opt["id"], iter_no, kind, batch_id, round_job_id=round_job_id, candidates=candidates)
    return job, batch
