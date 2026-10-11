"""스캔 결과 낡음(stale) 판정(phase3 §5.4). 순수 함수 — 조회는 호출자가 저장소로 한다."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

NOT_SCANNED = "아직 계산하지 않았습니다"


def stale_reason(scan: dict[str, Any] | None, *, finished_after: int, has_active: bool, now: datetime,
                 stale_after_hours: int) -> str | None:
    """낡았으면 한국어 사유, 아니면 None.

    scan: 최근 SUCCEEDED 스캔 작업 행(없으면 None). finished_after: 스캔 started_at 이후 종료된 다른 유형 작업 수.
    has_active: 지금 비종료 작업(스캔 자신 제외)이 있는지.
    """
    if scan is None:
        return NOT_SCANNED
    if finished_after > 0:
        return f"스캔 뒤 작업 {finished_after}개가 끝났습니다"
    if has_active:
        return "실행 중인 작업이 있습니다"
    done = scan.get("finished_at") or scan.get("started_at")
    if done is None or now - done > timedelta(hours=stale_after_hours):
        return f"계산한 지 {stale_after_hours}시간이 지났습니다"
    return None
