"""설정 스키마(계약 §14): Settings와 섹션별 *Cfg, 키 상수, ConfigIssue·LoadedConfig."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import Field

from ._model import _M
from .schema_capture import CaptureCfg
from .schema_geometry import GeometryCfg
from .schema_hpc import CommandsCfg, HpcCfg
from .schema_ops import (
    DEFAULT_LOG_ERROR_PATTERNS,
    DemoCfg,
    EnvCheckCfg,
    ErrorBundleCfg,
    LoggingCfg,
    NotificationsCfg,
    StudyStorageCfg,
    UiCfg,
)
from .schema_stages import (
    CurationCfg,
    DatasetCfg,
    OptimizeCfg,
    PackageCfg,
    ParamSetCfg,
    PredictBatchCfg,
    PredictCfg,
    ScoreCfg,
    SpdmImportCfg,
    SurrogateOptCfg,
    TrainDataCfg,
    TrainingLogCfg,
)


class ServerCfg(_M):
    host: str = "127.0.0.1"
    port: int = 8100
    base_path: str = "/physicsai"
    frontend_root: str | None = None  # 백엔드가 /physicsai/ 아래에 직접 서빙할 프런트 빌드 폴더. None·빈 값 = 서빙 안 함(Caddy 등 외부 서빙)


class DatabaseCfg(_M):
    url_env: str = "PHYSICSAI_DATABASE_URL"
    pool_size: int = 5


class MembershipCfg(_M):
    project_id: str
    role: str


class DevPrincipalCfg(_M):
    user_id: str = "dev-admin"
    username: str = "dev"
    display_name: str = "개발자"
    is_global_admin: bool = True
    memberships: list[MembershipCfg] = Field(default_factory=list)


class AuthCfg(_M):
    mode: str = "dashboard"
    dashboard_internal_url: str = "http://127.0.0.1:8000"
    dashboard_public_login_url: str = "/"
    cookie_name: str = "analysis_canvas_session"
    introspection_path: str = "/api/auth/me"
    projects_path: str = "/api/projects"
    cache_ttl_s: float = 30
    timeout_s: float = 3
    dev_static_principal: DevPrincipalCfg = Field(default_factory=DevPrincipalCfg)


class StorageCfg(_M):
    ai_root: str = ""
    allowed_import_roots: list[str] = Field(default_factory=list)
    spdm_roots: list[str] = Field(default_factory=list)
    # phase3 §12 S7(D3-46): 다른 PC가 네트워크 공유로 파일을 넣는 받은 파일 폴더(AI 루트 기준 상대). 없으면 탐색 루트에서 생략.
    inbox_dir: str = "inbox"
    inbox_share_hint: str | None = None  # 화면 안내 문구용 공유 경로(예 "\\\\<서버>\\physicsai-inbox"). 서버는 쓰지 않는다


class AltairCfg(_M):
    version_label: str = ""
    hyperstudy_path: str = ""
    simlab_path: str = ""
    edspy_path: str = ""
    hw_exe_path: str = ""
    hvtrans_exe_path: str = ""
    hstpy_path: str = ""  # 2차: 빈 값 = hyperstudy_path 폴더의 hstpy.bat (phase2 §8.1)
    altair_home: str = ""  # 2차: 빈 값 = hstpy 폴더/../../..


class LauncherCfg(_M):
    script: str
    core: str


def _default_launchers() -> dict[str, LauncherCfg]:
    # 원본 CONFIG/BATCHRUN 런처·BUILD_PYD 코어 이름(phase2 §8.2). 설정으로 바꿀 수 있다.
    return {
        "extract_params": LauncherCfg(script="BATCHRUN_get_parameter_from_cad.py", core="get_parameter_from_cad_core"),
        "gen_radioss": LauncherCfg(script="BATCHRUN_hst_gen_radioss_input.py", core="hst_gen_radioss_core"),
        "optimization": LauncherCfg(script="BATCHRUN_hst_physicsai_optimization.py", core="hst_physicsai_optimization_core"),
    }


RESOURCE_FILE_KEYS = (
    "preview_pred_h3d_tcl", "simlab_tpl_template", "doe_design_type_json", "hypermesh_include_tcl",
    "preview_h3d_tcl", "preview_hg_tcl", "curate_hg_tcl", "extract_minmax_tcl",
)
RESOURCE_DIR_KEYS = ("batchrun_dir", "pyd_dir")
LAUNCHER_KEYS = ("extract_params", "gen_radioss", "optimization")


GPU_QUERY_CANDIDATES = ("nvidia-smi", "%SystemRoot%\\System32\\nvidia-smi.exe",
                        "%ProgramFiles%\\NVIDIA Corporation\\NVSMI\\nvidia-smi.exe")


class ResourcesCfg(_M):
    preview_pred_h3d_tcl: str = ""
    batchrun_dir: str = ""
    pyd_dir: str = ""
    simlab_tpl_template: str = ""
    doe_design_type_json: str = ""
    hypermesh_include_tcl: str = ""
    preview_h3d_tcl: str = ""
    preview_hg_tcl: str = ""
    curate_hg_tcl: str = ""
    extract_minmax_tcl: str = ""
    contour_capture_tcl: str = ""  # phase3 §15 S10: 비면 저장소 resources/hyperview/contour_capture.tcl
    launchers: dict[str, LauncherCfg] = Field(default_factory=_default_launchers)
    # GPU 조회 실행 파일 자동 탐색 후보(phase3 D3-45): worker.gpu_query 첫 인자가 없거나 못 찾으면 순서대로. 이름만 = PATH, %VAR% 확장
    gpu_query_candidates: list[str] = Field(default_factory=lambda: list(GPU_QUERY_CANDIDATES))


class WorkerCfg(_M):
    limiter: str = "auto"
    max_logical_cores: int = 32
    max_memory_gb: float = 64
    priority: str = "below_normal"
    auto_detect: bool = False
    auto_detect_ratio: float = 0.7
    posix_rlimit_as: bool = False
    heartbeat_interval_s: float = 10
    lease_ttl_s: float = 60
    claim_interval_s: float = 2
    cancel_check_interval_s: float = 2
    resource_sample_interval_s: float = 10
    state_dir: str = "./state"
    gpu_query: list[str] | None = None
    env_passthrough: list[str] = Field(default_factory=list)  # 자식 프로세스에 추가로 넘길 환경변수 이름 패턴(fnmatch)


class Settings(_M):
    schema_version: int = 1
    profile: str = "dev"
    server: ServerCfg = Field(default_factory=ServerCfg)
    database: DatabaseCfg = Field(default_factory=DatabaseCfg)
    auth: AuthCfg = Field(default_factory=AuthCfg)
    storage: StorageCfg = Field(default_factory=StorageCfg)
    altair: AltairCfg = Field(default_factory=AltairCfg)
    resources: ResourcesCfg = Field(default_factory=ResourcesCfg)
    worker: WorkerCfg = Field(default_factory=WorkerCfg)
    dataset: DatasetCfg = Field(default_factory=DatasetCfg)
    package: PackageCfg = Field(default_factory=PackageCfg)
    training_log: TrainingLogCfg = Field(default_factory=TrainingLogCfg)
    score: ScoreCfg = Field(default_factory=ScoreCfg)
    param_set: ParamSetCfg = Field(default_factory=ParamSetCfg)
    predict: PredictCfg = Field(default_factory=PredictCfg)
    predict_batch: PredictBatchCfg = Field(default_factory=PredictBatchCfg)
    capture: CaptureCfg = Field(default_factory=CaptureCfg)
    geometry: GeometryCfg = Field(default_factory=GeometryCfg)  # native 형상 엔진(geometry-engine.md §7.1)
    commands: CommandsCfg = Field(default_factory=CommandsCfg)
    train_data: TrainDataCfg = Field(default_factory=TrainDataCfg)
    curation: CurationCfg = Field(default_factory=CurationCfg)
    spdm_import: SpdmImportCfg = Field(default_factory=SpdmImportCfg)
    optimize: OptimizeCfg = Field(default_factory=OptimizeCfg)
    surrogate_opt: SurrogateOptCfg = Field(default_factory=SurrogateOptCfg)  # phase3 §18.9 S13 내장 최적화
    env_check: EnvCheckCfg = Field(default_factory=EnvCheckCfg)
    error_bundle: ErrorBundleCfg = Field(default_factory=ErrorBundleCfg)
    study_storage: StudyStorageCfg = Field(default_factory=StudyStorageCfg)
    commands_log_error_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_LOG_ERROR_PATTERNS))
    hpc: HpcCfg = Field(default_factory=HpcCfg)
    notifications: NotificationsCfg = Field(default_factory=NotificationsCfg)
    ui: UiCfg = Field(default_factory=UiCfg)
    logging: LoggingCfg = Field(default_factory=LoggingCfg)
    demo: DemoCfg = Field(default_factory=DemoCfg)


@dataclass(frozen=True)
class ConfigIssue:
    key: str
    message: str


@dataclass
class LoadedConfig:
    settings: Settings
    issues: list[ConfigIssue] = field(default_factory=list)
    path: str | None = None
    sha256: str | None = None
    warnings: list[ConfigIssue] = field(default_factory=list)  # 기동은 막지 않는 안내(누락 → 기능 비활성, 예약 키)

    @property
    def ok(self) -> bool:
        return not self.issues

    def error_keys(self) -> list[str]:
        seen: list[str] = []
        for i in self.issues:
            if i.key not in seen:
                seen.append(i.key)
        return seen
