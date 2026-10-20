"""API 스키마 — ⑤ 해석 등가성 판정(equiv-check.md §6): 레시피·판정 생성·이력·결과."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import Field

from .common import Req, Resp
from .jobs import JobSummary

__all__ = [
    "EqRecipeRef", "EqRecipeCreate", "EqRecipeUpdate", "EqRecipeListItem", "EqRecipe", "EqProblem",
    "EqSideTrainDoe", "EqSidePredictBatch", "EqSideFemVerify", "EqSideFolder", "EqSide", "EqPairing", "EqRecipeInline",
    "EqCheckCreate", "EqPreview", "EqCheckCreated", "EqCheckListItem", "EqCheck", "EqCurves", "EqNotePatch",
]


class EqProblem(Resp):
    code: str
    message: str
    metric_id: str | None = None
    side: str | None = None
    only_a: list[str] | None = None
    only_b: list[str] | None = None


# ---- 레시피 -------------------------------------------------------------------------------------------


class EqRecipeRef(Req):
    key: str = Field(max_length=64)
    version: int | None = Field(default=None, ge=1)


class EqRecipeCreate(Req):
    """생성: definition 직접 | clone_from(레시피 key·version) | from_check(이력 스냅숏 복제) 중 하나."""

    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=500)
    scope: Literal["study", "global"] = "study"
    study_id: str | None = Field(default=None, max_length=64)
    definition: dict[str, Any] | None = None
    clone_from: EqRecipeRef | None = None
    from_check: str | None = Field(default=None, max_length=64)


class EqRecipeUpdate(Req):
    base_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=500)
    definition: dict[str, Any]


class EqRecipeListItem(Resp):
    key: str
    version: int
    name: str
    description: str = ""
    scope: Literal["system", "study", "global"]
    study_id: str | None = None
    metrics_count: int
    updated_at: datetime | None = None
    updated_by_name: str | None = None
    readonly: bool
    deleted: bool = False
    can_edit: bool = False


class EqRecipe(EqRecipeListItem):
    definition: dict[str, Any]
    parent: dict[str, Any] | None = None
    versions: list[dict[str, Any]] | None = None


# ---- 판정 요청 --------------------------------------------------------------------------------------


class EqSideTrainDoe(Req):
    kind: Literal["train_doe"]
    doe_id: str = Field(max_length=64)
    label: str | None = Field(default=None, max_length=120)


class EqSidePredictBatch(Req):
    kind: Literal["predict_batch"]
    batch_id: str = Field(max_length=64)
    label: str | None = Field(default=None, max_length=120)


class EqSideFemVerify(Req):
    kind: Literal["fem_verify"]
    fv_id: str = Field(max_length=64)
    attempt: int | None = Field(default=None, ge=1)
    label: str | None = Field(default=None, max_length=120)


class EqSideFolder(Req):
    kind: Literal["folder"]
    paths: list[Annotated[str, Field(min_length=1, max_length=400)]] = Field(min_length=1, max_length=500)
    label: str | None = Field(default=None, max_length=120)


EqSide = Annotated[Union[EqSideTrainDoe, EqSidePredictBatch, EqSideFemVerify, EqSideFolder], Field(discriminator="kind")]


class EqPairItem(Req):
    a: str = Field(max_length=200)
    b: str = Field(max_length=200)


class EqPairing(Req):
    mode: Literal["by_name", "by_params", "manual"] = "by_name"
    pairs: list[EqPairItem] | None = Field(default=None, max_length=5000)


class EqRecipeInline(Req):
    definition: dict[str, Any]
    base: EqRecipeRef | None = None


class EqCheckCreate(Req):
    """실행(202). recipe(저장된 레시피·시스템 기본 `sys:default`) 또는 recipe_inline(불러온 뒤 수정한 1회용) 중 하나 필수.
    bindings = {metric_id: source} — 레시피의 빈 원천(연결 필요)을 채운다. 필수 지표가 비어 있으면 422 METRIC_UNBOUND."""

    side_a: EqSide
    side_b: EqSide
    pairing: EqPairing = Field(default_factory=EqPairing)
    recipe: EqRecipeRef | None = None
    recipe_inline: EqRecipeInline | None = None
    bindings: dict[str, dict[str, Any] | None] | None = None
    note: str | None = Field(default=None, max_length=500)


class EqPreview(Resp):
    side_a: dict[str, Any]
    side_b: dict[str, Any]
    pairing: dict[str, Any]
    pairs: list[dict[str, Any]]
    unmatched_a: list[str]
    unmatched_b: list[str]
    metrics: list[dict[str, Any]]
    extract: dict[str, Any]
    problems: list[EqProblem]
    warnings: list[EqProblem]
    can_run: bool


class EqCheckCreated(Resp):
    eq_id: str
    eq_no: int
    label: str
    job_id: str


class EqCheckListItem(Resp):
    id: str
    label: str
    eq_no: int
    status: str
    status_text: str
    verdict: str | None = None
    verdict_text: str | None = None
    side_a: dict[str, Any]
    side_b: dict[str, Any]
    pairing: dict[str, Any]
    recipe: dict[str, Any]
    summary_line: str | None = None
    note: str | None = None
    created_at: datetime
    created_by: str
    created_by_name: str
    finished_at: datetime | None = None
    job_id: str | None = None


class EqCheck(EqCheckListItem):
    recipe_snapshot: dict[str, Any]
    summary: dict[str, Any] | None = None
    metrics: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    pairs: list[dict[str, Any]]
    unmatched_a: list[str] = Field(default_factory=list)
    unmatched_b: list[str] = Field(default_factory=list)
    warnings: list[EqProblem] = Field(default_factory=list)
    failure: EqProblem | None = None
    job: JobSummary | None = None
    dir: str | None = None
    can_edit_note: bool = False
    can_cancel: bool = False
    can_retry: bool = False


class EqCurves(Resp):
    pair_no: int
    metric_id: str
    a_run: str
    b_run: str
    t: list[float]
    a: list[float]
    b: list[float]
    corr: float | None = None
    nrmse_pct: float | None = None
    overlap_ratio: float | None = None
    downsampled: bool = False


class EqNotePatch(Req):
    note: str | None = Field(default=None, max_length=500)
