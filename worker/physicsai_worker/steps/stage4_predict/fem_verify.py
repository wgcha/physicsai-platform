"""④ FEM_VERIFY step 1~6(phase3 §21.3.5 S16): FV_PREP · FV_MESH · FV_ASSEMBLE · HPC_SUBMIT · COLLECT(HPC_WAIT는 폴러).

폴더 `F = <study>/{fem_verify.dir_name}/FV-NNN`, 시도 `F/a<n>`(mesh·assem·input·result·extract·curves·media). 조립 원본은
읽기만 하고 스냅숏 복사(SPDM은 열린 핸들 기준, 하드링크 없음). 메시 교체는 기존 m_2(`commands.mesh`)·`assemble_into` 재사용.
비교 step(7~10)은 fem_compare.py."""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any

from physicsai_core.db.repositories import fem_verifications as fv_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, write_json
from physicsai_core.stage4_predict import fem_assembly
from physicsai_core.stage4_predict.prepared_input import is_mesh_file

from simdash_adapters.hpc import scx_naming as _scx_naming

from ...signals import StepSkipped
from . import _verify_hpc
from .predict_inputs import LOG_BATCH, _append_log_batch, _judge_output, assemble_into, mesh_log_warning, mesh_preflight

SUBDIRS = ("mesh", "assem", "input", "result", "extract/pred", "extract/fem", "curves", "media/pred", "media/fem")
REUSE_SKIP = "예측 입력 재사용"


# ---- 공용 -------------------------------------------------------------------------------------------


def row(ctx: Any) -> dict[str, Any]:
    with ctx.ex.engine.connect() as conn:
        r = fv_repo.get(conn, ctx.params["fem_verify_id"])
    if r is None:
        raise StepFailure("INPUT_INVALID", "FEM 검증 행을 찾을 수 없습니다")
    return r


def predict_job(ctx: Any, r: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """(비교 대상 예측 P, P의 재시도 root id)."""
    with ctx.ex.engine.connect() as conn:
        pj = jobs_repo.get_job(conn, r["predict_job_id"]) if r.get("predict_job_id") else None
        if pj is None:
            raise StepFailure("INPUT_INVALID", "비교할 예측 작업이 없습니다")
        return pj, jobs_repo.root_job_id(conn, pj)


def attempt_dir(ctx: Any) -> str:
    rel = ctx.result().get("fv_rel")
    if not rel:
        raise StepFailure("INPUT_INVALID", "FEM 검증 시도 폴더가 없습니다(FV_PREP 먼저)")
    return ctx.abs(rel)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _mesh_source(ctx: Any, pj: dict[str, Any], root: str) -> str | None:
    batch_dir = run_key = None
    ref = pb_repo.batch_run_ref(pj)
    if ref is not None:
        with ctx.ex.engine.connect() as conn:
            b = pb_repo.get(conn, ref[0])
            run = next((x for x in pb_repo.runs(conn, ref[0]) if x["doe_no"] == ref[1]), None)
        if b is not None and run is not None:
            batch_dir, run_key = b["dir_rel"], run["run_key"]
    rel = fem_assembly.mesh_source_rel(pj, root, ctx.settings, batch_dir_rel=batch_dir, run_key=run_key)
    return ctx.abs(rel) if rel else None


def _assembly_path(ctx: Any, r: dict[str, Any]) -> str:
    ref = r.get("assem_ref") or {}
    if r["assem_kind"] == "TRAIN_DOE":
        with ctx.ex.engine.connect() as conn:
            doe = train_repo.get_doe(conn, ref.get("doe_id") or "")
        if doe is None or doe["status"] != "READY":
            raise StepFailure("INPUT_CHANGED", "① DOE 조립 폴더를 찾을 수 없습니다(READY 아님)")
        return ctx.abs(doe["assem_rel"])
    path = ref.get("path") or ""
    fem_assembly.check_custom_path(path, ctx.settings)  # 경로 규칙 재검사(PathError → 아래에서 INPUT_CHANGED)
    return path


# ---- 1 FV_PREP ---------------------------------------------------------------------------------------


def fv_prep(ctx: Any) -> None:
    r = row(ctx)
    pj, root = predict_job(ctx, r)
    if pj["state"] != "SUCCEEDED":
        raise StepFailure("INPUT_INVALID", "비교할 예측이 성공한 상태가 아닙니다")
    s = ctx.settings
    n = int(r["attempt_no"]) + 1
    ctx.ex.db(lambda c: fv_repo.set_row(c, r["id"], attempt_no=n))
    F = ctx.abs(r["dir_rel"])
    A = os.path.join(F, f"a{n}")
    if os.path.lexists(A):
        ctx.backup([A])
    for d in SUBDIRS:
        os.makedirs(os.path.join(A, *d.split("/")), exist_ok=True)
    res: dict[str, Any] = {"fv_rel": ctx.rel(A), "attempt": n, "input_mode": r["input_mode"], "assem_files": []}
    assem_info: dict[str, Any] = {"kind": r["assem_kind"], "path": None, "files": []}
    if r["input_mode"] == "rebuild":
        src = _mesh_source(ctx, pj, root)
        mesh_name = s.predict.simlab_mesh_name
        if not src or not os.path.isfile(src):
            raise StepFailure("INPUT_MISSING", "예측 폴더에 형상 메시가 없습니다(정리됨 또는 준비된 입력)")
        copy_file(src, os.path.join(A, "mesh", mesh_name), checkpoint=ctx.checkpoint)
        res["mesh_rel"] = ctx.rel(os.path.join(A, "mesh", mesh_name))
        try:
            path = _assembly_path(ctx, r)
        except StepFailure:
            raise
        except Exception as exc:  # noqa: BLE001 - PathError 등: 생성 뒤 경로가 바뀜
            raise StepFailure("INPUT_CHANGED", f"조립 원본 경로를 쓸 수 없습니다: {getattr(exc, 'message', exc)}") from None
        plan = fem_assembly.plan_assembly(path, s)
        if plan["problems"]:
            p0 = plan["problems"][0]
            raise StepFailure("INPUT_CHANGED", f"조립 원본이 바뀌었습니다: {p0['message']}"[:480])
        if fem_assembly.changed((r.get("options") or {}).get("assem_signature"), plan["signature"]):
            raise StepFailure("INPUT_CHANGED", "조립 원본 파일이 생성 때와 다릅니다(파일 목록·크기·수정 시각) — 새로 만드세요")
        names = fem_assembly.snapshot(path, os.path.join(A, "assem"), plan["files"], checkpoint=ctx.checkpoint)
        res["assem_files"] = names
        assem_info.update(path=path, files=[{"name": x, "sha256": _sha256(os.path.join(A, "assem", x))} for x in names])
        for w in plan["warnings"]:
            ctx.add_warning(w["code"], w["message"])
        ctx.log(f"조립 원본 스냅숏 {len(names)}개 → {os.path.join(A, 'assem')}")
    else:
        src = ctx.abs(f"04_predict/{root}/INPUT")
        if not os.path.isdir(src):
            raise StepFailure("INPUT_MISSING", "예측 INPUT 폴더가 없습니다(정리됨)")
        names = []
        for x in sorted(os.listdir(src)):
            p = os.path.join(src, x)
            if not os.path.isfile(p):
                continue
            why = fem_assembly.assembly_name_problem(p, src)
            if why:
                raise StepFailure("INPUT_INVALID", f"{x}: {why}")
            copy_file(p, os.path.join(A, "input", x), checkpoint=ctx.checkpoint)
            names.append(x)
        starter = (pj.get("result") or {}).get("starter")
        if not starter or is_mesh_file(starter) or starter not in names:
            raise StepFailure("INPUT_INVALID", "예측 입력의 starter가 조립 상태가 아닙니다(쿠션 메시뿐)")
        res["starter"] = starter
        res["assem_files"] = names
        assem_info.update(path=src, files=[{"name": x, "sha256": _sha256(os.path.join(A, "input", x))} for x in names])
    parts_src = [os.path.join(A, "mesh", s.predict.simlab_mesh_name), os.path.join(A, "input", s.predict.mesh_include_name),
                 os.path.join(A, "input", s.predict.simlab_mesh_name)]
    res["cushion_part_ids"] = next((fem_assembly.mesh_part_ids(p) for p in parts_src if os.path.isfile(p)), [])
    with ctx.ex.engine.connect() as conn:
        m = models_repo.get(conn, (pj.get("result") or {}).get("model_id") or (pj.get("params") or {}).get("model_id") or "")
    vj = os.path.join(F, "verify.json")
    if os.path.lexists(vj):
        ctx.backup([vj])
    write_json(vj, {"fv_no": r["fv_no"], "attempt": n, "source_kind": r["source_kind"], "source_ref": r["source_ref"],
                    "predict_job_id": pj["id"], "model": {"id": m["id"], "psmdl_sha256": m["psmdl_sha256"]} if m else None,
                    "input_mode": r["input_mode"], "assembly": assem_info})
    ctx.patch_result(res)


# ---- 2 FV_MESH ---------------------------------------------------------------------------------------


def fv_mesh(ctx: Any) -> None:
    res = ctx.result()
    if res.get("input_mode") != "rebuild":
        raise StepSkipped(REUSE_SKIP)
    s = ctx.settings
    if s.commands.mesh is None:
        raise StepFailure("TEMPLATE_NOT_CONFIGURED", "메시 변환 명령 템플릿(mesh)이 설정되지 않았습니다")
    A = attempt_dir(ctx)
    M = os.path.join(A, "mesh")
    v = {"include_tcl": s.resources.hypermesh_include_tcl, "simlab_mesh": os.path.join(M, s.predict.simlab_mesh_name),
         "mesh_inc": os.path.join(M, s.predict.mesh_include_name),
         "renum_csv": os.path.join(A, "assem", s.predict.renum_csv_name), "work_dir": M}
    for w in mesh_preflight(s, v["renum_csv"]):
        ctx.add_warning(*w)
    log_batch = os.path.join(M, LOG_BATCH)
    rc = ctx.run_local("mesh", v, cwd=M, outputs_to_backup=[v["mesh_inc"], log_batch], allow_nonzero_exit=True)
    text = _append_log_batch(ctx, log_batch) if os.path.isfile(log_batch) else ""
    w = mesh_log_warning(s, text)
    if w:
        ctx.add_warning(*w)
    _judge_output(ctx, rc, v["mesh_inc"], "메시 변환")


# ---- 3 FV_ASSEMBLE -----------------------------------------------------------------------------------


def fv_assemble(ctx: Any) -> None:
    res = ctx.result()
    A = attempt_dir(ctx)
    inp = os.path.join(A, "input")
    s = ctx.settings
    if res.get("input_mode") != "rebuild":
        starter = res.get("starter")
        if not starter or not os.path.isfile(os.path.join(inp, starter)):
            raise StepFailure("INPUT_INVALID", "해석 입력에 starter가 없습니다")
        return
    if os.path.isdir(inp) and os.listdir(inp):
        ctx.backup([os.path.join(inp, n) for n in os.listdir(inp)])
    os.makedirs(inp, exist_ok=True)
    starter, warnings = assemble_into(s, os.path.join(A, "assem"), os.path.join(A, "mesh", s.predict.mesh_include_name), inp,
                                      checkpoint=ctx.checkpoint, log=ctx.log)
    for w in warnings:
        ctx.add_warning(*w)
    if s.commands.rad_assemble is not None:
        ctx.run_local("rad_assemble", {"work_dir": A, "starter": os.path.join(inp, starter), "input_dir": inp}, cwd=inp)
    if is_mesh_file(starter):
        raise StepFailure("INPUT_INVALID", f"조립 결과 starter가 쿠션 메시 파일입니다: {starter}")
    ctx.patch_result({"starter": starter})


# ---- 4 HPC_SUBMIT · 6 COLLECT -----------------------------------------------------------------------


def hpc_submit(ctx: Any) -> None:
    res = ctx.result()
    A = attempt_dir(ctx)
    fv_no = int(ctx.params["fv_no"])
    n = int(res["attempt"])
    job_name = re.sub(r"[^A-Za-z0-9_\-]", "_", f"{ctx.study['folder_name']}_fv{fv_no:03d}_a{n}")[:64]
    _verify_hpc.submit(ctx, input_dir=os.path.join(A, "input"), result_dir=os.path.join(A, "result"),
                       starter=res.get("starter") or "", job_name=job_name, attempt=n,
                       scx_job_name=lambda ts: _scx_naming.fem_verify_job_name(fv_no, ts))


def collect(ctx: Any) -> None:
    _verify_hpc.collect(ctx, os.path.join(attempt_dir(ctx), "result"))


HANDLERS = {
    ("FEM_VERIFY", "FV_PREP"): fv_prep,
    ("FEM_VERIFY", "FV_MESH"): fv_mesh,
    ("FEM_VERIFY", "FV_ASSEMBLE"): fv_assemble,
    ("FEM_VERIFY", "HPC_SUBMIT"): hpc_submit,
    ("FEM_VERIFY", "COLLECT"): collect,
}
