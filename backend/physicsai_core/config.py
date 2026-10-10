"""설정 YAML 로드·검증(계약 §14, 예시 config/platform.example.yaml).

- 알 수 없는 키는 오류(pydantic extra=forbid).
- 스키마 검증 실패여도 API는 뜬다: `LoadedConfig.ok=False`, 쓰기 API는 503 CONFIG_INVALID.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .commands import TEMPLATE_SPECS, validate_template


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


# ---------------------------------------------------------------------------
# 경로 문자열 규칙
# ---------------------------------------------------------------------------

PATH_META_CHARS = set('&|<>^%!"')
_WIN_ABS = re.compile(r"^[A-Za-z]:[\\/]")


def is_abs_path_str(p: str) -> bool:
    return bool(_WIN_ABS.match(p)) or p.startswith("/")


def has_unsafe_chars(p: str) -> bool:
    return bool(re.search(r"[\s\x00-\x1f\x7f]", p)) or bool(PATH_META_CHARS.intersection(p))


def _norm_for_compare(p: str) -> str:
    n = os.path.normpath(p.replace("\\", "/")).replace("\\", "/")
    return n.lower() if (os.name == "nt" or _WIN_ABS.match(p)) else n


def paths_overlap(a: str, b: str) -> bool:
    """같거나 한쪽이 다른 쪽 안에 있으면 True."""
    na, nb = _norm_for_compare(a).rstrip("/"), _norm_for_compare(b).rstrip("/")
    return na == nb or na.startswith(nb + "/") or nb.startswith(na + "/")


# ---------------------------------------------------------------------------
# 로드·검증
# ---------------------------------------------------------------------------


def _pydantic_issues(exc: ValidationError) -> list[ConfigIssue]:
    out = []
    for e in exc.errors():
        key = ".".join(str(x) for x in e.get("loc", ())) or "(root)"
        msg = "알 수 없는 키입니다" if e.get("type") == "extra_forbidden" else f"형식 오류: {e.get('msg')}"
        out.append(ConfigIssue(key, msg))
    return out


def load_config(path: str | None = None, environ: dict[str, str] | None = None) -> LoadedConfig:
    env = environ if environ is not None else dict(os.environ)
    path = path or env.get("PHYSICSAI_CONFIG") or "config/platform.yaml"
    try:
        raw_bytes = Path(path).read_bytes()
    except OSError as exc:
        return LoadedConfig(Settings(), [ConfigIssue("(file)", f"설정 파일을 읽을 수 없습니다: {path} ({exc})")], path)
    sha = hashlib.sha256(raw_bytes).hexdigest()
    try:
        data = yaml.safe_load(raw_bytes.decode("utf-8")) or {}
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        return LoadedConfig(Settings(), [ConfigIssue("(file)", f"YAML 형식 오류: {exc}")], path, sha)
    if not isinstance(data, dict):
        return LoadedConfig(Settings(), [ConfigIssue("(root)", "최상위는 매핑이어야 합니다")], path, sha)
    return load_config_dict(data, env, path=path, sha256=sha)


def load_config_dict(
    data: dict[str, Any], environ: dict[str, str] | None = None, *, path: str | None = None, sha256: str | None = None
) -> LoadedConfig:
    env = environ if environ is not None else dict(os.environ)
    data = dict(data)
    if env.get("PHYSICSAI_PROFILE"):
        data["profile"] = env["PHYSICSAI_PROFILE"]
    if env.get("PHYSICSAI_HPC_GATEWAY"):
        hpc = dict(data.get("hpc") or {})
        hpc["gateway"] = env["PHYSICSAI_HPC_GATEWAY"]
        data["hpc"] = hpc
    try:
        settings = Settings.model_validate(data)
    except ValidationError as exc:
        return LoadedConfig(Settings(), _pydantic_issues(exc), path, sha256)
    absent = absent_keys(data, settings)
    issues = validate_settings(settings, absent=absent)
    return LoadedConfig(settings, issues, path, sha256, config_warnings(data, settings, absent))


# 예약(미사용) 키: 값이 있어도 동작에 쓰이지 않는다(경고만). 기존 설정 파일 호환을 위해 스키마에는 남긴다.
RESERVED_KEYS: tuple[tuple[str, ...], ...] = (("server", "base_path"), ("hpc", "transfer", "stage_in"), ("hpc", "adapter", "module"))


def _has(data: Any, *path: str) -> bool:
    for k in path:
        if not isinstance(data, dict) or k not in data:
            return False
        data = data[k]
    return True


def absent_keys(data: dict[str, Any], s: Settings) -> frozenset[str]:
    """설정 파일에 아예 없는 키(예시 yaml 일부만 복사한 경우). 이 키들은 오류가 아니라 '해당 기능 비활성'으로 다룬다.
    명시적으로 null을 쓴 1차 확정 템플릿은 그대로 오류(V2-CFG-1)."""
    out = {f"commands.{k}" for k in TEMPLATE_SPECS if not _has(data, "commands", k)}
    if s.hpc.gateway == "command" and not _has(data, "hpc", "command"):
        out.add("hpc.command")
    if not _has(data, "worker", "gpu_query"):
        out.add("worker.gpu_query")
    return frozenset(out)


def config_warnings(data: dict[str, Any], s: Settings, absent: frozenset[str]) -> list[ConfigIssue]:
    w: list[ConfigIssue] = []
    for path in RESERVED_KEYS:
        if _has(data, *path):
            w.append(ConfigIssue(".".join(path), "예약(미사용) 키입니다 — 값이 적용되지 않습니다(지워도 됩니다)"))
    for k in sorted(absent):
        if k.startswith("commands.") and TEMPLATE_SPECS[k.split(".", 1)[1]].required:
            w.append(ConfigIssue(k, "설정 파일에 없어 이 명령을 쓰는 기능이 비활성입니다(config/platform.example.yaml 참고)"))
    if "hpc.command" in absent:
        w.append(ConfigIssue("hpc.command", "hpc.gateway=command인데 hpc.command가 없어 PBS 제출이 비활성입니다"))
    if "worker.gpu_query" in absent:
        w.append(ConfigIssue("worker.gpu_query", "GPU 조회 명령이 없어 GPU 사용량을 표시하지 않습니다"))
    return w


def _compile(key: str, pattern: str, issues: list[ConfigIssue], required_groups: tuple[str, ...] = ()) -> None:
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        issues.append(ConfigIssue(key, f"정규식 컴파일 실패: {exc}"))
        return
    for g in required_groups:
        if g not in rx.groupindex:
            issues.append(ConfigIssue(key, f"정규식에 필수 그룹 '{g}'이 없습니다"))


def validate_settings(s: Settings, absent: frozenset[str] = frozenset()) -> list[ConfigIssue]:  # noqa: C901 - 표 기반 규칙 나열
    issues: list[ConfigIssue] = []
    add = lambda k, m: issues.append(ConfigIssue(k, m))  # noqa: E731

    if s.schema_version != 1:
        add("schema_version", "schema_version은 1이어야 합니다")
    if s.profile not in ("dev", "prod"):
        add("profile", "profile은 dev 또는 prod입니다")
    prod = s.profile == "prod"

    # storage
    spdm = [r for r in s.storage.spdm_roots]
    ai_root = s.storage.ai_root
    if not ai_root or not is_abs_path_str(ai_root):
        add("storage.ai_root", "ai_root는 절대경로여야 합니다")
    elif has_unsafe_chars(ai_root):
        add("storage.ai_root", "ai_root에 공백·제어문자·cmd 메타문자를 쓸 수 없습니다")
    elif not os.path.isdir(ai_root):
        add("storage.ai_root", f"ai_root 폴더가 없습니다: {ai_root}")
    elif not os.access(ai_root, os.W_OK):
        add("storage.ai_root", "ai_root에 쓸 수 없습니다")
    if ai_root:
        for r in spdm:
            if paths_overlap(ai_root, r):
                add("storage.ai_root", f"ai_root가 SPDM 루트와 겹칩니다: {r}")
    for i, r in enumerate(s.storage.allowed_import_roots):
        k = f"storage.allowed_import_roots[{i}]"
        if not is_abs_path_str(r):
            add(k, "절대경로여야 합니다")
        elif has_unsafe_chars(r):
            add(k, "공백·제어문자·cmd 메타문자를 쓸 수 없습니다")
        elif not os.path.isdir(r):
            add(k, f"폴더가 없습니다: {r}")
        elif not os.access(r, os.R_OK):
            add(k, "읽을 수 없습니다")
        for sp in spdm:
            if paths_overlap(r, sp):
                add(k, f"SPDM 루트와 겹칩니다: {sp}")

    # altair
    for k in ("hyperstudy_path", "simlab_path", "edspy_path", "hw_exe_path", "hvtrans_exe_path", "hstpy_path"):
        v = getattr(s.altair, k)
        if v:
            if not is_abs_path_str(v):
                add(f"altair.{k}", "절대경로여야 합니다")
            elif prod and not os.path.isfile(v):
                add(f"altair.{k}", f"실행 파일이 없습니다: {v}")
    if s.altair.altair_home and not is_abs_path_str(s.altair.altair_home):
        add("altair.altair_home", "절대경로여야 합니다")

    # resources (phase2 §8.2: 비었거나 절대경로·공백/메타 없음·prod면 존재)
    for k in RESOURCE_FILE_KEYS + RESOURCE_DIR_KEYS:
        v = getattr(s.resources, k)
        key = f"resources.{k}"
        if v:
            if not is_abs_path_str(v):
                add(key, "절대경로여야 합니다")
            elif has_unsafe_chars(v):
                add(key, "공백·제어문자·cmd 메타문자를 쓸 수 없습니다")
            elif prod and k in RESOURCE_DIR_KEYS and not os.path.isdir(v):
                add(key, f"폴더가 없습니다: {v}")
            elif prod and k in RESOURCE_FILE_KEYS and not os.path.isfile(v):
                add(key, f"파일이 없습니다: {v}")
            for sp in spdm:
                if paths_overlap(v, sp):
                    add(key, f"SPDM 루트와 겹칩니다: {sp}")
        elif prod and k == "preview_pred_h3d_tcl":
            add(key, "prod에서는 필수입니다")
    for name, lc in s.resources.launchers.items():
        key = f"resources.launchers.{name}"
        if name not in LAUNCHER_KEYS:
            add(key, "알 수 없는 런처 키입니다(extract_params | gen_radioss | optimization)")
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+\.py", lc.script) or has_unsafe_chars(lc.script):
            add(key + ".script", "파일 이름만(경로 구분자 없이) .py 로 끝나야 합니다")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", lc.core):
            add(key + ".core", "^[A-Za-z_][A-Za-z0-9_]*$")

    # worker
    w = s.worker
    if not 1 <= w.max_logical_cores <= 1024:
        add("worker.max_logical_cores", "1~1024")
    if not 1 <= w.max_memory_gb <= 4096:
        add("worker.max_memory_gb", "1~4096")
    if not 0.1 <= w.auto_detect_ratio <= 1.0:
        add("worker.auto_detect_ratio", "0.1~1.0")
    for k in ("heartbeat_interval_s", "lease_ttl_s", "claim_interval_s", "cancel_check_interval_s", "resource_sample_interval_s"):
        if getattr(w, k) <= 0:
            add(f"worker.{k}", "양수여야 합니다")
    if w.lease_ttl_s < 3 * w.heartbeat_interval_s:
        add("worker.lease_ttl_s", "lease_ttl_s ≥ 3 × heartbeat_interval_s 이어야 합니다")
    if w.limiter not in ("auto", "windows_job", "posix", "null"):
        add("worker.limiter", "auto | windows_job | posix | null")
    elif w.limiter == "null" and prod:
        add("worker.limiter", "null 제한기는 dev에서만 허용됩니다")
    if w.priority not in ("idle", "below_normal", "normal"):
        add("worker.priority", "idle | below_normal | normal")
    if w.gpu_query is not None and (not w.gpu_query or not all(isinstance(x, str) for x in w.gpu_query)):
        add("worker.gpu_query", "문자열 배열이어야 합니다")

    # auth
    a = s.auth
    if a.mode not in ("dashboard", "dev_static", "demo"):
        add("auth.mode", "dashboard | dev_static | demo")
    if a.mode == "dev_static" and (s.profile != "dev" or s.server.host != "127.0.0.1"):
        add("auth.mode", "dev_static은 profile=dev이고 127.0.0.1 바인딩일 때만 허용됩니다")
    if a.mode == "demo" and not s.demo.enabled:
        add("auth.mode", "demo 인증은 demo.enabled=true(시연 모드)일 때만 허용됩니다")
    # 시연 모드: 운영 설정에서는 켤 수 없다
    if s.demo.enabled and (s.profile != "dev" or s.server.host != "127.0.0.1"):
        add("demo.enabled", "시연 모드는 profile=dev이고 server.host=127.0.0.1일 때만 허용됩니다")
    if s.demo.frontend_root and not s.demo.enabled:
        add("demo.frontend_root", "demo.enabled=false이면 비워 두어야 합니다")
    elif s.demo.frontend_root and not os.path.isfile(os.path.join(s.demo.frontend_root, "index.html")):
        add("demo.frontend_root", f"프런트 빌드 폴더에 index.html이 없습니다: {s.demo.frontend_root}")
    if not re.match(r"^https?://[^\s/]+(:\d+)?/?$", a.dashboard_internal_url):
        add("auth.dashboard_internal_url", "URL 형식이 아닙니다(예: http://127.0.0.1:8000)")
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", a.cookie_name):
        add("auth.cookie_name", "^[A-Za-z0-9_\\-]+$")
    for k in ("introspection_path", "projects_path"):
        if not getattr(a, k).startswith("/"):
            add(f"auth.{k}", "'/'로 시작해야 합니다")
    for m in a.dev_static_principal.memberships:
        if m.role not in ("general", "power", "admin"):
            add("auth.dev_static_principal.memberships", "role은 general|power|admin")

    # dataset
    d = s.dataset
    if not 0.05 <= d.holdout_ratio <= 0.5:
        add("dataset.holdout_ratio", "0.05~0.5")
    if d.min_h3d_files < 2:
        add("dataset.min_h3d_files", "2 이상")
    if d.min_psdata_bytes < 0:
        add("dataset.min_psdata_bytes", "0 이상")
    if d.split_group not in ("file", "parent_dir"):
        add("dataset.split_group", "file | parent_dir")
    if s.package.link_mode not in ("hardlink_or_copy", "copy"):
        add("package.link_mode", "hardlink_or_copy | copy")

    # parsers
    for i, p in enumerate(s.training_log.parsers):
        _compile(f"training_log.parsers[{i}]", p.pattern, issues, ("epoch", "loss"))
    if s.training_log.max_curve_points < 3:
        add("training_log.max_curve_points", "3 이상")
    for i, p in enumerate(s.score.parsers):
        _compile(f"score.parsers[{i}]", p.pattern, issues, ("value",))
    for i, p in enumerate(s.commands_log_error_patterns):
        _compile(f"commands_log_error_patterns[{i}]", p, issues)
    lg = s.logging
    if lg.max_mb <= 0 or lg.max_mb > 1024:
        add("logging.max_mb", "0 초과 1024 이하")
    if not 1 <= lg.backups <= 100:
        add("logging.backups", "1~100")
    if lg.level.upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        add("logging.level", "DEBUG | INFO | WARNING | ERROR | CRITICAL")
    if lg.dir:
        if has_unsafe_chars(lg.dir) and not os.path.isdir(lg.dir):
            add("logging.dir", "공백·메타문자 없는 경로를 권장합니다(폴더도 없음)")
        if ai_root and paths_overlap(os.path.abspath(lg.dir), ai_root):
            add("logging.dir", "AI 루트와 겹칠 수 없습니다(운영 로그는 설치 폴더 쪽)")
        for sp in spdm:
            if paths_overlap(os.path.abspath(lg.dir), sp):
                add("logging.dir", f"SPDM 루트와 겹칩니다: {sp}")
    for i, p in enumerate(s.logging.mask_patterns):
        _compile(f"logging.mask_patterns[{i}]", p, issues)

    if s.predict.integer_rounding not in ("half_up", "truncate"):
        add("predict.integer_rounding", "half_up | truncate")
    if has_unsafe_chars(s.predict.rendered_script_name) or "/" in s.predict.rendered_script_name:
        add("predict.rendered_script_name", "파일 이름만, 공백·메타문자 금지")

    # commands
    for key in TEMPLATE_SPECS:
        if f"commands.{key}" in absent:
            continue  # 파일에 없음 → 해당 기능 비활성(경고, features·작업 생성 409)
        for msg in validate_template(key, getattr(s.commands, key)):
            add(f"commands.{key}", msg)

    # hpc
    if s.hpc.gateway not in ("none", "command", "adapter"):
        add("hpc.gateway", "none | command | adapter")
    t = s.hpc.transfer
    if t.collect_mode not in ("in_place", "shared_folder", "drive"):
        add("hpc.transfer.collect_mode", "in_place | shared_folder | drive")
    elif t.collect_mode in ("shared_folder", "drive"):
        for k in ("collect_root_local", "collect_root_remote"):
            if not getattr(t, k):
                add(f"hpc.transfer.{k}", "shared_folder·drive 모드에서는 필수입니다")
    if t.collect_root_local:
        k = "hpc.transfer.collect_root_local"
        v = t.collect_root_local
        if not is_abs_path_str(v):
            add(k, "절대경로여야 합니다")
        elif has_unsafe_chars(v):
            add(k, "공백·제어문자·cmd 메타문자를 쓸 수 없습니다")
        elif not os.path.isdir(v):
            add(k, f"폴더가 없습니다: {v}")
        if ai_root and paths_overlap(v, ai_root):
            add(k, "AI 루트와 겹칠 수 없습니다")
        for sp in spdm:
            if paths_overlap(v, sp):
                add(k, f"SPDM 루트와 겹칩니다: {sp}")
    if t.collect_root_remote and (has_unsafe_chars(t.collect_root_remote) or not is_abs_path_str(t.collect_root_remote)):
        add("hpc.transfer.collect_root_remote", "절대경로여야 하며 공백·메타문자를 쓸 수 없습니다")
    if s.hpc.gateway == "command" and "hpc.command" not in absent:  # 없으면 게이트웨이 미구성(train_solve 비활성)
        from .hpc.command import validate_command_config

        for msg in validate_command_config(s.hpc):
            add("hpc.command", msg)

    _validate_phase2(s, issues)

    if s.notifications.retention_days < 1:
        add("notifications.retention_days", "1 이상")
    if s.ui.max_artifact_bytes <= 0:
        add("ui.max_artifact_bytes", "양수")
    return issues


def _validate_phase2(s: Settings, issues: list[ConfigIssue]) -> None:
    """2차 키 검증(phase2 §8.2 끝)."""
    add = lambda k, m: issues.append(ConfigIssue(k, m))  # noqa: E731
    td = s.train_data
    for i, p in enumerate(td.hst_log_error_patterns):
        _compile(f"train_data.hst_log_error_patterns[{i}]", p, issues)
    _compile("train_data.hst_progress_regex", td.hst_progress_regex, issues, ("run",))
    _compile("train_data.paramitem_regex", td.paramitem_regex, issues, ("name", "value"))
    _compile("train_data.result_run_dir_regex", td.result_run_dir_regex, issues, ("run_key",))
    for k in ("tpl_prt_regex", "tpl_parameter_line_regex", "tpl_paramitem_line_regex"):
        _compile(f"train_data.{k}", getattr(td, k), issues)
    _compile("optimize.progress_regex", s.optimize.progress_regex, issues, ("run",))
    if not 1 <= td.max_multi_execution <= 64:
        add("train_data.max_multi_execution", "1~64")
    if not 2 <= td.max_runs <= 100000:
        add("train_data.max_runs", "2~100000")
    if not 0 < td.param_default_range_ratio < 1:
        add("train_data.param_default_range_ratio", "0~1 사이")
    if not re.fullmatch(r"%[-0-9.]*[idfeEgG]", td.param_default_format):
        add("train_data.param_default_format", "%[-0-9.]*[idfeEgG]")
    if td.samples_extractor not in ("paramitem", "csv", "none"):
        add("train_data.samples_extractor", "paramitem | csv | none")
    if td.extract_progress_total < 1:
        add("train_data.extract_progress_total", "1 이상")
    if not td.tpl_marker:
        add("train_data.tpl_marker", "비어 있을 수 없습니다")
    for e in td.cad_extensions:
        if not re.fullmatch(r"\.[A-Za-z0-9_]{1,16}", e):
            add("train_data.cad_extensions", f"확장자 형식 오류: {e}")
    if td.result_match_depth < 1:
        add("train_data.result_match_depth", "1 이상")
    if td.max_runs_per_submit < 1:
        add("train_data.max_runs_per_submit", "1 이상")
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", s.optimize.default_study_folder):
        add("optimize.default_study_folder", "^[A-Za-z0-9_-]{1,64}$")
    for i, sp in enumerate(s.optimize.summary_parsers):
        if sp.kind not in ("csv_table", "json_passthrough"):
            add(f"optimize.summary_parsers[{i}].kind", "csv_table | json_passthrough")
    for name in s.optimize.env:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            add("optimize.env", f"환경변수 이름 형식 오류: {name}")
    if s.env_check.probe_timeout_s <= 0 or s.env_check.expire_s <= 0:
        add("env_check", "probe_timeout_s·expire_s는 양수")
    from .commands import EXECUTABLE_PLACEHOLDERS, parse_placeholders

    for tool in ENV_PROBE_TOOLS:
        argv = getattr(s.env_check.probes, tool)
        if argv is None:
            continue
        key = f"env_check.probes.{tool}"
        if not argv or not all(isinstance(x, str) for x in argv) or argv[0] != "{" + tool + "}":
            add(key, f"argv[0]은 {{{tool}}}이어야 합니다")
            continue
        for el in argv[1:]:
            try:
                names = parse_placeholders(el)
            except ValueError as exc:
                add(key, str(exc))
                continue
            if names:
                add(key, "도구 placeholder 외 다른 placeholder는 쓸 수 없습니다")
        if tool not in EXECUTABLE_PLACEHOLDERS:
            add(key, "알 수 없는 도구")
    if s.error_bundle.log_tail_bytes < 1024 or s.error_bundle.max_total_bytes < s.error_bundle.log_tail_bytes:
        add("error_bundle", "log_tail_bytes ≥ 1024, max_total_bytes ≥ log_tail_bytes")
    if s.spdm_import.max_files < 1 or s.curation.max_files < 1:
        add("spdm_import.max_files", "1 이상")


# ---------------------------------------------------------------------------
# 2차 파생 값(phase2 §8.1): 경로 문자열은 설정값에서만 시작한다
# ---------------------------------------------------------------------------


def derived_hstpy_path(a: AltairCfg) -> str:
    if a.hstpy_path:
        return a.hstpy_path
    if not a.hyperstudy_path:
        return ""
    hs = a.hyperstudy_path.replace("\\", "/")
    return hs.rsplit("/", 1)[0] + "/hstpy.bat" if "/" in hs else ""


def derived_altair_home(a: AltairCfg) -> str:
    if a.altair_home:
        return a.altair_home.replace("\\", "/")
    hp = derived_hstpy_path(a)
    if not hp:
        return ""
    parts = hp.replace("\\", "/").split("/")[:-1]  # hstpy 폴더
    if len(parts) <= 3:
        return ""
    return "/".join(parts[:-3])


def effective_altair(s: Settings) -> dict[str, str]:
    """명령 펼침용 실행 파일 표(altair 키 → 경로). hstpy_path·altair_home은 파생값 포함."""
    d = {k: v for k, v in s.altair.model_dump().items() if isinstance(v, str)}
    d["hstpy_path"] = derived_hstpy_path(s.altair)
    d["altair_home"] = derived_altair_home(s.altair)
    return d


def redacted_settings(s: Settings) -> dict[str, Any]:
    """관리 조회용(§10.8). DB URL·비밀은 설정 파일에 없지만 혹시 모를 값을 가린다."""
    d = s.model_dump()
    d["database"] = {"url_env": s.database.url_env, "pool_size": s.database.pool_size}
    return d
