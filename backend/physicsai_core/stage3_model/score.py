"""평가 점수 파서(§8.7 EV_PARSE). 그룹 name·value 또는 파서 이름 + 그룹 value."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable


def parse_scores(lines: Iterable[str], parsers: list[tuple[str, str]]) -> tuple[str, dict[str, float]]:
    compiled = [(n, re.compile(p)) for n, p in parsers]
    metrics: dict[str, float] = {}
    for line in lines:
        for name, rx in compiled:
            m = rx.search(line)
            if not m:
                continue
            try:
                value = float(m.group("value"))
            except (ValueError, IndexError):
                continue
            if not math.isfinite(value):
                continue
            key = m.group("name").strip() if "name" in rx.groupindex and m.group("name") else name
            metrics[key] = value
    return ("PARSED" if metrics else "UNRECOGNIZED"), metrics
