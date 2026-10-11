"""Study 관리(stage 0) 작업 params·사전조건(phase3 §5.2): STUDY_STORAGE_SCAN, STUDY_CLEANUP.

`study_gate`는 모든 작업 생성·재시도에 쓰는 Study 상태 검사(R3-2 보관 예외, R3-4 정리 중 차단)다.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import study_manage as sm_repo
from physicsai_core.errors import DomainError
from physicsai_core.job_types import MANAGE_JOB_TYPES
from physicsai_core.study_storage.categories import CATEGORY_KEYS, CLEANUP_JOB_TYPE, SCAN_JOB_TYPE

from ...context import AppContext
from ..study_storage import is_stale
from .base import _P, invalid_at

CategoryKey = Literal[CATEGORY_KEYS]  # type: ignore[valid-type]  # schemas.study_storage.CategoryKey와 같은 값
STALE_MSG = "용량 계산 결과가 최신이 아닙니다. 다시 계산한 뒤 정리하세요"


class StudyStorageScanParams(_P):
    pass


class StudyCleanupParams(_P):
    scan_job_id: str = Field(min_length=1, max_length=64)
    categories: list[CategoryKey] = Field(min_length=1, max_length=6)

    @field_validator("categories")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("범주가 중복되었습니다")
        return v


PARAM_MODELS: dict[str, type[BaseModel]] = {
    SCAN_JOB_TYPE: StudyStorageScanParams,
    CLEANUP_JOB_TYPE: StudyCleanupParams,
}


def require_no_cleanup(conn: Any, study_id: str) -> None:
    """정리(STUDY_CLEANUP)가 대기·실행 중이면 409(R3-4, D3-24: 스캔·Final 지정 포함)."""
    if sm_repo.has_active_of_type(conn, study_id, CLEANUP_JOB_TYPE):
        raise DomainError("STUDY_CLEANUP_RUNNING", "Study 정리가 진행 중입니다. 정리가 끝난 뒤 다시 실행하세요", status=409)


def study_gate(conn: Any, study: dict[str, Any], job_type: str) -> None:
    """작업 생성·재시도 공통: 보관 Study(관리 작업 예외), 정리 대기·실행 중이면 모든 유형 차단(스캔 포함).

    호출자는 Study 행을 `for_update=True`로 잠근 뒤 부른다(동시 생성 경합 차단, D3-25).
    """
    if study["status"] != "ACTIVE" and job_type not in MANAGE_JOB_TYPES:
        raise DomainError("STUDY_ARCHIVED", "보관된 Study입니다", status=409)
    require_no_cleanup(conn, study["id"])


def require_retryable_type(job_type: str) -> None:
    if job_type in MANAGE_JOB_TYPES:
        raise DomainError("JOB_NOT_RETRYABLE", "이 작업은 재시도 대신 새로 실행하세요", status=409)


def prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any
            ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    """사전조건(§5.2 표) → (저장할 params, 초기 result, warnings)."""
    if job_type == SCAN_JOB_TYPE:
        return {}, None, []
    sid = study["id"]
    scan = jobs_repo.get_job(conn, p.scan_job_id)
    latest = sm_repo.latest_succeeded(conn, sid, SCAN_JOB_TYPE)
    if scan is None or scan["study_id"] != sid or scan["job_type"] != SCAN_JOB_TYPE or scan["state"] != "SUCCEEDED" \
            or latest is None or latest["id"] != scan["id"]:
        raise DomainError("STORAGE_SCAN_STALE", STALE_MSG, status=409)
    if (scan["result"] or {}).get("partial"):
        raise DomainError("STORAGE_SCAN_PARTIAL", f"{STALE_MSG} (부분 스캔)", status=409)
    if sm_repo.has_active_except(conn, sid):
        raise DomainError("STUDY_HAS_ACTIVE_JOB", "대기 중이거나 실행 중인 작업이 있어 정리할 수 없습니다", status=409)
    reason = is_stale(conn, ctx, sid, scan)
    if reason:
        raise DomainError("STORAGE_SCAN_STALE", STALE_MSG, status=409, stale_reason=reason)
    n = sum(c.get("item_count", 0) for c in (scan["result"] or {}).get("categories") or [] if c.get("key") in p.categories)
    if n < 1:
        raise invalid_at("categories", "옮길 항목이 없습니다", code="INPUT_INVALID")
    return {"scan_job_id": scan["id"], "categories": list(p.categories)}, None, []
