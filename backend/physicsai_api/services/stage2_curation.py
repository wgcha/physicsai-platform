"""② 데이터 정리 조회 API(phase2 §12.6)·SPDM 가져오기 목록."""

from __future__ import annotations

import json
import os
from typing import Any

from physicsai_core import curation as cu
from physicsai_core.db.repositories import curations as cur_repo
from physicsai_core.db.repositories import spdm_imports as imp_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import DomainError
from physicsai_core.paths import display_path, resolve_in_study

from ..context import AppContext
from .common import clamp_limit, decode_cursor, encode_cursor, study_root


def _count(root: str) -> tuple[int, int]:
    if not os.path.isdir(root):
        return 0, 0
    h = t = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d != "_backup"]
        for f in filenames:
            h += cu.is_h3d(f)
            t += cu.is_t01(f)
    return h, t


def curation_sources(ctx: AppContext, study_id: str) -> list[dict[str, Any]]:
    ai = ctx.settings.storage.ai_root
    out = []
    with ctx.engine.connect() as conn:
        st = studies_repo.require(conn, study_id)
        root = study_root(ctx, st)
        for d in train_repo.list_does(conn, study_id):
            if d["status"] != "READY":
                continue
            counts = train_repo.run_state_counts(conn, d["id"])
            if counts["COLLECTED"] < 1:
                continue
            rel = cu.source_root_rel({"kind": "TRAIN_DOE", "doe_id": d["id"]})
            h, t = _count(resolve_in_study(root, rel))
            out.append({"kind": "TRAIN_DOE", "ref_id": d["id"], "label": f"① DOE {d['doe_label']} · {d['id'][:8]}",
                        "display_path": display_path(ai, st["folder_name"], rel), "h3d_count": h, "t01_count": t,
                        "runs_expected": d["run_count"], "created_at": d["created_at"]})
        for i in imp_repo.list_imports(conn, study_id):
            if i["status"] != "READY":
                continue
            rel = i["dest_rel"]
            h, t = _count(resolve_in_study(root, rel))
            leaf = i["spdm_path"].replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
            out.append({"kind": "SPDM_IMPORT", "ref_id": i["id"], "label": f"SPDM 가져오기 · {leaf}",
                        "display_path": display_path(ai, st["folder_name"], rel), "h3d_count": h, "t01_count": t,
                        "runs_expected": None, "created_at": i["created_at"]})
    return out


def _source_label(src: dict[str, Any]) -> str:
    k = src.get("kind")
    if k == "TRAIN_DOE":
        return f"① DOE {str(src.get('doe_id'))[:8]}"
    if k == "SPDM_IMPORT":
        return f"SPDM 가져오기 {str(src.get('import_id'))[:8]}"
    return f"폴더 {src.get('path')}"


def curation_out(ctx: AppContext, conn: Any, st: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c["id"], "study_id": c["study_id"], "job_id": c["job_id"], "kind": c["kind"], "status": c["status"],
        "source": c["source"], "source_label": _source_label(c["source"]), "preview_job_id": c["preview_job_id"],
        "selection": c["selection"] or {}, "target_count": c["target_count"], "ok_count": c["ok_count"],
        "failed_count": c["failed_count"], "missing_runs": c["missing_runs"] or [],
        "output_display_path": display_path(ctx.settings.storage.ai_root, st["folder_name"], c["output_rel"]),
        "used_by_dataset_ids": cur_repo.datasets_using_curation(conn, c["id"]),
        "created_by_name": c["created_by_name"], "created_at": c["created_at"],
    }


def list_curations(ctx: AppContext, study_id: str, kind: str | None) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        st = studies_repo.require(conn, study_id)
        return [curation_out(ctx, conn, st, c) for c in cur_repo.list_curations(conn, study_id, kind)]


def _require(conn: Any, cid: str) -> dict[str, Any]:
    c = cur_repo.get_curation(conn, cid)
    if c is None:
        raise DomainError("NOT_FOUND", "큐레이션을 찾을 수 없습니다", status=404)
    return c


def get_curation(ctx: AppContext, cid: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        c = _require(conn, cid)
        st = studies_repo.require(conn, c["study_id"])
        return curation_out(ctx, conn, st, c)


def curation_files(ctx: AppContext, cid: str, ok: bool | None, limit: int | None, cursor: str | None) -> dict[str, Any]:
    lim, off = clamp_limit(limit), decode_cursor(cursor)
    with ctx.engine.connect() as conn:
        c = _require(conn, cid)
        st = studies_repo.require(conn, c["study_id"])
    p = resolve_in_study(study_root(ctx, st), c["file_list_rel"])
    items: list[dict[str, Any]] = []
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        for x in data if isinstance(data, list) else []:
            if ok is not None and bool(x.get("ok")) != ok:
                continue
            items.append({"run_folder": x.get("run_folder", ""), "run_key": x.get("run_key"),
                          "input_name": x.get("input_rel", ""), "output_name": x.get("output_rel"),
                          "size": x.get("size"), "ok": bool(x.get("ok")), "exit_code": x.get("exit_code")})
    page = items[off: off + lim]
    return {"items": page, "next_cursor": encode_cursor(off + lim) if off + lim < len(items) else None}


def list_imports(ctx: AppContext, study_id: str) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        st = studies_repo.require(conn, study_id)
        rows = imp_repo.list_imports(conn, study_id)
    return [{"id": i["id"], "study_id": i["study_id"], "job_id": i["job_id"], "status": i["status"],
             "spdm_path": i["spdm_path"], "file_count": i["file_count"], "total_bytes": i["total_bytes"],
             "renamed_count": i["renamed_count"],
             "dest_display_path": display_path(ctx.settings.storage.ai_root, st["folder_name"], i["dest_rel"]),
             "created_by_name": i["created_by_name"], "created_at": i["created_at"]} for i in rows]
