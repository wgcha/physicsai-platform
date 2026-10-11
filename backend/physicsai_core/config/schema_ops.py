"""설정 스키마 — 운영 절(notifications·ui·demo·logging·env_check·study_storage·error_bundle)과 관련 상수."""

from __future__ import annotations

from pydantic import Field

from ._model import _M


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


class StudyStorageCfg(_M):
    """Study 용량 계산·정리(phase3 §5.9). 절이 없으면 기본값."""

    max_entries: int = 2000000
    top_files: int = 20
    max_items_per_category: int = 500
    log_min_age_days: int = 30
    keep_failed_logs: int = 10
    stale_after_hours: int = 24


class ErrorBundleCfg(_M):
    log_tail_bytes: int = 262144
    max_total_bytes: int = 20971520


DEFAULT_LOG_ERROR_PATTERNS = [r"^\s*\d+\s+Error\s*:", r"Traceback \(most recent call last\):", r"^\s*\[ERROR\]"]
