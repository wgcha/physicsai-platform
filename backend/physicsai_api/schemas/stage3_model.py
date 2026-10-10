"""API 스키마 — ③ 데이터셋·모델·Final(§10.4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from .common import Req, Resp
from .studies import Study

__all__ = ["Dataset", "Model", "StudyDetail", "ModelPatch", "FinalModelRequest"]


class Dataset(Resp):
    id: str
    study_id: str
    job_id: str | None = None
    status: str
    source_path: str
    h3d_count: int | None = None
    train_count: int | None = None
    eval_count: int | None = None
    holdout_ratio: float
    seed: int
    split_group: str
    options: dict[str, bool]
    package_ready: bool
    package_rel: str | None = None
    dataset_display_path: str | None = None
    package_display_path: str | None = None
    curation_id: str | None = None
    created_by_name: str
    created_at: datetime


class Model(Resp):
    id: str
    study_id: str
    name: str
    version: int
    label: str | None = None
    dataset_id: str | None = None
    source_path: str
    log_status: str
    log_parser: str | None = None
    epochs_total: int | None = None
    last_epoch: int | None = None
    final_loss: float | None = None
    min_loss: float | None = None
    min_loss_epoch: int | None = None
    loss_curve: list[list[float]] | None = None
    curve_points: int = 0
    eval_status: str
    eval_score: dict[str, Any] | None = None
    status: str
    is_final: bool
    registered_by_name: str
    registered_at: datetime
    row_version: int
    stored_display_path: str | None = None


class StudyDetail(Study):
    final_model: Model | None = None
    stage_status: dict[str, dict[str, Any]]
    current_param_set_id: str | None = None


class ModelPatch(Req):
    row_version: int
    label: str | None = Field(default=None, max_length=120)
    status: Literal["ACTIVE", "ARCHIVED"] | None = None


class FinalModelRequest(Req):
    model_id: str | None
