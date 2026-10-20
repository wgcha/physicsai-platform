"""설정 스키마 — 외부 명령 템플릿(commands)과 HPC 절(hpc.defaults·command·adapter·transfer·scx)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ._model import _M


class CommandsCfg(_M):
    edspy_create_dataset: list[str] | None = None
    edspy_score: list[str] | None = None
    geom_update: list[str] | None = None
    mesh: list[str] | None = None
    rad_assemble: list[str] | None = None
    edspy_predict: list[str] | None = None
    contour_preview: list[str] | None = None
    response_extract: list[str] | None = None
    # phase3 §15 S10: 예측 컨투어 캡처(HyperView 배치). 설정 파일에 없으면 이 기본값(기능 켬, altair.hw_exe_path 필요)
    contour_capture: list[str] | None = Field(
        default_factory=lambda: ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{capture_tcl}"])
    # 2차(phase2 §8.1) — null이면 그 기능만 비활성(가정 A-11)
    simlab_extract_params: list[str] | None = None
    hst_gen_radioss: list[str] | None = None
    h3d_preview: list[str] | None = None
    hvtrans_curate: list[str] | None = None
    t01_preview: list[str] | None = None
    t01_curve_export: list[str] | None = None
    hst_optimization: list[str] | None = None
    # native 형상 엔진(geometry-engine.md §7.1) — 외부 도구 의존이 없으므로 기본값이 켜져 있다. null이면 그 기능만 꺼짐
    paicad_extract: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "extract", "--cad", "{cad_input}", "--renum-csv", "{renum_csv}", "--options", "{options_json}",
        "--out-dir", "{out_dir}"])
    paicad_tag: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "tag", "--cad", "{cad_input}", "--features", "{features_json}", "--baseline-inc", "{baseline_inc}",
        "--renum-csv", "{renum_csv}", "--assem-dir", "{assem_dir}", "--options", "{options_json}", "--out-dir", "{out_dir}"])
    paicad_update: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "update", "--cad", "{cad_input}", "--features", "{features_json}", "--values", "{values_json}",
        "--tag-dir", "{tag_dir}", "--options", "{options_json}", "--out-dir", "{update_dir}"])
    paicad_morph: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "morph", "--baseline-inc", "{baseline_inc}", "--tag-dir", "{tag_dir}", "--features", "{features_json}",
        "--update-dir", "{update_dir}", "--options", "{options_json}", "--out-dir", "{morph_dir}"])
    paicad_check: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "check", "--baseline-inc", "{baseline_inc}", "--morph-dir", "{morph_dir}", "--update-dir", "{update_dir}",
        "--tag-dir", "{tag_dir}", "--features", "{features_json}", "--values", "{values_json}", "--assem-dir", "{assem_dir}",
        "--renum-csv", "{renum_csv}", "--options", "{options_json}", "--out-dir", "{check_dir}", "--out-inc", "{out_inc}"])
    paicad_run: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "run", "--cad", "{cad_input}", "--features", "{features_json}", "--values", "{values_json}",
        "--baseline-inc", "{baseline_inc}", "--tag-dir", "{tag_dir}", "--assem-dir", "{assem_dir}", "--renum-csv", "{renum_csv}",
        "--options", "{options_json}", "--update-dir", "{update_dir}", "--morph-dir", "{morph_dir}", "--check-dir", "{check_dir}",
        "--out-inc", "{out_inc}"])
    paicad_version: list[str] | None = Field(default_factory=lambda: ["{paicad}", "version", "--json"])
    # 단계 3S 쉘 두께(§11.1) — null이면 쉘 두께 파라미터 기능만 꺼짐
    paicad_props_scan: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "props", "scan", "--assem-dir", "{assem_dir}", "--options", "{options_json}", "--out-dir", "{out_dir}"])
    paicad_props_apply: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "props", "apply", "--assem-dir", "{assem_dir}", "--values", "{values_json}", "--props", "{props_json}",
        "--out-dir", "{out_dir}"])
    # 단계 4B 다중 baseline 매칭 초안(§7.3.8) — null이면 baseline 추가·재매핑만 꺼짐
    paicad_map: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "map", "--baselines", "{baselines_json}", "--out-dir", "{map_out_dir}", "--user-map", "{user_map}",
        "--usage", "{usage}", "--split-param", "{split_param}", "--options", "{options_json}"])
    # 쉘 판금 모핑(shell-morph.md §8.1, paicad 0.8.0+) — null이면 쉘(kind=shell) 세트 기능만 꺼짐
    paicad_shell_fixed_scan: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "shell", "fixed-scan", "--assem-dir", "{assem_dir}", "--features", "{features_json}", "--options", "{options_json}",
        "--out-dir", "{out_dir}"])
    paicad_shell_extract: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "shell", "extract", "--cad", "{cad_input}", "--assem-dir", "{assem_dir}", "--options", "{options_json}",
        "--out-dir", "{out_dir}"])
    paicad_shell_tag: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "shell", "tag", "--cad", "{cad_input}", "--features", "{features_json}", "--assem-dir", "{assem_dir}",
        "--fixed-dir", "{fixed_dir}", "--options", "{options_json}", "--out-dir", "{out_dir}"])
    paicad_shell_update: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "shell", "update", "--cad", "{cad_input}", "--features", "{features_json}", "--values", "{values_json}",
        "--fixed-dir", "{fixed_dir}", "--options", "{options_json}", "--out-dir", "{update_dir}"])
    paicad_shell_morph: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "shell", "morph", "--assem-dir", "{assem_dir}", "--tag-dir", "{tag_dir}", "--fixed-dir", "{fixed_dir}",
        "--features", "{features_json}", "--update-dir", "{update_dir}", "--options", "{options_json}", "--out-dir", "{morph_dir}"])
    paicad_shell_check: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "shell", "check", "--assem-dir", "{assem_dir}", "--morph-dir", "{morph_dir}", "--update-dir", "{update_dir}",
        "--tag-dir", "{tag_dir}", "--fixed-dir", "{fixed_dir}", "--features", "{features_json}", "--values", "{values_json}",
        "--thickness", "{thickness_json}", "--options", "{options_json}", "--out-dir", "{check_dir}", "--out-files-dir", "{out_files_dir}"])
    paicad_shell_run: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "shell", "run", "--cad", "{cad_input}", "--features", "{features_json}", "--values", "{values_json}",
        "--assem-dir", "{assem_dir}", "--tag-dir", "{tag_dir}", "--fixed-dir", "{fixed_dir}", "--thickness", "{thickness_json}",
        "--options", "{options_json}", "--update-dir", "{update_dir}", "--morph-dir", "{morph_dir}", "--check-dir", "{check_dir}",
        "--out-files-dir", "{out_files_dir}"])
    # 3D 가시화(geometry-view.md §6.1, paicad 0.9.0+) — null이면 공칭 뷰·미리보기만 꺼짐(PNG 그림은 그대로)
    paicad_view_export: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "view", "export", "--cad", "{cad_input}", "--features", "{features_json}", "--view-options", "{view_options_json}",
        "--out-dir", "{out_dir}"])
    paicad_view_preview: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "view", "preview", "--cad", "{cad_input}", "--features", "{features_json}", "--values", "{values_json}",
        "--tag-dir", "{tag_dir}", "--options", "{options_json}", "--view-options", "{view_options_json}",
        "--nominal-manifest", "{nominal_manifest}", "--fe", "{fe_mode}", "--baseline-inc", "{baseline_inc}", "--renum-csv", "{renum_csv}",
        "--assem-dir", "{assem_dir}", "--threads", "{threads}", "--out-dir", "{out_dir}"])
    # 쉘 뷰(`paicad shell view`, paicad 0.10.0+, geometry-view.md §6.1) — null이면 쉘 세트 공칭 뷰·미리보기만 꺼짐
    paicad_shell_view_export: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "shell", "view", "export", "--cad", "{cad_input}", "--features", "{features_json}", "--fixed-dir", "{fixed_dir}",
        "--view-options", "{view_options_json}", "--out-dir", "{out_dir}"])
    paicad_shell_view_preview: list[str] | None = Field(default_factory=lambda: [
        "{paicad}", "shell", "view", "preview", "--cad", "{cad_input}", "--features", "{features_json}", "--values", "{values_json}",
        "--fixed-dir", "{fixed_dir}", "--tag-dir", "{tag_dir}", "--assem-dir", "{assem_dir}", "--options", "{options_json}",
        "--view-options", "{view_options_json}", "--nominal-manifest", "{nominal_manifest}", "--fe", "{fe_mode}",
        "--thickness", "{thickness_json}", "--threads", "{threads}", "--out-dir", "{out_dir}"])
    # 결과 3D 컨투어 추출(geometry-view.md §13.3) — contour3d.enabled=true일 때만 쓴다
    contour_extract: list[str] | None = Field(
        default_factory=lambda: ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{contour_extract_tcl}"])


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


SCX_MPI_KNOWN = ("SMP (default)", "Pure MPI", "Hybrid 2 Threads", "Hybrid 4 Threads", "Hybrid 8 Threads", "auto")


class HpcScxCfg(_M):
    """scx 모드(phase3 §16.8) — 대시보드 SCX relay 경유 Radioss 제출. 기본값의 단일 출처(환경별 값은 설정 파일에서만)."""

    relay_url: str = ""                     # scx면 필수. http://127.0.0.1:<port> | http://[::1]:<port> | http://localhost:<port>
    secret_file: str = ""                   # "" = <런타임>/secrets/scx_relay_key (한 줄 base64url 43~128자, 값은 어디에도 기록하지 않음)
    drive_base: str = "~"                   # "~"(공용 계정 홈) | "~/<상대>"
    home_display: str = "/Users/vd.dashboard"  # 표시 전용(계산에 쓰지 않음)
    appliance: str = ""                     # 필수(E4-11-1)
    version: str = "26.1"                   # 필수(E4-11-2). 작업 params hpc.version이 있으면 덮어씀(D3-68)
    ncpu: int = 16
    memory_gb: int | None = None
    queue_type: str = "implicit"
    run_type: str = "both - use starter and engine files"
    mpi: str = "Pure MPI"                   # 허용 값은 SCX_MPI_KNOWN(밖 값은 설정 경고 — 어댑터가 값을 늘릴 수 있음)
    single_precision: bool = False
    poll_interval_s: float | None = None    # null = hpc.poll_interval_s
    max_download_bytes: int = 21474836480
    stage_patterns: list[str] = Field(default_factory=lambda: ["*.rad", "*.inc", "*.csv"])
    list_additional_paths: bool = True      # E4-11-4
    max_stage_bytes: int = 21474836480
    stage_poll_s: float = 5
    stage_timeout_s: float = 7200
    submit_replay_attempts: int = 3
    submit_replay_wait_s: float = 10
    http_timeout_s: float = 30
    transfer_timeout_s: float = 3600
    collect_max_depth: int = 2
    health_ttl_s: float = 30


class HpcCfg(_M):
    gateway: str = "none"
    poll_interval_s: float = 60
    lost_after_polls: int = 10
    max_unreachable_minutes: float = 1440
    defaults: HpcDefaultsCfg = Field(default_factory=HpcDefaultsCfg)
    command: HpcCommandCfg = Field(default_factory=HpcCommandCfg)
    adapter: HpcAdapterCfg = Field(default_factory=HpcAdapterCfg)
    transfer: HpcTransferCfg = Field(default_factory=HpcTransferCfg)
    scx: HpcScxCfg = Field(default_factory=HpcScxCfg)
