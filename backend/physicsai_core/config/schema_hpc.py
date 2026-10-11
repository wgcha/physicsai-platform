"""설정 스키마 — 외부 명령 템플릿(commands)과 HPC 절(hpc.defaults·command·adapter·transfer)."""

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
