"""학습 로그 loss 파서(§8.6). 줄 단위 스트리밍, 메모리는 다운샘플 버퍼만."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LossResult:
    status: str  # PARSED | UNRECOGNIZED | MISSING
    parser: str | None = None
    epochs_total: int | None = None
    last_epoch: int | None = None
    final_loss: float | None = None
    min_loss: float | None = None
    min_loss_epoch: int | None = None
    loss_curve: list[list[float]] | None = None
    points: int = 0


@dataclass
class _Acc:
    max_points: int
    stride: int = 1
    count: int = 0
    buf: list[tuple[int, float]] = field(default_factory=list)
    first: tuple[int, float] | None = None
    last: tuple[int, float] | None = None
    min_pt: tuple[int, float] | None = None
    max_epoch: int | None = None
    last_total: int | None = None

    def add(self, epoch: int, loss: float, total: int | None) -> None:
        pt = (epoch, loss)
        if self.first is None:
            self.first = pt
        self.last = pt
        if self.min_pt is None or loss < self.min_pt[1]:
            self.min_pt = pt
        self.max_epoch = epoch if self.max_epoch is None else max(self.max_epoch, epoch)
        if total is not None:
            self.last_total = total
        if self.count % self.stride == 0:
            self.buf.append(pt)
            if len(self.buf) > 2 * self.max_points:
                self.buf = self.buf[::2]
                self.stride *= 2
        self.count += 1


def downsample(points: list[tuple[int, float]], max_points: int, keep: Iterable[tuple[int, float]]) -> list[list[float]]:
    """첫·마지막·최소 점 보존, 나머지 균등 간격으로 max_points 이하."""
    keep_set = {p for p in keep if p is not None}
    pts = sorted(set(points) | keep_set, key=lambda p: (p[0], p[1]))
    if len(pts) <= max_points:
        return [[e, v] for e, v in pts]
    must = sorted(keep_set, key=lambda p: (p[0], p[1]))
    room = max_points - len(must)
    others = [p for p in pts if p not in keep_set]
    chosen: list[tuple[int, float]] = []
    if room > 0 and others:
        step = len(others) / room
        chosen = [others[min(len(others) - 1, int(i * step))] for i in range(room)]
    final = sorted(set(chosen) | set(must), key=lambda p: (p[0], p[1]))
    return [[e, v] for e, v in final[:max_points]]


def parse_loss_lines(
    lines: Iterable[str],
    parsers: list[tuple[str, str]],
    max_points: int = 2000,
    progress: Callable[[int], None] | None = None,
) -> LossResult:
    """파서 목록을 순서대로 시도해 1줄 이상 일치한 첫 파서 채택.

    lines는 한 번만 순회할 수 있으므로 모든 파서를 동시에 누적하고, 끝난 뒤 첫 일치 파서를 고른다.
    """
    compiled = [(name, re.compile(p)) for name, p in parsers]
    accs = [_Acc(max_points) for _ in compiled]
    nbytes = 0
    for line in lines:
        nbytes += len(line.encode("utf-8", "replace"))
        for (_name, rx), acc in zip(compiled, accs):
            m = rx.search(line)
            if not m:
                continue
            try:
                epoch = int(m.group("epoch"))
                loss = float(m.group("loss"))
            except (ValueError, IndexError):
                continue
            if not math.isfinite(loss):
                continue
            total = None
            if "total" in rx.groupindex and m.group("total") is not None:
                try:
                    total = int(m.group("total"))
                except ValueError:
                    total = None
            acc.add(epoch, loss, total)
        if progress is not None:
            progress(nbytes)
    for (name, _rx), acc in zip(compiled, accs):
        if acc.count > 0:
            curve = downsample(acc.buf, max_points, [acc.first, acc.last, acc.min_pt])
            return LossResult(
                status="PARSED",
                parser=name,
                epochs_total=acc.last_total if acc.last_total is not None else acc.max_epoch,
                last_epoch=acc.last[0] if acc.last else None,
                final_loss=acc.last[1] if acc.last else None,
                min_loss=acc.min_pt[1] if acc.min_pt else None,
                min_loss_epoch=acc.min_pt[0] if acc.min_pt else None,
                loss_curve=curve,
                points=acc.count,
            )
    return LossResult(status="UNRECOGNIZED")


def parse_loss_file(path: str, parsers: list[tuple[str, str]], max_points: int = 2000,
                    progress: Callable[[int], None] | None = None) -> LossResult:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return parse_loss_lines(fh, parsers, max_points, progress)


def as_db_values(r: LossResult) -> dict[str, Any]:
    return {
        "log_status": r.status,
        "log_parser": r.parser,
        "epochs_total": r.epochs_total,
        "last_epoch": r.last_epoch,
        "final_loss": r.final_loss,
        "min_loss": r.min_loss,
        "min_loss_epoch": r.min_loss_epoch,
        "loss_curve": r.loss_curve,
    }
