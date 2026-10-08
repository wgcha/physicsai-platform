"""작업 상태 머신(계약 §7.2). 표에 없는 전이는 IllegalTransition."""

from __future__ import annotations

QUEUED = "QUEUED"
RUNNING = "RUNNING"
WAITING_HPC = "WAITING_HPC"
COLLECTING = "COLLECTING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
CANCELED = "CANCELED"
INTERRUPTED = "INTERRUPTED"

ALL_STATES = (QUEUED, RUNNING, WAITING_HPC, COLLECTING, SUCCEEDED, FAILED, CANCELED, INTERRUPTED)
TERMINAL = frozenset({SUCCEEDED, FAILED, CANCELED, INTERRUPTED})
ACTIVE = frozenset(ALL_STATES) - TERMINAL

# (from, to) → 전이 번호. from=None은 생성.
TRANSITIONS: dict[tuple[str | None, str], str] = {
    (None, QUEUED): "T1",
    (QUEUED, RUNNING): "T2",
    (QUEUED, CANCELED): "T3",
    (RUNNING, RUNNING): "T4",
    (RUNNING, WAITING_HPC): "T5",
    (RUNNING, SUCCEEDED): "T6",
    (RUNNING, FAILED): "T7",
    (RUNNING, CANCELED): "T8",
    (RUNNING, INTERRUPTED): "T9",
    (COLLECTING, INTERRUPTED): "T9",
    (WAITING_HPC, COLLECTING): "T10",
    (WAITING_HPC, WAITING_HPC): "T11",
    (WAITING_HPC, CANCELED): "T12",
    (COLLECTING, CANCELED): "T12",
    (WAITING_HPC, FAILED): "T13",
    (COLLECTING, QUEUED): "T14",
    (COLLECTING, SUCCEEDED): "T15",
    (COLLECTING, FAILED): "T16",
}


class IllegalTransition(RuntimeError):
    def __init__(self, src: str | None, dst: str) -> None:
        super().__init__(f"허용되지 않는 상태 전이: {src} → {dst}")
        self.src = src
        self.dst = dst


def check_transition(src: str | None, dst: str) -> str:
    """전이 번호를 돌려준다. 허용되지 않으면 IllegalTransition."""
    try:
        return TRANSITIONS[(src, dst)]
    except KeyError:
        raise IllegalTransition(src, dst) from None


def is_terminal(state: str) -> bool:
    return state in TERMINAL
