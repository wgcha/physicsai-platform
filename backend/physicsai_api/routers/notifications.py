from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from .. import schemas as S
from ..auth import Principal
from ..deps import get_ctx, get_principal
from ..services import system

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=S.NotificationList)
def list_notifications(request: Request, response: Response, after_seq: int | None = Query(default=None, ge=0),
                       limit: int | None = Query(default=None, ge=1, le=200), cursor: str | None = None,
                       principal: Principal = Depends(get_principal)) -> dict:
    body, nxt = system.list_notifications(get_ctx(request), principal, after_seq, limit, cursor)
    if nxt:
        response.headers["X-Next-Cursor"] = nxt
    return body


@router.get("/notifications/unread-count", response_model=S.UnreadCount)
def unread(request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return system.unread(get_ctx(request), principal)


@router.post("/notifications/read", response_model=S.ReadResponse)
def read(body: S.ReadRequest, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return system.mark_read(get_ctx(request), principal, body.seqs, body.all)
