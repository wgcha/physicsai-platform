"""④ 컨투어 캡처 API(phase3 §15 S10): 방향 목록·이미지/동영상(Range)·재캡처·템플릿 표시 설정."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response, StreamingResponse

from .. import schemas as S
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, request_id
from ..services import contour_capture as svc

router = APIRouter(tags=["contour-capture"])
ERR = {403: {"model": S.ErrorResponse}, 404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse},
       422: {"model": S.ErrorResponse}}
MEDIA_CONTENT = {"image/png": {}, "video/mp4": {}, "video/x-msvideo": {}, "image/gif": {}, "model/gltf-binary": {},
                 "application/octet-stream": {}}


@router.get("/jobs/{job_id}/media", response_model=S.JobMedia, responses=ERR)
def job_media(job_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """예측 작업의 방향별 컨투어 이미지·동영상(재캡처 결과는 방향별로 덮어씀)."""
    return svc.job_media(get_ctx(request), principal, job_id)


@router.get(
    "/artifacts/{artifact_id}/media",
    response_class=StreamingResponse,
    responses={**ERR, 410: {"model": S.ErrorResponse}, 413: {"model": S.ErrorResponse}, 200: {"content": MEDIA_CONTENT},
               206: {"content": MEDIA_CONTENT},
               416: {"description": "Range 범위 밖"}},
)
def media_content(artifact_id: str, request: Request, download: bool = Query(default=False),
                  _p: Principal = Depends(get_principal)) -> Response:
    """컨투어 이미지·동영상·형상/컨투어 3D GLB·프레임 파일. HTTP Range(단일 범위) → 206 + Content-Range, 범위 밖 416.
    정리된 서버측 캐시(미리보기·3D 컨투어)는 410 ARTIFACT_EXPIRED."""
    f = svc.media_file(get_ctx(request), artifact_id)
    size = f["size"]
    disp = "attachment" if download else "inline"
    headers = {"Accept-Ranges": "bytes", "ETag": f["etag"], "Cache-Control": "private, no-cache, no-transform",  # C3F-7: 프록시가 Range 응답을 변환·압축하지 않게
               "Content-Disposition": f'{disp}; filename="{f["filename"]}"', "X-Content-Type-Options": "nosniff"}
    rng = svc.parse_range(request.headers.get("range"), size)
    if rng == "unsatisfiable":
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
    if rng is None:
        start, end, status = 0, size - 1, 200
    else:
        start, end = rng  # type: ignore[misc]
        status = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(end - start + 1 if size else 0)
    body = svc.read_range(f["path"], start, end) if size else iter(())
    return StreamingResponse(body, status_code=status, media_type=f["content_type"], headers=headers)


@router.post("/jobs/{job_id}/capture", response_model=S.Job, status_code=201, responses=ERR)
def recapture(job_id: str, request: Request, body: S.RecaptureRequest | None = None,
              principal: Principal = Depends(get_principal)) -> dict:
    """재캡처(power): 성공한 예측의 h3d로 방향·표시 설정을 바꿔 다시 캡처하는 CONTOUR_RECAPTURE 작업(LIGHT)."""
    return svc.recapture(get_ctx(request), principal, job_id, body or S.RecaptureRequest(), request_id(request),
                         client_ip(request))


@router.put("/param-sets/{ps_id}/display", response_model=S.ParamSet, responses=ERR)
def put_display(ps_id: str, body: S.ParamSetDisplayUpdate, request: Request,
                principal: Principal = Depends(get_principal)) -> dict:
    """템플릿 컨투어 표시 설정(power). null = 지움(응답 정의 첫 항목·config 기본을 따름)."""
    return svc.put_display(get_ctx(request), principal, ps_id, body, request_id(request), client_ip(request))
