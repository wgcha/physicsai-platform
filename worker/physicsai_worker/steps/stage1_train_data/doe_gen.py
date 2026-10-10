"""①-3 TD_DOE_GEN: DOE·Radioss 입력 생성(phase2 §6.4)."""

from __future__ import annotations

import fnmatch
import glob
import os
import re
from typing import Any

from physicsai_core.stage1_train_data import doe_samples
from physicsai_core.stage1_train_data import train_params as tp
from physicsai_core.commands import fwd
from physicsai_core.config import effective_altair
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, sha256_file, write_json
from physicsai_core.naming import RUN_KEY_RE
from physicsai_core.paths import allowed_roots, check_user_path, is_link_or_reparse, PathError

from ..common import path_failure
from ..launcher import stage_launcher
from ._shared import TPL_NAME, _D, _doe


def _setup(ctx: Any) -> dict[str, Any]:
    with ctx.ex.engine.connect() as conn:
        s = train_repo.get_setup(conn, ctx.study["id"])
    if s is None:
        raise StepFailure("INPUT_INVALID", "학습 설정이 없습니다(①-1 파라미터 추출 먼저)")
    return s


def dg_prep(ctx: Any) -> None:
    s = ctx.settings
    p = ctx.params
    doe_id = p["doe_id"]
    setup = _setup(ctx)
    if not setup.get("tpl_rel") or not setup.get("cad_file_name"):
        raise StepFailure("INPUT_INVALID", "tpl이 생성되지 않았습니다")
    try:
        cp = check_user_path(p["radioss_assem_path"], allowed_roots(s, imports=True))
    except PathError as exc:
        raise path_failure(exc) from None
    D = _D(ctx)
    A = ctx.abs(f"01_train/radioss_assem/{doe_id}")
    os.makedirs(D, exist_ok=True)
    # ① 조립 폴더 직계 .rad·.inc → Study 사본(가정 A-6)
    copies: list[tuple[str, str]] = []
    for n in sorted(os.listdir(cp.path)):
        src = os.path.join(cp.path, n)
        if n.lower().endswith((".rad", ".inc")) and os.path.isfile(src) and not is_link_or_reparse(src):
            copies.append((src, os.path.join(A, n)))
    # ② D에 tpl·CAD·DOE 유형 json·include TCL
    tpl_src = ctx.abs(setup["tpl_rel"])
    if not os.path.isfile(tpl_src) or (setup.get("tpl_sha256") and sha256_file(tpl_src) != setup["tpl_sha256"]):
        raise StepFailure("INPUT_CHANGED", "생성된 tpl 파일이 없거나 바뀌었습니다 — tpl을 다시 생성하세요")
    cad_src = ctx.abs(f"01_train/cad/{setup['cad_file_name']}")
    if not os.path.isfile(cad_src):
        raise StepFailure("INPUT_CHANGED", "CAD 사본이 없습니다 — ①-1을 다시 실행하세요")
    res = s.resources
    for key in ("doe_design_type_json", "hypermesh_include_tcl"):
        if not getattr(res, key) or not os.path.isfile(getattr(res, key)):
            raise StepFailure("RESOURCE_MISSING", f"resources.{key} 파일이 없습니다: {getattr(res, key)}")
    copies += [
        (tpl_src, os.path.join(D, TPL_NAME)),
        (cad_src, os.path.join(D, setup["cad_file_name"])),
        (res.doe_design_type_json, os.path.join(D, "DATA_doe_design_type.json")),
        (res.hypermesh_include_tcl, os.path.join(D, os.path.basename(res.hypermesh_include_tcl))),
    ]
    ctx.backup([d for _s, d in copies if os.path.lexists(d)])
    for src, dst in copies:
        copy_file(src, dst, checkpoint=ctx.checkpoint)
    launcher = stage_launcher(ctx, "gen_radioss", D)
    # ③ INPUT_HST_RUN.json — 키는 원본 GUI:410-424 그대로
    alt = effective_altair(s)
    with ctx.ex.engine.connect() as conn:
        doe = train_repo.get_doe(conn, doe_id)
    num_runs = doe["num_runs_requested"] if doe["num_runs_requested"] is not None else int(p.get("default_runs") or 2)
    cfg = {
        "HST_EXECUTABLE": fwd(alt.get("hyperstudy_path", "")),
        "ALTAIR_PATHS": {k: fwd(alt.get(k, "") or "") for k in
                         ("hyperstudy_path", "simlab_path", "edspy_path", "hw_exe_path", "hvtrans_exe_path")},
        "DOE_NUM_RUNS": num_runs,
        "DIR_WORK": fwd(D),
        "CAD_PARAM": fwd(os.path.join(D, setup["cad_file_name"])),
        "RADIOSS_ASSEM_DIR": fwd(A),
        "DOE_TYPE": doe["doe_type"],
        "DOE_METHOD_OPTIONS": doe["options"] or {},
        "MULTI_EXECUTION": int(doe["multi_execution"]),
    }
    run_json = os.path.join(D, "INPUT_HST_RUN.json")
    ctx.backup([run_json])
    write_json(run_json, cfg)
    ctx.register_artifact("RUN_CONFIG", run_json, "application/json")
    # ④ 생성 시점 사용 파라미터 스냅샷·tpl sha
    snap = [{"name": q["name"], "nominal": q["nominal"], "min": q["min"], "max": q["max"], "format": q["format"],
             "unit": q.get("unit", "")} for q in tp.used(setup["parameters"])]
    ctx.ex.db(lambda c: train_repo.set_doe(c, doe_id, parameters_snapshot=snap, tpl_sha256=sha256_file(os.path.join(D, TPL_NAME))))
    ctx.patch_result({"doe_id": doe_id, "launcher_rel": ctx.rel(launcher), "num_runs": num_runs})


def hst_gen_radioss(ctx: Any) -> None:
    s = ctx.settings
    r = ctx.result()
    D = _D(ctx)
    doe = _doe(ctx)
    total = doe["num_runs_requested"]
    rx = re.compile(s.train_data.hst_progress_regex)

    def hook(line: str) -> tuple[float | None, str | None] | None:
        m = rx.search(line)
        if not m:
            return None
        run = int(m.group("run"))
        if total:
            return min(10 + run / total * 85, 95), f"run {run} 완료"  # 원본 FUNC:93-98
        return None, f"run {run} 완료"

    ctx.run_local("hst_gen_radioss", {"multi_execution": str(doe["multi_execution"]), "launcher": ctx.abs(r["launcher_rel"])},
                  cwd=D, error_patterns=list(s.train_data.hst_log_error_patterns), line_hook=hook)


def _find_starter(run_dir: str, starter_glob: str) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(run_dir, followlinks=False):
        dirnames.sort()
        for f in sorted(filenames):
            if fnmatch.fnmatch(f, starter_glob) and not f.lower().startswith("eps_mesh"):
                out.append(os.path.join(dirpath, f))
    return out


def dg_scan(ctx: Any) -> None:
    s = ctx.settings
    doe_id = ctx.params["doe_id"]
    D = _D(ctx)
    dirs = sorted((d for d in glob.glob(os.path.join(D, s.train_data.run_dir_glob)) if os.path.isdir(d)),
                  key=lambda d: (os.path.basename(d), d))
    runs: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for d in dirs:
        rk = os.path.basename(d)
        rel_dir = ctx.rel(d)
        if not RUN_KEY_RE.match(rk):
            skipped.append({"dir": rel_dir, "reason": "run 폴더 이름이 run_key 규칙에 맞지 않습니다"})
            continue
        if rk in seen:
            skipped.append({"run_key": rk, "reason": "같은 이름의 run 폴더가 여러 개입니다"})
            continue
        st = _find_starter(d, s.predict.starter_glob)
        if len(st) != 1:
            skipped.append({"run_key": rk, "reason": f"starter({s.predict.starter_glob})가 {len(st)}개"})
            continue
        seen.add(rk)
        runs.append({"run_key": rk, "input_rel": ctx.rel(os.path.dirname(st[0])), "starter_name": os.path.basename(st[0]),
                     "run_dir": d})
    for sk in skipped:
        ctx.add_warning("RUN_INPUT_INVALID", f"{sk.get('run_key') or sk.get('dir')}: {sk['reason']}")
    if not runs:
        raise StepFailure("OUTPUT_MISSING", "Radioss 입력 run 폴더를 찾지 못했습니다 — 설정 train_data.run_dir_glob 확인")
    doe = _doe(ctx)
    names = [q["name"] for q in doe["parameters_snapshot"]]
    sr = doe_samples.extract(D, [{"run_key": r["run_key"], "run_dir": r["run_dir"]} for r in runs], names, s.train_data)
    samples_rel = None
    if sr.rows:
        sp = os.path.join(D, "samples.csv")
        ctx.backup([sp])
        doe_samples.write_samples_csv(sp, names, sr.rows)
        ctx.register_artifact("DOE_SAMPLES", sp, "text/csv")
        samples_rel = ctx.rel(sp)
    if sr.status == "PARTIAL":
        ctx.add_warning("SAMPLES_PARTIAL", f"샘플 값을 찾지 못한 run {len(sr.missing_runs)}개: {', '.join(sr.missing_runs[:10])}")
    rj = os.path.join(D, "runs.json")
    ctx.backup([rj])
    write_json(rj, [{k: r[k] for k in ("run_key", "input_rel", "starter_name")} for r in runs])

    def reg(c: Any) -> None:
        train_repo.insert_runs(c, doe_id, runs)
        train_repo.set_doe(c, doe_id, run_count=len(runs), sample_status=sr.status, samples_rel=samples_rel, status="READY")

    ctx.ex.db(reg)
    ctx.log(f"run {len(runs)}개, 샘플 {sr.status}")
    ctx.patch_result({"doe_id": doe_id, "run_count": len(runs), "sample_status": sr.status, "skipped_runs": skipped})


HANDLERS = {
    ("TD_DOE_GEN", "DG_PREP"): dg_prep,
    ("TD_DOE_GEN", "HST_GEN_RADIOSS"): hst_gen_radioss,
    ("TD_DOE_GEN", "DG_SCAN"): dg_scan,
}
