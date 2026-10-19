"""④ 컨투어 동영상 변환·코덱 확인(phase3 §21.4.3 S16) — `capture.py run_capture`가 방향마다 부른다.

- 변환(`capture.ffmpeg.exe`가 비어 있지 않을 때): HyperView 산출 `<view>.<ext>` → `media/raw/<view>.<ext>`(이동, 삭제 없음) →
  단계표(`capture.ffmpeg.ladder`)를 차례로 `run_local("video_transcode", …)`(제한기 안, shell=False) → 시도 파일은 작업 임시 폴더
  `<study>/logs/<job>/tmp/`에만 → `video_target_bytes` 이하인 첫 단계(없으면 가장 작은 것 + 초과 표시)를 `media/<view>.mp4`로.
  변환 실패(rc≠0·출력 없음·시간 초과) → 원본을 그대로 쓰고 경고 사유를 돌려준다.
- 코덱 확인(`probe_exe`가 있을 때, 변환하지 않은 경우): `run_local("video_probe", …)` 출력 `codec_name=`·`pix_fmt=` → meta.
- 경고(작업당 1건으로 묶는 것)는 호출자가 낸다. 이 모듈은 결과만 돌려준다.
"""

from __future__ import annotations

import os
import time
from typing import Any

from physicsai_core.config.schema_capture import transcode_enabled
from physicsai_core.errors import StepFailure

from ...limiter.base import LimiterError

MP4 = "video/mp4"
H264, YUV420P = "h264", "yuv420p"


def _fmt_mb(n: int | float) -> str:
    return f"{n / 1048576:.1f} MB"


def _timeout_hook(ctx: Any, limit: float, state: dict[str, Any]) -> Any:
    start = time.monotonic()

    def hook() -> None:
        if limit and not state["timed_out"] and time.monotonic() - start > limit:
            state["timed_out"] = True
            ctx.log(f"[TIMEOUT] 영상 변환이 {limit:g}초를 넘어 프로세스를 종료합니다(capture.ffmpeg.timeout_s)")
            with ctx.ex._proc_lock:
                proc = ctx.ex.current_proc
            if proc is not None:
                ctx.ex.limiter.terminate(proc)
        return None

    return hook


def tmp_dir(ctx: Any) -> str:
    """작업 임시 폴더(삭제 허용 예외 platform.md §8.3) `<study>/logs/<job>/tmp`."""
    d = os.path.join(ctx.ex.log_dir, "tmp")
    os.makedirs(d, exist_ok=True)
    return d


def probe(ctx: Any, path: str, cwd: str) -> dict[str, str] | None:
    """ffprobe `codec_name=`·`pix_fmt=` → {codec, pix_fmt}. probe_exe 없음·실패 = None(경고 없음, 로그만)."""
    s = ctx.settings
    if not s.capture.ffmpeg.probe_exe or not os.path.isfile(s.capture.ffmpeg.probe_exe):
        return None
    lines: list[str] = []
    try:
        ctx.run_local("video_probe", {"video_in": path}, cwd=cwd, check_log_errors=False, allow_nonzero_exit=False,
                      line_hook=lambda ln: lines.append(ln) and None)
    except (StepFailure, LimiterError, OSError) as exc:
        ctx.log(f"[video_probe] 코덱 확인 실패: {getattr(exc, 'message', None) or exc}")
        return None
    out: dict[str, str] = {}
    for ln in lines:
        k, sep, v = ln.strip().partition("=")
        if sep and k in ("codec_name", "pix_fmt") and v.strip():
            out[k] = v.strip()
    if "codec_name" not in out:
        return None
    return {"codec": out["codec_name"], "pix_fmt": out.get("pix_fmt", "")}


def transcode(ctx: Any, *, media_dir: str, view: str, src: str, ext: str) -> dict[str, Any]:
    """변환 1방향 → {path, content_type?, meta, over_bytes|None, error|None}.

    성공: path = media/<view>.mp4, meta {transcoded, raw_rel, codec, pix_fmt, playable}. 실패: path = raw 원본, error = 사유."""
    s = ctx.settings
    f = s.capture.ffmpeg
    raw_dir = os.path.join(media_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    raw = os.path.join(raw_dir, os.path.basename(src))
    if os.path.exists(raw):
        ctx.backup([raw])
    os.replace(src, raw)
    tmp = tmp_dir(ctx)
    tries: list[tuple[int, str]] = []
    error: str | None = None
    for k, st in enumerate(f.ladder, start=1):
        out = os.path.join(tmp, f"{view}.try{k}.mp4")
        state = {"timed_out": False}
        vals = {"video_in": raw, "video_out": out, "scale": format(st.scale, "g"), "crf": str(st.crf), "fps": str(st.fps)}
        try:
            ctx.run_local("video_transcode", vals, cwd=media_dir, allow_nonzero_exit=False, check_log_errors=False,
                          poll_hook=_timeout_hook(ctx, f.timeout_s, state))
        except (StepFailure, LimiterError, OSError) as exc:
            error = "시간 초과" if state["timed_out"] else (getattr(exc, "message", None) or str(exc))
            break
        if not (os.path.isfile(out) and os.path.getsize(out) > 0):
            error = "변환 출력이 없습니다"
            break
        size = os.path.getsize(out)
        tries.append((size, out))
        ctx.log(f"[video_transcode] {view} 단계 {k}: {size} B (scale {st.scale:g}, crf {st.crf}, fps {st.fps})")
        if size <= s.capture.video_target_bytes:
            break
    if not tries:
        return {"path": raw, "meta": {"transcoded": False, "raw_rel": ctx.rel(raw)}, "over_bytes": None,
                "error": (error or "변환 출력이 없습니다")[:200]}
    within = [t for t in tries if t[0] <= s.capture.video_target_bytes]
    size, chosen = within[0] if within else min(tries)
    final = os.path.join(media_dir, f"{view}.mp4")
    if os.path.exists(final):
        ctx.backup([final])
    os.replace(chosen, final)
    meta = {"transcoded": True, "raw_rel": ctx.rel(raw), "codec": H264, "pix_fmt": YUV420P, "playable": True}
    return {"path": final, "content_type": MP4, "meta": meta, "over_bytes": None if within else size, "error": None}


def enabled(ctx: Any) -> bool:
    return transcode_enabled(ctx.settings)


__all__ = ["transcode", "probe", "enabled", "tmp_dir", "MP4", "H264", "YUV420P", "_fmt_mb"]
