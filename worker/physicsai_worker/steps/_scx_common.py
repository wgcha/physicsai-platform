"""scx 모드 공용: 상한·문구 상수, relay 문구 마스킹, run 단계 모양(RunStage·SubmitResult), hpc_jobs 행 일괄 표시 — _scx에서 재노출."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.masking import bundle_masker

MAX_LIST_ENTRIES = 20000
BATCH_FAIL = ("CONFLICT", "FAILED", "CANCELLED", "PARTIAL")
UNKNOWN_MESSAGE = "SCX 제출 결과를 알 수 없습니다 — SCX에서 확인 필요"
NOT_SUBMITTED_MESSAGE = "제출하지 않음(앞 run의 SCX 제출 결과 모름)"


def mask(ctx_or_settings: Any, text: str) -> str:
    """relay 오류·JobInfo.error_message 마스킹(오류 묶음 규칙 — Bearer·DB 자격·비밀 값) 후 500자."""
    s = getattr(ctx_or_settings, "settings", ctx_or_settings)
    return bundle_masker(s)(str(text))[:500]


def timestamp() -> str:
    """잡 폴더 시각: HPC_SUBMIT step 시작 시 워커 현지 시각(§16.3)."""
    return datetime.now().strftime("%Y%m%dT%H%M%S")


@dataclass
class RunStage:
    """run 1개의 STAGE_IN·제출 계획."""

    run_key: str
    input_dir: str
    starter: str
    job_name: str                       # 접미 전 잡 폴더 이름(01_D-…·04_V-…)
    client_ref: dict[str, str]
    files: list[dict[str, Any]] = field(default_factory=list)  # {name, size, sha256}
    remote_dir: str = ""
    hid: str = ""
    request_id: str = ""
    batches: list[str] = field(default_factory=list)
    bytes_total: int = 0


@dataclass
class SubmitResult:
    submitted: list[tuple[RunStage, str]] = field(default_factory=list)  # (계획, 외부 잡 ID)
    unknown: RunStage | None = None
    not_submitted: list[str] = field(default_factory=list)


def _mark_rows(ctx: Any, plans: list[RunStage], state: str, message: str, phase: str | None = None) -> None:
    def fn(c: Any) -> None:
        for p in plans:
            if not p.hid:
                continue
            row = hpc_repo.get(c, p.hid)
            if row is None or row["state"] != "SUBMITTING":
                continue
            staged = dict(row["staged"] or {})
            if phase:
                staged["phase"] = phase
            hpc_repo.set_fields(c, p.hid, state=state, error_message=message[:500], staged=staged,
                                finished_at=datetime.now().astimezone())

    ctx.ex.db(fn)
