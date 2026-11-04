"""③ 데이터셋·모델 작업 params·사전조건(§10.6, §8.2): DATASET_CREATE, PACKAGE_EXPORT, MODEL_REGISTER, EVALUATE."""

from __future__ import annotations

import os
import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from physicsai_core.db.repositories import datasets as datasets_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import study_manage as sm_repo
from physicsai_core.errors import DomainError
from physicsai_core.paths import allowed_roots, check_dataset_input, check_user_path

from ...context import AppContext
from ..common import study_root
from ..path_inspect import inspect_model_folder
from .dataset_engine import detect as detect_engine
from .base import _P, invalid_errors, prerequisite_missing, require_model_pscfg

MODEL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


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
    # data-health.md §7(DH-10): 입력 루트 기준 h3d 상대경로(`/`, 정확 일치) 제외. 최대 개수는 설정 dataset.max_exclude(prepare가 확인)
    exclude_files: list[str] = Field(default_factory=list)
    kept_required: list[str] = Field(default_factory=list)  # 점검이 제외 필수로 표시했지만 사용자가 해제한 파일(DS_INCONSISTENT_KEPT)
    health_job_id: str | None = Field(default=None, max_length=64)  # 근거 DATA_HEALTH 작업(기록용)


class DataHealthParams(_P):
    """③-1 데이터 점검(data-health.md §8): input 규칙은 DATASET_CREATE와 같다(둘 중 하나). responses = 점검할 스칼라 응답 이름(생략 = 전부)."""

    input_path: str | None = Field(default=None, max_length=400)
    curation_id: str | None = None
    responses: list[str] | None = Field(default=None, max_length=200)
    attrs: bool = True  # 모델 속성(메시 bbox·부피·CoG·총질량) 포함 여부


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


PARAM_MODELS: dict[str, type[BaseModel]] = {
    "DATASET_CREATE": DatasetCreateParams,
    "DATA_HEALTH": DataHealthParams,
    "PACKAGE_EXPORT": PackageExportParams,
    "MODEL_REGISTER": ModelRegisterParams,
    "EVALUATE": EvaluateParams,
}


def resolve_input(ctx: AppContext, conn: Any, study: dict[str, Any], p: Any) -> tuple[str, str | None]:
    """DATASET_CREATE·DATA_HEALTH 공용 입력 해석(data-health.md §4.1): input_path 또는 curation_id(둘 중 하나) → 검사를 마친 경로.
    반환 (경로, curation_id|None). 큐레이션은 READY H3D만(없으면 409 PREREQUISITE_MISSING)."""
    cfg = ctx.settings
    if (p.input_path is None) == (p.curation_id is None):
        raise invalid_errors([{"loc": ["params", "input_path"], "msg": "input_path와 curation_id 중 하나만 지정하세요"}])
    if p.curation_id is not None:
        from physicsai_core.db.repositories import curations as cur_repo

        cur = cur_repo.get_curation(conn, p.curation_id)
        if cur is None or cur["study_id"] != study["id"] or cur["status"] != "READY" or cur["kind"] != "H3D":
            raise prerequisite_missing("READY_H3D_CURATION")
        input_path = os.path.join(study_root(ctx, study), *cur["output_rel"].rstrip("/").split("/"))
    else:
        input_path = p.input_path
    cp = check_user_path(input_path, [cfg.storage.ai_root])
    check_dataset_input(cp.path, cfg.storage.ai_root)
    return cp.path, p.curation_id


def normalize_rel_list(items: list[str], key: str, limit: int) -> list[str]:
    """입력 루트 기준 상대경로 목록: `\\` → `/`, 앞뒤 공백·앞 `./` 제거, 중복 제거(순서 유지). 개수 > limit·빈 값·너무 긴 항목은 422."""
    out: list[str] = []
    for raw in items:
        s = str(raw).replace("\\", "/").strip()
        while s.startswith("./"):
            s = s[2:]
        if not s or len(s) > 1024 or "\x00" in s:
            raise invalid_errors([{"loc": ["params", key], "msg": "빈 값이거나 올바르지 않은 경로입니다"}])
        out.append(s)
    out = list(dict.fromkeys(out))
    if len(out) > limit:
        raise invalid_errors([{"loc": ["params", key], "msg": f"최대 {limit}개까지 지정할 수 있습니다(dataset.max_exclude)"}])
    return out


def check_health_job(conn: Any, study_id: str, job_id: str, input_path: str) -> None:
    """health_job_id 사전조건(§7): 같은 Study·DATA_HEALTH·SUCCEEDED·result.input_path == 이번 입력 경로. 아니면 422 DH_INPUT_MISMATCH."""
    j = jobs_repo.get_job(conn, job_id)
    if j is None or j["study_id"] != study_id or j["job_type"] != "DATA_HEALTH" or j["state"] != "SUCCEEDED":
        raise DomainError("DH_INPUT_MISMATCH", "데이터 점검 작업을 찾을 수 없거나 정상 완료된 점검이 아닙니다", status=422)
    prev = (j.get("result") or {}).get("input_path")
    norm = lambda s: os.path.normcase(os.path.normpath(str(s)))  # noqa: E731
    if not prev or norm(prev) != norm(input_path):
        raise DomainError("DH_INPUT_MISMATCH", "데이터 점검 대상과 데이터셋 입력 폴더가 다릅니다", status=422)


def prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any
            ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    """사전조건 확인(§8.2) → (저장할 params, 초기 result, warnings). 기능 확인(check_feature)은 디스패처가 먼저 한다."""
    cfg = ctx.settings
    sid = study["id"]
    warnings: list[dict[str, str]] = []
    if job_type == "DATA_HEALTH":
        cp_path, curation_id = resolve_input(ctx, conn, study, p)
        active = sm_repo.active_of_type(conn, sid, "DATA_HEALTH")
        if active is not None:
            raise DomainError("DATA_HEALTH_ACTIVE", "이 Study에 진행 중인 데이터 점검이 있습니다 — 끝나거나 취소한 뒤 다시 시작하세요", status=409,
                              job_id=active)
        names = list(dict.fromkeys(str(x).strip() for x in (p.responses or []) if str(x).strip())) if p.responses is not None else None
        params = {"input_path": cp_path, **({"curation_id": curation_id} if curation_id else {}), "responses": names, "attrs": bool(p.attrs)}
        engine, engine_version, ew = detect_engine(ctx, conn, study, cp_path)  # DH-15: 엔진 혼합 422 ENGINE_MIXED 그대로
        result: dict[str, Any] = {}
        if engine is not None:
            result.update({"engine": engine})
        return params, result or None, warnings + ew
    if job_type == "DATASET_CREATE":
        cp_path, curation_id = resolve_input(ctx, conn, study, p)
        excluded = normalize_rel_list(p.exclude_files, "exclude_files", cfg.dataset.max_exclude)
        kept = normalize_rel_list(p.kept_required, "kept_required", cfg.dataset.max_exclude)
        if p.health_job_id is not None:
            check_health_job(conn, sid, p.health_job_id, cp_path)
        opts = (p.options or DatasetOptions(**cfg.dataset.options_default.model_dump())).model_dump()
        params = {
            "input_path": cp_path,
            **({"curation_id": curation_id} if curation_id else {}),
            "holdout_ratio": p.holdout_ratio if p.holdout_ratio is not None else cfg.dataset.holdout_ratio,
            "seed": p.seed if p.seed is not None else cfg.dataset.seed,
            "split_group": p.split_group or cfg.dataset.split_group,
            "options": opts,
            **({"exclude_files": excluded} if excluded else {}),
            **({"kept_required": kept} if kept else {}),
            **({"health_job_id": p.health_job_id} if p.health_job_id else {}),
        }
        engine, engine_version, ew = detect_engine(ctx, conn, study, cp_path)  # geometry-engine.md §7.7
        ds_result: dict[str, Any] = {"dataset_id": str(uuid.uuid4())}
        if engine is not None:
            ds_result.update({"engine": engine, "engine_version": engine_version})
        return params, ds_result, warnings + ew
    if job_type == "PACKAGE_EXPORT":
        d = datasets_repo.get(conn, p.dataset_id)
        if d is None or d["study_id"] != sid or d["status"] != "READY":
            raise prerequisite_missing("READY_DATASET")
        return p.model_dump(), None, warnings
    if job_type == "MODEL_REGISTER":
        cp = check_user_path(p.model_path, allowed_roots(cfg, imports=True))
        name = p.name
        if name is None:
            found = inspect_model_folder(cp.path, cfg.training_log.log_globs)["psmdl"]
            stem = os.path.splitext(found[0])[0] if len(found) == 1 else ""
            if not MODEL_NAME_RE.match(stem):
                raise invalid_errors([{"loc": ["params", "name"], "msg": "모델 이름을 입력하세요(^[A-Za-z][A-Za-z0-9_]{0,63}$)"}],
                                     "모델 이름을 입력하세요")
            name = stem
        if p.dataset_id is not None:
            d = datasets_repo.get(conn, p.dataset_id)
            if d is None or d["study_id"] != sid:
                raise invalid_errors([{"loc": ["params", "dataset_id"], "msg": "이 Study의 데이터셋이 아닙니다"}])
        if p.log_file is not None and (os.path.basename(p.log_file) != p.log_file or p.log_file in (".", "..")):
            raise invalid_errors([{"loc": ["params", "log_file"], "msg": "폴더 안 파일 이름만 지정하세요"}])
        params = {"model_path": cp.path, "name": name, "label": p.label, "dataset_id": p.dataset_id, "log_file": p.log_file}
        return params, None, warnings
    if job_type == "EVALUATE":
        m = models_repo.get(conn, p.model_id)
        if m is None or m["study_id"] != sid or m["status"] != "ACTIVE":
            raise prerequisite_missing("ACTIVE_MODEL")
        require_model_pscfg(cfg, "edspy_score", m)
        d = datasets_repo.get(conn, m["dataset_id"]) if m["dataset_id"] else None
        if d is None or d["status"] != "READY":
            raise prerequisite_missing("READY_DATASET")
        return p.model_dump(), {"model_id": m["id"]}, warnings
    raise invalid_errors([{"loc": ["job_type"], "msg": "unknown"}])


def after_insert(conn: Any, principal: Any, study: dict[str, Any], job_type: str, job_id: str, params: dict[str, Any],
                 result: dict[str, Any] | None) -> None:
    """작업 생성과 같은 트랜잭션에서 데이터셋 행(BUILDING) 생성."""
    if job_type == "DATASET_CREATE":
        ds_id = result["dataset_id"]  # type: ignore[index]
        datasets_repo.insert(conn, {
            "id": ds_id, "study_id": study["id"], "job_id": job_id, "source_path": params["input_path"],
            "holdout_ratio": params["holdout_ratio"], "seed": params["seed"], "split_group": params["split_group"],
            "options_json": params["options"], "status": "BUILDING", "created_by": principal.user_id,
            "created_by_name": principal.display_name,
            "engine": (result or {}).get("engine"), "engine_version": (result or {}).get("engine_version"),
            "split_rel": f"03_dataset/{ds_id}/split.json",
            "train_psdata_rel": f"03_dataset/{ds_id}/train/dataset.psdata",
            "eval_psdata_rel": f"03_dataset/{ds_id}/eval/dataset.psdata",
            "health_job_id": params.get("health_job_id"),
        })


def on_retry(conn: Any, old: dict[str, Any], new_id: str) -> None:
    """재시도: 데이터셋 행을 다시 BUILDING."""
    if old["job_type"] == "DATASET_CREATE" and (old["result"] or {}).get("dataset_id"):
        datasets_repo.set_values(conn, old["result"]["dataset_id"], status="BUILDING")
