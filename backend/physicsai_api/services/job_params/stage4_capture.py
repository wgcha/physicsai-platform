"""④ 컨투어 재캡처 작업 params·사전조건(phase3 §15 S10): CONTOUR_RECAPTURE, 그리고 예측 작업 params `display` 저장.

생성은 `POST /jobs/{id}/capture`(services/contour_capture.py)가 기존 create_job으로 한다.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field

from physicsai_core.db.repositories import contour_media as media_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.errors import DomainError
from physicsai_core.features import contour_capture_missing
from physicsai_core.paths import resolve_in_study
from physicsai_core.stage4_predict.contour_capture import clean_display

from ...context import AppContext
from ...schemas.contour_capture import CaptureDisplay, CaptureView
from ..common import study_root
from .base import _P, prerequisite_missing


class ContourRecaptureParams(_P):
    source_job_id: str = Field(min_length=1, max_length=64)
    views: list[CaptureView] | None = Field(default=None, min_length=1, max_length=7)
    display: CaptureDisplay | None = None


PARAM_MODELS: dict[str, type[BaseModel]] = {
    "CONTOUR_RECAPTURE": ContourRecaptureParams,
}


def display_param(p: Any) -> dict[str, Any]:
    """요청 params의 `display`(선택)를 저장 형태로({display} 또는 {}). PREDICT·PREDICT_BATCH 공용."""
    d = getattr(p, "display", None)
    if d is None:
        return {}
    cleaned = clean_display(d.model_dump(exclude_none=True))
    return {"display": cleaned} if cleaned else {}


def require_capture_feature(ctx: AppContext) -> None:
    tmpl, res = contour_capture_missing(ctx.settings)
    if tmpl or res:
        raise DomainError("CAPTURE_NOT_CONFIGURED", f"컨투어 캡처 설정 필요(관리자): {', '.join(tmpl + res)}", status=409,
                          missing=tmpl + res)


def prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any
            ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    """원래 작업 = 같은 Study의 성공한 PREDICT, 결과 h3d가 남아 있어야 한다(409). 같은 작업의 재캡처 진행 중이면 409."""
    require_capture_feature(ctx)
    src = jobs_repo.get_job(conn, p.source_job_id)
    if src is None or src["study_id"] != study["id"] or src["job_type"] != "PREDICT" or src["state"] != "SUCCEEDED":
        raise prerequisite_missing("SUCCEEDED_PREDICT")
    pred_rel = (src.get("result") or {}).get("pred_h3d_rel")
    if not pred_rel:
        raise prerequisite_missing("PREDICT_H3D")
    if not os.path.isfile(resolve_in_study(study_root(ctx, study), pred_rel)):
        raise prerequisite_missing("PREDICT_H3D")  # Study 정리로 옮겨졌을 수 있다
    if any(r["state"] not in ("SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED")
           for r in media_repo.recaptures(conn, [src["id"]])):
        raise DomainError("RECAPTURE_ACTIVE", "이 예측의 컨투어 재캡처가 이미 진행 중입니다", status=409)
    params: dict[str, Any] = {"source_job_id": src["id"], **display_param(p)}
    if p.views:
        params["views"] = list(p.views)
    return params, {"source_job_id": src["id"]}, []
