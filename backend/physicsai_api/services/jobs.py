"""작업 생성·조회·로그·취소·재시도·대기열(§10.2, §10.5, §8.2)."""

from __future__ import annotations

import math
import os
import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select

from physicsai_core.db.repositories import artifacts as artifacts_repo
from physicsai_core.db.repositories import datasets as datasets_repo
from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import queue as queue_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.tables import hpc_jobs, jobs, studies
from physicsai_core.errors import DomainError
from physicsai_core.paths import check_dataset_input, check_user_path, resolve_in_study
from physicsai_core.state_machine import TERMINAL

from ..auth import Principal
from ..context import AppContext
from .common import (
    audit,
    clamp_limit,
    decode_cursor,
    encode_cursor,
    file_size,
    job_detail,
    job_summary,
    require_config_ok,
    require_global_admin,
    require_power,
    study_root,
)
from .studies import inspect_model_folder

MODEL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
RUN_KEY_RE = r"^[A-Za-z0-9_\-]{1,64}$"
MAX_LOG_LIMIT = 262144


# ---- params 스키마(§10.6) ---------------------------------------------------


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DatasetOptions(_P):
    extract_faces: bool = True
    extract_mdi: bool = False
    extract_time_history_vectors: bool = False


class DatasetCreateParams(_P):
    input_path: str | None = Field(default=None, max_length=400)
    curation_id: str | None = None  # phase2 §6.8: ② 큐레이션 출력(CURATED_DATA)을 입력으로
    holdout_ratio: float | None = Field(default=None, ge=0.05, le=0.5)
    seed: int | None = None
    split_group: Literal["file", "parent_dir"] | None = None
    options: DatasetOptions | None = None


class PackageExportParams(_P):
    dataset_id: str


class ModelRegisterParams(_P):
    model_path: str = Field(max_length=400)
    name: str | None = Field(default=None, pattern=MODEL_NAME_RE.pattern)
    label: str | None = Field(default=None, max_length=120)
    dataset_id: str | None = None
    log_file: str | None = Field(default=None, max_length=255)


class EvaluateParams(_P):
    model_id: str


class PredictParams(_P):
    param_set_id: str | None = None
    model_id: str | None = None
    values: dict[str, float]
    value_source: Literal["nominal", "run", "manual"]
    source_run_key: str | None = Field(default=None, pattern=RUN_KEY_RE)

    @field_validator("values")
    @classmethod
    def _finite(cls, v: dict[str, float]) -> dict[str, float]:
        for k, x in v.items():
            if not math.isfinite(x):
                raise ValueError(f"{k} 값은 유한해야 합니다")
        return v


class HpcOverrides(_P):
    queue: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.\-@]{1,64}$")
    ncpus: int | None = Field(default=None, ge=1, le=4096)
    walltime: str | None = Field(default=None, pattern=r"^\d{1,4}:\d{2}:\d{2}$")


class PredictVerifyParams(_P):
    predict_job_id: str
    hpc: HpcOverrides | None = None


from . import phase2_params as P2  # noqa: E402

PARAM_MODELS: dict[str, type[BaseModel]] = {
    "DATASET_CREATE": DatasetCreateParams,
    "PACKAGE_EXPORT": PackageExportParams,
    "MODEL_REGISTER": ModelRegisterParams,
    "EVALUATE": EvaluateParams,
    "PREDICT": PredictParams,
    "PREDICT_VERIFY": PredictVerifyParams,
    **P2.PARAM_MODELS,
}


def _invalid(errors: list[dict[str, Any]], message: str = "요청 값이 올바르지 않습니다") -> DomainError:
    return DomainError("INVALID_PARAMS", message, status=422, errors=errors)


def _parse_params(job_type: str, params: dict[str, Any]) -> Any:
    try:
        return PARAM_MODELS[job_type].model_validate(params)
    except ValidationError as exc:
        raise _invalid([{"loc": ["params", *e["loc"]], "msg": e["msg"]} for e in exc.errors()]) from None


def _missing(*items: str) -> DomainError:
    return DomainError("PREREQUISITE_MISSING", "사전 조건이 충족되지 않았습니다", status=409, missing=list(items))


# ---- 작업 생성 ----------------------------------------------------------------


def _prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    """사전조건 확인(§8.2) → (저장할 params, 초기 result, warnings)."""
    cfg = ctx.settings
    sid = study["id"]
    warnings: list[dict[str, str]] = []
    if job_type in P2.PARAM_MODELS:
        return P2.prepare(ctx, conn, study, job_type, p)
    if job_type == "DATASET_CREATE":
        if (p.input_path is None) == (p.curation_id is None):
            raise _invalid([{"loc": ["params", "input_path"], "msg": "input_path와 curation_id 중 하나만 지정하세요"}])
        if p.curation_id is not None:
            from physicsai_core.db.repositories import curations as cur_repo

            cur = cur_repo.get_curation(conn, p.curation_id)
            if cur is None or cur["study_id"] != sid or cur["status"] != "READY" or cur["kind"] != "H3D":
                raise _missing("READY_H3D_CURATION")
            input_path = os.path.join(study_root(ctx, study), *cur["output_rel"].rstrip("/").split("/"))
        else:
            input_path = p.input_path
        cp = check_user_path(input_path, [cfg.storage.ai_root])
        check_dataset_input(cp.path, cfg.storage.ai_root)
        opts = (p.options or DatasetOptions(**cfg.dataset.options_default.model_dump())).model_dump()
        params = {
            "input_path": cp.path,
            **({"curation_id": p.curation_id} if p.curation_id else {}),
            "holdout_ratio": p.holdout_ratio if p.holdout_ratio is not None else cfg.dataset.holdout_ratio,
            "seed": p.seed if p.seed is not None else cfg.dataset.seed,
            "split_group": p.split_group or cfg.dataset.split_group,
            "options": opts,
        }
        return params, {"dataset_id": str(uuid.uuid4())}, warnings
    if job_type == "PACKAGE_EXPORT":
        d = datasets_repo.get(conn, p.dataset_id)
        if d is None or d["study_id"] != sid or d["status"] != "READY":
            raise _missing("READY_DATASET")
        return p.model_dump(), None, warnings
    if job_type == "MODEL_REGISTER":
        cp = check_user_path(p.model_path, [cfg.storage.ai_root, *cfg.storage.allowed_import_roots])
        name = p.name
        if name is None:
            found = inspect_model_folder(cp.path, cfg.training_log.log_globs)["psmdl"]
            stem = os.path.splitext(found[0])[0] if len(found) == 1 else ""
            if not MODEL_NAME_RE.match(stem):
                raise _invalid([{"loc": ["params", "name"], "msg": "모델 이름을 입력하세요(^[A-Za-z][A-Za-z0-9_]{0,63}$)"}],
                               "모델 이름을 입력하세요")
            name = stem
        if p.dataset_id is not None:
            d = datasets_repo.get(conn, p.dataset_id)
            if d is None or d["study_id"] != sid:
                raise _invalid([{"loc": ["params", "dataset_id"], "msg": "이 Study의 데이터셋이 아닙니다"}])
        if p.log_file is not None and (os.path.basename(p.log_file) != p.log_file or p.log_file in (".", "..")):
            raise _invalid([{"loc": ["params", "log_file"], "msg": "폴더 안 파일 이름만 지정하세요"}])
        params = {"model_path": cp.path, "name": name, "label": p.label, "dataset_id": p.dataset_id, "log_file": p.log_file}
        return params, None, warnings
    if job_type == "EVALUATE":
        m = models_repo.get(conn, p.model_id)
        if m is None or m["study_id"] != sid or m["status"] != "ACTIVE":
            raise _missing("ACTIVE_MODEL")
        d = datasets_repo.get(conn, m["dataset_id"]) if m["dataset_id"] else None
        if d is None or d["status"] != "READY":
            raise _missing("READY_DATASET")
        return p.model_dump(), {"model_id": m["id"]}, warnings
    if job_type == "PREDICT":
        ps = ps_repo.get(conn, p.param_set_id) if p.param_set_id else ps_repo.current(conn, sid)
        if ps is None or ps["study_id"] != sid:
            raise _missing("PARAM_SET")
        if p.model_id:
            m = models_repo.get(conn, p.model_id)
            if m is None or m["study_id"] != sid or m["status"] != "ACTIVE":
                raise _missing("ACTIVE_MODEL")
        else:
            if not study["final_model_id"]:
                raise DomainError("FINAL_MODEL_REQUIRED", "Final 모델을 먼저 지정하세요", status=409)
            m = models_repo.get(conn, study["final_model_id"])
            if m is None or m["status"] != "ACTIVE":
                raise DomainError("FINAL_MODEL_REQUIRED", "Final 모델이 ACTIVE가 아닙니다", status=409)
        if cfg.commands.geom_update is None:
            raise DomainError("TEMPLATE_NOT_CONFIGURED", "형상 갱신 명령 템플릿(geom_update)이 설정되지 않았습니다", status=409,
                              template="geom_update")
        names = [x["name"] for x in ps["parameters"]]
        unknown = [k for k in p.values if k not in names]
        missing = [n for n in names if n not in p.values]
        if unknown or missing:
            raise _invalid([{"loc": ["params", "values", k], "msg": "unknown" if k in unknown else "required"}
                            for k in unknown + missing])
        if p.value_source == "run" and not p.source_run_key:
            raise _invalid([{"loc": ["params", "source_run_key"], "msg": "required"}])
        params = {
            "param_set_id": ps["id"], "model_id": m["id"], "values": dict(p.values), "value_source": p.value_source,
            "source_run_key": p.source_run_key,
        }
        return params, {"model_id": m["id"], "param_set_id": ps["id"]}, warnings
    if job_type == "PREDICT_VERIFY":
        av = ctx.hpc.availability()
        if not av.configured:
            raise DomainError("HPC_NOT_CONFIGURED", "PBS 연결 안 됨 — 2차에서 제공(관리자 설정 필요)", status=409,
                              mode=av.mode)
        pj = jobs_repo.get_job(conn, p.predict_job_id)
        if pj is None or pj["study_id"] != sid or pj["job_type"] != "PREDICT" or pj["state"] != "SUCCEEDED":
            raise _missing("SUCCEEDED_PREDICT")
        return p.model_dump(), None, warnings
    raise _invalid([{"loc": ["job_type"], "msg": "unknown"}])


def create_job(ctx: AppContext, principal: Principal, study_id: str, job_type: str, raw_params: dict[str, Any],
               rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        study = studies_repo.require(conn, study_id)
        require_power(principal, study["project_id"])
        require_config_ok(ctx)
        if study["status"] != "ACTIVE":
            raise DomainError("STUDY_ARCHIVED", "보관된 Study입니다", status=409)
        p = _parse_params(job_type, raw_params)
        params, result, warnings = _prepare(ctx, conn, study, job_type, p)
        job_id = str(uuid.uuid4())
        job = jobs_repo.insert_job(conn, study=study, job_type=job_type, params=params, user_id=principal.user_id,
                                   user_name=principal.display_name, result=result, warnings=warnings, job_id=job_id)
        if job_type == "DATASET_CREATE":
            ds_id = result["dataset_id"]  # type: ignore[index]
            datasets_repo.insert(conn, {
                "id": ds_id, "study_id": study_id, "job_id": job_id, "source_path": params["input_path"],
                "holdout_ratio": params["holdout_ratio"], "seed": params["seed"], "split_group": params["split_group"],
                "options_json": params["options"], "status": "BUILDING", "created_by": principal.user_id,
                "created_by_name": principal.display_name,
                "split_rel": f"03_dataset/{ds_id}/split.json",
                "train_psdata_rel": f"03_dataset/{ds_id}/train/dataset.psdata",
                "eval_psdata_rel": f"03_dataset/{ds_id}/eval/dataset.psdata",
            })
        if job_type in P2.PARAM_MODELS:
            P2.after_insert(conn, principal, study, job_type, job_id, params)
        audit(conn, principal, "JOB_CREATE", "job", job_id, {"job_type": job_type, "study_id": study_id}, rid, ip)
        return job_detail(conn, job, principal, include_commands=False, ai_root=ctx.settings.storage.ai_root)


# ---- 조회 -------------------------------------------------------------------


def list_jobs(ctx: AppContext, principal: Principal, *, study_id: str | None, state: str | None, mine: bool,
              job_type: str | None, limit: int | None, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    lim, off = clamp_limit(limit), decode_cursor(cursor)
    q = select(jobs, studies.c.title.label("study_title")).select_from(jobs.join(studies, studies.c.id == jobs.c.study_id))
    if study_id:
        q = q.where(jobs.c.study_id == study_id)
    if state:
        q = q.where(jobs.c.state.in_(state.split(",")))
    if mine:
        q = q.where(jobs.c.created_by == principal.user_id)
    if job_type:
        q = q.where(jobs.c.job_type == job_type)
    q = q.order_by(jobs.c.created_at.desc(), jobs.c.id).limit(lim + 1).offset(off)
    with ctx.engine.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(q)]
        pos = {"SLOT": jobs_repo.queue_positions(conn, "SLOT"), "LIGHT": jobs_repo.queue_positions(conn, "LIGHT")}
        hs = hpc_repo.summary_for_jobs(conn, [r["id"] for r in rows[:lim]])
    out = [job_summary(r, r["study_title"], pos[r["lane"]].get(r["id"]), hs.get(r["id"])) for r in rows[:lim]]
    return out, (encode_cursor(off + lim) if len(rows) > lim else None)


def _require_job(conn: Any, job_id: str) -> dict[str, Any]:
    j = jobs_repo.get_job(conn, job_id)
    if j is None:
        raise DomainError("NOT_FOUND", "작업을 찾을 수 없습니다", status=404)
    return j


def get_job(ctx: AppContext, principal: Principal, job_id: str, include_commands: bool) -> tuple[dict[str, Any], str]:
    with ctx.engine.connect() as conn:
        j = _require_job(conn, job_id)
        if include_commands:
            require_global_admin(principal)
        detail = job_detail(conn, j, principal, include_commands=include_commands, ai_root=ctx.settings.storage.ai_root)
        s = studies_repo.get(conn, j["study_id"])
    log_size = file_size(os.path.join(study_root(ctx, s), "logs", job_id, "job.log")) if s else 0
    etag = f'"{job_id}:{j["version"]}:{log_size}{":c" if include_commands else ""}"'
    return detail, etag


def job_etag(ctx: AppContext, job_id: str) -> str | None:
    with ctx.engine.connect() as conn:
        j = jobs_repo.get_job(conn, job_id)
        if j is None:
            return None
        s = studies_repo.get(conn, j["study_id"])
    log_size = file_size(os.path.join(study_root(ctx, s), "logs", job_id, "job.log")) if s else 0
    return f'"{job_id}:{j["version"]}:{log_size}"'


def read_log(ctx: AppContext, job_id: str, step_no: int | None, cursor: int, limit: int) -> dict[str, Any]:
    if cursor < 0 or limit < 1 or limit > MAX_LOG_LIMIT:
        raise _invalid([{"loc": ["query", "limit"], "msg": f"1~{MAX_LOG_LIMIT}"}])
    with ctx.engine.connect() as conn:
        j = _require_job(conn, job_id)
        s = studies_repo.require(conn, j["study_id"])
        if step_no is None:
            rel = f"logs/{job_id}/job.log"
        else:
            steps = {x["step_no"]: x for x in jobs_repo.get_steps(conn, job_id)}
            if step_no not in steps:
                raise DomainError("NOT_FOUND", "step을 찾을 수 없습니다", status=404)
            rel = steps[step_no]["log_rel"]
    path = resolve_in_study(study_root(ctx, s), rel)
    if not os.path.isfile(path):
        raise DomainError("LOG_NOT_FOUND", "로그가 아직 없습니다", status=404)
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        fh.seek(min(cursor, size))
        data = fh.read(limit)
    # 끝에서 잘린 UTF-8 문자는 다음 요청으로 넘긴다
    end = len(data)
    i = end - 1
    while i >= 0 and end - i <= 4 and (data[i] & 0xC0) == 0x80:
        i -= 1
    if i >= 0:
        lead = data[i]
        need = 1 if lead < 0x80 else 2 if lead >> 5 == 0b110 else 3 if lead >> 4 == 0b1110 else 4 if lead >> 3 == 0b11110 else 1
        if end - i < need:
            end = i
    if end == 0:
        end = len(data)
    chunk = data[:end]
    nxt = min(cursor, size) + end
    return {"text": chunk.decode("utf-8", errors="replace"), "next_cursor": nxt, "eof": nxt >= size, "size": size}


# ---- 취소·재시도·대기열 ---------------------------------------------------------


def cancel_job(ctx: AppContext, principal: Principal, job_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        _require_job(conn, job_id)
        require_global_admin(principal)
        j = jobs_repo.request_cancel(conn, job_id, principal.user_id)
        audit(conn, principal, "JOB_CANCEL", "job", job_id, {"state": j["state"]}, rid, ip)
        return job_detail(conn, j, principal, include_commands=False, ai_root=ctx.settings.storage.ai_root)


def retry_job(ctx: AppContext, principal: Principal, job_id: str, from_step: int | None, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        old = _require_job(conn, job_id)
        if old["created_by"] == principal.user_id:
            require_power(principal, old["project_id"])
        else:
            require_global_admin(principal)
        require_config_ok(ctx)
        if old["state"] not in TERMINAL or old["state"] == "SUCCEEDED":
            raise DomainError("JOB_NOT_RETRYABLE", "실패·취소·중단된 작업만 재시도할 수 있습니다", status=409)
        study = studies_repo.require(conn, old["study_id"])
        if study["status"] != "ACTIVE":
            raise DomainError("STUDY_ARCHIVED", "보관된 Study입니다", status=409)
        steps = jobs_repo.get_steps(conn, job_id)
        default_from = next((s["step_no"] for s in steps if s["state"] in ("FAILED", "CANCELED", "PENDING", "RUNNING")), 1)
        if from_step is None:
            from_step = default_from
        if from_step > default_from or from_step > len(steps):
            raise _invalid([{"loc": ["from_step"], "msg": f"1~{default_from}"}])
        if from_step > 1 and old["job_type"] in ("PREDICT_VERIFY", "TD_SOLVE"):
            from_step = 1  # HPC 제출 이력은 재사용하지 않는다(phase2 §7.1: TD_SOLVE는 항상 TS_PREP부터)
        new_id = str(uuid.uuid4())
        job = jobs_repo.insert_job(
            conn, study=study, job_type=old["job_type"], params=old["params"], user_id=principal.user_id,
            user_name=principal.display_name, result=dict(old["result"] or {}), retry_of_job_id=job_id,
            resume_from_step=from_step if from_step > 1 else None, job_id=new_id,
        )
        if old["job_type"] == "DATASET_CREATE" and (old["result"] or {}).get("dataset_id"):
            datasets_repo.set_values(conn, old["result"]["dataset_id"], status="BUILDING")
        if old["job_type"] in P2.PARAM_MODELS:
            P2.on_retry(conn, old, new_id)
        audit(conn, principal, "JOB_RETRY", "job", new_id, {"retry_of": job_id, "from_step": from_step}, rid, ip)
        return job_detail(conn, job, principal, include_commands=False, ai_root=ctx.settings.storage.ai_root)


def queue_view(ctx: AppContext) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        slot = queue_repo.slot_row(conn)
        rows = queue_repo.active_jobs(conn)
        hs = hpc_repo.summary_for_jobs(conn, [r["id"] for r in rows])
    out: dict[str, Any] = {
        "slot": {"holder_job_id": slot["holder_job_id"], "since": slot["lease_acquired_at"]},
        "running": None, "queued": [], "light": {"running": None, "queued": []}, "waiting_hpc": [], "collecting": [],
    }
    slot_pos = light_pos = 0
    for r in rows:
        if r["state"] == "QUEUED":
            if r["lane"] == "SLOT":
                slot_pos += 1
                out["queued"].append(job_summary(r, r["study_title"], slot_pos))
            else:
                light_pos += 1
                out["light"]["queued"].append(job_summary(r, r["study_title"], light_pos))
        elif r["state"] == "RUNNING":
            if r["lane"] == "SLOT":
                out["running"] = job_summary(r, r["study_title"], None)
            else:
                out["light"]["running"] = job_summary(r, r["study_title"], None)
        elif r["state"] == "WAITING_HPC":
            out["waiting_hpc"].append(job_summary(r, r["study_title"], None, hs.get(r["id"])))
        elif r["state"] == "COLLECTING":
            out["collecting"].append(job_summary(r, r["study_title"], None, hs.get(r["id"])))
    return out


def move_job(ctx: AppContext, principal: Principal, job_id: str, position: int, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        _require_job(conn, job_id)
        require_global_admin(principal)
        jobs_repo.move_in_queue(conn, job_id, position)
        audit(conn, principal, "QUEUE_MOVE", "job", job_id, {"position": position}, rid, ip)
    return queue_view(ctx)


# ---- 산출물·HPC ----------------------------------------------------------------


def list_artifacts(ctx: AppContext, job_id: str) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        _require_job(conn, job_id)
        rows = artifacts_repo.list_for_job(conn, job_id)
    return [
        {"id": a["id"], "study_id": a["study_id"], "job_id": a["job_id"], "kind": a["kind"],
         "file_name": os.path.basename(a["rel_path"]), "size": a["size"], "sha256": a["sha256"],
         "content_type": a["content_type"], "created_at": a["created_at"]}
        for a in rows
    ]


def artifact_file(ctx: AppContext, artifact_id: str) -> tuple[str, str, str]:
    with ctx.engine.connect() as conn:
        a = artifacts_repo.get(conn, artifact_id)
        if a is None:
            raise DomainError("NOT_FOUND", "산출물을 찾을 수 없습니다", status=404)
        s = studies_repo.require(conn, a["study_id"])
    if a["content_type"] not in artifacts_repo.ALLOWED_CONTENT_TYPES:
        raise DomainError("NOT_FOUND", "내려받을 수 없는 형식입니다", status=404)
    path = resolve_in_study(study_root(ctx, s), a["rel_path"])
    if not os.path.isfile(path):
        raise DomainError("NOT_FOUND", "산출물 파일이 없습니다", status=404)
    if os.path.getsize(path) > ctx.settings.ui.max_artifact_bytes:
        raise DomainError("NOT_FOUND", "산출물이 크기 상한을 넘습니다", status=404)
    return path, a["content_type"], os.path.basename(a["rel_path"])


def list_hpc_jobs(ctx: AppContext, job_id: str) -> list[dict[str, Any]]:
    from sqlalchemy import func

    with ctx.engine.connect() as conn:
        _require_job(conn, job_id)
        rows = conn.execute(
            select(hpc_jobs, func.extract("epoch", func.coalesce(hpc_jobs.c.finished_at, func.now()) - hpc_jobs.c.submitted_at).label("elapsed"))
            .where(hpc_jobs.c.job_id == job_id)
            .order_by(hpc_jobs.c.attempt_no, hpc_jobs.c.run_key)
        ).all()
    return [
        {"id": r.id, "run_key": r.run_key, "attempt_no": r.attempt_no, "external_job_id": r.external_job_id,
         "state": r.state, "external_state_raw": r.external_state_raw, "submitted_at": r.submitted_at,
         "elapsed_s": float(r.elapsed) if r.elapsed is not None else None, "collect_state": r.collect_state}
        for r in rows
    ]



# ---- ④ 입력 파일 zip(스트리밍) ------------------------------------------------------

ZIP_CHUNK = 1024 * 1024


class _ZipSink:
    """zipfile이 쓰는 비탐색(non-seekable) 출력. 쓴 바이트를 모았다가 생성기가 꺼내 간다."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.pos = 0

    def write(self, b: bytes) -> int:
        self.buf += b
        self.pos += len(b)
        return len(b)

    def tell(self) -> int:
        return self.pos

    def seek(self, *_a: Any) -> int:
        raise OSError("not seekable")

    def flush(self) -> None:
        return None

    def take(self) -> bytes:
        out = bytes(self.buf)
        self.buf.clear()
        return out


def input_zip(ctx: AppContext, job_id: str) -> tuple[Any, str]:
    """PREDICT 작업의 `P/INPUT/` 직계 파일(.rad·.inc 등)을 zip으로 스트리밍. (생성기, 파일 이름)."""
    import zipfile

    from .common import input_zip_ready

    with ctx.engine.connect() as conn:
        j = _require_job(conn, job_id)
        if not input_zip_ready(conn, j):
            raise DomainError("INPUT_NOT_READY", "입력 파일이 아직 준비되지 않았습니다(예측 작업의 .rad 조립 완료 후 가능)", status=409)
        s = studies_repo.require(conn, j["study_id"])
        root_id = jobs_repo.root_job_id(conn, j)
    root = study_root(ctx, s)
    inp = resolve_in_study(root, f"04_predict/{root_id}/INPUT")
    if not os.path.isdir(inp):
        raise DomainError("INPUT_NOT_READY", "입력 파일 폴더가 없습니다", status=409)
    names = []
    for n in sorted(os.listdir(inp)):
        p = os.path.join(inp, n)
        if os.path.islink(p) or not os.path.isfile(p):
            continue  # 링크·하위 폴더 제외(경로 탈출 방지)
        if os.path.dirname(os.path.realpath(p)) != os.path.realpath(inp):
            continue
        names.append(n)

    def gen() -> Any:
        sink = _ZipSink()
        with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for n in names:
                with open(os.path.join(inp, n), "rb") as src, zf.open(n, "w", force_zip64=True) as dst:
                    while True:
                        b = src.read(ZIP_CHUNK)
                        if not b:
                            break
                        dst.write(b)
                        chunk = sink.take()
                        if chunk:
                            yield chunk
                chunk = sink.take()
                if chunk:
                    yield chunk
        tail = sink.take()
        if tail:
            yield tail

    return gen(), f"{s['folder_name']}_{job_id[:8]}_INPUT.zip"
