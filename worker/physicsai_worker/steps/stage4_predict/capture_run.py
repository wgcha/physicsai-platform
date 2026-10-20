"""④ 컨투어 캡처 실행·판정(등록·영상 준비·제한 시간 훅·run_capture·요약) — capture에서 재노출."""

from __future__ import annotations

import os
import time
from typing import Any

from physicsai_core.config.schema_capture import capture_missing, effective_capture_tcl, effective_video_ext
from physicsai_core.db.repositories import artifacts as artifacts_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, sha256_file, write_text
from physicsai_core.stage4_predict import contour_capture as cc

from . import video_transcode as vt

# ---- 실행·판정 ---------------------------------------------------------------------------------


def _register(ctx: Any, kind: str, path: str, ctype: str, view: str, meta: dict[str, Any] | None = None) -> str:
    size = os.path.getsize(path)
    sha = sha256_file(path, checkpoint=ctx.checkpoint)
    ctx.add_output(path)
    full = {"view": view, **(meta or {})}
    return ctx.ex.db(lambda c: artifacts_repo.insert(
        c, study_id=ctx.study["id"], job_id=ctx.ex.job_id, kind=kind, rel_path=ctx.rel(path), size=size, sha256=sha,
        content_type=ctype, meta=full))


def _video_missing_reason(info: dict[str, Any], *, exists: bool, timed_out: bool, rc: int) -> str:
    """동영상이 없거나 0바이트인 방향의 원인(§21.4.3 순서): manifest 오류 → 성공 보고 + 파일 없음 → 시간 초과 → 0바이트·종료코드."""
    err = info.get("error") or ""
    vid_err = "; ".join(p.strip() for p in err.split(";") if p.strip().startswith("video:"))
    if vid_err:
        return vid_err
    if info.get("video") == "OK":
        return "파일이 만들어지지 않았습니다(HyperView 성공 보고)"
    if timed_out:
        return "시간 초과"
    if exists:
        return "동영상 파일이 0바이트입니다"
    return f"동영상 파일 없음(종료코드 {rc})"


def _prepare_video(ctx: Any, *, media_dir: str, view: str, vp: str, ext: str, notes: dict[str, list[str]]
                   ) -> tuple[str, str, dict[str, Any]]:
    """등록할 (경로, content_type, meta). 변환(ffmpeg) 또는 코덱 확인(ffprobe) — §21.4.3."""
    s = ctx.settings
    ctype = cc.VIDEO_CONTENT_TYPES[ext]
    if vt.enabled(ctx):
        out = vt.transcode(ctx, media_dir=media_dir, view=view, src=vp, ext=ext)
        if out["error"] is None:
            if out["over_bytes"] is not None:
                notes["over"].append(f"{view} {vt._fmt_mb(out['over_bytes'])}")
            return out["path"], out["content_type"], out["meta"]
        notes["transcode_failed"].append(f"{view}: {out['error']}")
        meta = dict(out["meta"])
        meta["playable"] = False if ext == "avi" else None
        if ext == "gif":
            meta["playable"] = True
        vp = out["path"]
    else:
        meta = {}
        if ext == "avi":
            meta["playable"] = False
        elif ext == "gif":
            meta["playable"] = True
        else:
            pr = vt.probe(ctx, vp, media_dir)
            if pr is not None:
                ok = pr["codec"] == vt.H264 and pr["pix_fmt"] == vt.YUV420P
                meta.update({"codec": pr["codec"], "pix_fmt": pr["pix_fmt"], "playable": ok})
                if not ok:
                    notes["not_playable"].append(pr["codec"])
            else:
                meta["playable"] = None
    size = os.path.getsize(vp)
    if size > s.capture.video_target_bytes:
        notes["over"].append(f"{view} {vt._fmt_mb(size)}")
    return vp, ctype, meta


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


def run_capture(ctx: Any, *, h3d: str, media_dir: str, display: dict[str, Any], views: list[str],
                video: bool | None = None, extra_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """캡처 1회 → {media, failed:[{view, reason}], video_failed:[{view, reason}], message}. 설정·실행 오류는 StepFailure.
    video None = config capture.video(일괄 예측 캡처 옵션이 덮어씀, D3-53). extra_meta = artifacts meta 추가 키(S16 V2 side·fv_id).
    동영상 경고(S16 §21.4.3: CAPTURE_VIDEO_FAILED·OVER_TARGET·TRANSCODE_FAILED·NOT_PLAYABLE)는 작업당 1건씩 여기서 낸다."""
    s = ctx.settings
    bad = cc.validate_display(display) + cc.validate_views(views, ["views"])
    if bad:  # API·설정 검증을 거친 값이지만 TCL 명령 문자열로 들어가므로 쓰기 전에 한 번 더(D3-53)
        raise StepFailure("INPUT_INVALID", f"표시 설정 오류: {'.'.join(map(str, bad[0]['loc']))} — {bad[0]['msg']}")
    missing = capture_missing(s)
    if "resources.contour_capture_tcl" in missing:
        raise StepFailure("RESOURCE_MISSING", f"캡처 TCL이 없습니다: {effective_capture_tcl(s) or 'resources.contour_capture_tcl'}")
    if not os.path.isfile(h3d):
        raise StepFailure("INPUT_MISSING", f"예측 결과 h3d가 없습니다: {os.path.basename(h3d)}")
    ctx.backup([media_dir])
    os.makedirs(media_dir, exist_ok=True)
    tcl = os.path.join(media_dir, cc.SCRIPT_NAME)
    copy_file(effective_capture_tcl(s), tcl, checkpoint=ctx.checkpoint)
    save_video, ext = bool(s.capture.video if video is None else video), effective_video_ext(s)
    write_text(os.path.join(media_dir, cc.SETTINGS_NAME), cc.settings_text(
        h3d_path=h3d, out_dir=media_dir, display=display, views=views, save_video=save_video, video_ext=ext,
        use_last=s.capture.use_last, video_scope=s.capture.video_scope))
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
    video_failed: list[dict[str, str]] = []
    notes: dict[str, list[str]] = {"over": [], "transcode_failed": [], "not_playable": []}
    xmeta = dict(extra_meta or {})
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
        img = _register(ctx, "CONTOUR_IMAGE", png, cc.IMAGE_CONTENT_TYPE, v, xmeta)
        vid, verr = None, None
        vp = os.path.join(media_dir, f"{v}.{ext}")
        if save_video and os.path.isfile(vp) and os.path.getsize(vp) > 0:
            if os.path.getsize(vp) > s.capture.max_video_bytes:
                verr = f"상한 초과({os.path.getsize(vp)} B > capture.max_video_bytes)"
                ctx.add_warning("CAPTURE_VIDEO_TOO_LARGE",
                                f"{v} 동영상이 상한(capture.max_video_bytes)을 넘어 등록하지 않았습니다: {os.path.getsize(vp)} B")
            else:
                path, ctype, vmeta = _prepare_video(ctx, media_dir=media_dir, view=v, vp=vp, ext=ext, notes=notes)
                vid = _register(ctx, "CONTOUR_VIDEO", path, ctype, v, {**vmeta, **xmeta})
        elif save_video:
            verr = _video_missing_reason(info, exists=os.path.isfile(vp), timed_out=state["timed_out"], rc=rc)[:200]
            video_failed.append({"view": v, "reason": verr})
        item: dict[str, Any] = {"view": v, "image_artifact_id": img, "video_artifact_id": vid}
        if verr:
            item["video_error"] = verr
        media.append(item)
    if video_failed:
        detail = "; ".join(f"{f['view']}: {f['reason']}" for f in video_failed)
        ctx.add_warning("CAPTURE_VIDEO_FAILED", f"동영상 저장 실패 {len(video_failed)}/{len(views)} 방향: {detail}"[:300])
    if notes["over"]:
        ctx.add_warning("CAPTURE_VIDEO_OVER_TARGET", (f"영상이 목표 크기({vt._fmt_mb(s.capture.video_target_bytes)})를 넘습니다: "
                                                      + ", ".join(notes["over"]))[:300])
    if notes["transcode_failed"]:
        ctx.add_warning("CAPTURE_VIDEO_TRANSCODE_FAILED",
                        ("영상 변환 실패 — 원본을 그대로 씁니다: " + "; ".join(notes["transcode_failed"]))[:300])
    if notes["not_playable"]:
        ctx.add_warning("CAPTURE_VIDEO_NOT_PLAYABLE", f"브라우저가 재생하지 못할 수 있는 코덱({notes['not_playable'][0]}) — "
                                                      "ffmpeg 변환을 설정하세요"[:300])
    msg = None
    if state["timed_out"]:
        msg = f"시간 초과(capture.timeout_s = {s.capture.timeout_s:g}초)"
    elif failed:
        msg = "; ".join(f"{f['view']}: {f['reason']}" for f in failed)[:400]
    return {"media": media, "failed": failed, "video_failed": video_failed, "message": msg, "rc": rc, "video": save_video,
            "video_ext": ext}


def _summary(out: dict[str, Any] | None, *, status: str, display: dict[str, Any] | None, source: str | None,
             views: list[str], media_dir: str | None, ctx: Any, message: str | None = None) -> dict[str, Any]:
    return {
        "status": status, "views": views, "display": display, "field_source": source,
        "video": bool((out or {}).get("video", ctx.settings.capture.video)), "video_ext": effective_video_ext(ctx.settings),
        "dir_rel": ctx.rel(media_dir) if media_dir and os.path.isdir(media_dir) else None,
        "message": message if message is not None else (out or {}).get("message"),
        "failed_views": [f["view"] for f in (out or {}).get("failed", [])],
    }


def _status(out: dict[str, Any]) -> str:
    return "OK" if not out["failed"] else ("PARTIAL" if out["media"] else "FAILED")
