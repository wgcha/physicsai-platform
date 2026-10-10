"""② 데이터 정리·SPDM 가져오기 작업 params·사전조건(phase2 §4.4, §6.7~§6.10, §12.10): CU_*, SPDM_IMPORT."""

from __future__ import annotations

import os
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from physicsai_core import curation as cu
from physicsai_core import optimize as opt
from physicsai_core import spdm
from physicsai_core.db.repositories import curations as cur_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import spdm_imports as imp_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import DomainError
from physicsai_core.paths import check_dataset_input, check_user_path, resolve_in_study

from ...context import AppContext
from ..common import study_root
from .base import _P, invalid_at, prerequisite_missing


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


class PreviewParams(_P):
    source: Source
    sample_file: str | None = Field(default=None, max_length=400)


class SelItem(_P):
    datatype: str = Field(pattern=opt.FIELD_PATTERN)
    component: str = Field(pattern=opt.FIELD_PATTERN)


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
    type: str = Field(pattern=opt.FIELD_PATTERN)
    request: str = Field(pattern=opt.FIELD_PATTERN)
    component: str = Field(pattern=opt.FIELD_PATTERN)


class T01CurvesParams(_P):
    source: Source
    curves: list[CurveIn] = Field(min_length=1)
    exclude_files: list[str] = Field(default_factory=list)


class SpdmImportParams(_P):
    spdm_path: str = Field(max_length=400)


PARAM_MODELS: dict[str, type[BaseModel]] = {
    "CU_H3D_PREVIEW": PreviewParams,
    "CU_T01_PREVIEW": PreviewParams,
    "CU_H3D_CURATE": H3dCurateParams,
    "CU_T01_CURVES": T01CurvesParams,
    "SPDM_IMPORT": SpdmImportParams,
}


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
            raise prerequisite_missing("READY_SPDM_IMPORT")
        return {"kind": "SPDM_IMPORT", "import_id": i["id"]}, resolve_in_study(root_dir, f"02_import/{i['id']}")
    cp = check_user_path(source.path, [ctx.settings.storage.ai_root])
    check_dataset_input(cp.path, ctx.settings.storage.ai_root)
    return {"kind": "FOLDER", "path": cp.path}, cp.path


def _source_files(ctx: AppContext, root: str, kind: str) -> list[str]:
    files = cu.collect_files(root, kind, ctx.settings.curation.max_files) if os.path.isdir(root) else []
    if not files:
        raise prerequisite_missing("SOURCE_FILES")
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


def prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any
            ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    """사전조건 확인(§8.2) → (저장할 params, 초기 result, warnings). 기능 확인(check_feature)은 디스패처가 먼저 한다."""
    cfg = ctx.settings
    if job_type in ("CU_H3D_PREVIEW", "CU_T01_PREVIEW"):
        kind = "H3D" if job_type == "CU_H3D_PREVIEW" else "T01"
        src, root = resolve_source(ctx, conn, study, p.source)
        files = _source_files(ctx, root, kind)
        if p.sample_file:
            rels = {os.path.relpath(f, root).replace(os.sep, "/") for f in files}
            if p.sample_file.replace("\\", "/") not in rels:
                raise invalid_at("sample_file", "원천에 없는 파일입니다")
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
    raise invalid_at("job_type", "unknown")


def after_insert(conn: Any, principal: Any, study: dict[str, Any], job_type: str, job_id: str, params: dict[str, Any],
                 result: dict[str, Any] | None) -> None:
    """작업 생성과 같은 트랜잭션에서 큐레이션·가져오기 행(BUILDING) 생성(B8 방식)."""
    base = {"study_id": study["id"], "job_id": job_id, "created_by": principal.user_id,
            "created_by_name": principal.display_name}
    if job_type in ("CU_H3D_CURATE", "CU_T01_CURVES"):
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
    """재시도: 큐레이션·가져오기 행을 새 작업으로 다시 BUILDING."""
    p = old["params"] or {}
    if old["job_type"] in ("CU_H3D_CURATE", "CU_T01_CURVES") and p.get("curation_id"):
        cur_repo.set_building_job(conn, p["curation_id"], new_id)
    elif old["job_type"] == "SPDM_IMPORT" and p.get("import_id"):
        imp_repo.set_building_job(conn, p["import_id"], new_id)
