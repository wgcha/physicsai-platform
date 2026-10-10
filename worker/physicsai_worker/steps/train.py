"""① 학습데이터 생성(phase2 §6.2, §6.4~§6.6.1): TD_EXTRACT_PARAMS, TD_DOE_GEN, TD_SOLVE, TD_RESULT_IMPORT, TD_RESP_EXTRACT."""

from __future__ import annotations

import csv
import fnmatch
import glob
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from physicsai_core import doe_samples
from physicsai_core import train_params as tp
from physicsai_core.commands import fwd
from physicsai_core.config import effective_altair
from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, sha256_file, write_json
from physicsai_core.hpc.command import map_path
from physicsai_core.hpc.gateway import HpcGatewayError, HpcSubmitSpec
from physicsai_core.param_sets import RUN_KEY_RE
from physicsai_core.parsers.name_value import read_name_value_csv
from physicsai_core.paths import PathError, check_user_path, is_link_or_reparse

from ..signals import EnterWaitingHpc
from . import _collect
from .common import path_failure
from .launcher import stage_launcher

TPL_REL = "01_train/tpl/simlab_parametered_mesh.tpl"
TPL_NAME = "simlab_parametered_mesh.tpl"


def _setup(ctx: Any) -> dict[str, Any]:
    with ctx.ex.engine.connect() as conn:
        s = train_repo.get_setup(conn, ctx.study["id"])
    if s is None:
        raise StepFailure("INPUT_INVALID", "학습 설정이 없습니다(①-1 파라미터 추출 먼저)")
    return s


def _doe(ctx: Any, doe_id: str | None = None) -> dict[str, Any]:
    did = doe_id or ctx.params.get("doe_id")
    with ctx.ex.engine.connect() as conn:
        d = train_repo.get_doe(conn, did) if did else None
    if d is None or d["study_id"] != ctx.study["id"]:
        raise StepFailure("INPUT_INVALID", "DOE를 찾을 수 없습니다")
    return d


def _tail(path: str, n: int = 2048) -> str:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - n))
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


# ===========================================================================
# ①-1 TD_EXTRACT_PARAMS
# ===========================================================================


def _X(ctx: Any) -> str:
    return ctx.abs(f"01_train/extract/{ctx.workspace_id}")


def tx_prep(ctx: Any) -> None:
    s = ctx.settings
    try:
        cp = check_user_path(ctx.params["cad_path"], [s.storage.ai_root, *s.storage.allowed_import_roots], expect="file")
    except PathError as exc:
        raise path_failure(exc) from None
    name = os.path.basename(cp.path)
    if os.path.splitext(name)[1].lower() not in [e.lower() for e in s.train_data.cad_extensions]:
        raise StepFailure("INPUT_INVALID", f"CAD 확장자가 허용 목록({s.train_data.cad_extensions})에 없습니다")
    dst = ctx.abs(f"01_train/cad/{name}")
    if os.path.realpath(dst) != os.path.realpath(cp.path):
        ctx.backup([dst])
        copy_file(cp.path, dst, checkpoint=ctx.checkpoint)
    sha = sha256_file(dst, ctx.checkpoint)
    X = _X(ctx)
    os.makedirs(X, exist_ok=True)
    launcher = stage_launcher(ctx, "extract_params", X)
    ctx.patch_result({"cad_file_name": name, "cad_sha256": sha, "launcher_rel": ctx.rel(launcher)})


def simlab_extract(ctx: Any) -> None:
    s = ctx.settings
    r = ctx.result()
    X = _X(ctx)
    launcher = ctx.abs(r["launcher_rel"])
    xml = os.path.join(X, "parameter_extracted.xml")  # 원본 GUI:239
    logfile = os.path.join(X, os.path.splitext(os.path.basename(launcher))[0] + "_LogFile.txt")
    token, total = s.train_data.extract_progress_token, s.train_data.extract_progress_total
    last = [0.0]

    def poll() -> tuple[float | None, str | None] | None:
        # 원본 get_simlab_progress(1_create_tpl_file.py:8-21): 'Passed' 개수 / total × 100, 상한 99. 2초마다
        if time.time() - last[0] < 2.0:
            return None
        last[0] = time.time()
        try:
            with open(logfile, encoding="utf-8", errors="ignore") as fh:
                cnt = fh.read().count(token)
        except OSError:
            return None
        return min(cnt / total * 100.0, 99.0), f"SimLab 진행 {cnt}/{total}"

    try:
        ctx.run_local("simlab_extract_params",
                      {"launcher": launcher, "cad_file": ctx.abs(f"01_train/cad/{r['cad_file_name']}"), "xml_out": xml},
                      cwd=X, outputs_to_backup=[xml, logfile], check_log_errors=False, poll_hook=poll)
        if not os.path.isfile(xml):
            raise StepFailure("OUTPUT_MISSING", "parameter_extracted.xml이 만들어지지 않았습니다")
    finally:
        if os.path.isfile(logfile):
            ctx.log(f"--- {os.path.basename(logfile)} 꼬리 ---\n{_tail(logfile)}")
    ctx.add_output(xml)


def tx_parse(ctx: Any) -> None:
    s = ctx.settings
    r = ctx.result()
    xml = os.path.join(_X(ctx), "parameter_extracted.xml")
    pairs = tp.read_extracted_xml(xml, s.train_data.max_xml_bytes)
    if not pairs:
        raise StepFailure("OUTPUT_MISSING", "추출 XML에 파라미터가 없습니다")
    params = tp.build_from_extracted(pairs, s.train_data.param_default_range_ratio, s.train_data.param_default_format)
    pj = ctx.abs("01_train/params.json")
    ctx.backup([pj])
    write_json(pj, {"schema_version": 1, "parameters": params})

    def upd(c: Any) -> None:
        train_repo.update_setup(
            c, ctx.study["id"], None, parameters=params, cad_source_path=ctx.params["cad_path"],
            cad_file_name=r["cad_file_name"], cad_sha256=r["cad_sha256"], extract_job_id=ctx.ex.job_id,
            tpl_params=None, updated_by=ctx.job["created_by"], updated_by_name=ctx.job["created_by_name"],
        )

    ctx.ex.db(upd)
    valid = sum(1 for p in params if p["valid"])
    ctx.log(f"파라미터 {len(params)}개 추출(유효 {valid}개)")
    ctx.patch_result({"param_count": len(params), "valid_count": valid, "cad_file_name": r["cad_file_name"]})


# ===========================================================================
# ①-3 TD_DOE_GEN
# ===========================================================================


def _D(ctx: Any, doe_id: str | None = None) -> str:
    return ctx.abs(f"01_train/doe/{doe_id or ctx.params['doe_id']}")


def dg_prep(ctx: Any) -> None:
    s = ctx.settings
    p = ctx.params
    doe_id = p["doe_id"]
    setup = _setup(ctx)
    if not setup.get("tpl_rel") or not setup.get("cad_file_name"):
        raise StepFailure("INPUT_INVALID", "tpl이 생성되지 않았습니다")
    try:
        cp = check_user_path(p["radioss_assem_path"], [s.storage.ai_root, *s.storage.allowed_import_roots])
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


# ===========================================================================
# ①-4 TD_SOLVE
# ===========================================================================


def _R(ctx: Any, doe_id: str, run_key: str) -> str:
    return ctx.abs(f"01_train/results/{doe_id}/{run_key}")


def ts_prep(ctx: Any) -> None:
    s = ctx.settings
    doe = _doe(ctx)
    if doe["status"] != "READY":
        raise StepFailure("INPUT_INVALID", "DOE가 READY가 아닙니다")
    keys = ctx.params.get("run_keys")
    with ctx.ex.engine.connect() as conn:
        runs = train_repo.runs_for_doe(conn, doe["id"])
        attempt = train_repo.count_solve_jobs(conn, doe["id"])
    by_key = {r["run_key"]: r for r in runs}
    if keys:
        unknown = [k for k in keys if k not in by_key]
        if unknown:
            raise StepFailure("INPUT_INVALID", f"DOE에 없는 run: {', '.join(unknown[:10])}")
        targets = list(keys)
    else:
        targets = [r["run_key"] for r in runs if r["state"] in train_repo.RESUBMIT_STATES]
    if not targets:
        raise StepFailure("INPUT_INVALID", "제출할 run이 없습니다")
    if len(targets) > s.train_data.max_runs_per_submit:
        raise StepFailure("INPUT_INVALID", f"한 번에 제출할 수 있는 run은 {s.train_data.max_runs_per_submit}개입니다")
    dirs = [_R(ctx, doe["id"], k) for k in targets]
    ctx.backup([d for d in dirs if os.path.lexists(d)])
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    ctx.patch_result({"doe_id": doe["id"], "run_keys": targets, "attempt": attempt})
    ctx.log(f"제출 대상 run {len(targets)}개 (attempt {attempt})")


def _remote_result_dir(ctx: Any, doe_id: str, run_key: str) -> tuple[str, str | None]:
    """(PBS result_dir, 회수할 로컬 경로 | None=in_place)."""
    t = ctx.settings.hpc.transfer
    if t.collect_mode in ("shared_folder", "drive"):
        sub = f"{ctx.study['folder_name']}/{doe_id}/{run_key}"
        remote = fwd(t.collect_root_remote).rstrip("/") + "/" + sub
        local = os.path.join(os.path.normpath(t.collect_root_local), ctx.study["folder_name"], doe_id, run_key)
        return remote, local
    return map_path(_R(ctx, doe_id, run_key), t.path_map), None


def ts_submit(ctx: Any) -> None:
    gw = ctx.ex.w.hpc
    av = gw.availability()
    if not av.configured:
        raise StepFailure("HPC_SUBMIT_FAILED", f"PBS 연결 안 됨: {av.message}")
    r = ctx.result()
    doe = _doe(ctx)
    hcfg = ctx.settings.hpc
    over = ctx.params.get("hpc") or {}
    with ctx.ex.engine.connect() as conn:
        by_key = {x["run_key"]: x for x in train_repo.runs_for_doe(conn, doe["id"])}
    submitted: list[tuple[str, str]] = []  # (hpc row id, external id)
    keys = r["run_keys"]
    n = len(keys)
    for k, rk in enumerate(keys, 1):
        run = by_key[rk]
        input_dir = ctx.abs(run["input_rel"])
        result_dir, _local = _remote_result_dir(ctx, doe["id"], rk)
        job_name = re.sub(r"[^A-Za-z0-9_\-]", "_", f"{ctx.study['folder_name']}_{doe['id'][:8]}_{rk}_a{r['attempt']}")[:64]
        spec = HpcSubmitSpec(
            job_name=job_name, run_key=rk, study=ctx.study["folder_name"],
            input_file=map_path(os.path.join(input_dir, run["starter_name"]), hcfg.transfer.path_map),
            input_dir=map_path(input_dir, hcfg.transfer.path_map), result_dir=result_dir,
            queue=over.get("queue"), ncpus=over.get("ncpus"), walltime=over.get("walltime"),
        )
        try:
            res = gw.submit(spec)
        except HpcGatewayError as exc:
            ctx.log(f"[FAIL] {rk} 제출 실패: {exc} — 이미 제출한 {len(submitted)}개를 취소합니다")
            for hid, ext in submitted:
                try:
                    gw.cancel(ext)
                except HpcGatewayError as cexc:
                    ctx.add_warning("HPC_CANCEL_FAILED", f"{ext} 취소 실패: {cexc}")

                def cancel_row(c: Any, hid: str = hid) -> None:
                    row = next(h for h in hpc_repo.for_job(c, ctx.ex.job_id) if h["id"] == hid)
                    hpc_repo.update_hpc(c, hid, row["version"], state="CANCELED", finished_at=datetime.now(timezone.utc))
                    train_repo.set_run_state_by_hpc(c, hid, "SOLVE_FAILED")

                ctx.ex.db(cancel_row)
            raise StepFailure("HPC_SUBMIT_FAILED", f"{rk} 제출 실패: {exc}") from None

        def ins(c: Any, rk: str = rk, ext: str = res.external_job_id) -> str:
            hid = hpc_repo.insert(c, job_id=ctx.ex.job_id, step_id=ctx.step["id"], run_key=rk, attempt_no=int(r["attempt"]),
                                  gateway_mode=av.mode, external_job_id=ext, submit_argv=None)
            train_repo.set_run(c, doe["id"], rk, state="SUBMITTED", hpc_job_id=hid, last_job_id=ctx.ex.job_id)
            return hid

        hid = ctx.ex.db(ins)
        submitted.append((hid, res.external_job_id))
        ctx.log(f"PBS 제출 [{k}/{n}] {rk}: {res.external_job_id}")
        ctx.progress(k / n * 100.0, f"제출 {k}/{n}")
    ctx.patch_result({"submitted": n})
    raise EnterWaitingHpc()


def _match_files(root: str, patterns: list[str]) -> dict[str, tuple[int, float]]:
    out: dict[str, tuple[int, float]] = {}
    if not os.path.isdir(root):
        return out
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != "_backup" and not is_link_or_reparse(os.path.join(dirpath, d)))
        for f in filenames:
            p = os.path.join(dirpath, f)
            if any(fnmatch.fnmatch(f, pat) for pat in patterns) and not is_link_or_reparse(p) and os.path.isfile(p):
                st = os.stat(p)
                out[os.path.relpath(p, root).replace(os.sep, "/")] = (st.st_size, st.st_mtime)
    return out


def _summary(root: str) -> dict[str, int]:
    h3d = t01 = files = total = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d != "_backup"]
        for f in filenames:
            p = os.path.join(dirpath, f)
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            files += 1
            total += os.path.getsize(p)
            h3d += f.lower().endswith(".h3d")
            t01 += f.endswith("T01")
    return {"h3d": h3d, "t01": t01, "files": files, "total_bytes": total}


def ts_collect(ctx: Any) -> None:
    """COLLECT(phase2 §6.5): 성공 run마다 collect_mode별 회수. run별 실패는 COLLECT_FAILED, 성공 0개면 실패."""
    s = ctx.settings
    r = ctx.result()
    doe = _doe(ctx)
    pats = s.hpc.transfer.collect_patterns
    limit = s.hpc.transfer.max_collect_bytes
    with ctx.ex.engine.connect() as conn:
        hj = [h for h in hpc_repo.for_job(conn, ctx.ex.job_id) if h["attempt_no"] == int(r["attempt"])]
    ok_rows = [h for h in hj if h["state"] == "SUCCEEDED"]
    failed_n = sum(1 for h in hj if h["state"] in ("FAILED", "LOST"))
    pending = {h["run_key"]: h for h in ok_rows}
    src_of = {}
    for rk in pending:
        _remote, local = _remote_result_dir(ctx, doe["id"], rk)
        src_of[rk] = local or _R(ctx, doe["id"], rk)
    collected: dict[str, list[str]] = {}
    failed: dict[str, str] = {}
    for attempt in range(1, 4):
        if not pending:
            break
        a = {rk: _match_files(src_of[rk], pats) for rk in pending}
        time.sleep(_collect.COLLECT_STABLE_INTERVAL_S)
        ctx.checkpoint()
        b = {rk: _match_files(src_of[rk], pats) for rk in pending}
        time.sleep(_collect.COLLECT_STABLE_INTERVAL_S)
        c = {rk: _match_files(src_of[rk], pats) for rk in pending}
        for rk in list(pending):
            if not (a[rk] and a[rk] == b[rk] == c[rk]):
                continue
            big = [n for n, (sz, _m) in c[rk].items() if sz > limit]
            if big:
                failed[rk] = f"회수 파일이 상한을 넘습니다: {big[0]}"
            else:
                dst_root = _R(ctx, doe["id"], rk)
                if src_of[rk] != dst_root:  # shared_folder·drive: 복사(원본은 지우지 않는다)
                    for rel in sorted(c[rk]):
                        copy_file(os.path.join(src_of[rk], *rel.split("/")), os.path.join(dst_root, *rel.split("/")),
                                  checkpoint=ctx.checkpoint)
                collected[rk] = sorted(c[rk])
            pending.pop(rk)
        if pending:
            ctx.log(f"회수 재시도 {attempt}/3: 남은 run {len(pending)}개(결과 파일 없음 또는 아직 바뀌는 중)")
    for rk in pending:
        failed[rk] = "결과 파일 없음 또는 아직 바뀌는 중"

    def rec(c: Any) -> None:
        for h in ok_rows:
            rk = h["run_key"]
            if rk in collected:
                hpc_repo.set_collect_state(c, h["id"], "COLLECTED", collected[rk])
            else:
                hpc_repo.set_collect_state(c, h["id"], "FAILED")
                train_repo.set_run(c, doe["id"], rk, state="COLLECT_FAILED")

    ctx.ex.db(rec)
    for rk, why in sorted(failed.items()):
        ctx.log(f"[COLLECT_FAILED] {rk}: {why}")
    ctx.patch_result({"submitted": len(hj), "failed": failed_n, "collected": len(collected),
                      "collected_runs": sorted(collected), "collect_failed": sorted(failed)})
    if not collected:
        raise StepFailure("COLLECT_FAILED", f"PBS 결과 회수 실패: {next(iter(failed.values()), '회수할 run이 없습니다')}")
    if failed:
        ctx.add_warning("COLLECT_PARTIAL", f"{len(ok_rows)}개 중 {len(failed)}개 회수 실패")


def _write_collected_json(ctx: Any, doe_id: str) -> None:
    with ctx.ex.engine.connect() as conn:
        runs = train_repo.runs_for_doe(conn, doe_id, states=["COLLECTED"])
    p = ctx.abs(f"01_train/results/{doe_id}/collected.json")
    ctx.backup([p])
    write_json(p, {"doe_id": doe_id, "updated_at": datetime.now(timezone.utc).isoformat(),
                   "runs": [{"run_key": x["run_key"], "result_rel": x["result_rel"], "summary": x["result_summary"],
                             "job_id": x["last_job_id"]} for x in runs]})


def ts_register(ctx: Any) -> None:
    r = ctx.result()
    doe = _doe(ctx)
    keys = r.get("collected_runs") or []

    def reg(c: Any) -> None:
        for rk in keys:
            rel = f"01_train/results/{doe['id']}/{rk}/"
            train_repo.set_run(c, doe["id"], rk, state="COLLECTED", result_rel=rel,
                               result_summary=_summary(_R(ctx, doe["id"], rk)), last_job_id=ctx.ex.job_id)

    ctx.ex.db(reg)
    _write_collected_json(ctx, doe["id"])
    with ctx.ex.engine.connect() as conn:
        solved = sum(1 for h in hpc_repo.for_job(conn, ctx.ex.job_id)
                     if h["attempt_no"] == int(r["attempt"]) and h["state"] == "SUCCEEDED")
    ctx.patch_result({"submitted": r.get("submitted"), "solved": solved, "failed": r.get("failed", 0), "collected": len(keys)})


# ===========================================================================
# ①-5 TD_RESULT_IMPORT
# ===========================================================================


def _import_roots(s: Any) -> list[str]:
    roots = [s.storage.ai_root, *s.storage.allowed_import_roots]
    if s.hpc.transfer.collect_root_local:
        roots.append(s.hpc.transfer.collect_root_local)
    return roots


def ri_scan(ctx: Any) -> None:
    s = ctx.settings
    doe = _doe(ctx)
    try:
        cp = check_user_path(ctx.params["source_path"], _import_roots(s))
    except PathError as exc:
        raise path_failure(exc) from None
    with ctx.ex.engine.connect() as conn:
        run_keys = {x["run_key"] for x in train_repo.runs_for_doe(conn, doe["id"])}
    matcher = tp.RunDirMatcher(s.train_data.result_run_dir_regex, run_keys)
    depth = s.train_data.result_match_depth
    found: dict[str, list[str]] = {}
    seen_dirs: list[str] = []
    base_depth = cp.path.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, _files in os.walk(cp.path, followlinks=False):
        d = dirpath.rstrip(os.sep).count(os.sep) - base_depth
        dirnames[:] = sorted(x for x in dirnames if x != "_backup" and not is_link_or_reparse(os.path.join(dirpath, x)))
        if d >= depth:
            dirnames[:] = []
            continue
        for x in dirnames:
            rk = matcher.match(x)  # run_key 그룹만 대소문자 무시(C13)
            if rk:
                found.setdefault(rk, []).append(os.path.join(dirpath, x))
            elif len(seen_dirs) < 20:
                seen_dirs.append(os.path.relpath(os.path.join(dirpath, x), cp.path).replace(os.sep, "/"))
    matched = {rk: v[0] for rk, v in found.items() if len(v) == 1}
    dups = sorted(rk for rk, v in found.items() if len(v) > 1)
    invalid = []
    for rk in dups:
        dirs = [os.path.relpath(x, cp.path).replace(os.sep, "/") for x in found[rk]]
        invalid.append({"run_key": rk, "reason": "같은 run의 결과 폴더가 여러 개", "dirs": dirs[:10]})
        ctx.add_warning("RUN_FOLDER_DUPLICATE", f"{rk}: 결과 폴더가 {len(dirs)}개({', '.join(dirs[:3])}) — 이 run은 가져오지 않습니다. 하나만 남기고 다시 실행하세요")
    if not matched:
        if dups:
            raise StepFailure("INPUT_INVALID", f"모든 run의 결과 폴더가 중복입니다: {', '.join(dups[:10])} — run마다 폴더를 하나만 두세요")
        raise StepFailure("INPUT_INVALID", "run 폴더를 찾지 못했습니다 — 하위 폴더: " + ", ".join(seen_dirs[:20]))
    ctx.patch_result({"source_path": cp.path, "matches": {rk: matched[rk] for rk in sorted(matched)},
                      "duplicate_runs": dups, "invalid_runs": invalid, "unmatched_dirs": seen_dirs[:20]})


def ri_copy(ctx: Any) -> None:
    s = ctx.settings
    r = ctx.result()
    doe = _doe(ctx)
    plan: list[tuple[str, str, int]] = []
    for rk, src in r["matches"].items():
        files = _match_files(src, s.hpc.transfer.collect_patterns)
        for rel, (size, _m) in sorted(files.items()):
            if size > s.hpc.transfer.max_collect_bytes:
                raise StepFailure("INPUT_INVALID", f"{rk}/{rel}: 파일이 상한(max_collect_bytes)을 넘습니다")
            plan.append((os.path.join(src, *rel.split("/")), os.path.join(_R(ctx, doe["id"], rk), *rel.split("/")), size))
    total = sum(x[2] for x in plan) or 1
    ctx.backup([_R(ctx, doe["id"], rk) for rk in r["matches"] if os.path.lexists(_R(ctx, doe["id"], rk))])
    done = [0]
    for src, dst, _size in plan:
        base = done[0]
        copy_file(src, dst, progress=lambda b, base=base: ctx.progress((base + b) / total * 100.0, "결과 복사"),
                  checkpoint=ctx.checkpoint)
        done[0] += _size
    for rk in r["matches"]:
        os.makedirs(_R(ctx, doe["id"], rk), exist_ok=True)
    ctx.patch_result({"copied_files": len(plan), "total_bytes": sum(x[2] for x in plan)})


def ri_register(ctx: Any) -> None:
    r = ctx.result()
    doe = _doe(ctx)
    keys = sorted(r["matches"])

    def reg(c: Any) -> None:
        for rk in keys:
            train_repo.set_run(c, doe["id"], rk, state="COLLECTED", result_rel=f"01_train/results/{doe['id']}/{rk}/",
                               result_summary=_summary(_R(ctx, doe["id"], rk)), last_job_id=ctx.ex.job_id)

    ctx.ex.db(reg)
    _write_collected_json(ctx, doe["id"])
    with ctx.ex.engine.connect() as conn:
        all_keys = [x["run_key"] for x in train_repo.runs_for_doe(conn, doe["id"])]
    missing = [k for k in all_keys if k not in r["matches"]]
    ctx.patch_result({"matched": len(keys), "copied_files": r.get("copied_files", 0), "total_bytes": r.get("total_bytes", 0),
                      "unmatched_dirs": (r.get("unmatched_dirs") or [])[:20], "missing_runs": missing[:5000]})


# ===========================================================================
# ①-6 TD_RESP_EXTRACT
# ===========================================================================


def rx_prep(ctx: Any) -> None:
    doe = _doe(ctx)
    D = _D(ctx, doe["id"])
    rj = os.path.join(D, "responses.json")
    ctx.backup([rj])
    write_json(rj, {"responses": ctx.params["responses"]})
    with ctx.ex.engine.connect() as conn:
        runs = train_repo.runs_for_doe(conn, doe["id"], states=["COLLECTED"])
    targets = []
    for x in runs:
        R = _R(ctx, doe["id"], x["run_key"])
        h3ds = sorted(_match_files(R, ["*.h3d", "*.H3D"]))
        if not h3ds:
            ctx.add_warning("RUN_H3D_MISSING", f"{x['run_key']}: h3d가 없어 건너뜁니다")
            continue
        targets.append({"run_key": x["run_key"], "h3d": os.path.join(R, *h3ds[0].split("/"))})
    if not targets:
        raise StepFailure("INPUT_INVALID", "응답을 추출할 h3d가 있는 run이 없습니다")
    ctx.patch_result({"doe_id": doe["id"], "targets": targets})


def rx_extract(ctx: Any) -> None:
    doe = _doe(ctx)
    rj = os.path.join(_D(ctx, doe["id"]), "responses.json")
    targets = []
    for t in ctx.result()["targets"]:
        R = _R(ctx, doe["id"], t["run_key"])
        out = os.path.join(R, "responses_run.csv")
        ctx.backup([out])
        targets.append({"target_id": t["run_key"], "cwd": R, "out": out,
                        "values": {"pred_h3d": t["h3d"], "pred_h3d_fwd": fwd(t["h3d"]), "responses_json": rj,
                                   "out_csv": out, "work_dir": R}})
    res = ctx.run_fanout("response_extract", targets, cwd=_D(ctx, doe["id"]), success=lambda t: os.path.isfile(t["out"]))
    ctx.patch_result({"extracted_runs": res["ok"], "extract_failed": [f["target_id"] for f in res["failed"]]})


def rx_table(ctx: Any) -> None:
    doe = _doe(ctx)
    names = [r["name"] for r in ctx.params["responses"]]
    rows = []
    for rk in ctx.result().get("extracted_runs") or []:
        vals = read_name_value_csv(os.path.join(_R(ctx, doe["id"], rk), "responses_run.csv"))
        rows.append([rk, *["" if vals.get(n) is None else repr(vals[n]) for n in names]])
    out = os.path.join(_D(ctx, doe["id"]), "run_responses.csv")
    ctx.backup([out])
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["run_key", *names])
        w.writerows(rows)
    ctx.ex.db(lambda c: train_repo.set_doe(c, doe["id"], responses_rel=ctx.rel(out)))
    ctx.patch_result({"run_count": len(rows)})


HANDLERS = {
    ("TD_EXTRACT_PARAMS", "TX_PREP"): tx_prep,
    ("TD_EXTRACT_PARAMS", "SIMLAB_EXTRACT"): simlab_extract,
    ("TD_EXTRACT_PARAMS", "TX_PARSE"): tx_parse,
    ("TD_DOE_GEN", "DG_PREP"): dg_prep,
    ("TD_DOE_GEN", "HST_GEN_RADIOSS"): hst_gen_radioss,
    ("TD_DOE_GEN", "DG_SCAN"): dg_scan,
    ("TD_SOLVE", "TS_PREP"): ts_prep,
    ("TD_SOLVE", "HPC_SUBMIT"): ts_submit,
    ("TD_SOLVE", "COLLECT"): ts_collect,
    ("TD_SOLVE", "TS_REGISTER"): ts_register,
    ("TD_RESULT_IMPORT", "RI_SCAN"): ri_scan,
    ("TD_RESULT_IMPORT", "RI_COPY"): ri_copy,
    ("TD_RESULT_IMPORT", "RI_REGISTER"): ri_register,
    ("TD_RESP_EXTRACT", "RX_PREP"): rx_prep,
    ("TD_RESP_EXTRACT", "RESPONSE_EXTRACT_RUNS"): rx_extract,
    ("TD_RESP_EXTRACT", "RX_TABLE"): rx_table,
}
