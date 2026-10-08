from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .. import schemas as S
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, request_id
from ..services import jobs as svc

router = APIRouter(tags=["queue"])


@router.get("/queue", response_model=S.QueueResponse)
def queue(request: Request, _p: Principal = Depends(get_principal)) -> dict:
    return svc.queue_view(get_ctx(request))


@router.post("/queue/{job_id}/move", response_model=S.QueueResponse, responses={409: {"model": S.ErrorResponse}})
def move(job_id: str, body: S.MoveRequest, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.move_job(get_ctx(request), principal, job_id, body.position, request_id(request), client_ip(request))
