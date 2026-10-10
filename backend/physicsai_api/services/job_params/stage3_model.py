"""③ 데이터셋·모델 작업 params·사전조건(§10.6, §8.2): DATASET_CREATE, PACKAGE_EXPORT, MODEL_REGISTER, EVALUATE."""

from __future__ import annotations

import os
import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from physicsai_core.db.repositories import datasets as datasets_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.paths import allowed_roots, check_dataset_input, check_user_path

from ...context import AppContext
from ..common import study_root
from ..path_inspect import inspect_model_folder
from .base import _P, invalid_errors, prerequisite_missing

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
    "PACKAGE_EXPORT": PackageExportParams,
    "MODEL_REGISTER": ModelRegisterParams,
    "EVALUATE": EvaluateParams,
}


def prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any
            ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    """사전조건 확인(§8.2) → (저장할 params, 초기 result, warnings). 기능 확인(check_feature)은 디스패처가 먼저 한다."""
    cfg = ctx.settings
    sid = study["id"]
    warnings: list[dict[str, str]] = []
    if job_type == "DATASET_CREATE":
        if (p.input_path is None) == (p.curation_id is None):
            raise invalid_errors([{"loc": ["params", "input_path"], "msg": "input_path와 curation_id 중 하나만 지정하세요"}])
        if p.curation_id is not None:
            from physicsai_core.db.repositories import curations as cur_repo

            cur = cur_repo.get_curation(conn, p.curation_id)
            if cur is None or cur["study_id"] != sid or cur["status"] != "READY" or cur["kind"] != "H3D":
                raise prerequisite_missing("READY_H3D_CURATION")
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
            "split_rel": f"03_dataset/{ds_id}/split.json",
            "train_psdata_rel": f"03_dataset/{ds_id}/train/dataset.psdata",
            "eval_psdata_rel": f"03_dataset/{ds_id}/eval/dataset.psdata",
        })


def on_retry(conn: Any, old: dict[str, Any], new_id: str) -> None:
    """재시도: 데이터셋 행을 다시 BUILDING."""
    if old["job_type"] == "DATASET_CREATE" and (old["result"] or {}).get("dataset_id"):
        datasets_repo.set_values(conn, old["result"]["dataset_id"], status="BUILDING")
