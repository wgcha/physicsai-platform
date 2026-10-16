"""④ 컨투어 캡처 step(phase3 §15 S10). HyperView 배치(`commands.contour_capture`)로 방향별 PNG·애니메이션 동영상.

- (PREDICT, CONTOUR_CAPTURE): 예측 체인 맨 끝, cwd `P/RESULT/media/`. **실패는 경고(CAPTURE_FAILED)만** — 예측 작업은 성공 유지.
- (CONTOUR_RECAPTURE, CONTOUR_CAPTURE): 성공한 예측의 h3d로 다시 캡처(LIGHT 레인), cwd `P/RESULT/media_recapture/<작업 id>/`.
  이미지가 하나도 없으면 작업 실패(CAPTURE_FAILED).
- 판정 = 방향별 `<view>.png` 존재·크기>0(동영상 `<view>.<ext>`는 선택), `capture_result.txt`는 오류 문구용.
- `capture.timeout_s`를 넘기면 이 step이 프로세스 트리를 끝낸다(플랫폼 공통 실행기에는 시간 한도가 없다 — platform.md §8.4).
"""

from __future__ import annotations

import os
import time
from typing import Any

from physicsai_core.config.schema_capture import capture_missing, effective_capture_tcl
from physicsai_core.db.repositories import artifacts as artifacts_repo
from physicsai_core.db.repositories import contour_media as media_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.errors import DomainError, StepFailure
from physicsai_core.fileutil import copy_file, sha256_file, write_text
from physicsai_core.stage4_predict import contour_capture as cc

from ...limiter.base import LimiterError
from ...signals import StepSkipped
from .predict_inputs import predict_dir

_CATCH = (StepFailure, DomainError, LimiterError, OSError)


# ---- 설정·표시 ---------------------------------------------------------------------------------


def not_configured(ctx: Any) -> str | None:
    """기능 꺼짐·미구성 사유(없으면 None). 실행 파일 없음은 실행 단계에서 EXECUTABLE_MISSING."""
    s = ctx.settings
    if not s.capture.enabled:
        return "컨투어 캡처 꺼짐(capture.enabled)"
    if s.commands.contour_capture is None:
        return "컨투어 캡처 미구성(commands.contour_capture)"
    return None


def _batch_display(conn: Any, job: dict[str, Any]) -> dict[str, Any] | None:
    """일괄 예측 하위 PREDICT → 배치(처음 생성 작업) params.display(배치 단위 범례 등)."""
    ref = pb_repo.batch_run_ref(job)
    return media_repo.batch_display(conn, ref[0]) if ref else None


def display_for(ctx: Any, predict_job: dict[str, Any], *extra: dict[str, Any] | None) -> tuple[dict[str, Any], str]:
    """config → 응답 정의 → 템플릿 display → 배치 display → 예측 params display → extra(재캡처)."""
    psid = (predict_job.get("params") or {}).get("param_set_id")
    with ctx.ex.engine.connect() as conn:
        ps = ps_repo.get(conn, psid) if psid else None
        batch = _batch_display(conn, predict_job)
    return cc.resolve_display(ctx.settings.capture, ps, batch, (predict_job.get("params") or {}).get("display"), *extra)


# ---- 실행·판정 ---------------------------------------------------------------------------------


def _register(ctx: Any, kind: str, path: str, ctype: str, view: str) -> str:
    size = os.path.getsize(path)
    sha = sha256_file(path, checkpoint=ctx.checkpoint)
    ctx.add_output(path)
    return ctx.ex.db(lambda c: artifacts_repo.insert(
        c, study_id=ctx.study["id"], job_id=ctx.ex.job_id, kind=kind, rel_path=ctx.rel(path), size=size, sha256=sha,
        content_type=ctype, meta={"view": view}))


def _timeout_hook(ctx: Any, media_dir: str, views: list[str], state: dict[str, Any]) -> Any:
    limit = ctx.settings.capture.timeout_s
    start = time.monotonic()

    def hook() -> tuple[float | None, str | None] | None:
        if limit and not state["timed_out"] and time.monotonic() - start > limit:
            state["timed_out"] = True
            ctx.log(f"[TIMEOUT] 컨투어 캡처가 {limit:g}초를 넘어 프로세스를 종료합니다(capture.timeout_s)")
            with ctx.ex._proc_lock:
                proc = ctx.ex.current_proc
            if proc is not None:
                ctx.ex.limiter.terminate(proc)
        done = sum(1 for v in views if os.path.isfile(os.path.join(media_dir, f"{v}.png")))
        return (done / len(views) * 100.0, f"컨투어 캡처 {done}/{len(views)} 방향")

    return hook


def run_capture(ctx: Any, *, h3d: str, media_dir: str, display: dict[str, Any], views: list[str]) -> dict[str, Any]:
    """캡처 1회 → {media, failed:[{view, reason}], message}. 설정·실행 오류는 StepFailure(호출자가 경고/실패로)."""
    s = ctx.settings
    missing = capture_missing(s)
    if "resources.contour_capture_tcl" in missing:
        raise StepFailure("RESOURCE_MISSING", f"캡처 TCL이 없습니다: {effective_capture_tcl(s) or 'resources.contour_capture_tcl'}")
    if not os.path.isfile(h3d):
        raise StepFailure("INPUT_MISSING", f"예측 결과 h3d가 없습니다: {os.path.basename(h3d)}")
    ctx.backup([media_dir])
    os.makedirs(media_dir, exist_ok=True)
    tcl = os.path.join(media_dir, cc.SCRIPT_NAME)
    copy_file(effective_capture_tcl(s), tcl, checkpoint=ctx.checkpoint)
    save_video, ext = bool(s.capture.video), s.capture.video_ext
    write_text(os.path.join(media_dir, cc.SETTINGS_NAME), cc.settings_text(
        h3d_path=h3d, out_dir=media_dir, display=display, views=views, save_video=save_video, video_ext=ext,
        use_last=s.capture.use_last))
    state = {"timed_out": False}
    rc = ctx.run_local("contour_capture", {"capture_tcl": tcl}, cwd=media_dir, allow_nonzero_exit=True,
                       check_log_errors=False, poll_hook=_timeout_hook(ctx, media_dir, views, state))
    manifest_path = os.path.join(media_dir, cc.RESULT_NAME)
    manifest = {"status": None, "message": None, "views": {}}
    if os.path.isfile(manifest_path):
        with open(manifest_path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        manifest = cc.parse_result(text)
        ctx.log("[capture_result.txt]\n" + text.rstrip())
    media: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    vtype = cc.VIDEO_CONTENT_TYPES[ext]
    for v in views:
        png = os.path.join(media_dir, f"{v}.png")
        info = manifest["views"].get(v) or {}
        if not (os.path.isfile(png) and os.path.getsize(png) > 0):
            reason = info.get("error") or manifest["message"] or manifest["status"] or (
                "시간 초과" if state["timed_out"] else f"이미지가 만들어지지 않았습니다(종료코드 {rc})")
            failed.append({"view": v, "reason": str(reason)[:200]})
            continue
        if os.path.getsize(png) > s.ui.max_artifact_bytes:
            failed.append({"view": v, "reason": "이미지가 표시 상한(ui.max_artifact_bytes)을 넘습니다"})
            continue
        img = _register(ctx, "CONTOUR_IMAGE", png, cc.IMAGE_CONTENT_TYPE, v)
        vid = None
        vp = os.path.join(media_dir, f"{v}.{ext}")
        if save_video and os.path.isfile(vp) and os.path.getsize(vp) > 0:
            if os.path.getsize(vp) > s.capture.max_video_bytes:
                ctx.add_warning("CAPTURE_VIDEO_TOO_LARGE",
                                f"{v} 동영상이 상한(capture.max_video_bytes)을 넘어 등록하지 않았습니다: {os.path.getsize(vp)} B")
            else:
                vid = _register(ctx, "CONTOUR_VIDEO", vp, vtype, v)
        media.append({"view": v, "image_artifact_id": img, "video_artifact_id": vid})
    msg = None
    if state["timed_out"]:
        msg = f"시간 초과(capture.timeout_s = {s.capture.timeout_s:g}초)"
    elif failed:
        msg = "; ".join(f"{f['view']}: {f['reason']}" for f in failed)[:400]
    return {"media": media, "failed": failed, "message": msg, "rc": rc}


def _summary(out: dict[str, Any] | None, *, status: str, display: dict[str, Any] | None, source: str | None,
             views: list[str], media_dir: str | None, ctx: Any, message: str | None = None) -> dict[str, Any]:
    return {
        "status": status, "views": views, "display": display, "field_source": source,
        "video": bool(ctx.settings.capture.video), "video_ext": ctx.settings.capture.video_ext,
        "dir_rel": ctx.rel(media_dir) if media_dir and os.path.isdir(media_dir) else None,
        "message": message if message is not None else (out or {}).get("message"),
        "failed_views": [f["view"] for f in (out or {}).get("failed", [])],
    }


def _status(out: dict[str, Any]) -> str:
    return "OK" if not out["failed"] else ("PARTIAL" if out["media"] else "FAILED")


# ---- 핸들러 ------------------------------------------------------------------------------------


def predict_capture(ctx: Any) -> None:
    """(PREDICT, CONTOUR_CAPTURE): 실패해도 경고만(예측 성공 유지)."""
    reason = not_configured(ctx)
    if reason:
        ctx.patch_result({"media": [], "capture": {"status": "SKIPPED", "message": reason}})
        raise StepSkipped(reason)
    display, source = display_for(ctx, ctx.job)
    views = list(display["views"])
    media_dir = os.path.join(predict_dir(ctx), *cc.MEDIA_DIR_REL.split("/"))
    try:
        pred_rel = ctx.result().get("pred_h3d_rel")
        if not pred_rel:
            raise StepFailure("INPUT_MISSING", "예측 결과 h3d 경로가 없습니다")
        out = run_capture(ctx, h3d=ctx.abs(pred_rel), media_dir=media_dir, display=display, views=views)
    except _CATCH as exc:
        msg = getattr(exc, "message", None) or str(exc)
        ctx.log(f"[CAPTURE_FAILED] {msg}")
        ctx.add_warning("CAPTURE_FAILED", f"컨투어 캡처 실패(예측은 성공): {msg}"[:300])
        ctx.patch_result({"media": [], "capture": _summary(None, status="FAILED", display=display, source=source, views=views,
                                                             media_dir=media_dir, ctx=ctx, message=msg[:400])})
        return
    status = _status(out)
    if out["failed"]:
        ctx.add_warning("CAPTURE_FAILED", (f"컨투어 캡처 실패 {len(out['failed'])}/{len(views)} 방향(예측은 성공): "
                                           f"{out['message']}")[:300])
    ctx.patch_result({"media": out["media"], "capture": _summary(out, status=status, display=display, source=source,
                                                                  views=views, media_dir=media_dir, ctx=ctx)})


def recapture(ctx: Any) -> None:
    """(CONTOUR_RECAPTURE, CONTOUR_CAPTURE): params {source_job_id, views?, display?}. 이미지 0개면 작업 실패."""
    reason = not_configured(ctx)
    if reason:
        raise StepFailure("TEMPLATE_NOT_CONFIGURED", reason)
    with ctx.ex.engine.connect() as conn:
        src = jobs_repo.get_job(conn, ctx.params["source_job_id"])
        if src is None or src["study_id"] != ctx.study["id"] or src["job_type"] != "PREDICT":
            raise StepFailure("INPUT_INVALID", "원래 예측 작업을 찾을 수 없습니다")
        root_id = jobs_repo.root_job_id(conn, src)
    pred_rel = (src.get("result") or {}).get("pred_h3d_rel")
    if not pred_rel:
        raise StepFailure("INPUT_MISSING", "원래 예측 작업에 결과 h3d가 없습니다")
    display, source = display_for(ctx, src, ctx.params.get("display"))
    views = list(ctx.params.get("views") or display["views"])
    display["views"] = views
    media_dir = os.path.join(ctx.abs(f"04_predict/{root_id}"), *cc.RECAPTURE_DIR_REL.split("/"), ctx.workspace_id)
    out = run_capture(ctx, h3d=ctx.abs(pred_rel), media_dir=media_dir, display=display, views=views)
    status = _status(out)
    ctx.patch_result({"source_job_id": src["id"], "media": out["media"],
                      "capture": _summary(out, status=status, display=display, source=source, views=views,
                                          media_dir=media_dir, ctx=ctx)})
    if not out["media"]:
        raise StepFailure("CAPTURE_FAILED", f"컨투어 캡처 실패: {out['message'] or '이미지 없음'}")
    if out["failed"]:
        ctx.add_warning("CAPTURE_FAILED", f"컨투어 캡처 실패 {len(out['failed'])}/{len(views)} 방향: {out['message']}"[:300])


HANDLERS = {
    ("PREDICT", "CONTOUR_CAPTURE"): predict_capture,
    ("CONTOUR_RECAPTURE", "CONTOUR_CAPTURE"): recapture,
}
