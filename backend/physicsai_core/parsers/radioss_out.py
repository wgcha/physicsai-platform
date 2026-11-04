"""Radioss 출력(`*_0001.out` engine, `*_0000.out`·`.sty` starter) 꼬리·요약 파서(data-health.md DH-9, §3.1).

결과 파일 본문을 대량으로 읽지 않는다 — engine out은 끝 `limit` 바이트만, starter out은 앞에서부터 줄 단위로 읽다 첫 일치에서 멈춘다
(`max_bytes` 넘으면 포기). 정규식은 호출자(설정 `data_health.*`)가 넘긴다. equiv `starter_mass`와 ③-1 데이터 점검이 함께 쓴다.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass

# equiv-check `starter_mass`가 쓰던 값 그대로(설정 `data_health.total_mass_regex` 기본값과 같다 — 시험이 같음을 확인)
TOTAL_MASS_RE = r"TOTAL\s+MASS\s*[:=]?\s*([-+0-9.eE]+)"

NORMAL, ERROR, UNKNOWN = "NORMAL", "ERROR", "UNKNOWN"


def read_tail(path: str, limit: int) -> tuple[str, int]:
    """파일 꼬리 ≤ limit 바이트(UTF-8 경계 보정). (텍스트, 읽지 않은 앞 바이트 수)."""
    size = os.path.getsize(path)
    start = max(0, size - limit)
    with open(path, "rb") as fh:
        fh.seek(start)
        data = fh.read(limit)
    skip = 0
    if start > 0:
        while skip < len(data) and skip < 4 and (data[skip] & 0xC0) == 0x80:
            skip += 1
    return data[skip:].decode("utf-8", errors="replace"), start + skip


@dataclass(frozen=True)
class CycleLine:
    time: float | None
    err: float | None
    mas: float | None


@dataclass(frozen=True)
class EngineTail:
    term: str                 # NORMAL | ERROR | UNKNOWN
    cycle: CycleLine | None   # 꼬리의 마지막 사이클 줄(없으면 None)
    omitted_bytes: int


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def parse_engine_tail(text: str, *, normal_regex: str, error_regex: str, cycle_regex: str) -> tuple[str, CycleLine | None]:
    """꼬리 텍스트 → (종료 판정, 마지막 사이클 줄). 오류 종료 표지가 정상 종료 표지보다 우선한다(둘 다 있으면 ERROR)."""
    nrx, erx, crx = (re.compile(p, re.I) for p in (normal_regex, error_regex, cycle_regex))
    term = UNKNOWN
    if erx.search(text):
        term = ERROR
    elif nrx.search(text):
        term = NORMAL
    last: CycleLine | None = None
    for line in text.splitlines():
        m = crx.search(line)
        if m is None:
            continue
        g = m.groupdict()
        last = CycleLine(_num(g.get("time")), _num(g.get("err")), _num(g.get("mas")))
    return term, last


def read_engine_tail(path: str, *, limit: int, normal_regex: str, error_regex: str, cycle_regex: str) -> EngineTail:
    text, omitted = read_tail(path, limit)
    term, last = parse_engine_tail(text, normal_regex=normal_regex, error_regex=error_regex, cycle_regex=cycle_regex)
    return EngineTail(term, last, omitted)


class ScanTooLarge(Exception):
    """starter 출력이 읽기 상한을 넘었다(값을 못 찾음)."""


def starter_total_mass(path: str, *, regex: str = TOTAL_MASS_RE, max_bytes: int | None = None) -> float | None:
    """앞에서부터 줄 단위로 읽다 `regex` 첫 일치(그룹 1 = 질량)에서 멈춘다. 값 없음 → None, `max_bytes`를 넘기도록 못 찾으면 ScanTooLarge.
    max_bytes=None = 파일 끝까지(equiv 기존 동작). 읽기·값 오류(OSError·ValueError)는 호출자가 처리한다."""
    rx = re.compile(regex, re.I)
    read = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            read += len(line.encode("utf-8", errors="replace"))
            m = rx.search(line)
            if m:
                return float(m.group(1))
            if max_bytes is not None and read > max_bytes:
                raise ScanTooLarge(path)
    return None
