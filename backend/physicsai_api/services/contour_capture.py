"""④ 컨투어 캡처 API(phase3 §15 S10): 방향 목록·이미지/동영상 제공(Range)·재캡처·템플릿 표시 설정.

권한: 조회·파일 = 로그인, 재캡처·표시 설정 = power 이상. 파일은 산출물(artifacts) 행으로 찾고 Study 폴더 안 경로만 연다.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from typing import Any

from physicsai_core.db.repositories import contour_media as media_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.features import contour_capture_missing
from physicsai_core.paths import resolve_in_study
from physicsai_core.stage4_predict import contour_capture as cc

from ..auth import Principal
from ..context import AppContext
from . import jobs as jobs_svc
from .common import MOVED_HINT, audit, param_set_out, require_job, require_power, study_root

API_PREFIX = "/physicsai/api"  # main.API_PREFIX와 같은 값(브라우저 <video src>가 쓰는 절대 경로)
CHUNK = 1024 * 1024
MEDIA_TYPES = frozenset({cc.IMAGE_CONTENT_TYPE, *cc.VIDEO_CONTENT_TYPES.values()})
_RANGE = re.compile(r"bytes=([0-9]*)-([0-9]*)")  # fullmatch 전용, ASCII 숫자만(D3-53)


# ---- 목록 ----------------------------------------------------------------------------------------


def _playable(a: dict[str, Any]) -> bool | None:
    """S16 §21.4.3: meta.playable 우선, 없으면 avi = false·gif·png = true·그 밖(mp4 미확인) = null."""
    meta = a.get("meta") or {}
    if isinstance(meta.get("playable"), bool):
        return meta["playable"]
    ct = a["content_type"]
    if ct == cc.VIDEO_CONTENT_TYPES["avi"]:
        return False
    if ct in (cc.VIDEO_CONTENT_TYPES["gif"], cc.IMAGE_CONTENT_TYPE):
        return True
    return None


def _file_out(a: dict[str, Any]) -> dict[str, Any]:
    url = f"{API_PREFIX}/artifacts/{a['id']}/media"
    meta = a.get("meta") or {}
    return {"artifact_id": a["id"], "content_type": a["content_type"], "size": a["size"], "url": url,
            "download_url": url + "?download=true", "playable": _playable(a),
            "codec": meta.get("codec") if isinstance(meta.get("codec"), str) else None,
            "transcoded": bool(meta.get("transcoded"))}


def file_out(a: dict[str, Any]) -> dict[str, Any]:
    """MediaFile 모양(V2 FEM 검증 컨투어 공용)."""
    return _file_out(a)


def capture_enabled(ctx: AppContext) -> bool:
    tmpl, res = contour_capture_missing(ctx.settings)
    return not tmpl and not res


def job_media(ctx: AppContext, principal: Principal, job_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        j = require_job(conn, job_id)
        if j["job_type"] != "PREDICT":
            raise DomainError("NOT_FOUND", "예측 작업이 아닙니다", status=404)
        s = studies_repo.require(conn, j["study_id"])
        eff = media_repo.effective_media(conn, j)
        ids = [x for m in eff["items"] for x in (m.get("image_artifact_id"), m.get("video_artifact_id"))]
        arts = media_repo.artifacts_by_ids(conn, ids)
    root = study_root(ctx, s)
    items = []
    for m in eff["items"]:
        img = arts.get(m["image_artifact_id"])
        if img is None or not os.path.isfile(resolve_in_study(root, img["rel_path"])):
            continue  # Study 정리로 옮겨졌거나 파일이 없어진 방향은 목록에서 뺀다
        vid = arts.get(m.get("video_artifact_id") or "")
        items.append({"view": m["view"], "label": cc.VIEW_LABELS.get(m["view"], m["view"]), "job_id": m["job_id"],
                      "image": _file_out(img), "video": _file_out(vid) if vid else None,
                      "video_error": m.get("video_error") if not vid else None})
    cap = eff["capture"] or {}
    enabled = capture_enabled(ctx)
    recap = eff["recapture"]
    return {
        "job_id": j["id"], "status": cap.get("status") or "NONE", "message": cap.get("message"),
        "display": cap.get("display"), "field_source": cap.get("field_source"), "video_ext": cap.get("video_ext"),
        "items": items, "recapture": recap, "capture_enabled": enabled,
        "can_recapture": (enabled and j["state"] == "SUCCEEDED" and principal.can_execute(s["project_id"])
                          and not (recap and recap["active"])),
    }


# ---- 파일(Range) ---------------------------------------------------------------------------------


def parse_range(header: str | None, size: int) -> tuple[int, int] | None | str:
    """HTTP Range(단일 바이트 범위) → (start, end 포함) | None(전체 200) | "unsatisfiable"(416).

    RFC 9110 §14.2: 문법상 잘못된 범위(`bytes=10-5`처럼 끝 < 시작, 숫자 아님·여러 범위·다른 단위)는 무시하고 전체 200.
    416은 만족할 수 없는 범위만 — 시작 ≥ 크기, 끝에서 0바이트(`bytes=-0`), 빈 파일."""
    if not header:
        return None
    m = _RANGE.fullmatch(header.strip().replace(" ", ""))
    if not m or (not m.group(1) and not m.group(2)):
        return None
    if not m.group(1):  # bytes=-N (끝에서 N바이트)
        n = int(m.group(2))
        if n == 0 or size == 0:
            return "unsatisfiable"
        return max(0, size - n), size - 1
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else None
    if end is not None and end < start:
        return None  # 문법상 잘못된 범위 → 무시(200 전체)
    if start >= size:
        return "unsatisfiable"
    return start, size - 1 if end is None else min(end, size - 1)


def media_file(ctx: AppContext, artifact_id: str) -> dict[str, Any]:
    """컨투어 이미지·동영상 산출물 → {path, content_type, size, filename, etag}. 크기 상한: 이미지 ui.max_artifact_bytes,
    동영상 capture.max_video_bytes(넘으면 413)."""
    with ctx.engine.connect() as conn:
        rows = media_repo.artifacts_by_ids(conn, [artifact_id])
        a = rows.get(artifact_id)
        if a is None or a["kind"] not in cc.MEDIA_KINDS:
            raise DomainError("NOT_FOUND", "컨투어 파일을 찾을 수 없습니다", status=404)
        s = studies_repo.require(conn, a["study_id"])
    if a["content_type"] not in MEDIA_TYPES:
        raise DomainError("NOT_FOUND", "내려받을 수 없는 형식입니다", status=404)
    path = resolve_in_study(study_root(ctx, s), a["rel_path"])
    if not os.path.isfile(path):
        raise DomainError("NOT_FOUND", f"컨투어 파일이 없습니다. {MOVED_HINT}", status=404)
    size = os.path.getsize(path)
    cap = ctx.settings.capture.max_video_bytes if a["kind"] == "CONTOUR_VIDEO" else ctx.settings.ui.max_artifact_bytes
    if size > cap:
        raise DomainError("ARTIFACT_TOO_LARGE", "파일이 제공 크기 상한을 넘습니다", status=413, size=size, limit=cap)
    view = (a.get("meta") or {}).get("view") or "media"
    ext = os.path.splitext(a["rel_path"])[1] or ""
    return {"path": path, "content_type": a["content_type"], "size": size, "etag": f'"{a["id"]}-{size}"',
            "filename": f"{(a['job_id'] or 'job')[:8]}_{view}{ext}"}


def read_range(path: str, start: int, end: int) -> Iterator[bytes]:
    with open(path, "rb") as fh:
        fh.seek(start)
        left = end - start + 1
        while left > 0:
            b = fh.read(min(CHUNK, left))
            if not b:
                break
            left -= len(b)
            yield b


# ---- 재캡처·표시 설정 -----------------------------------------------------------------------------------


def recapture(ctx: AppContext, principal: Principal, job_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        j = require_job(conn, job_id)
    raw: dict[str, Any] = {"source_job_id": j["id"]}
    if body.views:
        raw["views"] = list(body.views)
    if body.display is not None:
        raw["display"] = body.display.model_dump(exclude_none=True)
    return jobs_svc.create_job(ctx, principal, j["study_id"], "CONTOUR_RECAPTURE", raw, rid, ip)


def put_display(ctx: AppContext, principal: Principal, ps_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    disp = cc.clean_display(body.display.model_dump(exclude_none=True)) if body.display is not None else None
    with ctx.engine.begin() as conn:
        p = ps_repo.get(conn, ps_id)
        if p is None:
            raise DomainError("NOT_FOUND", "파라미터 세트를 찾을 수 없습니다", status=404)
        s = studies_repo.require(conn, p["study_id"])
        require_power(principal, s["project_id"])
        media_repo.set_param_set_display(conn, ps_id, disp)
        audit(conn, principal, "PARAM_SET_UPDATE", "param_set", ps_id, {"display": disp}, rid, ip)
        p = ps_repo.get(conn, ps_id)
    return param_set_out(p)
