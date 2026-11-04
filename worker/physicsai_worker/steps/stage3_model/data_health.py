"""③-1 DATA_HEALTH(data-health.md §5): 입력 h3d run의 이상치 제외 추천. 데이터셋·입력 파일을 바꾸지 않는다(추천만).

DH_PREP(입력 해석·run 해석·지표 목록 → inputs.json) → DH_SCAN(run마다 ①·모델 속성·응답·프레임 원천 ①② → runs_raw.csv·scan.json·frames_todo.json,
진행률·취소 = run 경계) → DH_FRAMES(LOCAL, res=cpu: 원천이 없는 run만 hw 1회 — 불가·실패는 작업 실패 아님) → DH_SCORE(§3.2~§3.5 → runs.csv·report.json)
→ DH_REPORT(jobs.result 요약·artifact). 산출 폴더 `<study>/03_dataset/_health/<job_id>/`(이전 폴더는 `_backup`).
외부 도구는 DH_FRAMES의 hw 1회뿐(결과장 로드 없음). 응답은 ①-6 `responses_run.csv` 재사용만 — 추출하지 않는다.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Mapping
from typing import Any

from physicsai_core.config.schema_capture import effective_frame_probe_tcl
from physicsai_core.data_health import attrs as attrs_mod
from physicsai_core.data_health.input_key import input_key
from physicsai_core.data_health import frame_probe as fp
from physicsai_core.data_health import metrics as mx
from physicsai_core.data_health import report as rp
from physicsai_core.data_health import resolve as rsv
from physicsai_core.data_health import sources as src
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json, write_text
from physicsai_core.paths import PathError, check_dataset_input, check_user_path, file_safety_problem
from physicsai_core.stage3_model.dataset_split import collect_h3d

from ...signals import StepSkipped
from ..common import path_failure

ATTR_CACHE_REL = "03_dataset/_health/_attrs"
INPUTS, SCAN, RAW_CSV, RUNS_CSV, REPORT, TODO = "inputs.json", "scan.json", "runs_raw.csv", "runs.csv", "report.json", "frames_todo.json"


def _H(ctx: Any) -> str:
    return ctx.abs(f"03_dataset/_health/{ctx.ex.job_id}")


WARN_FILE = "warnings.json"


def _warn(ctx: Any, code: str, message: str, count: int | None = None) -> None:
    """작업 warnings와 보고서 `summary.warnings`에 같은 코드·문구를 남긴다(보고서용 목록은 작업 폴더 warnings.json에 모았다가 DH_SCORE가 합친다)."""
    ctx.add_warning(code, message)
    path = os.path.join(_H(ctx), WARN_FILE)
    try:
        cur = _load(path) if os.path.isfile(path) else []
    except (OSError, ValueError):
        cur = []
    item: dict[str, Any] = {"code": code, "message": message}
    if count is not None:
        item["count"] = count
    if item not in cur:
        cur.append(item)
    write_json(path, cur)


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _resp_defs(rs: rsv.RunSet, selected: list[str] | None) -> dict[str, list[dict[str, Any]]]:
    """DOE → 점검할 스칼라 응답 정의(D/responses.json, CURVE 제외, 선택 이름만)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for doe, resp in rs.responses.items():
        defs = src.scalar_response_defs(resp)
        out[doe] = [d for d in defs if selected is None or d["name"] in selected]
    return out


def _zmetrics(inputs: Mapping[str, Any]) -> list[mx.MetricDef]:
    return mx.zscore_metrics([mx.resp_metric(r["name"], r.get("unit", "")) for r in inputs.get("responses") or []],
                             attrs=bool(inputs["params"].get("attrs", True)))


# ---- DH_PREP ----------------------------------------------------------------------------------------


def dh_prep(ctx: Any) -> None:
    p, s = ctx.params, ctx.settings
    ctx.progress(0, "점검 입력 확인", force=True)
    try:
        cp = check_user_path(p["input_path"], [s.storage.ai_root])
        exclude = check_dataset_input(cp.path, s.storage.ai_root)
    except PathError as exc:
        raise path_failure(exc) from None
    files = collect_h3d(cp.path, exclude)
    bad = [(f, why) for f in files if (why := file_safety_problem(f, cp.path))]
    if bad:
        listing = ", ".join(f"{os.path.relpath(f, cp.path)}({w})" for f, w in bad[:10])
        raise StepFailure("INPUT_INVALID", f"경로 규칙 위반 파일 {len(bad)}개: {listing}")
    if len(files) < s.dataset.min_h3d_files:
        raise StepFailure("INPUT_INVALID", f"h3d 파일이 {len(files)}개입니다(최소 {s.dataset.min_h3d_files}개)")
    H = _H(ctx)
    if os.path.lexists(H):
        ctx.backup([H])
    os.makedirs(H)
    with ctx.ex.engine.connect() as conn:
        rs = rsv.resolve_runs(conn, s, ctx.study, ctx.root, cp.path, files, p.get("curation_id"))
    for w in rs.warnings:
        _warn(ctx, w["code"], w["message"])
    defs = _resp_defs(rs, p.get("responses"))
    names: dict[str, str] = {}
    for dl in defs.values():
        for d in dl:
            names.setdefault(d["name"], d["unit"])
    ikey = input_key(cp.path, p.get("curation_id"))
    inputs = {"input_key": ikey, "params": {k: p.get(k) for k in ("input_path", "curation_id", "responses", "attrs")},
              "thresholds": mx.thresholds_snapshot(s.data_health), "limited": rs.limited, "doe_ids": rs.doe_ids,
              "preview_frames": rs.preview_frames, "responses": [{"name": n, "unit": u} for n, u in sorted(names.items())],
              "snapshots": {k: [{"name": q.get("name"), "min": q.get("min"), "max": q.get("max"), "format": q.get("format")} for q in v]
                            for k, v in rs.snapshots.items()},
              "targets": [{"idx": i, "file_rel": t.file_rel, "run_key": t.run_key, "doe_id": t.doe_id, "linked": not t.unlinked}
                          for i, t in enumerate(rs.targets)]}
    ip = os.path.join(H, INPUTS)
    write_json(ip, inputs)
    ctx.add_output(ip)
    res: dict[str, Any] = {"input_path": cp.path, "input_key": ikey, "doe_ids": rs.doe_ids, "n_runs": len(files), "limited": rs.limited,
                           "thresholds": inputs["thresholds"]}
    if p.get("curation_id"):
        res["curation_id"] = p["curation_id"]
    ctx.patch_result(res)
    ctx.log(f"h3d {len(files)}개, DOE {len(rs.doe_ids)}개{' · 제한 모드(DOE 연결 없음)' if rs.limited else ''}")


# ---- DH_SCAN ----------------------------------------------------------------------------------------


def _scan_one(ctx: Any, t: rsv.Target, i: int, rs: rsv.RunSet, defs: dict[str, list[dict[str, Any]]], inputs: Mapping[str, Any],
              t01: Mapping[str, str], manifests: Mapping[str, str], cache_dir: str, notes: dict[str, Any]) -> dict[str, Any]:
    s, d = ctx.settings, ctx.settings.data_health
    linked = not t.unlinked
    vals: dict[str, Any] = {}
    na: dict[str, str] = {}
    aux: dict[str, Any] = {}
    row = {"idx": i, "file_rel": t.file_rel, "run_key": t.run_key, "doe_id": t.doe_id, "params": (t.run.params if t.run else None),
           "values": vals, "na": na, "aux": aux, "t_end": None}
    out_folder, rec = (t.result_dir, True) if linked else (os.path.dirname(t.h3d), False)
    info = src.engine_out_info(out_folder, d, recursive=rec)
    for k in ("term", "energy_err_pct", "added_mass"):
        if k in info.values:
            vals[k] = info.values[k]
        else:
            na[k] = info.na.get(k, "OUT_MISSING")
    aux["t_last_out"] = info.values.get("t_last_out")
    aux["t_last_out_na"] = info.na.get("t_last_out")
    # hg/접촉 비(②-4 곡선 JSON + 설정 t01_series가 있을 때만)
    curve = None
    if d.t01_series is not None and t.run_key and t.run_key in t01:
        curve = src.read_manifest(t01[t.run_key], s.ui.max_artifact_bytes)
    tv, tn = src.t01_ratios(curve, d.t01_series, d.zero_tol)
    vals.update(tv)
    na.update(tn)
    # 모델 속성·총질량·응답
    attrs_on = bool(inputs["params"].get("attrs", True))
    if attrs_on:
        if linked and t.run is not None:
            mass, why = src.starter_mass_of([t.result_dir, t.input_dir], d)
            if mass is None:
                na["mass_total"] = why or "MASS_SOURCE_MISSING"
            else:
                vals["mass_total"] = mass
            ar = attrs_mod.model_attrs(mesh_inc=t.run.mesh_inc, mesh_tree=t.run.mesh_tree, mesh_parts=t.run.mesh_parts,
                                       max_bytes=s.fem_verify.include_scan_max_bytes * 16, cache_dir=cache_dir)
            for k in attrs_mod.ATTR_IDS:
                if k in ar.values:
                    vals[k] = ar.values[k]
                else:
                    na[k] = ar.na or "MESH_MISSING"
            notes["skipped_kinds"].update(ar.skipped_kinds)
            if ar.na == "NO_SOLID":
                notes["no_solid"].append(t.run_key or t.file_rel)
        else:
            for k in ("mass_total", *attrs_mod.ATTR_IDS):
                na[k] = "RUN_UNLINKED"
    if linked and t.run is not None and inputs.get("responses"):
        side = rs.sides.get(t.doe_id or "")
        rv, rn = src.read_responses(t.result_dir, defs.get(t.doe_id or "", []), side.responses if side else None)
        for r in inputs["responses"]:
            nm = r["name"]
            if nm in rv:
                vals[f"resp:{nm}"] = rv[nm]
            else:
                na[f"resp:{nm}"] = rn.get(nm, "RESP_NOT_EXTRACTED")
                if na[f"resp:{nm}"] == "RESP_NOT_EXTRACTED":
                    notes["resp_missing"] += 1
    elif inputs.get("responses"):
        for r in inputs["responses"]:
            na[f"resp:{r['name']}"] = "RUN_UNLINKED"
    # 입력 rad Tstop
    row["t_end"], t_end_na = src.rad_tstop(t.input_dir, d) if linked else (None, "RUN_UNLINKED")
    if row["t_end"] is None:
        na["t_end"] = t_end_na or "RAD_MISSING"
    # 프레임 원천 ①(3D 컨투어 캐시 manifest) → ②(engine out 기록)
    frames = t_last = None
    man = manifests.get(t.study_rel)
    if man:
        frames, t_last = src.frames_from_manifest(src.read_manifest(man, s.ui.max_artifact_bytes))
        if frames is not None:
            aux["frames_src"] = "cache"
    if frames is None:
        frames = src.frames_from_out(out_folder, d, recursive=rec)
        if frames is not None:
            aux["frames_src"] = "out_log"
    if frames is not None:
        vals["frames"] = frames
    aux["t_last_h3d"] = t_last
    return row


def dh_scan(ctx: Any) -> None:
    p, s = ctx.params, ctx.settings
    H = _H(ctx)
    inputs = _load(os.path.join(H, INPUTS))
    cache_dir = ctx.abs(ATTR_CACHE_REL)
    files = collect_h3d(inputs["params"]["input_path"], check_dataset_input(inputs["params"]["input_path"], s.storage.ai_root))
    with ctx.ex.engine.connect() as conn:
        rs = rsv.resolve_runs(conn, s, ctx.study, ctx.root, inputs["params"]["input_path"], files, p.get("curation_id"))
        t01 = rsv.t01_curve_index(conn, ctx.root, ctx.study["id"]) if s.data_health.t01_series is not None else {}
        manifests = rsv.contour_manifests(conn, s, ctx.root, ctx.study["id"], rs.targets)
    defs = _resp_defs(rs, p.get("responses"))
    notes: dict[str, Any] = {"skipped_kinds": set(), "no_solid": [], "resp_missing": 0}
    rows: list[dict[str, Any]] = []
    todo: list[dict[str, Any]] = []
    failed: list[str] = []
    n = len(rs.targets)
    for i, t in enumerate(rs.targets):
        ctx.checkpoint_cancel()
        try:
            row = _scan_one(ctx, t, i, rs, defs, inputs, t01, manifests, cache_dir, notes)
        except (OSError, ValueError) as exc:  # run 하나의 읽기 실패는 그 값 NA + 경고(작업은 계속)
            failed.append(t.file_rel)
            ctx.log(f"[READ FAILED] {t.file_rel}: {type(exc).__name__}")
            row = {"idx": i, "file_rel": t.file_rel, "run_key": t.run_key, "doe_id": t.doe_id, "params": None, "values": {},
                   "na": {"term": "READ_FAILED"}, "aux": {}, "t_end": None}
        rows.append(row)
        if "frames" not in row["values"]:
            todo.append({"idx": i, "file_rel": t.file_rel, "h3d": t.h3d})
        ctx.progress((i + 1) / max(1, n) * 100.0, f"{i + 1}/{n} {t.file_rel}")
    if failed:
        _warn(ctx, "DH_RUN_READ_FAILED", f"읽기에 실패한 run {len(failed)}개(예: {', '.join(failed[:3])}) — 그 run의 값을 비웠습니다", len(failed))
    if notes["skipped_kinds"]:
        _warn(ctx, "EQ_VOLUME_ELEM_SKIPPED", f"지원하지 않는 요소형을 건너뜀 — {', '.join(sorted(notes['skipped_kinds']))}")
    if notes["no_solid"]:
        _warn(ctx, "DH_NO_SOLID", f"솔리드 요소가 없어 모델 속성(bbox·부피·무게중심)을 비운 run {len(notes['no_solid'])}개(쉘 쿠션 등)", len(notes["no_solid"]))
    if inputs["params"].get("responses") != [] and (not inputs.get("responses") or notes["resp_missing"]):
        _warn(ctx, "DH_RESP_NOT_EXTRACTED", "①-6 run 응답 추출을 먼저 실행하면 응답 지표를 함께 봅니다", notes["resp_missing"] or None)
    sc = os.path.join(H, SCAN)
    write_json(sc, {"rows": rows, "preview_frames": inputs.get("preview_frames")})
    write_json(os.path.join(H, TODO), todo)
    write_text(os.path.join(H, RAW_CSV), rp.raw_csv_text(rows, [m.id for m in _zmetrics(inputs)]))
    ctx.add_output(os.path.join(H, RAW_CSV))
    ctx.patch_result({"n_runs": n})
    ctx.log(f"run {n}개 읽음, 프레임 원천 없음 {len(todo)}개")


# ---- DH_FRAMES --------------------------------------------------------------------------------------


def _frames_na(rows: list[dict[str, Any]], idxs: list[int], code: str) -> None:
    for r in rows:
        if r["idx"] in idxs:
            r["na"]["frames"] = code


def dh_frames(ctx: Any) -> None:
    s, d = ctx.settings, ctx.settings.data_health
    H = _H(ctx)
    todo = _load(os.path.join(H, TODO))
    if not todo:
        raise StepSkipped("프레임 원천이 모두 정해짐(컨투어 캐시·out 기록)")
    state = _load(os.path.join(H, SCAN))
    rows = state["rows"]
    idxs = [t["idx"] for t in todo]

    def unavailable(why: str) -> None:
        _frames_na(rows, idxs, "FRAMES_PROBE_UNAVAILABLE")
        write_json(os.path.join(H, SCAN), state)
        _warn(ctx, "DH_FRAMES_UNAVAILABLE", f"h3d 프레임 수를 확인하지 못했습니다({why}) — {len(idxs)}개 run은 프레임 일관성을 검사하지 못합니다", len(idxs))
        ctx.log(f"[FRAMES UNAVAILABLE] {why}")

    if s.commands.h3d_frame_probe is None:
        unavailable("commands.h3d_frame_probe 템플릿이 꺼져 있음")
        raise StepSkipped("프레임 조회 템플릿 꺼짐")
    tcl = effective_frame_probe_tcl(s)
    if not tcl or not os.path.isfile(tcl):
        unavailable(f"조회 TCL 없음: {tcl or 'resources.h3d_frame_probe_tcl'}")
        return
    F = os.path.join(H, "frame_probe")
    os.makedirs(os.path.join(F, fp.FRAMES_DIR), exist_ok=True)
    shutil.copyfile(tcl, os.path.join(F, fp.SCRIPT_NAME))
    targets = [{"idx": t["idx"], "h3d": t["h3d"], "out": os.path.join(F, fp.FRAMES_DIR, f"{t['idx']}.txt")} for t in todo]
    write_text(os.path.join(F, fp.SETTINGS_NAME), fp.settings_text(targets))
    limit = float(d.frame_probe_timeout_s)
    began = time.monotonic()
    st = {"timed_out": False}

    def poll() -> tuple[float | None, str | None] | None:
        if not st["timed_out"] and time.monotonic() - began > limit:
            st["timed_out"] = True
            ctx.log(f"[TIMEOUT] 프레임 조회가 {limit:g}초를 넘어 프로세스를 종료합니다(data_health.frame_probe_timeout_s)")
            with ctx.ex._proc_lock:
                proc = ctx.ex.current_proc
            if proc is not None:
                ctx.ex.limiter.terminate(proc)
        done = len(os.listdir(os.path.join(F, fp.FRAMES_DIR)))
        return min(99.0, 100.0 * done / max(1, len(targets))), f"프레임 조회 {done}/{len(targets)}"

    try:
        rc = ctx.run_local("h3d_frame_probe", {"frame_probe_tcl": os.path.join(F, fp.SCRIPT_NAME)}, cwd=F, allow_nonzero_exit=True,
                           check_log_errors=False, poll_hook=poll)
    except StepFailure as exc:  # hw 실행 파일 없음·제한 초과 등 — 작업은 실패시키지 않는다
        unavailable(f"{exc.code} {exc.message}"[:200])
        return
    if st["timed_out"]:
        unavailable(f"시간 초과 {limit:g}초")
        return
    outs = {t["idx"]: os.path.join(F, fp.FRAMES_DIR, f"{t['idx']}.txt") for t in targets}
    if rc != 0 and not any(os.path.isfile(p) for p in outs.values()):
        unavailable(f"명령 실패(종료코드 {rc}, 출력 없음)")
        return
    n_ok = 0
    for r in rows:
        if r["idx"] not in outs:
            continue
        res = fp.read_result(outs[r["idx"]])
        if res.ok:
            r["values"]["frames"] = res.frames
            r["aux"]["frames_src"] = "probe"
            r["aux"]["t_last_h3d"] = res.t_last
            r["na"].pop("frames", None)
            n_ok += 1
        else:
            r["na"]["frames"] = res.code or "FRAMES_PROBE_FAILED"
            ctx.log(f"[PROBE FAIL] {r['file_rel']}: {res.message}")
    write_json(os.path.join(H, SCAN), state)
    if n_ok < len(targets):
        _warn(ctx, "DH_FRAMES_PARTIAL", f"프레임 수를 조회하지 못한 run {len(targets) - n_ok}개 — 프레임 일관성을 검사하지 못합니다", len(targets) - n_ok)
    ctx.log(f"프레임 조회 {n_ok}/{len(targets)}")


# ---- DH_SCORE / DH_REPORT ---------------------------------------------------------------------------


def dh_score(ctx: Any) -> None:
    s, d = ctx.settings, ctx.settings.data_health
    H = _H(ctx)
    inputs = _load(os.path.join(H, INPUTS))
    state = _load(os.path.join(H, SCAN))
    rows = state["rows"]
    for r in rows:  # 마지막 시각: h3d 마지막 프레임(캐시·조회) → engine out 꼬리 마지막 사이클 줄(§3.6)
        aux = r.get("aux") or {}
        t = aux.get("t_last_h3d") if aux.get("t_last_h3d") is not None else aux.get("t_last_out")
        if t is not None:
            r["values"]["t_last"] = t
        else:
            r["na"]["t_last"] = "TIME_SOURCE_NONE"
        if "frames" not in r["values"] and not r["na"].get("frames"):
            r["na"]["frames"] = "FRAMES_SOURCE_NONE"
    zm = _zmetrics(inputs)
    wp = os.path.join(H, WARN_FILE)
    extra: list[dict[str, Any]] = _load(wp) if os.path.isfile(wp) else []  # 앞 단계에서 작업 warnings에 남긴 것 — 보고서 summary.warnings에도 같은 코드·문구
    pf = inputs.get("preview_frames")
    scored = rp.score(rows, zm, d, snapshots=inputs.get("snapshots") or {}, extra_warnings=extra, limited=bool(inputs.get("limited")))
    fr = scored.summary.get("frames_ref")
    if pf is not None and fr is not None and pf != fr:
        scored.summary["warnings"].append({"code": "DH_PREVIEW_FRAMES_DIFF", "message":
                                           f"② 큐레이션 기준 프레임 {pf}이 데이터셋 기준 {fr}과 다릅니다 — ② 큐레이션 결과가 이미 어긋났을 수 있습니다"})
    scored.summary["preview_frames"] = pf
    scored.summary["input_key"] = inputs.get("input_key")
    scored.summary["thresholds"] = inputs["thresholds"]
    rep = rp.fit_report(scored.report, s.ui.max_artifact_bytes, d.report_max_rows)
    write_text(os.path.join(H, RAW_CSV), rp.raw_csv_text(rows, scored.zmetric_ids))
    write_text(os.path.join(H, RUNS_CSV), rp.runs_csv_text(rows, scored))
    write_json(os.path.join(H, REPORT), rep)
    for w in scored.summary["warnings"]:
        if w["code"] in ("DH_REF_TIE", "DH_REF_DOE_DIFF", "DH_PARAMS_MIXED", "DH_PREVIEW_FRAMES_DIFF", "DH_CONSISTENCY_UNDECIDED"):
            ctx.add_warning(w["code"], w["message"])
    for f in (RAW_CSV, RUNS_CSV, REPORT):
        ctx.add_output(os.path.join(H, f))
    write_json(os.path.join(H, "summary.json"), scored.summary)
    ctx.log(f"추천 {scored.summary['n_recommended']} / {scored.summary['n_runs']}(제외 필수 {scored.summary['n_required']})")


def dh_report(ctx: Any) -> None:
    H = _H(ctx)
    summ = _load(os.path.join(H, "summary.json"))
    keep = ("input_key", "n_runs", "n_required", "n_frames_unknown", "n_consistency_undecided", "frames_ref", "t_end_ref", "n_recommended", "n_sigma_only", "n_sound_fail",
            "n_na_by_metric", "metrics_used", "thresholds", "limited")
    res = {k: summ.get(k) for k in keep}
    res["warnings"] = summ.get("warnings") or []
    res["report_rel"] = ctx.rel(os.path.join(H, REPORT))
    res["csv_rel"] = ctx.rel(os.path.join(H, RUNS_CSV))
    ctx.register_artifact("DATA_HEALTH_REPORT", os.path.join(H, REPORT), "application/json")
    ctx.register_artifact("DATA_HEALTH_CSV", os.path.join(H, RUNS_CSV), "text/csv")
    ctx.patch_result(res)


HANDLERS = {
    ("DATA_HEALTH", "DH_PREP"): dh_prep,
    ("DATA_HEALTH", "DH_SCAN"): dh_scan,
    ("DATA_HEALTH", "DH_FRAMES"): dh_frames,
    ("DATA_HEALTH", "DH_SCORE"): dh_score,
    ("DATA_HEALTH", "DH_REPORT"): dh_report,
}
