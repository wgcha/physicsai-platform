"""경로 확인 확장(phase2 §12.4): CAD_FILE, RADIOSS_ASSEM, RESULT_FOLDER, CURATION_INPUT, SPDM_IMPORT."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core import curation as cu
from physicsai_core import spdm
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.paths import check_dataset_input, check_user_path

from ..context import AppContext
from .phase2_params import starters_in


def inspect_phase2(ctx: AppContext, study: dict[str, Any], body: Any) -> dict[str, Any]:
    s = ctx.settings
    problems: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    if body.purpose == "SPDM_IMPORT":
        if not s.storage.spdm_roots:
            from physicsai_core.errors import DomainError

            raise DomainError("SPDM_IMPORT_DISABLED", "SPDM 가져오기가 설정되지 않았습니다(storage.spdm_roots)", status=409)
        path = spdm.check_spdm_path(body.path, s.storage.spdm_roots)
        res = spdm.scan(path, s.spdm_import.patterns, s.spdm_import.max_files)
        summary = {"h3d_count": res.h3d_count, "t01_count": res.t01_count, "total_bytes": res.total_bytes,
                   "renamed_count": res.renamed_count, "sample_files": [f.source_rel for f in res.files[:10]]}
        if not res.files:
            problems.append({"code": "NO_FILES", "message": "가져올 h3d·T01 파일이 없습니다"})
        if res.total_bytes > s.spdm_import.max_total_bytes:
            problems.append({"code": "TOO_LARGE", "message": "총량이 상한(spdm_import.max_total_bytes)을 넘습니다"})
        return {"normalized_path": path, "ok": not problems, "problems": problems, "summary": summary}
    if body.purpose == "CAD_FILE":
        cp = check_user_path(body.path, [s.storage.ai_root, *s.storage.allowed_import_roots], expect="file")
        name = os.path.basename(cp.path)
        ok_ext = os.path.splitext(name)[1].lower() in [e.lower() for e in s.train_data.cad_extensions]
        summary = {"file_name": name, "size": os.path.getsize(cp.path), "extension_ok": ok_ext}
        if not ok_ext:
            problems.append({"code": "CAD_EXTENSION", "message": f"CAD 확장자는 {', '.join(s.train_data.cad_extensions)} 중 하나여야 합니다"})
    elif body.purpose == "RADIOSS_ASSEM":
        cp = check_user_path(body.path, [s.storage.ai_root, *s.storage.allowed_import_roots])
        names = sorted(n for n in os.listdir(cp.path) if os.path.isfile(os.path.join(cp.path, n)))
        rad = [n for n in names if n.lower().endswith(".rad")]
        st = starters_in(cp.path, s.predict.starter_glob)
        summary = {"rad": rad[:50], "inc_count": sum(1 for n in names if n.lower().endswith(".inc")), "starter": st,
                   "starter_ok": len(st) == 1}
        if len(st) != 1:
            problems.append({"code": "STARTER_COUNT", "message": f"starter({s.predict.starter_glob})가 정확히 1개 있어야 합니다(현재 {len(st)}개)"})
    elif body.purpose == "RESULT_FOLDER":
        roots = [s.storage.ai_root, *s.storage.allowed_import_roots]
        if s.hpc.transfer.collect_root_local:
            roots.append(s.hpc.transfer.collect_root_local)
        cp = check_user_path(body.path, roots)
        run_keys: set[str] | None = None
        if body.doe_id:
            with ctx.engine.connect() as conn:
                d = train_repo.get_doe(conn, body.doe_id)
                if d is not None and d["study_id"] == study["id"]:
                    run_keys = {r["run_key"] for r in train_repo.runs_for_doe(conn, d["id"])}
        from physicsai_core.train_params import RunDirMatcher

        matcher = RunDirMatcher(s.train_data.result_run_dir_regex, run_keys)
        matched, unmatched, files = set(), [], 0
        base = cp.path.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(cp.path, followlinks=False):
            dirnames[:] = sorted(x for x in dirnames if x != "_backup")
            files += len(filenames)
            if dirpath.rstrip(os.sep).count(os.sep) - base >= s.train_data.result_match_depth:
                dirnames[:] = []
                continue
            for x in dirnames:
                rk = matcher.match(x)
                if rk:
                    matched.add(rk)
                elif len(unmatched) < 20:
                    unmatched.append(os.path.relpath(os.path.join(dirpath, x), cp.path).replace(os.sep, "/"))
        summary = {"doe_id": body.doe_id, "matched_runs": len(matched), "unmatched_dirs": unmatched, "file_count": files}
        if not matched:
            problems.append({"code": "NO_RUN_FOLDER", "message": "run 폴더를 찾지 못했습니다"})
    else:  # CURATION_INPUT
        cp = check_user_path(body.path, [s.storage.ai_root])
        excl = check_dataset_input(cp.path, s.storage.ai_root)
        del excl
        h3d = cu.collect_files(cp.path, "H3D", s.curation.max_files)
        t01 = cu.collect_files(cp.path, "T01", s.curation.max_files)
        names = cu.run_folder_names(cp.path, h3d or t01)
        summary = {"h3d_count": len(h3d), "t01_count": len(t01), "run_folders": sorted(set(names))[:20]}
        if not h3d and not t01:
            problems.append({"code": "NO_FILES", "message": "h3d·T01 파일이 없습니다"})
    return {"normalized_path": cp.path, "ok": not problems, "problems": problems, "summary": summary}
