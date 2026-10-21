"""HTML 결과 요약 보고서 서비스(upload-report.md §9): 대상 분기·파일 이름·응답 헤더 — 원천 읽기는 `reports_*.py`.

요청 시 DB 값 + 기존 산출 파일만 읽어 만들고 저장하지 않는다(외부 프로그램 실행 없음 — V-SEC-3). 권한 = 로그인(Study 조회는 member 이상 공통).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

from physicsai_core import __version__
from physicsai_core.errors import DomainError
from physicsai_core.path_names import name_unsafe_chars
from physicsai_core.report_html import analysis as r_analysis
from physicsai_core.report_html import equiv as r_equiv
from physicsai_core.report_html import opt as r_opt
from physicsai_core.report_html.page import REPORT_CSP, Doc, limits_from, render

from ..auth import Principal
from ..context import AppContext
from . import reports_analysis, reports_equiv, reports_opt

TARGETS = ("analysis", "equiv-check", "surrogate-opt", "optimization")  # 구현된 대상(upload-report.md §9.1 1차)
ID_TARGETS = ("equiv-check", "surrogate-opt", "optimization")
NAME_MAX = 40
_BAD_NAME_CHARS = frozenset('/\\:*?')


def now() -> datetime:
    """서버 표준 시간대의 지금(시험이 바꿔 끼운다 — 결정성)."""
    return datetime.now().astimezone()


def study_name_part(title: str | None, fallback: str = "study") -> str:
    """파일 이름 속 Study 이름: `name_unsafe_chars` 문자·경로 구분자(`/ \\ : * ?`)를 `_`로, ≤ 40자, 앞뒤 점·공백 제거."""
    out = []
    for c in title or "":
        out.append("_" if (c in _BAD_NAME_CHARS or name_unsafe_chars(c)) else c)
    s = "".join(out)[:NAME_MAX].strip(". ")
    return s or fallback


def make_filename(study_title: str | None, target_key: str, target_id: str, at: datetime) -> str:
    """`PAI_<Study>_<target>_<id8>_<YYYYMMDD-HHMM>.html`."""
    return f"PAI_{study_name_part(study_title)}_{target_key}_{str(target_id)[:8]}_{at.strftime('%Y%m%d-%H%M')}.html"


def response_headers(filename: str, download: bool) -> dict[str, str]:
    h = {"Content-Security-Policy": REPORT_CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
         "Cache-Control": "no-store"}
    if download:  # RFC 5987 — 한글 파일명
        h["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename, safe='')}"
    return h


def unknown_target(target: str) -> DomainError:
    return DomainError("REPORT_TARGET_UNKNOWN", f"보고서를 만들 수 없는 대상입니다: {target}", status=404, targets=list(TARGETS))


def not_ready(what: str) -> DomainError:
    return DomainError("REPORT_NOT_READY", f"{what}이(가) 아직 끝나지 않았습니다 — 끝난 뒤 받으세요", status=409)


def _stamp(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


def build_by_id(ctx: AppContext, principal: Principal, target: str, target_id: str) -> tuple[bytes, str]:
    """`GET /reports/{target}/{target_id}`: surrogate-opt·optimization·equiv-check → (HTML 바이트, 파일 이름)."""
    if target not in ID_TARGETS:
        raise unknown_target(target)
    at = now()
    if target == "surrogate-opt":
        inp = reports_opt.surrogate_input(ctx, principal, target_id)
        fn = r_opt.surrogate_doc
    elif target == "optimization":
        inp = reports_opt.legacy_input(ctx, principal, target_id)
        fn = r_opt.legacy_doc
    else:
        inp = reports_equiv.equiv_input(ctx, principal, target_id)
        fn = r_equiv.equiv_doc
    return _render(ctx, fn, inp, target, target_id, at)


def build_analysis(ctx: AppContext, principal: Principal, *, source: str, source_id: str, compare_source: str | None,
                   compare_id: str | None, vars_: list[str] | None, resp: str | None) -> tuple[bytes, str]:
    """`GET /reports/analysis?source=&id=…`: ⑤ 결과 표 분석(영향도는 서버 numpy 재계산)."""
    at = now()
    inp = reports_analysis.analysis_input(ctx, principal, source, source_id, compare_source, compare_id, vars_, resp)
    return _render(ctx, r_analysis.analysis_doc, inp, f"analysis-{source}", source_id, at)


def _render(ctx: AppContext, fn: Any, inp: dict[str, Any], key: str, target_id: str, at: datetime) -> tuple[bytes, str]:
    inp = {**inp, "generated_by": inp.get("generated_by")}
    body = render(lambda c: _doc(fn, inp, c), limits_resolved(ctx), generated_at=_stamp(at), platform_version=__version__)
    return body, make_filename((inp.get("study") or {}).get("title") or (inp.get("study") or {}).get("folder_name"), key, target_id, at)


def _doc(fn: Any, inp: dict[str, Any], ctx_: Any) -> Doc:
    return fn(inp, ctx_)


def limits_resolved(ctx: AppContext) -> Any:
    """`report.*` 설정(없으면 코드 기본값 — 설정 클래스는 업로드 브랜치 소유)."""
    return limits_from(ctx.settings)
