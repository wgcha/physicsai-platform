"""DB 메타데이터 단일 객체와 공용 타입(TS·ID)·대기열 시퀀스·종료 상태."""

from __future__ import annotations

from sqlalchemy import MetaData, Sequence, String
from sqlalchemy.dialects.postgresql import TIMESTAMP

metadata = MetaData()

TS = TIMESTAMP(timezone=True)
ID = String(36)

job_queue_seq = Sequence("job_queue_seq", metadata=metadata)

TERMINAL_STATES = ("SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED")
