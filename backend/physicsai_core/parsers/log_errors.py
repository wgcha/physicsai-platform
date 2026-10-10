"""외부 프로그램 로그 오류 감지(§8.3). 비밀 마스킹은 physicsai_core.masking."""

from __future__ import annotations

import re


class ErrorDetector:
    def __init__(self, patterns: list[str]) -> None:
        self._rx = [re.compile(p, re.IGNORECASE) for p in patterns]
        self.first_match: str | None = None
        self.count = 0

    def feed(self, line: str) -> bool:
        for rx in self._rx:
            if rx.search(line):
                self.count += 1
                if self.first_match is None:
                    self.first_match = line.strip()[:200]
                return True
        return False
