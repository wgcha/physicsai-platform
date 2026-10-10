"""①-1 TD_EXTRACT_PARAMS: CAD에서 SimLab 파라미터 추출(phase2 §6.2)."""

from __future__ import annotations

import os
import time
from typing import Any

from physicsai_core import train_params as tp
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, sha256_file, write_json
from physicsai_core.paths import allowed_roots, check_user_path, PathError

from ..common import path_failure
from ..launcher import stage_launcher


def _tail(path: str, n: int = 2048) -> str:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - n))
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _X(ctx: Any) -> str:
    return ctx.abs(f"01_train/extract/{ctx.workspace_id}")


def tx_prep(ctx: Any) -> None:
    s = ctx.settings
    try:
        cp = check_user_path(ctx.params["cad_path"], allowed_roots(s, imports=True), expect="file")
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


HANDLERS = {
    ("TD_EXTRACT_PARAMS", "TX_PREP"): tx_prep,
    ("TD_EXTRACT_PARAMS", "SIMLAB_EXTRACT"): simlab_extract,
    ("TD_EXTRACT_PARAMS", "TX_PARSE"): tx_parse,
}
