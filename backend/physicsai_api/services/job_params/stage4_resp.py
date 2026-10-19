"""④ PB_RESP_EXTRACT params·사전조건(phase3 §22.3.5 S17): 끝난 일괄 예측 배치의 H3D 성능 다시 추출.

`POST /predict-batches/{bid}/extract-responses`(권장)와 `POST /studies/{id}/jobs`가 같은 사전조건을 쓴다.
서버가 `param_set_id`와 H3D 성능 이름 목록을 확정 기록한다. Study당 진행 중 1개는 기존 `ux_jobs_study_type_active`(STUDY_JOB_BUSY).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import surrogate_opts as so_repo
from physicsai_core.errors import DomainError
from physicsai_core.features import predict_responses_missing, response_extract_uses_tcl
from physicsai_core.stage4_predict import performance

from ...context import AppContext
from .base import _P


class PbRespExtractParams(_P):
    batch_id: str = Field(max_length=64)


PARAM_MODELS: dict[str, type[BaseModel]] = {"PB_RESP_EXTRACT": PbRespExtractParams}


def prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any
            ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    tmpl, res = predict_responses_missing(ctx.settings)
    if tmpl or res or not response_extract_uses_tcl(ctx.settings):
        missing = tmpl + res or ["commands.response_extract({extract_tcl})"]
        raise DomainError("FEATURE_NOT_AVAILABLE", f"예측 성능 추출을 쓸 수 없습니다(관리자 설정 필요): {', '.join(missing[:3])}",
                          status=409, missing=missing)
    b = pb_repo.get(conn, p.batch_id)
    if b is None or b["study_id"] != study["id"]:
        raise DomainError("BATCH_NOT_FOUND", "일괄 예측을 찾을 수 없습니다", status=404)
    if b["status"] != "DONE":
        raise DomainError("BATCH_NOT_DONE", "완료(DONE)된 배치만 성능을 다시 추출할 수 있습니다", status=409)
    it = so_repo.owned_iter_of_batch(conn, b["id"])
    if it is not None and it["opt_status"] in so_repo.ACTIVE:
        raise DomainError("BATCH_OWNED_BY_OPT",
                          f"진행 중인 내장 최적화 {so_repo.opt_label(it['opt_no'])}의 배치입니다 — 끝난 뒤 다시 추출하세요",
                          status=409, surrogate_opt_id=it["opt_id"])
    ps = ps_repo.get(conn, b["param_set_id"]) or {}
    names = [n for n, d in performance.perf_defs(ps.get("responses")).items() if d.source == "H3D"]
    if not names:
        raise DomainError("NO_H3D_PERFORMANCE", "템플릿에 H3D 성능이 없습니다 — 커브 성능은 다시 추출하지 않아도 됩니다", status=422)
    params = {"batch_id": b["id"], "param_set_id": b["param_set_id"], "performances": names}
    return params, {"batch_id": b["id"]}, []
