"""HTML 결과 요약 보고서 API(upload-report.md §9.4): 서버가 요청 시 만들어 저장 없이 응답하는 단일 파일 HTML.

권한 = 로그인(Study 조회는 member 이상 공통 — 다른 GET과 같음). 외부 프로그램 실행 없음. 응답 헤더는 esl `html_report`와 같다(CSP·nosniff·no-store).
x-mcp exclude: 단일 HTML(최대 30 MiB)은 도구 결과 상한(64 KiB)·텍스트 모델에 맞지 않는다 — LLM은 같은 대상의 `get_summary`를 쓴다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from .. import schemas as S
from ..auth import Principal
from ..deps import get_ctx, get_principal
from ..schemas import mcp as M
from ..services import reports as svc

router = APIRouter(tags=["reports"])
ERR = {403: {"model": S.ErrorResponse}, 404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse}, 413: {"model": S.ErrorResponse},
       422: {"model": S.ErrorResponse}}
HTML_OK = {**ERR, 200: {"content": {"text/html": {}}, "description": "단일 파일 HTML(외부 자원 0)"}}
NO_TOOL = M.xmcp_exclude("HTML 파일 응답")


def _response(body: bytes, filename: str, download: bool) -> Response:
    return Response(content=body, media_type="text/html; charset=utf-8", headers=svc.response_headers(filename, download))


@router.get("/reports/analysis", response_class=Response, responses=HTML_OK, openapi_extra=NO_TOOL)
def report_analysis(request: Request, source: str = Query(max_length=16), id: str = Query(min_length=1, max_length=64),
                    compare_source: str | None = Query(default=None, max_length=16), compare_id: str | None = Query(default=None, max_length=64),
                    vars: list[str] | None = Query(default=None, max_length=100), resp: str | None = Query(default=None, max_length=400),
                    download: bool = Query(default=False), principal: Principal = Depends(get_principal)) -> Response:
    """⑤ 결과분석 보고서(`?source=batch|doe&id=` + 비교 `compare_source`·`compare_id`, 선택 변수 `vars`(반복·쉼표)·응답 `resp`). 영향도는 서버 numpy 재계산."""
    body, name = svc.build_analysis(get_ctx(request), principal, source=source, source_id=id, compare_source=compare_source,
                                    compare_id=compare_id, vars_=vars, resp=resp)
    return _response(body, name, download)


@router.get("/reports/{target}/{target_id}", response_class=Response, responses=HTML_OK, openapi_extra=NO_TOOL)
def report_by_target(target: str, target_id: str, request: Request, download: bool = Query(default=False),
                     principal: Principal = Depends(get_principal)) -> Response:
    """대상 보고서: target = `surrogate-opt`(⑥ 내장)·`optimization`(⑥ HyperStudy 레거시)·`equiv-check`(⑤ 등가성 판정). 그 밖은 404 REPORT_TARGET_UNKNOWN."""
    body, name = svc.build_by_id(get_ctx(request), principal, target, target_id)
    return _response(body, name, download)
