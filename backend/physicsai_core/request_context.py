"""요청 문맥(contextvar): 토큰 요청으로 만든 작업에 `jobs.api_token_id`를 남기고 만든 작업 id를 모은다(mcp.md §14).

공통 작업 계약(`run_job`)이 생성 함수 호출을 `token_job_context`로 감싼다. 워커·세션 요청은 기본값(None)이라 기존 동작 불변.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_API_TOKEN_ID: ContextVar[str | None] = ContextVar("api_token_id", default=None)
_CREATED_JOBS: ContextVar[list[str] | None] = ContextVar("created_job_ids", default=None)


def current_api_token_id() -> str | None:
    return _API_TOKEN_ID.get()


def note_created_job(job_id: str) -> None:
    got = _CREATED_JOBS.get()
    if got is not None:
        got.append(job_id)


@contextmanager
def token_job_context(api_token_id: str | None) -> Iterator[list[str]]:
    """블록 안에서 insert_job이 만든 작업 id 목록(생성 순서)을 돌려주고, 토큰 id가 있으면 행에 기록하게 한다."""
    created: list[str] = []
    t1 = _API_TOKEN_ID.set(api_token_id)
    t2 = _CREATED_JOBS.set(created)
    try:
        yield created
    finally:
        _CREATED_JOBS.reset(t2)
        _API_TOKEN_ID.reset(t1)
