"""④ 일괄 예측(DOE) 작업 params·사전조건(phase3 §14.5·§14.7 S9): PREDICT_BATCH.

조합 계산은 공용 `batch_matrix.build_matrix_for` — 미리보기(`services/predict_batches.preview`)와 같은 함수(`build_matrix`)를 쓴다.
저장 params에는 표 본문을 넣지 않는다(출처 요약만) — run 값은 predict_batch_runs에, 워커는 배치 행을 읽는다.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any

from pydantic import BaseModel, Field

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import DomainError
from physicsai_core.paths import resolve_in_study
from physicsai_core.stage1_train_data import doe_samples
from physicsai_core.stage4_predict.batch_matrix import BatchMatrix, BatchShapeError, batch_dir_rel, build_matrix_for

from ...context import AppContext
from ...schemas.contour_capture import CaptureDisplay
from ...schemas.predict_batch import BatchSource
from ..common import study_root
from .base import _P, invalid_at, prerequisite_missing, require_model_pscfg
from .stage4_predict import model_for, require_template_features, template_kind


class PredictBatchParams(_P):
    """§14.7 생성 body params. multi_execution = 사용자 입력 동시 실행 수(1~train_data.max_multi_execution)."""

    param_set_id: str | None = None
    model_id: str | None = None
    multi_execution: int = Field(ge=1, le=64)
    source: BatchSource
    display: CaptureDisplay | None = None  # phase3 §15 S10: 배치 단위 컨투어 표시(범례 fixed로 run끼리 비교)


PARAM_MODELS: dict[str, type[BaseModel]] = {
    "PREDICT_BATCH": PredictBatchParams,
}

# prepare → after_insert(같은 요청·같은 스레드)로 조합 행을 넘긴다(params에는 표 본문을 넣지 않으므로)
_PENDING: ContextVar[dict[str, Any] | None] = ContextVar("predict_batch_pending", default=None)


def resolve_param_set(conn: Any, study: dict[str, Any], param_set_id: str | None) -> dict[str, Any]:
    ps = ps_repo.get(conn, param_set_id) if param_set_id else ps_repo.current(conn, study["id"])
    if ps is None or ps["study_id"] != study["id"]:
        raise prerequisite_missing("PARAM_SET")
    return ps


def build_matrix(ctx: AppContext, conn: Any, study: dict[str, Any], ps: dict[str, Any], source: dict[str, Any]
                 ) -> BatchMatrix:
    """source(모양 검사 끝난 dict) → 조합. train_doe는 DOE 상태 확인(409) 후 samples.csv를 읽는다. 모양 오류 → 422."""
    header = rows = None
    if source.get("kind") == "train_doe":
        d = train_repo.get_doe(conn, source.get("doe_id") or "")
        if d is None or d["study_id"] != study["id"] or d["status"] != "READY":
            raise DomainError("DOE_NOT_READY", "READY 상태의 DOE가 필요합니다", status=409)
        if d["sample_status"] not in ("PARSED", "PARTIAL") or not d["samples_rel"]:
            raise DomainError("SAMPLES_MISSING", "DOE 샘플 표가 없습니다(샘플 추출기 설정 확인)", status=409)
        path = resolve_in_study(study_root(ctx, study), d["samples_rel"])
        if not os.path.isfile(path):
            raise DomainError("SAMPLES_MISSING", "DOE 샘플 표 파일이 없습니다(Study 정리로 옮겨졌을 수 있습니다)", status=409)
        header, rows = doe_samples.read_samples_csv(path)
    try:
        return build_matrix_for(source, ps, ctx.settings, samples_header=header, samples=rows)
    except BatchShapeError as exc:
        raise invalid_at("source", str(exc)) from None


def source_invalid(problems: list[dict[str, Any]]) -> DomainError:
    return DomainError("BATCH_SOURCE_INVALID", "조합을 만들 수 없습니다", status=422, problems=problems)


def prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any
            ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    """사전조건(§14.7 순서): 세트(409) → 템플릿 종류별 기능(409) → 모델(409) → 동시 실행 수(422) → 조합(422·409)."""
    cfg = ctx.settings
    if job_type != "PREDICT_BATCH":
        raise invalid_at("job_type", "unknown")
    ps = resolve_param_set(conn, study, p.param_set_id)
    kind = template_kind(ps)
    require_template_features(cfg, kind)
    m = model_for(conn, study, p.model_id)
    require_model_pscfg(cfg, "edspy_predict", m)
    cap = cfg.train_data.max_multi_execution
    if p.multi_execution > cap:
        raise invalid_at("multi_execution", f"동시 실행 수는 1~{cap}")
    source = p.source.model_dump()
    matrix = build_matrix(ctx, conn, study, ps, source)
    if matrix.problems or not matrix.rows:
        raise source_invalid(matrix.problems or [{"code": "TOO_FEW_ROWS", "message": "조합이 없습니다"}])
    batch_no = pb_repo.next_batch_no(conn, study["id"])  # create_job이 Study 행을 잠근 트랜잭션(D3-25)
    batch_id = pb_repo.new_batch_id()
    dir_rel = batch_dir_rel(cfg.predict_batch.dir_name, batch_no)
    params = {
        "batch_id": batch_id, "batch_no": batch_no, "param_set_id": ps["id"], "model_id": m["id"],
        "multi_execution": p.multi_execution, "template_kind": kind,
        "source": {"kind": source["kind"], **matrix.source_meta},  # 표 본문 저장 안 함(§14.3)
    }
    _PENDING.set({"batch_id": batch_id, "matrix": matrix, "dir_rel": dir_rel,
                  "simlab_mesh_name": cfg.predict.simlab_mesh_name})
    result = {"batch_id": batch_id, "batch_no": batch_no, "run_count": len(matrix.rows), "dir_rel": dir_rel}
    return params, result, []


def after_insert(conn: Any, principal: Any, study: dict[str, Any], job_type: str, job_id: str, params: dict[str, Any],
                 result: dict[str, Any] | None) -> None:
    """같은 트랜잭션에서 배치 행 + run 행(GENERATING, gen_state PENDING)."""
    pend = _PENDING.get()
    _PENDING.set(None)
    if pend is None or pend["batch_id"] != params.get("batch_id"):
        raise RuntimeError("PREDICT_BATCH 조합이 준비되지 않았습니다")
    pb_repo.create_batch(
        conn, batch_id=params["batch_id"], batch_no=params["batch_no"], study_id=study["id"], job_id=job_id,
        param_set_id=params["param_set_id"], model_id=params["model_id"], input_kind=params["template_kind"],
        matrix=pend["matrix"], multi_execution=params["multi_execution"], dir_rel=pend["dir_rel"],
        simlab_mesh_name=pend["simlab_mesh_name"], user_id=principal.user_id, user_name=principal.display_name,
    )


def on_retry(conn: Any, old: dict[str, Any], new_id: str) -> None:
    """부모 재시도(기존 /jobs/{id}/retry): 최신 부모를 새 작업으로, 배치 GENERATING, 생성 실패·중단 run은 생성 대기로."""
    bid = (old.get("params") or {}).get("batch_id")
    b = pb_repo.get(conn, bid, for_update=True) if isinstance(bid, str) else None
    if b is None or b["job_id"] != old["id"]:
        return
    pb_repo.reset_failed_gen(conn, b["id"])
    pb_repo.set_parent_job(conn, b["id"], new_id)
