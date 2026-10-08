"""환경 점검 공용(phase2 §9): 항목 모양, 워커 항목 키 목록(claim 전 PENDING 자리 항목), 요약."""

from __future__ import annotations

from typing import Any

from .config import ENV_PROBE_TOOLS, LAUNCHER_KEYS, RESOURCE_DIR_KEYS, RESOURCE_FILE_KEYS, Settings

CATEGORIES = ("CONFIG", "DATABASE", "AUTH", "HPC", "WORKER", "EXECUTABLE", "RESOURCE", "STORAGE", "GPU")
STATUSES = ("OK", "WARN", "FAIL", "SKIP", "PENDING")
ALTAIR_CHECK_KEYS = ("hyperstudy_path", "simlab_path", "edspy_path", "hw_exe_path", "hvtrans_exe_path", "hstpy_path")

LABELS = {
    "config.valid": "설정 검증", "db.connection": "DB 연결", "db.migration_head": "DB migration head",
    "auth.dashboard": "대시보드 인증", "auth.projects": "대시보드 프로젝트 목록", "hpc.gateway": "PBS 게이트웨이",
    "worker.heartbeat": "워커 하트비트", "storage.ai_root.write": "AI 루트 쓰기", "storage.ai_root.free": "AI 루트 여유 공간",
    "storage.roots_overlap": "루트 겹침", "storage.spdm_roots": "SPDM 루트 읽기", "worker.limiter": "자원 제한기",
    "worker.job_object": "Windows Job Object", "gpu.detect": "GPU 감지",
}


def item(key: str, category: str, status: str, message: str, source: str, detail: dict[str, Any] | None = None,
         label: str | None = None) -> dict[str, Any]:
    assert category in CATEGORIES and status in STATUSES and source in ("API", "WORKER")
    return {"key": key, "category": category, "label": label or LABELS.get(key, key), "status": status,
            "message": message[:200], "source": source, "detail": detail}


def worker_item_keys(s: Settings) -> list[tuple[str, str]]:
    """(key, category) — 고정 목록(§9.3)."""
    keys: list[tuple[str, str]] = [(f"altair.{k}", "EXECUTABLE") for k in ALTAIR_CHECK_KEYS]
    keys += [(f"probe.{t}", "EXECUTABLE") for t in ENV_PROBE_TOOLS]
    keys += [(f"resource.{k}", "RESOURCE") for k in (*RESOURCE_FILE_KEYS, *RESOURCE_DIR_KEYS)]
    keys += [(f"resource.launchers.{k}", "RESOURCE") for k in LAUNCHER_KEYS]
    keys += [("storage.ai_root.write", "STORAGE"), ("storage.ai_root.free", "STORAGE"), ("storage.roots_overlap", "STORAGE"),
             ("storage.spdm_roots", "STORAGE"), ("worker.limiter", "WORKER"), ("worker.job_object", "WORKER"),
             ("gpu.detect", "GPU")]
    return keys


def pending_worker_items(s: Settings) -> list[dict[str, Any]]:
    return [item(k, c, "PENDING", "워커 점검 대기 중", "WORKER") for k, c in worker_item_keys(s)]


def report_rel(check_id: str) -> str:
    """AI 루트 기준(§9.3)."""
    return f"_platform/env_checks/{check_id}/report.json"
