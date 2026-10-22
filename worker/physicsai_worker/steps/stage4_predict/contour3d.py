"""④⑤ CONTOUR_3D(geometry-view.md §13.5): 결과 3D 컨투어 — 열 때 생성(사용자 요청 때만, PREDICT·DOE에 연쇄하지 않음). CPU 대기열(LIGHT 아님, job-queues.md JQ-8·2026-10-22 사용자 결정).

C3_PREP(h3d 확인·캐시 폴더·extract_settings.tcl·TCL 복사) → C3_EXTRACT(`commands.contour_extract`, 출력 파일로 판정, 시간 한도
contour3d.timeout_s) → C3_CONVERT(physicsai_core.contour3d — 형상 → 프레임 변환, 진행률 단계 표시) → C3_REGISTER(artifacts 3종 + 캐시 행).
캐시 폴더 C = 서버측 `<study>/_cache/contour3d/<key[0:2]>/<key>/`(§6.6과 같은 housekeeping). 결정적 실패(TOO_LARGE·FIELD_EMPTY)는
작업 성공 + 결과 FAIL로 캐시, 인프라 실패(hw 없음·시간 초과·추출 오류·EXTRACT_INVALID)는 작업 실패(행 FAILED는 종료 훅).
진행 단계(화면 대기 안내): 대기(QUEUED) → H3D 읽기(C3_PREP·C3_EXTRACT) → 형상(C3_CONVERT < 30%) → 프레임 변환 → 완료·실패.
"""

from __future__ import annotations

import os
import time
from typing import Any

from physicsai_core.cache_store import remove_cache_dir, remove_cache_file
from physicsai_core.config.schema_capture import effective_extract_tcl
from physicsai_core.contour3d.convert import ConvertError, convert
from physicsai_core.contour3d.settings import (
    DETERMINISTIC_FAILS,
    OUT_FRAMES,
    OUT_GLB,
    OUT_MANIFEST,
    RESULT_NAME,
    SCRIPT_NAME,
    SETTINGS_NAME,
    TCL_STATUS_CODE,
    message_ko,
    parse_result,
    settings_text,
)
from physicsai_core.db.repositories import geom_view as gv_repo
from physicsai_core.db.tables import contour3d_cache
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, write_text
from physicsai_core.geometry.view import (
    CONTOUR_CACHE,
    GLB_CONTENT_TYPE,
    JSON_CONTENT_TYPE,
    OCTET_CONTENT_TYPE,
    cache_rel,
    dir_bytes,
)
from physicsai_core.path_links import is_link_or_reparse

def _C(ctx: Any) -> str:
    return ctx.abs(cache_rel(CONTOUR_CACHE, ctx.params["cache_key"]))


def _row(ctx: Any, **vals: Any) -> None:
    ctx.ex.db(lambda c: gv_repo.set_values(c, contour3d_cache, ctx.params["contour_id"], **vals))


def c3_prep(ctx: Any) -> None:
    s, p = ctx.settings, ctx.params
    ctx.progress(0, "대기·H3D 확인", force=True)
    if not s.contour3d.enabled or s.commands.contour_extract is None:
        raise StepFailure("CONTOUR3D_NOT_CONFIGURED", message_ko("CONTOUR3D_NOT_CONFIGURED") or "")
    tcl = effective_extract_tcl(s)
    if not tcl or not os.path.isfile(tcl):
        raise StepFailure("RESOURCE_MISSING", f"3D 컨투어 추출 TCL이 없습니다: {tcl or 'resources.contour_extract_tcl'}")
    h3d = ctx.abs(p["h3d_rel"])
    if not os.path.isfile(h3d) or is_link_or_reparse(h3d):
        raise StepFailure("INPUT_MISSING", f"결과 h3d가 없습니다: {os.path.basename(h3d)}")
    C = _C(ctx)
    if not remove_cache_dir(ctx.root, C, CONTOUR_CACHE):  # 캐시(플랫폼 임시 산출물) — _backup 이동 대신 지운다(§6.6)
        raise StepFailure("PATH_UNSAFE", "3D 컨투어 캐시 폴더 경로가 안전하지 않습니다")
    X = os.path.join(C, "extract")
    os.makedirs(X)
    copy_file(tcl, os.path.join(X, SCRIPT_NAME), checkpoint=ctx.checkpoint)
    write_text(os.path.join(X, SETTINGS_NAME), settings_text(h3d_path=h3d, out_dir=X, display=p.get("display") or {},
                                                            max_frames=int(p["max_frames"]), include_disp=bool(p["include_disp"])))
    _row(ctx, status="RUNNING")
    ctx.patch_result({"contour_id": p["contour_id"], "cache_rel": ctx.rel(C), "started_ts": time.time()})


def c3_extract(ctx: Any) -> None:
    s = ctx.settings
    X = os.path.join(_C(ctx), "extract")
    limit = float(s.contour3d.timeout_s)
    began = time.monotonic()
    state = {"timed_out": False}
    total = int(ctx.params["max_frames"])

    def poll() -> tuple[float | None, str | None] | None:
        if not state["timed_out"] and time.monotonic() - began > limit:
            state["timed_out"] = True
            ctx.log(f"[TIMEOUT] 3D 컨투어 추출이 {limit:g}초를 넘어 프로세스를 종료합니다(contour3d.timeout_s)")
            with ctx.ex._proc_lock:
                proc = ctx.ex.current_proc
            if proc is not None:
                ctx.ex.limiter.terminate(proc)
        done = sum(1 for n in os.listdir(X) if n.startswith("frame_") and n.endswith(".csv")) if os.path.isdir(X) else 0
        return min(99.0, 100.0 * done / max(1, total)), f"H3D 읽기 · 프레임 {done}"

    ctx.run_local("contour_extract", {"contour_extract_tcl": os.path.join(X, SCRIPT_NAME)}, cwd=X, allow_nonzero_exit=True,
                  check_log_errors=False, poll_hook=poll)
    if state["timed_out"]:
        raise StepFailure("CONTOUR3D_TIMEOUT", f"{message_ko('CONTOUR3D_TIMEOUT')}(contour3d.timeout_s = {limit:g}초)")
    rp = os.path.join(X, RESULT_NAME)
    if not os.path.isfile(rp):
        raise StepFailure("CONTOUR3D_EXTRACT_INVALID", f"{message_ko('CONTOUR3D_EXTRACT_INVALID')} — {RESULT_NAME} 없음")
    with open(rp, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    ctx.log("[extract_result.txt]\n" + text[:4000].rstrip())
    res = parse_result(text)
    if res["status"] != "OK":
        code = TCL_STATUS_CODE.get(str(res["status"]), "CONTOUR3D_EXTRACT_INVALID")
        raise StepFailure(code, f"{message_ko(code)} — {res['message'] or res['status']}")
    if not os.path.isfile(os.path.join(X, "nodes.csv")) or not any(os.path.isfile(os.path.join(X, n)) for n in ("faces.csv", "elements.csv")):
        raise StepFailure("CONTOUR3D_EXTRACT_INVALID", f"{message_ko('CONTOUR3D_EXTRACT_INVALID')} — nodes.csv·faces.csv 없음")
    ctx.patch_result({"extract": {"nodes": res["nodes"], "frames_total": res["frames_total"], "unit": res["unit"]}})


def c3_convert(ctx: Any) -> None:
    s, p = ctx.settings, ctx.params
    C = _C(ctx)
    X, out = os.path.join(C, "extract"), os.path.join(C, "out")
    t0 = time.monotonic()

    def prog(pct: float, label: str) -> None:
        ctx.progress(pct, label)

    src = {"kind": p["source_kind"], "ref": p.get("source_ref") or {}, "h3d_name": os.path.basename(p["h3d_rel"])}
    try:
        man = convert(X, out, source=src, max_nodes=int(s.contour3d.max_nodes), max_bin_bytes=int(s.contour3d.max_bin_bytes),
                      max_frames=int(p["max_frames"]), progress=prog, checkpoint=ctx.checkpoint,
                      discard=lambda f: remove_cache_file(ctx.root, f, CONTOUR_CACHE))
    except ConvertError as exc:
        raise StepFailure(exc.code, f"{message_ko(exc.code) or exc.code} — {exc.message}") from None
    remove_cache_dir(ctx.root, X, CONTOUR_CACHE)  # 변환 후 추출 CSV 삭제(공간 절약, 캐시 폴더 안)
    for w in man.get("warnings") or []:
        ctx.add_warning(str(w.get("code")), str(w.get("message") or "")[:300])
    if man["status"] != "OK" and man["code"] not in DETERMINISTIC_FAILS:
        raise StepFailure(man["code"] or "CONTOUR3D_EXTRACT_INVALID", man.get("message") or "")
    ctx.patch_result({"convert": {"status": man["status"], "code": man.get("code"), "convert_s": round(time.monotonic() - t0, 1)}})


def c3_register(ctx: Any) -> None:
    from sqlalchemy import func

    p, r = ctx.params, ctx.result()
    out = os.path.join(_C(ctx), "out")
    man_path = os.path.join(out, OUT_MANIFEST)
    from physicsai_core.geometry.view import read_json

    man = read_json(man_path) or {}
    ids: dict[str, str | None] = {"glb_artifact_id": None, "frames_artifact_id": None, "manifest_artifact_id": None}
    ok = man.get("status") == "OK"
    if ok:
        ids["glb_artifact_id"] = _register(ctx, "CONTOUR3D_GLB", os.path.join(out, OUT_GLB), GLB_CONTENT_TYPE)
        ids["frames_artifact_id"] = _register(ctx, "CONTOUR3D_FRAMES", os.path.join(out, OUT_FRAMES), OCTET_CONTENT_TYPE)
    if os.path.isfile(man_path):
        ids["manifest_artifact_id"] = ctx.register_artifact("CONTOUR3D_MANIFEST", man_path, JSON_CONTENT_TYPE)
    started = r.get("started_ts")
    total = round(time.time() - float(started), 1) if started else None
    timing = {"total_s": total, "convert_s": (r.get("convert") or {}).get("convert_s")}
    vals = {"status": "DONE", "result_status": "OK" if ok else "FAIL", "code": man.get("code"),
            "frames": (man.get("frames") or {}).get("count"), "nodes": (man.get("mesh") or {}).get("nodes"),
            "bytes": dir_bytes(_C(ctx)), "timing": timing, "finished_at": func.now(), "last_access_at": func.now(), **ids}
    _row(ctx, **vals)
    ctx.patch_result({"artifacts": ids, "result_status": vals["result_status"]})


def _register(ctx: Any, kind: str, path: str, ctype: str) -> str | None:
    """프레임 파일은 ui.max_artifact_bytes가 아니라 contour3d.max_bin_bytes 상한(Range로 나눠 받는다)."""
    from physicsai_core.db.repositories import artifacts as artifacts_repo
    from physicsai_core.fileutil import sha256_file

    size = os.path.getsize(path)
    return ctx.ex.db(lambda c: artifacts_repo.insert(
        c, study_id=ctx.study["id"], job_id=ctx.ex.job_id, kind=kind, rel_path=ctx.rel(path), size=size,
        sha256=sha256_file(path, checkpoint=ctx.checkpoint), content_type=ctype))


HANDLERS = {
    ("CONTOUR_3D", "C3_PREP"): c3_prep,
    ("CONTOUR_3D", "C3_EXTRACT"): c3_extract,
    ("CONTOUR_3D", "C3_CONVERT"): c3_convert,
    ("CONTOUR_3D", "C3_REGISTER"): c3_register,
}
