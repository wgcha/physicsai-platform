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
from typing import Any, Literal

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


class ResourcesCfg(_M):
    preview_pred_h3d_tcl: str = ""


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
    collect_mode: str = "in_place"
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


class LoggingCfg(_M):
    level: str = "INFO"
    mask_patterns: list[str] = Field(
        default_factory=lambda: [r"(?i)(password|passwd|token|secret)\s*[=:]\s*\S+"]
    )


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
    commands_log_error_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_LOG_ERROR_PATTERNS))
    hpc: HpcCfg = Field(default_factory=HpcCfg)
    notifications: NotificationsCfg = Field(default_factory=NotificationsCfg)
    ui: UiCfg = Field(default_factory=UiCfg)
    logging: LoggingCfg = Field(default_factory=LoggingCfg)


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


def default_config_path() -> str:
    return os.environ.get("PHYSICSAI_CONFIG", "config/platform.yaml")


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
    issues = validate_settings(settings)
    return LoadedConfig(settings, issues, path, sha256)


def _compile(key: str, pattern: str, issues: list[ConfigIssue], required_groups: tuple[str, ...] = ()) -> None:
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        issues.append(ConfigIssue(key, f"정규식 컴파일 실패: {exc}"))
        return
    for g in required_groups:
        if g not in rx.groupindex:
            issues.append(ConfigIssue(key, f"정규식에 필수 그룹 '{g}'이 없습니다"))


def validate_settings(s: Settings) -> list[ConfigIssue]:  # noqa: C901 - 표 기반 규칙 나열
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
    for k in ("hyperstudy_path", "simlab_path", "edspy_path", "hw_exe_path", "hvtrans_exe_path"):
        v = getattr(s.altair, k)
        if v:
            if not is_abs_path_str(v):
                add(f"altair.{k}", "절대경로여야 합니다")
            elif prod and not os.path.isfile(v):
                add(f"altair.{k}", f"실행 파일이 없습니다: {v}")

    # resources
    tcl = s.resources.preview_pred_h3d_tcl
    if tcl:
        if not is_abs_path_str(tcl):
            add("resources.preview_pred_h3d_tcl", "절대경로여야 합니다")
        elif has_unsafe_chars(tcl):
            add("resources.preview_pred_h3d_tcl", "공백·제어문자·cmd 메타문자를 쓸 수 없습니다")
        elif prod and not os.path.isfile(tcl):
            add("resources.preview_pred_h3d_tcl", f"파일이 없습니다: {tcl}")
    elif prod:
        add("resources.preview_pred_h3d_tcl", "prod에서는 필수입니다")

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
    if a.mode not in ("dashboard", "dev_static"):
        add("auth.mode", "dashboard | dev_static")
    if a.mode == "dev_static" and (s.profile != "dev" or s.server.host != "127.0.0.1"):
        add("auth.mode", "dev_static은 profile=dev이고 127.0.0.1 바인딩일 때만 허용됩니다")
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
    for i, p in enumerate(s.logging.mask_patterns):
        _compile(f"logging.mask_patterns[{i}]", p, issues)

    if s.predict.integer_rounding not in ("half_up", "truncate"):
        add("predict.integer_rounding", "half_up | truncate")
    if has_unsafe_chars(s.predict.rendered_script_name) or "/" in s.predict.rendered_script_name:
        add("predict.rendered_script_name", "파일 이름만, 공백·메타문자 금지")

    # commands
    for key in TEMPLATE_SPECS:
        for msg in validate_template(key, getattr(s.commands, key)):
            add(f"commands.{key}", msg)

    # hpc
    if s.hpc.gateway not in ("none", "command", "adapter"):
        add("hpc.gateway", "none | command | adapter")
    if s.hpc.transfer.collect_mode != "in_place":
        add("hpc.transfer.collect_mode", "1차는 in_place만 지원합니다(shared_folder·drive는 2차)")
    if s.hpc.gateway == "command":
        from .hpc.command import validate_command_config

        for msg in validate_command_config(s.hpc):
            add("hpc.command", msg)

    if s.notifications.retention_days < 1:
        add("notifications.retention_days", "1 이상")
    if s.ui.max_artifact_bytes <= 0:
        add("ui.max_artifact_bytes", "양수")
    return issues


def redacted_settings(s: Settings) -> dict[str, Any]:
    """관리 조회용(§10.8). DB URL·비밀은 설정 파일에 없지만 혹시 모를 값을 가린다."""
    d = s.model_dump()
    d["database"] = {"url_env": s.database.url_env, "pool_size": s.database.pool_size}
    return d


Profile = Literal["dev", "prod"]
