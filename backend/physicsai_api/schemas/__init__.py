"""API 스키마(계약 §10). 요청은 알 수 없는 키를 거부(422 INVALID_PARAMS)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Resp(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ---- 공통 ----------------------------------------------------------------


class ErrorBody(Resp):
    code: str
    message: str


class ErrorResponse(Resp):
    detail: ErrorBody


class Health(Resp):
    status: str
    version: str


class Me(Resp):
    user_id: str
    username: str
    display_name: str
    is_global_admin: bool
    roles: dict[str, str]


class Project(Resp):
    id: str
    name: str
    product_name: str | None = None


# ---- 상태·대기열·자원 -----------------------------------------------------


class StatusConfig(Resp):
    ok: bool
    errors: list[str]


class StatusWorker(Resp):
    online: bool
    worker_id: str | None = None
    last_seen_at: datetime | None = None
    limiter: str | None = None


class StatusHpc(Resp):
    mode: str
    configured: bool
    message: str
    collect_mode: str = "in_place"


class KeyOk(Resp):
    key: str
    ok: bool


class TemplateConfigured(Resp):
    key: str
    configured: bool


class StatusLimits(Resp):
    configured: dict[str, Any]
    detected: dict[str, Any] | None = None
    effective: dict[str, Any] | None = None


class ResourceStatus(Resp):
    key: str
    configured: bool
    ok: bool


class FeatureState(Resp):
    enabled: bool
    missing: list[str]


class StatusFeatures(Resp):
    train_extract: FeatureState
    train_tpl: FeatureState
    train_doe: FeatureState
    train_solve: FeatureState
    train_import: FeatureState
    train_resp: FeatureState
    curation_h3d: FeatureState
    curation_t01: FeatureState
    spdm_import: FeatureState
    optimize: FeatureState


class StatusEnvCheck(Resp):
    latest_id: str | None = None
    latest_state: str | None = None
    finished_at: datetime | None = None
    fail: int | None = None
    warn: int | None = None


class StatusResponse(Resp):
    config: StatusConfig
    worker: StatusWorker
    hpc: StatusHpc
    altair: list[KeyOk]
    templates: list[TemplateConfigured]
    limits: StatusLimits
    ui: dict[str, int]
    auth: dict[str, str]
    resources: list[ResourceStatus] = Field(default_factory=list)
    features: StatusFeatures | None = None
    env_check: StatusEnvCheck | None = None
    demo: bool = Field(False, description="시연 모드(fake tools 배포판) 여부 — true면 화면 상단에 '시연 모드' 배지")


class HpcSummary(Resp):
    total: int
    queued: int
    running: int
    succeeded: int
    failed: int
    collected: int


class JobSummary(Resp):
    id: str
    study_id: str
    project_id: str
    study_title: str | None = None
    job_type: str
    stage: int
    lane: str
    state: str
    created_by: str
    created_by_name: str
    queue_position: int | None = None
    progress_pct: float | None = None
    progress_label: str | None = None
    cancel_requested: bool
    created_at: datetime
    started_at: datetime | None = None
    stage_label: str | None = None
    current_step_key: str | None = None
    current_step_label: str | None = None
    hpc_summary: HpcSummary | None = None
    attention_code: str | None = None


class JobStep(Resp):
    step_no: int
    step_key: str
    kind: str
    state: str
    progress_pct: float | None = None
    progress_label: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    command: dict[str, Any] | None = None


class Job(JobSummary):
    params: dict[str, Any]
    result: dict[str, Any] | None = None
    warnings: list[dict[str, Any]]
    steps: list[JobStep]
    failure_code: str | None = None
    failure_message: str | None = None
    finished_at: datetime | None = None
    retry_of_job_id: str | None = None
    version: int
    can_cancel: bool
    can_retry: bool
    can_download_error_bundle: bool = False
    input_display_path: str | None = None


class QueueSlot(Resp):
    holder_job_id: str | None = None
    since: datetime | None = None


class QueueLight(Resp):
    running: JobSummary | None = None
    queued: list[JobSummary]


class QueueResponse(Resp):
    slot: QueueSlot
    running: JobSummary | None = None
    queued: list[JobSummary]
    light: QueueLight
    waiting_hpc: list[JobSummary]
    collecting: list[JobSummary]


class MoveRequest(Req):
    position: int = Field(ge=1)


class GpuInfo(Resp):
    name: str
    util_pct: float | None = None
    mem_used_mb: float | None = None
    mem_total_mb: float | None = None


class ResourceJob(Resp):
    job_id: str
    cpu_time_s: float | None = None
    peak_memory_gb: float | None = None


class ResourceLimits(Resp):
    cores: int | None = None
    cpu_rate: int | None = None
    memory_gb: float | None = None
    priority: str | None = None
    cpu_cap_enforced: bool = False


class ResourcesResponse(Resp):
    sampled_at: datetime | str | None = None
    cpu_pct: float | None = None
    ram_used_gb: float | None = None
    ram_total_gb: float | None = None
    gpu: list[GpuInfo]
    job: ResourceJob | None = None
    limits: ResourceLimits


# ---- Study·경로 ------------------------------------------------------------


class Study(Resp):
    id: str
    project_id: str
    folder_name: str
    title: str
    status: str
    final_model_id: str | None = None
    created_by: str
    created_by_name: str
    created_at: datetime
    updated_at: datetime
    version: int
    can_execute: bool
    folder_display_path: str | None = None


class StudyCreate(Req):
    project_id: str = Field(min_length=1, max_length=200)
    folder_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
    title: str = Field(min_length=1, max_length=120)

    @field_validator("folder_name")
    @classmethod
    def _not_reserved(cls, v: str) -> str:
        from physicsai_core.paths import windows_reserved_name

        if windows_reserved_name(v):
            raise ValueError("Windows 예약 이름(CON·PRN·AUX·NUL·COM1-9·LPT1-9)은 폴더 이름으로 쓸 수 없습니다")
        return v


class StudyPatch(Req):
    version: int
    title: str = Field(min_length=1, max_length=120)


class PathInspectRequest(Req):
    purpose: Literal["DATASET_INPUT", "MODEL_FOLDER", "PARAM_SET", "CAD_FILE", "RADIOSS_ASSEM", "RESULT_FOLDER",
                     "CURATION_INPUT", "SPDM_IMPORT"]
    path: str = Field(max_length=400)
    doe_id: str | None = None


class PathProblem(Resp):
    code: str
    message: str | None = None
    file: str | None = None


class PathInspectResponse(Resp):
    normalized_path: str
    ok: bool
    problems: list[PathProblem]
    summary: dict[str, Any]


# ---- 데이터셋·모델·파라미터 세트 -------------------------------------------


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


class ParamSetCreate(Req):
    path: str = Field(max_length=400)


class Parameter(Resp):
    name: str
    nominal: float
    min: float
    max: float
    unit: str = ""


class ResponseDef(Resp):
    name: str
    unit: str = ""


class TplParam(Resp):
    var: str
    name: str
    format: str


class ParamSet(Resp):
    id: str
    study_id: str
    source_path: str
    unit_system: str
    parameters: list[Parameter]
    responses: list[ResponseDef]
    sample_count: int
    sample_has_measured: bool
    cad_file_name: str
    starter_name: str
    tpl_params: list[TplParam]
    is_current: bool
    registered_by_name: str
    registered_at: datetime
    origin: str = "FOLDER"
    train_doe_id: str | None = None


class SampleRow(Resp):
    run_key: str
    values: dict[str, float]
    measured: dict[str, float | None]


class SamplesPage(Resp):
    columns: list[str]
    rows: list[SampleRow]
    next_cursor: str | None = None


class PredictCheckRequest(Req):
    param_set_id: str | None = None
    values: dict[str, float]


class OutOfRange(Resp):
    name: str
    value: float
    min: float
    max: float


class Rounded(Resp):
    name: str
    value: float
    applied: float


class Nearest(Resp):
    run_key: str
    distance: float
    values: dict[str, float]
    measured: dict[str, float | None] | None = None


class PredictCheckResponse(Resp):
    out_of_range: list[OutOfRange]
    rounded: list[Rounded]
    nearest: Nearest | None = None


# ---- 작업 -----------------------------------------------------------------


JobType = Literal[
    "DATASET_CREATE", "PACKAGE_EXPORT", "MODEL_REGISTER", "EVALUATE", "PREDICT", "PREDICT_VERIFY",
    "TD_EXTRACT_PARAMS", "TD_DOE_GEN", "TD_SOLVE", "TD_RESULT_IMPORT", "TD_RESP_EXTRACT", "CU_H3D_PREVIEW", "CU_H3D_CURATE",
    "CU_T01_PREVIEW", "CU_T01_CURVES", "SPDM_IMPORT", "OPTIMIZE",
]


class JobCreate(Req):
    job_type: JobType
    params: dict[str, Any] = Field(default_factory=dict)


class RetryRequest(Req):
    from_step: int | None = Field(default=None, ge=1)


class LogChunk(Resp):
    text: str
    next_cursor: int
    eof: bool
    size: int


class Artifact(Resp):
    id: str
    study_id: str
    job_id: str | None = None
    kind: str
    file_name: str
    size: int
    sha256: str | None = None
    content_type: str
    created_at: datetime


class HpcJob(Resp):
    id: str
    run_key: str
    attempt_no: int
    external_job_id: str | None = None
    state: str
    external_state_raw: str | None = None
    submitted_at: datetime | None = None
    elapsed_s: float | None = None
    collect_state: str


# ---- 알림 -----------------------------------------------------------------


class Notification(Resp):
    seq: int
    event: str
    job_id: str | None = None
    study_id: str | None = None
    project_id: str | None = None
    title: str
    body: str
    created_at: datetime
    read_at: datetime | None = None


class NotificationList(Resp):
    items: list[Notification]
    max_seq: int
    unread_count: int


class UnreadCount(Resp):
    unread_count: int
    max_seq: int


class ReadRequest(Req):
    seqs: list[int] | None = None
    all: bool = False


class ReadResponse(Resp):
    unread_count: int


class AdminConfig(Resp):
    path: str | None = None
    sha256: str | None = None
    ok: bool
    issues: list[dict[str, str]]
    settings: dict[str, Any]
    templates: dict[str, Any]


# ---- 2차(phase2 §12) ---------------------------------------------------------


class ParamSetFromTrain(Req):
    doe_id: str
    runs: Literal["collected", "all"] = "collected"
    unit_system: str | None = Field(default=None, max_length=40)


class TrainParamOut(Resp):
    name: str
    raw_nominal: str = ""
    nominal: float | None = None
    min: float | None = None
    max: float | None = None
    use: bool
    format: str
    unit: str = ""
    valid: bool
    problems: list[str]


class TrainParamUpdate(Req):
    name: str
    min: float | None = None
    max: float | None = None
    use: bool
    format: str | None = Field(default=None, max_length=16)
    unit: str | None = Field(default=None, max_length=16)


class TrainParamsPut(Req):
    version: int
    parameters: list[TrainParamUpdate]


class VersionBody(Req):
    version: int


class TrainCad(Resp):
    source_path: str | None = None
    file_name: str | None = None
    sha256: str | None = None
    display_path: str | None = None


class TrainTpl(Resp):
    generated_at: datetime | None = None
    sha256: str | None = None
    display_path: str | None = None
    params: list[TplParam]
    warnings: list[dict[str, str]]
    stale: bool


class TrainSetup(Resp):
    study_id: str
    cad: TrainCad | None = None
    extract_job_id: str | None = None
    parameters: list[TrainParamOut]
    used_count: int
    tpl: TrainTpl | None = None
    version: int
    updated_by_name: str | None = None
    updated_at: datetime | None = None


class DoeField(Resp):
    key: str
    label: str
    type: Literal["combo", "int", "bool"]
    items: list[str] | None = None
    default: Any = None
    min: int | None = None
    max: int | None = None


class DoeType(Resp):
    label: str
    value: str
    default_runs: int
    runs_editable: bool
    fields: list[DoeField]


class RunStateCounts(Resp):
    GENERATED: int = 0
    SUBMITTED: int = 0
    SOLVED: int = 0
    SOLVE_FAILED: int = 0
    COLLECTED: int = 0
    COLLECT_FAILED: int = 0


class TrainDoe(Resp):
    id: str
    study_id: str
    job_id: str
    status: str
    doe_label: str
    doe_type: str
    num_runs_requested: int | None = None
    options: dict[str, Any]
    multi_execution: int
    radioss_assem_source_path: str
    run_count: int | None = None
    sample_status: str
    collected_count: int
    solve_failed_count: int
    has_run_responses: bool
    dir_display_path: str | None = None
    results_display_path: str | None = None
    created_by_name: str
    created_at: datetime
    run_state_counts: RunStateCounts


class TrainRunHpc(Resp):
    external_job_id: str | None = None
    state: str
    attempt_no: int


class TrainRunResult(Resp):
    h3d: int = 0
    t01: int = 0
    files: int = 0
    total_bytes: int = 0


class TrainRun(Resp):
    run_key: str
    state: str
    starter_name: str
    input_display_path: str | None = None
    hpc: TrainRunHpc | None = None
    result: TrainRunResult | None = None
    updated_at: datetime


class SourceRef(Resp):
    kind: str
    doe_id: str | None = None
    import_id: str | None = None
    path: str | None = None


class CurationSource(Resp):
    kind: str
    ref_id: str
    label: str
    display_path: str | None = None
    h3d_count: int
    t01_count: int
    runs_expected: int | None = None
    created_at: datetime


class Curation(Resp):
    id: str
    study_id: str
    job_id: str
    kind: str
    status: str
    source: SourceRef
    source_label: str
    preview_job_id: str | None = None
    selection: dict[str, Any]
    target_count: int | None = None
    ok_count: int | None = None
    failed_count: int | None = None
    missing_runs: list[str]
    output_display_path: str | None = None
    used_by_dataset_ids: list[str]
    created_by_name: str
    created_at: datetime


class CurationFile(Resp):
    run_folder: str
    run_key: str | None = None
    input_name: str
    output_name: str | None = None
    size: int | None = None
    ok: bool
    exit_code: int | None = None


class CurationFilesPage(Resp):
    items: list[CurationFile]
    next_cursor: str | None = None


class SpdmImport(Resp):
    id: str
    study_id: str
    job_id: str
    status: str
    spdm_path: str
    file_count: int | None = None
    total_bytes: int | None = None
    renamed_count: int | None = None
    dest_display_path: str | None = None
    created_by_name: str
    created_at: datetime


class Optimization(Resp):
    id: str
    study_id: str
    job_id: str
    status: str
    approach: str
    opt_method: str
    max_designs: int
    model_id: str
    model_name: str | None = None
    param_set_id: str
    study_folder: str
    runs_started: int | None = None
    responses: list[dict[str, Any]]
    summary_status: str
    summary_meta: dict[str, Any] | None = None
    summary_artifact_id: str | None = None
    file_count: int | None = None
    file_list_artifact_id: str | None = None
    folder_display_path: str | None = None
    created_by_name: str
    created_at: datetime


class CandidateDatatype(Resp):
    name: str
    components: list[str]
    layers: list[str]
    format: Any = None


class CandidateSubcase(Resp):
    id: int
    label: str
    datatypes: list[CandidateDatatype]


class CandidateH3d(Resp):
    subcases: list[CandidateSubcase]


class CandidateXy(Resp):
    requests: dict[str, list[str]]


class ResponseCandidates(Resp):
    source_job_id: str | None = None
    h3d: CandidateH3d | None = None
    xydata: CandidateXy | None = None


class EnvCheckItem(Resp):
    key: str
    category: Literal["CONFIG", "DATABASE", "AUTH", "HPC", "WORKER", "EXECUTABLE", "RESOURCE", "STORAGE", "GPU"]
    label: str
    status: Literal["OK", "WARN", "FAIL", "SKIP", "PENDING"]
    message: str
    source: Literal["API", "WORKER"]
    detail: Any = None


class EnvCheckCounts(Resp):
    ok: int = 0
    warn: int = 0
    fail: int = 0
    skip: int = 0


class EnvCheckSummary(Resp):
    id: str
    state: str
    requested_by_name: str
    created_at: datetime
    finished_at: datetime | None = None
    summary: EnvCheckCounts


class EnvCheck(EnvCheckSummary):
    started_at: datetime | None = None
    expires_at: datetime
    worker_id: str | None = None
    items: list[EnvCheckItem]
    failure_message: str | None = None
    report_display_path: str | None = None
