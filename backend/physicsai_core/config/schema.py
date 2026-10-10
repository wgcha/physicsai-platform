"""설정 스키마(계약 §14): Settings와 섹션별 *Cfg, 키 상수, ConfigIssue·LoadedConfig."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServerCfg(_M):
    host: str = "127.0.0.1"
    port: int = 8100
    base_path: str = "/physicsai"


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
    launchers: dict[str, LauncherCfg] = Field(default_factory=_default_launchers)


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


class DatasetOptionsCfg(_M):
    extract_faces: bool = True
    extract_mdi: bool = False
    extract_time_history_vectors: bool = False


class DatasetCfg(_M):
    holdout_ratio: float = 0.1
    seed: int = 20261008
    split_group: str = "file"
    min_h3d_files: int = 2
    min_psdata_bytes: int = 1048576
    options_default: DatasetOptionsCfg = Field(default_factory=DatasetOptionsCfg)


class PackageCfg(_M):
    link_mode: str = "hardlink_or_copy"


class ParserCfg(_M):
    name: str
    pattern: str


class TrainingLogCfg(_M):
    log_globs: list[str] = Field(default_factory=lambda: ["*.log", "*.txt"])
    max_curve_points: int = 2000
    parsers: list[ParserCfg] = Field(
        default_factory=lambda: [
            ParserCfg(
                name="physicsai_default",
                pattern=r"epoch=\s*(?P<epoch>\d+)\s*/\s*(?P<total>\d+)\s+loss=(?P<loss>[0-9.eE+\-]+)",
            )
        ]
    )


class ScoreCfg(_M):
    write_files: bool = False
    parsers: list[ParserCfg] = Field(default_factory=list)


class ParamSetCfg(_M):
    max_samples: int = 20000
    max_total_bytes: int = 2147483648


class PredictCfg(_M):
    rendered_script_name: str = "simlab_parametered_mesh.py"
    mesh_output_glob: str = "eps_mesh*"
    starter_glob: str = "*_0000.rad"
    integer_rounding: str = "half_up"
    env: dict[str, str] = Field(default_factory=lambda: {"EDS_TNS_ACTVN_CHCKPT": "1"})


class CommandsCfg(_M):
    edspy_create_dataset: list[str] | None = None
    edspy_score: list[str] | None = None
    geom_update: list[str] | None = None
    mesh: list[str] | None = None
    rad_assemble: list[str] | None = None
    edspy_predict: list[str] | None = None
    contour_preview: list[str] | None = None
    response_extract: list[str] | None = None
    # 2차(phase2 §8.1) — null이면 그 기능만 비활성(가정 A-11)
    simlab_extract_params: list[str] | None = None
    hst_gen_radioss: list[str] | None = None
    h3d_preview: list[str] | None = None
    hvtrans_curate: list[str] | None = None
    t01_preview: list[str] | None = None
    t01_curve_export: list[str] | None = None
    hst_optimization: list[str] | None = None


class HpcDefaultsCfg(_M):
    queue: str | None = "workq"
    ncpus: int | None = 16
    walltime: str | None = "24:00:00"


class HpcCommandCfg(_M):
    allowed_executables: list[str] = Field(default_factory=list)
    submit: Any = None
    status: Any = None
    cancel: Any = None
    job_id_regex: str = r"^\s*(?P<job_id>\d+(?:\.[A-Za-z0-9_.\-]+)?)\s*$"
    state_regex: str = r"job_state\s*=\s*(?P<state>[A-Z])"
    exit_code_regex: str | None = r"Exit_status\s*=\s*(?P<exit>-?\d+)"
    not_found_regex: str | None = "Unknown Job Id"
    state_map: dict[str, str] = Field(default_factory=dict)
    submit_timeout_s: float = 60
    status_timeout_s: float = 30
    cancel_timeout_s: float = 30


class HpcAdapterCfg(_M):
    module: str | None = None


class PathMapCfg(_M):
    local: str
    remote: str


class HpcTransferCfg(_M):
    stage_in: str = "shared_path"
    path_map: list[PathMapCfg] = Field(default_factory=list)
    collect_mode: str = "in_place"  # in_place | shared_folder | drive(= shared_folder 별칭, phase2 §6.5)
    collect_root_local: str = ""
    collect_root_remote: str = ""
    collect_patterns: list[str] = Field(default_factory=lambda: ["*.h3d", "*T01", "*_0000.out", "*_0001.out"])
    max_collect_bytes: int = 21474836480


class HpcCfg(_M):
    gateway: str = "none"
    poll_interval_s: float = 60
    lost_after_polls: int = 10
    max_unreachable_minutes: float = 1440
    defaults: HpcDefaultsCfg = Field(default_factory=HpcDefaultsCfg)
    command: HpcCommandCfg = Field(default_factory=HpcCommandCfg)
    adapter: HpcAdapterCfg = Field(default_factory=HpcAdapterCfg)
    transfer: HpcTransferCfg = Field(default_factory=HpcTransferCfg)


class NotificationsCfg(_M):
    retention_days: int = 30
    purge_interval_h: float = 6


class UiCfg(_M):
    max_artifact_bytes: int = 20971520
    poll_job_running_ms: int = 2000
    poll_job_queued_ms: int = 5000
    poll_job_waiting_hpc_ms: int = 15000
    poll_log_ms: int = 2000
    poll_queue_ms: int = 5000
    poll_resources_ms: int = 10000
    poll_notifications_ms: int = 10000
    poll_status_ms: int = 30000


class DemoCfg(_M):
    """시연 모드(fake tools 배포판). 운영에서는 켤 수 없다(profile=dev + server.host=127.0.0.1일 때만)."""

    enabled: bool = False
    frontend_root: str = ""  # 시연 때 백엔드가 직접 서빙할 프런트 빌드 폴더(Caddy 없이). 빈 값 = 서빙 안 함


class LoggingCfg(_M):
    level: str = "INFO"
    dir: str = ""        # 운영 파일 로그 폴더. 빈 값 = 작업 폴더의 ./logs(설치본은 <install_root>\logs). ai_root·SPDM 밖
    max_mb: float = 20   # 로그 파일 하나의 최대 크기(MB) — 넘으면 회전
    backups: int = 10    # 회전 보관 개수(backend.log.1 … .N)
    mask_patterns: list[str] = Field(
        default_factory=lambda: [r"(?i)(password|passwd|token|secret)\s*[=:]\s*\S+"]
    )


class TrainDataCfg(_M):
    """① 학습데이터 생성(phase2 §8.2). 기본값은 원본 인용."""

    cad_extensions: list[str] = Field(default_factory=lambda: [".prt"])
    max_xml_bytes: int = 4194304
    extract_progress_token: str = "Passed"
    extract_progress_total: int = 4
    param_default_range_ratio: float = 0.05
    param_default_format: str = "%3i"
    tpl_marker: str = "#" + "*" * 63
    tpl_prt_regex: str = r'dir_file_prt\s*=\s*r"[^"]*"'
    tpl_parameter_line_regex: str = r"(?m)^[^\n]*\{parameter\(.*?\)\}[^\n]*\n?"
    tpl_paramitem_line_regex: str = r"(?m)^[^\n]*<paramitem[^>]*/>[^\n]*\n?"
    max_runs: int = 2000
    max_multi_execution: int = 8
    hst_progress_regex: str = r"Finished run\s*\(\s*(?P<run>\d+)\s*\),\s*model\s*\(\s*m_?3\s*\)"
    hst_log_error_patterns: list[str] = Field(default_factory=lambda: [
        r"^\s*\d+\s+Error\s*:",
        r"Traceback \(most recent call last\):",
        r"^\s*\[ERROR\]",
        r"^\s*(?:FileNotFoundError|RuntimeError|ValueError|OSError|PermissionError|ImportError|TypeError|AttributeError|NameError|SyntaxError)\s*:",
    ])
    run_dir_glob: str = "approaches/*/run__*"
    samples_extractor: str = "paramitem"
    rendered_tpl_glob: str = "**/*"
    rendered_tpl_exts: list[str] = Field(default_factory=lambda: [".py", ".tcl", ".txt", ".xml", ""])
    samples_scan_max_bytes: int = 1048576
    paramitem_regex: str = r'<paramitem\s+Name="(?P<name>[^"]+)"\s+NewValue="(?P<value>[^"]*)"'
    samples_csv_glob: str | None = None
    samples_csv_run_column: str = "run_key"
    max_runs_per_submit: int = 500
    result_run_dir_regex: str = r"^(?P<run_key>run__\d+)$"
    result_match_depth: int = 3


class CurationCfg(_M):
    max_files: int = 20000


class SpdmImportCfg(_M):
    patterns: list[str] = Field(default_factory=lambda: ["*.h3d", "*T01"])
    max_files: int = 20000
    max_total_bytes: int = 536870912000


class SummaryParserCfg(_M):
    name: str
    glob: str
    kind: str
    max_rows: int | None = None


class OptimizeCfg(_M):
    default_study_folder: str = "HST_PHYSICSAI_OPTIMIZATION"
    env: dict[str, str] = Field(default_factory=lambda: {"EDS_TNS_ACTVN_CHCKPT": "1"})
    progress_regex: str = r"Started\s+run\s+\(\s*(?P<run>\d+)\s*\),\s*model\s+\(\s*m_1\s*\)"
    max_listed_files: int = 5000
    viewable_globs: list[str] = Field(default_factory=lambda: ["*.csv", "*.txt", "*.json", "*.log"])
    max_viewable_files: int = 200
    summary_parsers: list[SummaryParserCfg] = Field(default_factory=list)


ENV_PROBE_TOOLS = ("edspy", "simlab", "hw", "hstbatch", "hvtrans", "hstpy")


class EnvCheckProbesCfg(_M):
    edspy: list[str] | None = None
    simlab: list[str] | None = None
    hw: list[str] | None = None
    hstbatch: list[str] | None = None
    hvtrans: list[str] | None = None
    hstpy: list[str] | None = None


class EnvCheckCfg(_M):
    probe_timeout_s: float = 60
    expire_s: float = 900
    min_free_gb: float = 50
    probes: EnvCheckProbesCfg = Field(default_factory=EnvCheckProbesCfg)


class ErrorBundleCfg(_M):
    log_tail_bytes: int = 262144
    max_total_bytes: int = 20971520


DEFAULT_LOG_ERROR_PATTERNS = [r"^\s*\d+\s+Error\s*:", r"Traceback \(most recent call last\):", r"^\s*\[ERROR\]"]


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
    commands: CommandsCfg = Field(default_factory=CommandsCfg)
    train_data: TrainDataCfg = Field(default_factory=TrainDataCfg)
    curation: CurationCfg = Field(default_factory=CurationCfg)
    spdm_import: SpdmImportCfg = Field(default_factory=SpdmImportCfg)
    optimize: OptimizeCfg = Field(default_factory=OptimizeCfg)
    env_check: EnvCheckCfg = Field(default_factory=EnvCheckCfg)
    error_bundle: ErrorBundleCfg = Field(default_factory=ErrorBundleCfg)
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
