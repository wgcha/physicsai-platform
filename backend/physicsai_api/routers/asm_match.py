"""조립 매칭 API(asm-match.md §6.3): 바디 ↔ 조립 component 매칭 표 — 생성·조회·행 저장·검사·확정. 검사 GLB는 `/artifacts/{id}/media`."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse

from .. import schemas as S
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, request_id
from ..schemas import mcp as M
from ..services import asm_match_api as svc

router = APIRouter(tags=["asm-match"])
MATCH_ID = "조립 매칭 id(asm_match_create 응답의 match_id)"
STUDY_ID = "Study id(list_studies)"


@router.post("/studies/{study_id}/asm-matches", response_model=S.AsmMatchCreated, status_code=202, summary="조립 매칭 시작",
             responses=M.errors(e403="PERMISSION_DENIED", e404="NOT_FOUND",
                                e409="PREREQUISITE_MISSING(① Native 추출 없음, missing GEOM_FEATURES) · TEMPLATE_NOT_CONFIGURED · STUDY_JOB_BUSY · STUDY_ARCHIVED",
                                e422="PATH_OUTSIDE_ROOT · PATH_UNSAFE · PATH_NOT_FOUND · INPUT_INVALID · ASM_MATCH_UNSUPPORTED(쉘 판금 세트)"),
             openapi_extra=M.xmcp_tool("asm_match_create", "run", "Start assembly matching: scan the assembly include tree for components (job ASM_MATCH)",
                                       "조립 매칭 시작: 조립 폴더 include 트리의 component 목록 수집(작업 ASM_MATCH)"))
def create_asm_match(body: S.AsmMatchCreate, request: Request, study_id: str = Path(max_length=64, description=STUDY_ID),
                     principal: Principal = Depends(get_principal)) -> JSONResponse:
    """Native 솔리드의 STEP 바디와 조립(Radioss) component를 매칭하기 위한 묶음을 만들고 component 목록 수집 작업(ASM_MATCH, mode parts)을
    대기열에 올린다. renum.csv·기준본 파일은 필요 없다. 응답의 job_id는 job_status로, 끝나면 asm_match_get으로 목록·추천을 본다.
    부작용: 대기열 작업 1개·Study 안 asm_match 폴더 생성."""
    out = svc.create(get_ctx(request), principal, study_id, body, request_id(request), client_ip(request))
    return JSONResponse(S.AsmMatchCreated.model_validate(out).model_dump(mode="json"), status_code=202)


@router.get("/studies/{study_id}/asm-matches", response_model=S.AsmMatchList, summary="조립 매칭 목록",
            responses=M.errors(e404="NOT_FOUND"),
            openapi_extra=M.xmcp_tool("asm_match_list", "read", "List assembly matches of a study, newest first (filter by source; latest=true for one)",
                                      "Study의 조립 매칭 목록(최신순, source로 거르고 latest=true면 1개)"))
def list_asm_matches(request: Request, study_id: str = Path(max_length=64, description=STUDY_ID),
                     source: Literal["train", "path"] | None = Query(default=None, description="STEP 출처로 거르기 — train(①-1 추출 결과) | path(④ 새 템플릿 STEP 경로)"),
                     latest: bool = Query(default=False, description="true면 가장 최근 1개만"),
                     limit: int = Query(default=20, ge=1, le=100, description="최대 개수 [개](1~100, 기본 20)"),
                     _p: Principal = Depends(get_principal)) -> dict:
    """Study 안 조립 매칭(match.json) 목록을 최신순으로 돌려준다. 항목은 asm_match_get과 같은 모양. 화면이 ①의 마지막 매칭을 다시 찾을 때
    source=train&latest=true. 부작용 없음."""
    return svc.list_matches(get_ctx(request), study_id, source, latest, limit)


@router.get("/asm-matches/{match_id}", response_model=S.AsmMatch, summary="조립 매칭 조회",
            responses=M.errors(e404="NOT_FOUND"),
            openapi_extra=M.xmcp_tool("asm_match_get", "read", "Get an assembly match: state, bodies, components, recommendations, rows, last check",
                                      "조립 매칭 조회: 상태·바디·component 목록·추천·행·마지막 검사"))
def get_asm_match(request: Request, match_id: str = Path(max_length=64, description=MATCH_ID),
                  _p: Principal = Depends(get_principal)) -> dict:
    """상태(SCANNING·DRAFT·CHECKING·CHECKED·CONFIRMED·FAILED·STALE)와 바디·component(PART) 목록·추천·저장된 행·마지막 검사 결과
    (행별 판정·거리·공유 노드·원점/단위 진단)를 돌려준다. 진행 중이면 수 초 간격으로 다시 조회. 부작용 없음."""
    return svc.get(get_ctx(request), match_id)


@router.put("/asm-matches/{match_id}/rows", response_model=S.AsmMatch, summary="조립 매칭 행 저장",
            responses=M.errors(e403="PERMISSION_DENIED", e404="NOT_FOUND",
                               e409="ASM_MATCH_CONFIRMED · ASM_MATCH_BUSY · ASM_MATCH_STALE · PREREQUISITE_MISSING(component 목록 없음)",
                               e422="ASM_ROW_INVALID(problems[].code: UNKNOWN_BODY·BODY_DUPLICATE·UNKNOWN_PID·PID_DUPLICATE·NOT_SOLID·BODY_MISSING·USE_PARAM·ROWS_EMPTY)"),
            openapi_extra=M.xmcp_tool("asm_match_set_rows", "run", "Save the body-to-component rows of an assembly match (draft; invalidates the last check)",
                                      "조립 매칭 행 저장(초안, 마지막 검사는 무효가 됨)"))
def put_asm_match_rows(body: S.AsmRowsPut, request: Request, match_id: str = Path(max_length=64, description=MATCH_ID),
                       principal: Principal = Depends(get_principal)) -> dict:
    """바디마다 component(PART id) 1개 이상을 정하거나 매칭 안 함(excluded_bodies)으로 둔다(모든 바디가 둘 중 하나, 매칭 행 1개 이상).
    pid는 한 행에만, TETRA4만 가진 component만. 확정된 매칭은 바꿀 수 없다(새로 만들기). 부작용: match.json 갱신."""
    return svc.set_rows(get_ctx(request), principal, match_id, body, request_id(request), client_ip(request))


@router.post("/asm-matches/{match_id}/check", response_model=S.AsmCheckStarted, status_code=202, summary="조립 매칭 검사",
             responses=M.errors(e403="PERMISSION_DENIED", e404="NOT_FOUND",
                                e409="ASM_ROWS_INCOMPLETE · ASM_MATCH_CONFIRMED · ASM_MATCH_BUSY · ASM_MATCH_STALE · STUDY_JOB_BUSY · TEMPLATE_NOT_CONFIGURED"),
             openapi_extra=M.xmcp_tool("asm_match_check", "run", "Optional advanced check of the saved rows: outer nodes vs CAD faces, shared nodes (job ASM_MATCH, no time limit, cancellable)",
                                       "저장한 행 선택 검사(고급): component 외곽 노드 ↔ CAD 경계면 거리·공유 노드(작업 ASM_MATCH, 시간 제한 없음, 취소 가능)"))
def check_asm_match(request: Request, match_id: str = Path(max_length=64, description=MATCH_ID),
                    principal: Principal = Depends(get_principal)) -> JSONResponse:
    """저장된 행으로 검사 작업(ASM_MATCH, mode check)을 시작한다. 검사는 선택(고급)이며 확정(confirm)의 조건이 아니다.
    대형 모델은 수십 분 걸릴 수 있어 시간 제한이 없고(`asm_match.check_timeout_s` null) 작업 취소로 중단한다. 끝나면 asm_match_get의 check에서 행별 판정을 본다.
    원점·단위가 다르면 FAIL(suggest)이며 자동 보정은 없다. 부작용: 대기열 작업 1개·check/<seq> 폴더."""
    out = svc.check(get_ctx(request), principal, match_id, request_id(request), client_ip(request))
    return JSONResponse(S.AsmCheckStarted.model_validate(out).model_dump(mode="json"), status_code=202)


@router.post("/asm-matches/{match_id}/cancel", response_model=S.AsmMatch, status_code=202, summary="조립 매칭 작업 취소",
             responses=M.errors(e403="PERMISSION_DENIED", e404="NOT_FOUND", e409="JOB_TERMINAL(진행 중인 작업 없음)"),
             openapi_extra=M.xmcp_exclude("작업 취소는 cancel_job(같은 토큰이 만든 작업)을 쓴다 — 이 경로는 화면 [취소]용(power)"))
def cancel_asm_match(request: Request, match_id: str = Path(max_length=64, description=MATCH_ID),
                     principal: Principal = Depends(get_principal)) -> JSONResponse:
    """진행 중(대기·실행)인 목록 읽기·검사 작업을 취소한다(power). 검사에는 시간 제한이 없으므로(AM-C3) 사용자가 직접 멈추는 경로다.
    실행 중이면 워커가 프로세스를 종료하며 작업이 CANCELED가 되고, 매칭 표(행)는 그대로 남는다. 진행 중 작업이 없으면 409 JOB_TERMINAL.
    부작용: 작업 취소 요청 1건."""
    out = svc.cancel(get_ctx(request), principal, match_id, request_id(request), client_ip(request))
    return JSONResponse(S.AsmMatch.model_validate(out).model_dump(mode="json"), status_code=202)


@router.post("/asm-matches/{match_id}/confirm", response_model=S.AsmMatch, summary="조립 매칭 확정(저장)",
             responses=M.errors(e403="PERMISSION_DENIED", e404="NOT_FOUND",
                                e409="ASM_ROWS_INCOMPLETE · ASM_MATCH_STALE(조립 트리·STEP·피처 변경) · ASM_MATCH_BUSY",
                                e422="ASM_ROW_INVALID"),
             openapi_extra=M.xmcp_tool("asm_match_confirm", "run", "Confirm (save) the assembly match rows; the boundary check is optional (failed or outdated check only adds warnings)",
                                       "조립 매칭 확정(저장) — 경계 검사는 선택(불합격·낡음은 warnings에만 남음), DOE·템플릿 등록이 사용"))
def confirm_asm_match(request: Request, match_id: str = Path(max_length=64, description=MATCH_ID),
                      principal: Principal = Depends(get_principal)) -> dict:
    """행이 완전하고(모든 바디가 component 또는 매칭 안 함, 매칭 행 1개 이상) 조립·STEP·피처가 그대로면 확정본(asm_match.json)을 만든다.
    경계 검사는 필수가 아니다 — 검사를 실행했는데 불합격이거나 현재 행과 다르면 확정은 되고 응답 warnings에 ASM_CHECK_FAILED_WARN·
    ASM_CHECK_STALE_WARN이 남는다. 확정본은 바꿀 수 없고 DOE·세트가 자기 폴더로 복사해 쓴다. 이미 확정이면 그대로 돌려준다(멱등).
    부작용: asm_match.json 작성."""
    return svc.confirm(get_ctx(request), principal, match_id, request_id(request), client_ip(request))
