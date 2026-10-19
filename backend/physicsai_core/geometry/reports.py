"""paicad 보고 JSON 읽기(geometry-engine.md §7.2, §17.3) — 표준 라이브러리만, 키 존재·타입만 검사한다.

`geometry.max_report_bytes`를 넘거나 JSON이 아니거나 아는 `schema_version`이 아니면 `ReportError`(코드 INPUT_INVALID).
"""

from __future__ import annotations

import json
import os
from typing import Any

KNOWN_SCHEMA_VERSIONS = (1,)  # 플랫폼이 읽는 보고 JSON 형식(envelope.json 등 sweep 산출물은 읽지 않음)


class ReportError(Exception):
    """보고 JSON을 읽을 수 없음. code는 항상 INPUT_INVALID, message는 한국어."""

    code = "INPUT_INVALID"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def read_report(path: str, max_bytes: int, *, schemas: tuple[int, ...] = KNOWN_SCHEMA_VERSIONS) -> dict[str, Any]:
    name = os.path.basename(path)
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise ReportError(f"{name}을(를) 읽을 수 없습니다: {exc.__class__.__name__}") from None
    if size > max_bytes:
        raise ReportError(f"{name}이(가) 읽기 상한({max_bytes} bytes)을 넘습니다")
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ReportError(f"{name} 형식 오류: {exc.__class__.__name__}") from None
    if not isinstance(doc, dict):
        raise ReportError(f"{name}의 최상위는 객체여야 합니다")
    sv = doc.get("schema_version")
    if isinstance(sv, bool) or not isinstance(sv, int) or sv not in schemas:
        raise ReportError(f"{name}의 schema_version({sv!r})을 플랫폼이 읽을 수 없습니다(paicad 버전 확인)")
    return doc


def report_status(doc: dict[str, Any]) -> str | None:
    s = doc.get("status")
    return s if isinstance(s, str) else None


def parse_version_json(text: str) -> dict[str, str]:
    """`paicad version --json` stdout → {"paicad","ocp","numpy","scipy","python"}(있는 키만, 문자열)."""
    try:
        doc = json.loads(text.strip().splitlines()[-1] if text.strip() else "")
    except (ValueError, IndexError):
        raise ReportError("paicad version 출력이 JSON이 아닙니다") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("paicad"), str):
        raise ReportError("paicad version 출력에 paicad 버전이 없습니다")
    return {k: str(v) for k, v in doc.items() if isinstance(v, (str, int, float))}


def version_display(doc: dict[str, str]) -> str:
    """환경 점검 표시(§7.1): `paicad 0.5.0 · OCP 7.8.1.1.post1`."""
    out = f"paicad {doc.get('paicad', '?')}"
    if doc.get("ocp"):
        out += f" · OCP {doc['ocp']}"
    return out


def same_major_minor(a: str | None, b: str | None) -> bool:
    """§17.3 준비본 유효성: MAJOR.MINOR가 같으면 True(PATCH 차이는 READY). 모르면 True(판정 불가는 STALE로 보지 않음)."""
    def mm(v: str | None) -> tuple[str, str] | None:
        parts = (v or "").split(".")
        return (parts[0], parts[1]) if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit() else None

    ma, mb = mm(a), mm(b)
    return ma is None or mb is None or ma == mb
