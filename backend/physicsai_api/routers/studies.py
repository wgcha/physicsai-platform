from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from .. import schemas as S
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, get_token, request_id
from ..schemas import mcp as M
from ..services import path_inspect as inspect_svc
from ..services import studies as svc

router = APIRouter(tags=["studies"])
ERR = {404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse}, 422: {"model": S.ErrorResponse}}


@router.get("/studies", response_model=list[S.Study], summary="Study 목록", responses=M.errors(e422="INVALID_PARAMS"),
            openapi_extra=M.xmcp_tool("list_studies", "read", "List studies (filter by project or status)",
                                      "Study 목록(프로젝트·상태로 거르기)"))
def list_studies(request: Request, response: Response,
                 project_id: str | None = Query(default=None, description="대시보드 프로젝트 id로 거르기"),
                 status: str | None = Query(default=None, description="ACTIVE | ARCHIVED"),
                 limit: int | None = Query(default=None, ge=1, le=200, description="최대 개수[개](1~200, 기본 50)"),
                 cursor: str | None = Query(default=None, description="다음 페이지 커서(응답 헤더 X-Next-Cursor)"),
                 principal: Principal = Depends(get_principal)) -> list:
    """Study 목록(최신순). study_id를 찾을 때 먼저 호출한다. 다음 페이지가 있으면 헤더 X-Next-Cursor. 부작용 없음."""
    items, nxt = svc.list_studies(get_ctx(request), principal, project_id, status, limit, cursor)
    if nxt:
        response.headers["X-Next-Cursor"] = nxt
    return items


@router.post("/studies", response_model=S.Study, status_code=201, responses=ERR)
def create_study(body: S.StudyCreate, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.create_study(get_ctx(request), principal, get_token(request), body, request_id(request), client_ip(request))


@router.get("/studies/{study_id}", response_model=S.StudyDetail, responses=ERR)
def get_study(study_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.get_study(get_ctx(request), principal, study_id)


@router.patch("/studies/{study_id}", response_model=S.Study, responses=ERR)
def patch_study(study_id: str, body: S.StudyPatch, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.patch_study(get_ctx(request), principal, study_id, body, request_id(request), client_ip(request))


@router.post("/studies/{study_id}/archive", response_model=S.Study, responses=ERR)
def archive_study(study_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.archive_study(get_ctx(request), principal, study_id, request_id(request), client_ip(request))


@router.post("/studies/{study_id}/unarchive", response_model=S.Study, responses=ERR)
def unarchive_study(study_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.unarchive_study(get_ctx(request), principal, study_id, request_id(request), client_ip(request))


@router.post("/studies/{study_id}/paths/inspect", response_model=S.PathInspectResponse, responses=ERR)
def inspect(study_id: str, body: S.PathInspectRequest, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return inspect_svc.inspect_path(get_ctx(request), principal, study_id, body)
