"""2차 작업 params 스키마·사전조건(phase2 §6.1.1, §12.9, §12.10). 알 수 없는 키는 422(1차 §10.6)."""

from __future__ import annotations

import fnmatch
import math
import os
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from physicsai_core import curation as cu
from physicsai_core import doe_types as dt_mod
from physicsai_core import optimize as opt
from physicsai_core import spdm
from physicsai_core import train_params as tp
from physicsai_core.db.repositories import curations as cur_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import spdm_imports as imp_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.db.tables import curations, spdm_imports, train_does
from physicsai_core.errors import DomainError
from physicsai_core.features import JOB_FEATURE, missing_for
from physicsai_core.param_sets import NAME_RE
from physicsai_core.paths import check_dataset_input, check_user_path, resolve_in_study
from physicsai_core.train_tpl import tpl_params_snapshot

from ..context import AppContext
from .common import study_root

RUN_KEY_PATTERN = r"^[A-Za-z0-9_\-]{1,64}$"


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class HpcOverrides(_P):
    queue: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.\-@]{1,64}$")
    ncpus: int | None = Field(default=None, ge=1, le=4096)
    walltime: str | None = Field(default=None, pattern=r"^\d{1,4}:\d{2}:\d{2}$")


class TrainDoeSource(_P):
    kind: Literal["TRAIN_DOE"]
    doe_id: str


class SpdmImportSource(_P):
    kind: Literal["SPDM_IMPORT"]
    import_id: str


class FolderSource(_P):
    kind: Literal["FOLDER"]
    path: str = Field(max_length=400)


Source = Annotated[TrainDoeSource | SpdmImportSource | FolderSource, Field(discriminator="kind")]


class TdExtractParams(_P):
    cad_path: str = Field(max_length=400)


class TdDoeGenParams(_P):
    doe_label: str = Field(max_length=120)
    num_runs: int | None = Field(default=None, ge=2)
    options: dict[str, Any] = Field(default_factory=dict)
    multi_execution: int = Field(default=1, ge=1)
    radioss_assem_path: str = Field(max_length=400)


class TdSolveParams(_P):
    doe_id: str
    run_keys: list[Annotated[str, Field(pattern=RUN_KEY_PATTERN)]] | None = None
    hpc: HpcOverrides | None = None
    on_run_failure: Literal["collect_partial", "fail"] = "collect_partial"


class TdResultImportParams(_P):
    doe_id: str
    source_path: str = Field(max_length=400)


class ResponseDefIn(_P):
    name: str = Field(pattern=NAME_RE.pattern)
    unit: str = Field(default="", max_length=40)
    spec: dict[str, Any] = Field(default_factory=dict)


class TdRespExtractParams(_P):
    doe_id: str
    responses: list[ResponseDefIn] = Field(min_length=1)


class PreviewParams(_P):
    source: Source
    sample_file: str | None = Field(default=None, max_length=400)


class SelItem(_P):
    datatype: str = Field(min_length=1, max_length=200)
    component: str = Field(min_length=1, max_length=200)


class SelParts(_P):
    shell: list[int] = Field(default_factory=list)
    solid: list[int] = Field(default_factory=list)
    rbody: list[int] = Field(default_factory=list)


class Selection(_P):
    items: list[SelItem]
    parts: SelParts = Field(default_factory=SelParts)
    time_increment: int = Field(default=1, ge=1)


class H3dCurateParams(_P):
    source: Source
    preview_job_id: str
    selection: Selection
    exclude_files: list[str] = Field(default_factory=list)


class CurveIn(_P):
    type: str = Field(min_length=1, max_length=200)
    request: str = Field(min_length=1, max_length=200)
    component: str = Field(min_length=1, max_length=200)


class T01CurvesParams(_P):
    source: Source
    curves: list[CurveIn] = Field(min_length=1)
    exclude_files: list[str] = Field(default_factory=list)


class SpdmImportParams(_P):
    spdm_path: str = Field(max_length=400)


class OptSettings(_P):
    abs_convergence: float = Field(default=0.001, ge=1e-6, le=1000)
    rel_convergence: float = Field(default=1.0, ge=1e-6, le=1000)
    dv_convergence: float = Field(default=0.001, ge=0, le=1000)


class OptimizeParams(_P):
    param_set_id: str | None = None
    model_id: str | None = None
    approach: Literal["OPT", "DOE"] = "OPT"
    opt_method: Literal["ARSM", "GRSM", "SQP"] = "ARSM"
    max_designs: int = Field(default=25, ge=1, le=100000)
    run_nominal: bool = True
    study_folder: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_\-]{1,64}$")
    opt_settings: OptSettings = Field(default_factory=OptSettings)
    on_failed: Literal["IGNORE", "TERMINATE"] = "IGNORE"
    responses: list[dict[str, Any]]

    @field_validator("responses")
    @classmethod
    def _finite(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for r in v:
            x = r.get("value") if isinstance(r, dict) else None
            if isinstance(x, float) and not math.isfinite(x):
                raise ValueError("value는 유한해야 합니다")
        return v


PARAM_MODELS: dict[str, type[BaseModel]] = {
    "TD_EXTRACT_PARAMS": TdExtractParams,
    "TD_DOE_GEN": TdDoeGenParams,
    "TD_SOLVE": TdSolveParams,
    "TD_RESULT_IMPORT": TdResultImportParams,
    "TD_RESP_EXTRACT": TdRespExtractParams,
    "CU_H3D_PREVIEW": PreviewParams,
    "CU_T01_PREVIEW": PreviewParams,
    "CU_H3D_CURATE": H3dCurateParams,
    "CU_T01_CURVES": T01CurvesParams,
    "SPDM_IMPORT": SpdmImportParams,
    "OPTIMIZE": OptimizeParams,
}


def _missing(*items: str) -> DomainError:
    return DomainError("PREREQUISITE_MISSING", "사전 조건이 충족되지 않았습니다", status=409, missing=list(items))


def _invalid(loc: str, msg: str, code: str = "INVALID_PARAMS", **extra: Any) -> DomainError:
    return DomainError(code, msg, status=422, errors=[{"loc": ["params", *loc.split(".")], "msg": msg}], **extra)


def check_feature(ctx: AppContext, job_type: str) -> None:
    req = JOB_FEATURE.get(job_type)
    if req is None:
        return
    tmpl, res = missing_for(ctx.settings, req, None)
    if tmpl:
        raise DomainError("TEMPLATE_NOT_CONFIGURED", f"명령 템플릿이 설정되지 않았습니다: {', '.join(tmpl)}", status=409,
                          template=tmpl[0].split(".", 1)[1], missing=tmpl)
    if res:
        raise DomainError("RESOURCE_NOT_CONFIGURED", f"관리자 설정 필요: {', '.join(res[:3])}", status=409, missing=res)


def _ready_doe(conn: Any, sid: str, doe_id: str) -> dict[str, Any]:
    d = train_repo.get_doe(conn, doe_id)
    if d is None or d["study_id"] != sid or d["status"] != "READY":
        raise DomainError("DOE_NOT_READY", "READY 상태의 DOE가 필요합니다", status=409)
    return d


def starters_in(folder: str, glob_: str) -> list[str]:
    return sorted(n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n))
                  and fnmatch.fnmatch(n, glob_) and not n.lower().startswith("eps_mesh"))


def resolve_source(ctx: AppContext, conn: Any, study: dict[str, Any], source: Any) -> tuple[dict[str, Any], str]:
    """원천 확인(§4.4) → (저장할 source 객체, 루트 절대경로)."""
    sid = study["id"]
    root_dir = study_root(ctx, study)
    if source.kind == "TRAIN_DOE":
        d = train_repo.get_doe(conn, source.doe_id)
        if d is None or d["study_id"] != sid or d["status"] != "READY":
            raise DomainError("DOE_NOT_READY", "READY 상태의 DOE가 필요합니다", status=409)
        return {"kind": "TRAIN_DOE", "doe_id": d["id"]}, resolve_in_study(root_dir, f"01_train/results/{d['id']}")
    if source.kind == "SPDM_IMPORT":
        i = imp_repo.get_import(conn, source.import_id)
        if i is None or i["study_id"] != sid or i["status"] != "READY":
            raise _missing("READY_SPDM_IMPORT")
        return {"kind": "SPDM_IMPORT", "import_id": i["id"]}, resolve_in_study(root_dir, f"02_import/{i['id']}")
    cp = check_user_path(source.path, [ctx.settings.storage.ai_root])
    check_dataset_input(cp.path, ctx.settings.storage.ai_root)
    return {"kind": "FOLDER", "path": cp.path}, cp.path


def _source_files(ctx: AppContext, root: str, kind: str) -> list[str]:
    files = cu.collect_files(root, kind, ctx.settings.curation.max_files) if os.path.isdir(root) else []
    if not files:
        raise _missing("SOURCE_FILES")
    return files


def _preview_summary(ctx: AppContext, conn: Any, study: dict[str, Any], preview_job_id: str) -> dict[str, Any]:
    import json

    pj = jobs_repo.get_job(conn, preview_job_id)
    if pj is None or pj["study_id"] != study["id"] or pj["job_type"] != "CU_H3D_PREVIEW" or pj["state"] != "SUCCEEDED":
        raise DomainError("CURATION_PREVIEW_REQUIRED", "같은 Study의 완료된 h3d 미리보기가 필요합니다", status=409)
    root = jobs_repo.root_job_id(conn, pj)
    p = resolve_in_study(study_root(ctx, study), f"02_preview/{root}/preview_summary.json")
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        raise DomainError("CURATION_PREVIEW_REQUIRED", "미리보기 결과 파일을 읽을 수 없습니다. 미리보기를 다시 실행하세요", status=409) from None


def tpl_is_stale(setup: dict[str, Any]) -> bool:
    if not setup.get("tpl_rel"):
        return False
    return setup.get("tpl_params") != tpl_params_snapshot(tp.used(setup.get("parameters") or []))


def prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any
            ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    cfg = ctx.settings
    sid = study["id"]
    check_feature(ctx, job_type)
    if job_type == "TD_EXTRACT_PARAMS":
        cp = check_user_path(p.cad_path, [cfg.storage.ai_root, *cfg.storage.allowed_import_roots], expect="file")
        if os.path.splitext(cp.path)[1].lower() not in [e.lower() for e in cfg.train_data.cad_extensions]:
            raise _invalid("cad_path", f"CAD 확장자는 {', '.join(cfg.train_data.cad_extensions)} 중 하나여야 합니다")
        return {"cad_path": cp.path}, None, []
    if job_type == "TD_DOE_GEN":
        setup = train_repo.get_setup(conn, sid)
        if setup is None or not setup.get("tpl_rel"):
            raise DomainError("TPL_REQUIRED", "tpl을 먼저 생성하세요(①-2)", status=409)
        if tpl_is_stale(setup):
            raise DomainError("TPL_STALE", "파라미터 표가 바뀌었습니다 — tpl을 다시 생성하세요", status=409)
        cp = check_user_path(p.radioss_assem_path, [cfg.storage.ai_root, *cfg.storage.allowed_import_roots])
        st = starters_in(cp.path, cfg.predict.starter_glob)
        if len(st) != 1:
            raise DomainError("PREREQUISITE_MISSING", f"Radioss 조립 폴더에 starter({cfg.predict.starter_glob})가 정확히 1개 있어야 합니다(현재 {len(st)}개)",
                              status=409, missing=["RADIOSS_STARTER"])
        types = dt_mod.load_doe_types(cfg.resources.doe_design_type_json, cfg.ui.max_artifact_bytes)
        t = dt_mod.find(types, p.doe_label)
        if t is None:
            raise _invalid("doe_label", f"알 수 없는 DOE 유형: {p.doe_label}", "DOE_TYPE_UNKNOWN")
        if not t["runs_editable"] and p.num_runs is not None:
            raise _invalid("num_runs", "이 DOE 유형은 run 수를 직접 정할 수 없습니다(HyperStudy가 결정)", "DOE_OPTIONS_INVALID")
        num_runs = (p.num_runs if p.num_runs is not None else t["default_runs"]) if t["runs_editable"] else None
        if num_runs is not None and not 2 <= num_runs <= cfg.train_data.max_runs:
            raise _invalid("num_runs", f"run 수는 2~{cfg.train_data.max_runs}", "DOE_OPTIONS_INVALID")
        probs = dt_mod.validate_options(t, p.options)
        if probs:
            raise DomainError("DOE_OPTIONS_INVALID", "DOE 옵션이 올바르지 않습니다", status=422, problems=probs)
        if p.multi_execution > cfg.train_data.max_multi_execution:
            raise _invalid("multi_execution", f"동시 실행 수는 1~{cfg.train_data.max_multi_execution}")
        doe_id = str(uuid.uuid4())
        params = {"doe_label": t["label"], "doe_type": t["value"], "num_runs": num_runs, "default_runs": t["default_runs"],
                  "options": dict(p.options), "multi_execution": p.multi_execution, "radioss_assem_path": cp.path,
                  "doe_id": doe_id}
        return params, {"doe_id": doe_id}, []
    if job_type == "TD_SOLVE":
        d = _ready_doe(conn, sid, p.doe_id)
        av = ctx.hpc.availability()
        if not av.configured:
            raise DomainError("HPC_NOT_CONFIGURED", "PBS 연결 안 됨 — DOE 입력 폴더를 직접 해석한 뒤 ①-5에서 결과 폴더를 지정하세요",
                              status=409, mode=av.mode)
        runs = train_repo.runs_for_doe(conn, d["id"])
        keys = {r["run_key"] for r in runs}
        if p.run_keys is not None:
            unknown = [k for k in p.run_keys if k not in keys]
            if unknown or not p.run_keys:
                raise _invalid("run_keys", f"DOE에 없는 run: {', '.join(unknown[:10])}" if unknown else "run이 비어 있습니다")
            n = len(set(p.run_keys))
        else:
            n = sum(1 for r in runs if r["state"] in train_repo.RESUBMIT_STATES)
            if n == 0:
                raise _missing("SUBMITTABLE_RUN")
        if n > cfg.train_data.max_runs_per_submit:
            raise _invalid("run_keys", f"한 번에 제출할 수 있는 run은 {cfg.train_data.max_runs_per_submit}개입니다")
        params = {"doe_id": d["id"], "run_keys": sorted(set(p.run_keys)) if p.run_keys else None,
                  "hpc": p.hpc.model_dump() if p.hpc else None, "on_run_failure": p.on_run_failure}
        return params, {"doe_id": d["id"]}, []
    if job_type == "TD_RESULT_IMPORT":
        d = _ready_doe(conn, sid, p.doe_id)
        roots = [cfg.storage.ai_root, *cfg.storage.allowed_import_roots]
        if cfg.hpc.transfer.collect_root_local:
            roots.append(cfg.hpc.transfer.collect_root_local)
        cp = check_user_path(p.source_path, roots)
        return {"doe_id": d["id"], "source_path": cp.path}, {"doe_id": d["id"]}, []
    if job_type == "TD_RESP_EXTRACT":
        d = _ready_doe(conn, sid, p.doe_id)
        if train_repo.run_state_counts(conn, d["id"])["COLLECTED"] < 1:
            raise _missing("COLLECTED_RUN")
        names = [r.name for r in p.responses]
        if len(set(names)) != len(names):
            raise _invalid("responses", "응답 이름이 중복됩니다")
        return {"doe_id": d["id"], "responses": [r.model_dump() for r in p.responses]}, {"doe_id": d["id"]}, []
    if job_type in ("CU_H3D_PREVIEW", "CU_T01_PREVIEW"):
        kind = "H3D" if job_type == "CU_H3D_PREVIEW" else "T01"
        src, root = resolve_source(ctx, conn, study, p.source)
        files = _source_files(ctx, root, kind)
        if p.sample_file:
            rels = {os.path.relpath(f, root).replace(os.sep, "/") for f in files}
            if p.sample_file.replace("\\", "/") not in rels:
                raise _invalid("sample_file", "원천에 없는 파일입니다")
        return {"source": src, "sample_file": p.sample_file}, None, []
    if job_type == "CU_H3D_CURATE":
        src, root = resolve_source(ctx, conn, study, p.source)
        _source_files(ctx, root, "H3D")
        summary = _preview_summary(ctx, conn, study, p.preview_job_id)
        sel = p.selection.model_dump()
        probs = cu.validate_selection(sel, summary)
        if probs:
            raise DomainError("SELECTION_INVALID", "선택 항목이 미리보기와 맞지 않습니다", status=422, problems=probs)
        cid = str(uuid.uuid4())
        params = {"source": src, "preview_job_id": p.preview_job_id, "selection": sel,
                  "exclude_files": [e.replace("\\", "/") for e in p.exclude_files], "curation_id": cid}
        return params, {"curation_id": cid}, []
    if job_type == "CU_T01_CURVES":
        src, root = resolve_source(ctx, conn, study, p.source)
        _source_files(ctx, root, "T01")
        cid = str(uuid.uuid4())
        params = {"source": src, "curves": [c.model_dump() for c in p.curves],
                  "exclude_files": [e.replace("\\", "/") for e in p.exclude_files], "curation_id": cid}
        return params, {"curation_id": cid}, []
    if job_type == "SPDM_IMPORT":
        if not cfg.storage.spdm_roots:
            raise DomainError("SPDM_IMPORT_DISABLED", "SPDM 가져오기가 설정되지 않았습니다(storage.spdm_roots)", status=409)
        path = spdm.check_spdm_path(p.spdm_path, cfg.storage.spdm_roots)
        iid = str(uuid.uuid4())
        return {"spdm_path": path, "import_id": iid}, {"import_id": iid}, []
    if job_type == "OPTIMIZE":
        ps = ps_repo.get(conn, p.param_set_id) if p.param_set_id else ps_repo.current(conn, sid)
        if ps is None or ps["study_id"] != sid:
            raise _missing("PARAM_SET")
        if p.model_id:
            m = models_repo.get(conn, p.model_id)
            if m is None or m["study_id"] != sid or m["status"] != "ACTIVE":
                raise _missing("ACTIVE_MODEL")
        else:
            m = models_repo.get(conn, study["final_model_id"]) if study["final_model_id"] else None
            if m is None or m["status"] != "ACTIVE":
                raise DomainError("FINAL_MODEL_REQUIRED", "Final 모델을 먼저 지정하세요", status=409)
        rows, probs = opt.validate_responses(p.responses, p.approach)
        if probs == [{"row": "", "message": "OBJECTIVE_REQUIRED"}]:
            raise DomainError("OBJECTIVE_REQUIRED", "최적화에는 목적함수(MINIMIZE / MAXIMIZE)가 1개 이상 필요합니다", status=422)
        if probs:
            raise DomainError("RESPONSES_INVALID", "응답 정의가 올바르지 않습니다", status=422, problems=probs)
        oid = str(uuid.uuid4())
        params = {
            "param_set_id": ps["id"], "model_id": m["id"], "approach": p.approach, "opt_method": p.opt_method,
            "max_designs": p.max_designs, "run_nominal": p.run_nominal,
            "study_folder": p.study_folder or cfg.optimize.default_study_folder,
            "opt_settings": p.opt_settings.model_dump(), "on_failed": p.on_failed, "responses": rows,
            "optimization_id": oid,
        }
        return params, {"optimization_id": oid, "model_id": m["id"], "param_set_id": ps["id"]}, []
    raise _invalid("job_type", "unknown")


def after_insert(conn: Any, principal: Any, study: dict[str, Any], job_type: str, job_id: str, params: dict[str, Any]) -> None:
    """작업 생성과 같은 트랜잭션에서 엔터티 행(BUILDING) 생성(B8 방식)."""
    base = {"study_id": study["id"], "job_id": job_id, "created_by": principal.user_id,
            "created_by_name": principal.display_name}
    if job_type == "TD_DOE_GEN":
        did = params["doe_id"]
        train_repo.insert_doe(conn, {
            **base, "id": did, "doe_label": params["doe_label"], "doe_type": params["doe_type"],
            "num_runs_requested": params["num_runs"], "options": params["options"],
            "multi_execution": params["multi_execution"], "radioss_assem_source_path": params["radioss_assem_path"],
            "dir_rel": f"01_train/doe/{did}/", "assem_rel": f"01_train/radioss_assem/{did}/", "status": "BUILDING",
            "sample_status": "PENDING",
        })
    elif job_type in ("CU_H3D_CURATE", "CU_T01_CURVES"):
        cid = params["curation_id"]
        h3d = job_type == "CU_H3D_CURATE"
        cur_repo.insert_curation(conn, {
            **base, "id": cid, "kind": "H3D" if h3d else "T01", "source": params["source"],
            "preview_job_id": params.get("preview_job_id"),
            "selection": params["selection"] if h3d else {"curves": params["curves"]},
            "output_rel": f"02_curated/{cid}/{'CURATED_DATA' if h3d else 'CURVES'}/",
            "file_list_rel": f"02_curated/{cid}/file_list.json", "status": "BUILDING",
        })
    elif job_type == "SPDM_IMPORT":
        iid = params["import_id"]
        imp_repo.insert_import(conn, {**base, "id": iid, "spdm_path": params["spdm_path"], "dest_rel": f"02_import/{iid}/",
                                      "status": "BUILDING"})


def on_retry(conn: Any, old: dict[str, Any], new_id: str) -> None:
    """재시도: 엔터티 행을 새 작업으로 다시 BUILDING."""
    from sqlalchemy import update

    p = old["params"] or {}
    if old["job_type"] == "TD_DOE_GEN" and p.get("doe_id"):
        conn.execute(update(train_does).where(train_does.c.id == p["doe_id"]).values(status="BUILDING", job_id=new_id))
    elif old["job_type"] in ("CU_H3D_CURATE", "CU_T01_CURVES") and p.get("curation_id"):
        conn.execute(update(curations).where(curations.c.id == p["curation_id"]).values(status="BUILDING", job_id=new_id))
    elif old["job_type"] == "SPDM_IMPORT" and p.get("import_id"):
        conn.execute(update(spdm_imports).where(spdm_imports.c.id == p["import_id"]).values(status="BUILDING", job_id=new_id))
