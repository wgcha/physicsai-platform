"""paicad 실행 결과 판정(geometry-engine.md §5.4·§7.2): 출력 파일 우선, 보고 JSON이 FAIL이면 그 code로 실패.

판정 순서
1. 보고 JSON을 읽을 수 없음(상한 초과·형식·알 수 없는 schema_version) → INPUT_INVALID.
2. 보고 `status`(없으면 stdout `PAICAD RESULT` 줄의 상태)가 FAIL → 보고의 `code`(run은 skip.code)로 실패.
3. 상태 OK/PASS: 성공 파일이 모두 있으면 성공(종료코드 ≠0이면 경고 EXIT_NONZERO_IGNORED), 없으면 OUTPUT_MISSING.
4. 보고에 상태가 없고 종료코드 13이면 GEOM_EXTRACT_EMPTY(§5.4 — features 빈 배열 보고).
5. 보고 JSON 없음: 종료코드 ≠0 → EXIT_NONZERO, 0 → OUTPUT_MISSING.
메시지는 한국어 표준 문구 + 영문 기술 메시지(messages.korean_message)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from ..errors import StepFailure
from .messages import category_of, korean_message
from .reports import ReportError, read_report, report_status

OK_STATUSES = ("OK", "PASS")
EXIT_EXTRACT_EMPTY = 13


@dataclass
class Verdict:
    ok: bool
    code: str | None = None
    category: str | None = None
    message: str | None = None  # 한국어(표준 문구 — 영문 기술 메시지)
    english: str | None = None  # paicad 영문 기술 메시지(로그·디버깅)
    step: str | None = None  # run 실패 단계 update|morph|check
    report_rel: str | None = None  # run 실패 단계 보고 경로(paicad가 준 값)
    exit_code: int | None = None
    warnings: list[tuple[str, str]] = field(default_factory=list)
    report: dict[str, Any] | None = None

    def raise_if_failed(self) -> None:
        if not self.ok:
            raise StepFailure(self.code or "EXIT_NONZERO", self.message or "paicad 실행 실패")


def _fail(code: str, english: str | None, rc: int | None, **kw: Any) -> Verdict:
    return Verdict(False, code, category_of(code, kw.pop("category", None)), korean_message(code, english), english, exit_code=rc, **kw)


def judge_paicad(rc: int | None, report_path: str, success_paths: list[str], *, max_bytes: int,
                 result_line: tuple[str, str | None] | None = None) -> Verdict:
    """rc = paicad 종료코드, report_path = 보고 JSON, success_paths = 성공 판정 파일(보고 JSON 제외),
    result_line = stdout 마지막 `PAICAD RESULT <status> <code|-> …`의 (status, code)."""
    rc_ = -1 if rc is None else rc
    report: dict[str, Any] | None = None
    if os.path.isfile(report_path):
        try:
            report = read_report(report_path, max_bytes)
        except ReportError as exc:
            return Verdict(False, exc.code, None, exc.message, exc.message, exit_code=rc_)
    status = report_status(report) if report else None
    if status is None and report is not None and result_line is not None:
        status = result_line[0]
    if report is None:
        what = f" (paicad 결과: {result_line[0]} {result_line[1] or '-'})" if result_line else ""
        if rc_ != 0:
            return Verdict(False, "EXIT_NONZERO", None, f"종료코드 {rc_}: 보고 {os.path.basename(report_path)}이(가) 없습니다{what}",
                           exit_code=rc_)
        return Verdict(False, "OUTPUT_MISSING", None, f"보고 {os.path.basename(report_path)}이(가) 만들어지지 않았습니다{what}",
                       exit_code=rc_)
    if status == "FAIL" or (status not in OK_STATUSES and status is not None):
        skip = report.get("skip") if isinstance(report.get("skip"), dict) else {}
        # 보고에 코드가 없으면(추출 결과 0개 보고 등) stdout `PAICAD RESULT FAIL <code>`의 코드를 쓴다
        line_code = result_line[1] if result_line is not None and result_line[0] == "FAIL" else None
        code = report.get("code") or skip.get("code") or line_code or "GEOM_INTERNAL"
        eng = report.get("message") or skip.get("message")
        return _fail(str(code), eng if isinstance(eng, str) else None, rc_, category=report.get("category") or skip.get("category"),
                     step=skip.get("step") if isinstance(skip.get("step"), str) else None,
                     report_rel=skip.get("report") if isinstance(skip.get("report"), str) else None, report=report)
    if status is None and rc_ == EXIT_EXTRACT_EMPTY:
        return _fail("GEOM_EXTRACT_EMPTY", "no features recognized", rc_, report=report)
    if status is None and rc_ != 0:
        return Verdict(False, "EXIT_NONZERO", None, f"종료코드 {rc_}: 보고 {os.path.basename(report_path)}에 상태가 없습니다",
                       exit_code=rc_, report=report)
    missing = [os.path.basename(p) for p in success_paths if not (os.path.isfile(p) and os.path.getsize(p) > 0)]
    if missing:
        return Verdict(False, "OUTPUT_MISSING", None, f"출력 {', '.join(missing)}이(가) 만들어지지 않았습니다", exit_code=rc_, report=report)
    v = Verdict(True, exit_code=rc_, report=report)
    if rc_ != 0:
        v.warnings.append(("EXIT_NONZERO_IGNORED", f"종료코드 {rc_}였지만 보고·출력이 정상이라 성공으로 처리했습니다"))
    return v


def parse_result_line(line: str) -> tuple[str, str | None] | None:
    """`PAICAD RESULT <status> <code|-> <보고 파일 이름>` → (status, code|None). 아니면 None."""
    parts = line.strip().split()
    if len(parts) >= 4 and parts[0] == "PAICAD" and parts[1] == "RESULT":
        return parts[2], (None if parts[3] == "-" else parts[3])
    return None
