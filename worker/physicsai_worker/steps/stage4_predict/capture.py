"""④ 컨투어 캡처 step(phase3 §15 S10). HyperView 배치(`commands.contour_capture`)로 방향별 PNG·애니메이션 동영상.

- (PREDICT, CONTOUR_CAPTURE): 예측 체인 맨 끝, cwd `P/RESULT/media/`. **실패는 경고(CAPTURE_FAILED)만** — 예측 작업은 성공 유지.
- (CONTOUR_RECAPTURE, CONTOUR_CAPTURE): 성공한 예측의 h3d로 다시 캡처(LIGHT 레인), cwd `P/RESULT/media_recapture/<작업 id>/`.
  이미지가 하나도 없으면 작업 실패(CAPTURE_FAILED).
- 일괄 예측 하위: 배치 params `capture{enabled, views?, video?}`를 따른다 — enabled false면 SKIPPED(D3-53).
- 판정 = 방향별 `<view>.png` 존재·크기>0(동영상 `<view>.<ext>`는 선택), `capture_result.txt`는 오류 문구용.
- `capture.timeout_s`를 넘기면 이 step이 프로세스 트리를 끝낸다(플랫폼 공통 실행기에는 시간 한도가 없다 — platform.md §8.4).
300줄 분할(R-B): 실행·판정(run_capture·영상 준비·제한 시간 훅)은 `capture_run`(여기서 재노출). 핸들러는 이 파일에서
`run_capture`를 조회한다(`capture.run_capture` monkeypatch 유지)."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.db.repositories import contour_media as media_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.errors import DomainError, StepFailure
from physicsai_core.stage4_predict import contour_capture as cc

from ...limiter.base import LimiterError
from ...signals import StepSkipped
from .predict_inputs import predict_dir
from .capture_run import _video_missing_reason, run_capture, _summary, _status  # noqa: F401 - 기존 경로 재노출

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


def batch_capture_for(ctx: Any, job: dict[str, Any]) -> dict[str, Any]:
    """일괄 예측 하위 PREDICT → 배치 params.capture `{enabled, views?, video?}`(D3-53). 하위가 아니거나 없으면 {}."""
    ref = pb_repo.batch_run_ref(job)
    if not ref:
        return {}
    with ctx.ex.engine.connect() as conn:
        return media_repo.batch_capture(conn, ref[0]) or {}


def display_for(ctx: Any, predict_job: dict[str, Any], *extra: dict[str, Any] | None) -> tuple[dict[str, Any], str]:
    """config → 응답 정의 → 템플릿 display → 배치 display → 예측 params display → extra(재캡처)."""
    psid = (predict_job.get("params") or {}).get("param_set_id")
    with ctx.ex.engine.connect() as conn:
        ps = ps_repo.get(conn, psid) if psid else None
        batch = _batch_display(conn, predict_job)
    return cc.resolve_display(ctx.settings.capture, ps, batch, (predict_job.get("params") or {}).get("display"), *extra)


# ---- 핸들러 ------------------------------------------------------------------------------------


def predict_capture(ctx: Any) -> None:
    """(PREDICT, CONTOUR_CAPTURE): 실패해도 경고만(예측 성공 유지)."""
    reason = not_configured(ctx)
    if reason:
        ctx.patch_result({"media": [], "capture": {"status": "SKIPPED", "message": reason}})
        raise StepSkipped(reason)
    opts = batch_capture_for(ctx, ctx.job)
    if opts.get("enabled") is False:
        reason = "일괄 예측 설정에서 컨투어 캡처를 껐습니다"
        ctx.patch_result({"media": [], "capture": {"status": "SKIPPED", "message": reason}})
        raise StepSkipped(reason)
    display, source = display_for(ctx, ctx.job)
    if opts.get("views"):
        display["views"] = list(opts["views"])
    views = list(display["views"])
    video = opts.get("video") if isinstance(opts.get("video"), bool) else None
    media_dir = os.path.join(predict_dir(ctx), *cc.MEDIA_DIR_REL.split("/"))
    try:
        pred_rel = ctx.result().get("pred_h3d_rel")
        if not pred_rel:
            raise StepFailure("INPUT_MISSING", "예측 결과 h3d 경로가 없습니다")
        out = run_capture(ctx, h3d=ctx.abs(pred_rel), media_dir=media_dir, display=display, views=views, video=video)
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
    opts = batch_capture_for(ctx, src)  # 일괄 예측 하위의 재캡처: 배치 캡처 방향·동영상 옵션이 기본(D3-53)
    views = list(ctx.params.get("views") or opts.get("views") or display["views"])
    display["views"] = views
    video = opts.get("video") if isinstance(opts.get("video"), bool) else None
    media_dir = os.path.join(ctx.abs(f"04_predict/{root_id}"), *cc.RECAPTURE_DIR_REL.split("/"), ctx.workspace_id)
    out = run_capture(ctx, h3d=ctx.abs(pred_rel), media_dir=media_dir, display=display, views=views, video=video)
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
