"""API 스키마 — 셸: 상태·대기열·자원·알림·관리 설정(§10.5, §10.7, §10.8, phase2 §12.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from .common import Req, Resp
from .jobs import JobSummary

__all__ = [
    "StatusConfig", "StatusWorker", "StatusHpc", "KeyOk", "TemplateConfigured", "StatusLimits", "ResourceStatus",
    "FeatureState", "StatusFeatures", "StatusEnvCheck", "StatusCapture", "StatusCaptureEstimate", "StatusSurrogateDefaults", "StatusAlgoDefaults", "StatusSurrogateOpt", "StatusResponse", "QueueSlot", "QueueLight",
    "QueueResponse", "MoveRequest", "GpuInfo", "ResourceJob", "ResourceLimits", "ResourcesResponse",
    "Notification", "NotificationList", "UnreadCount", "ReadRequest", "ReadResponse", "AdminConfig",
]


class StatusConfig(Resp):
    ok: bool
    errors: list[str]
    warnings: list[str] = Field(default_factory=list, description="기동은 막지 않는 설정 안내 키(누락 → 기능 비활성, 예약 키)")


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
    scx_version: str | None = None  # D3-68: gateway scx일 때 hpc.scx.version(화면 기본값), 아니면 null


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
    # opt-native §4.2: HyperStudy 레거시 기능(train_doe·optimize). true일 때만 내보낸다(기존 응답 모양 {enabled, missing} 유지)
    legacy: bool = Field(default=False, exclude_if=lambda v: not v,
                         description="opt-native §4.2: HyperStudy 레거시 기능(train_doe·optimize) — 미설정이면 화면에서 숨김")


class StatusFeatures(Resp):
    train_extract: FeatureState
    train_tpl: FeatureState
    train_doe: FeatureState
    train_doe_platform: FeatureState | None = None  # S18 §23.8 ① 플랫폼 DOE 생성(geom_update + simlab)
    train_solve: FeatureState
    train_import: FeatureState
    train_resp: FeatureState
    curation_h3d: FeatureState
    curation_t01: FeatureState
    spdm_import: FeatureState
    optimize: FeatureState
    dataset_create: FeatureState | None = None
    evaluate: FeatureState | None = None
    predict: FeatureState | None = None
    predict_parametric: FeatureState | None = None
    predict_mesh_only: FeatureState | None = None  # phase3 §14.4 메시 단독 템플릿 예측
    predict_responses: FeatureState | None = None  # phase3 §14.6 예측 응답 추출
    contour_capture: FeatureState | None = None  # phase3 §15.5 예측 컨투어 캡처
    optimize_builtin: FeatureState | None = None  # phase3 §18.2 ⑤ 플랫폼 내장 최적화(numpy·scipy)
    geometry_native: FeatureState | None = None  # geometry-engine.md §7.1 native 형상 엔진(paicad)
    geometry_native_shell: FeatureState | None = None  # shell-morph.md §8.1 쉘 판금 비드 모핑(paicad shell)
    geometry_view: FeatureState | None = None  # geometry-view.md §6.1 형상 3D 보기·미리보기(솔리드)
    geometry_view_shell: FeatureState | None = None  # geometry-view.md §6.1 형상 3D 보기·미리보기(쉘)
    contour3d: FeatureState | None = None  # geometry-view.md §13 결과 3D 컨투어
    fem_verify: FeatureState | None = None  # phase3 §21.3.8 S16 조립 FEM 검증(fem_verify.enabled + HPC)
    fem_verify_rebuild: FeatureState | None = None  # + 메시 교체(commands.mesh·include TCL)


class StatusEnvCheck(Resp):
    latest_id: str | None = None
    latest_state: str | None = None
    finished_at: datetime | None = None
    fail: int | None = None
    warn: int | None = None


class StatusCaptureEstimate(Resp):
    """일괄 예측 화면 "캡처 예상" 참고 문구의 가정값(config `capture.estimate_*`, 서버 실측 아님)."""

    image_mb: float
    video_mb: float
    sec_per_view: float
    sec_per_video: float


class StatusCapture(Resp):
    """컨투어 캡처 기본값(config `capture`) — 일괄 예측 설정 화면의 방향·동영상 기본 표시(D3-53)."""

    views: list[str]
    video: bool
    video_ext: str
    default_field: str = "CornerStress"  # D3-54: 화면 결과 종류 기본·성분 후보 판단
    default_component: str = ""  # D3-54: 결과 종류가 default_field일 때 성분 기본(빈 값 = 없음)
    estimate: StatusCaptureEstimate | None = None  # D3-54: 일괄 예측 "캡처 예상" 가정값
    # S16(phase3 §21.4.4): 표시용 영상 목표 크기, ffmpeg 변환 가능 여부, 실제 저장 확장자(avi → mp4 대체 반영)
    video_target_bytes: int | None = None
    transcode: bool = False
    video_ext_effective: str | None = None


class StatusSurrogateDefaults(Resp):
    iterations: int
    candidates: int
    tol_rel: float
    surrogate: str


class StatusAlgoDefaults(Resp):
    """GA·NSGA-II 고급 옵션 기본값(opt-native §6.7). pop_size·mutation_prob null = 변수 수로 정하는 식."""

    pop_size: int | None = None
    generations: int
    crossover_prob: float
    mutation_prob: float | None = None
    eta_c: float
    eta_m: float


class StatusSurrogateOpt(Resp):
    """⑤ 내장 최적화 화면 기본값·상한(config `surrogate_opt`, phase3 §18.6)."""

    defaults: StatusSurrogateDefaults
    max_variables: int
    max_iterations: int
    max_candidates: int
    max_objectives: int = 3  # S17 §22.10
    max_observe: int = 10
    max_extra_points: int = 10
    # opt-native §4.2·§9
    algorithms: list[str] = Field(default_factory=lambda: ["ego", "ga", "nsga2"])
    default_algorithm: str = "ego"
    algo_defaults: dict[str, StatusAlgoDefaults] = Field(default_factory=dict)
    ga_max_evals: int = 100000
    verifications: list[str] = Field(default_factory=lambda: ["loop", "none"])
    max_levels: int = 8


class StatusGeometry(Resp):
    """native 형상 엔진 상태(geometry-engine.md §7.1)."""

    engine_default: str = Field(description="새 파라미터 세트·추출·DOE의 기본 엔진: altair | native")
    native_available: bool
    reason: str | None = Field(None, description="native를 쓸 수 없는 이유(한국어), 쓸 수 있으면 null")


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
    capture: StatusCapture | None = None
    surrogate_opt: StatusSurrogateOpt | None = None
    geometry: StatusGeometry | None = None
    demo: bool = Field(False, description="시연 모드(fake tools 배포판) 여부 — true면 화면 상단에 '시연 모드' 배지")


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
    # GPU 조회 상태(phase3 D3-45): OK | NOT_FOUND(nvidia-smi 못 찾음) | ERROR(실행 실패). 이전 워커 표본은 null
    gpu_status: Literal["OK", "NOT_FOUND", "ERROR"] | None = None
    gpu_message: str | None = None
    # GPU 조회 실패 대응(phase3 §24.3 S19): 연속 실패 수·마지막 조회 시각·다음 조회 시각(간격을 늘린 중일 때만). 옛 표본은 null
    gpu_fail_streak: int | None = None
    gpu_sampled_at: datetime | str | None = None
    gpu_next_query_at: datetime | str | None = None
    job: ResourceJob | None = None
    limits: ResourceLimits


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
