"""경로 확인(§10.3 inspect, phase2 §12.4): 용도별 폴더·파일 검사와 공용 폴더 조사 헬퍼."""

from __future__ import annotations

import fnmatch
import os
from typing import Any

from physicsai_core.stage2_curation import curation as cu
from physicsai_core.stage4_predict import param_sets as ps_mod
from physicsai_core.stage2_curation import spdm
from physicsai_core.stage3_model.dataset_split import collect_h3d, n_eval_groups, split_files
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.paths import allowed_roots, check_dataset_input, check_user_path, file_safety_problem

from ..auth import Principal
from ..context import AppContext
from .common import require_power


def starters_in(folder: str, glob_: str) -> list[str]:
    return sorted(n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n))
                  and fnmatch.fnmatch(n, glob_) and not n.lower().startswith("eps_mesh"))


P2_PURPOSES = ("CAD_FILE", "RADIOSS_ASSEM", "RESULT_FOLDER", "CURATION_INPUT", "SPDM_IMPORT")


def _list_direct(folder: str, patterns: list[str]) -> list[str]:
    out = []
    for name in sorted(os.listdir(folder)):
        p = os.path.join(folder, name)
        if os.path.isfile(p) and any(fnmatch.fnmatch(name.lower(), pat.lower()) for pat in patterns):
            out.append(name)
    return out


def inspect_model_folder(folder: str, log_globs: list[str]) -> dict[str, list[str]]:
    psmdl = _list_direct(folder, ["*.psmdl"])
    pscfg = _list_direct(folder, ["*.pscfg"])
    logs = _list_direct(folder, log_globs)
    return {"psmdl": psmdl, "pscfg": pscfg, "logs": logs}


def inspect_path(ctx: AppContext, principal: Principal, study_id: str, body: Any) -> dict[str, Any]:
    s_cfg = ctx.settings
    with ctx.engine.connect() as conn:
        s = studies_repo.require(conn, study_id)
    require_power(principal, s["project_id"])
    if body.purpose in P2_PURPOSES:
        return inspect_phase2(ctx, s, body)
    roots = allowed_roots(s_cfg, imports=body.purpose == "MODEL_FOLDER")
    cp = check_user_path(body.path, roots)
    problems: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    if body.purpose == "DATASET_INPUT":
        files = collect_h3d(cp.path, check_dataset_input(cp.path, s_cfg.storage.ai_root))
        for f in files:
            why = file_safety_problem(f, cp.path)
            if why:
                problems.append({"code": "PATH_UNSAFE", "message": f"{why}가 포함된 파일", "file": os.path.relpath(f, cp.path)})
        groups = len(files) if s_cfg.dataset.split_group == "file" else len({os.path.dirname(f) for f in files})
        if len(files) < s_cfg.dataset.min_h3d_files or groups < 2:
            problems.append({"code": "TOO_FEW_H3D", "message": f"h3d 파일이 {s_cfg.dataset.min_h3d_files}개 이상 필요합니다"})
        sp = split_files(files, s_cfg.dataset.holdout_ratio, s_cfg.dataset.seed, s_cfg.dataset.split_group)
        summary = {
            "h3d_count": len(files),
            "sample_files": [os.path.relpath(f, cp.path).replace(os.sep, "/") for f in files[:10]],
            "expected_train": len(sp.train),
            "expected_eval": len(sp.eval) if groups >= 2 else (n_eval_groups(groups, s_cfg.dataset.holdout_ratio) if groups else 0),
        }
    elif body.purpose == "MODEL_FOLDER":
        summary = inspect_model_folder(cp.path, s_cfg.training_log.log_globs)
        if len(summary["psmdl"]) != 1:
            problems.append({"code": "PSMDL_COUNT", "message": f".psmdl 파일이 정확히 1개 있어야 합니다(현재 {len(summary['psmdl'])}개)"})
        if len(summary["pscfg"]) != 1:
            problems.append({"code": "PSCFG_COUNT", "message": f".pscfg 파일이 정확히 1개 있어야 합니다(현재 {len(summary['pscfg'])}개)"})
        if len(summary["logs"]) > 1:
            problems.append({"code": "LOG_SELECT_REQUIRED", "message": "학습 로그 후보가 여러 개입니다. 로그 파일을 선택하세요"})
    else:
        f = ps_mod.validate_folder(cp.path, max_samples=s_cfg.param_set.max_samples,
                                   max_total_bytes=s_cfg.param_set.max_total_bytes, starter_glob=s_cfg.predict.starter_glob)
        problems.extend(f.problems)
        summary = f.summary()
    return {"normalized_path": cp.path, "ok": not problems, "problems": problems, "summary": summary}


def inspect_phase2(ctx: AppContext, study: dict[str, Any], body: Any) -> dict[str, Any]:
    """경로 확인 확장(phase2 §12.4): CAD_FILE, RADIOSS_ASSEM, RESULT_FOLDER, CURATION_INPUT, SPDM_IMPORT."""
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
        cp = check_user_path(body.path, allowed_roots(s, imports=True), expect="file")
        name = os.path.basename(cp.path)
        ok_ext = os.path.splitext(name)[1].lower() in [e.lower() for e in s.train_data.cad_extensions]
        summary = {"file_name": name, "size": os.path.getsize(cp.path), "extension_ok": ok_ext}
        if not ok_ext:
            problems.append({"code": "CAD_EXTENSION", "message": f"CAD 확장자는 {', '.join(s.train_data.cad_extensions)} 중 하나여야 합니다"})
    elif body.purpose == "RADIOSS_ASSEM":
        cp = check_user_path(body.path, allowed_roots(s, imports=True))
        names = sorted(n for n in os.listdir(cp.path) if os.path.isfile(os.path.join(cp.path, n)))
        rad = [n for n in names if n.lower().endswith(".rad")]
        st = starters_in(cp.path, s.predict.starter_glob)
        summary = {"rad": rad[:50], "inc_count": sum(1 for n in names if n.lower().endswith(".inc")), "starter": st,
                   "starter_ok": len(st) == 1}
        if len(st) != 1:
            problems.append({"code": "STARTER_COUNT", "message": f"starter({s.predict.starter_glob})가 정확히 1개 있어야 합니다(현재 {len(st)}개)"})
    elif body.purpose == "RESULT_FOLDER":
        roots = allowed_roots(s, imports=True)
        if s.hpc.transfer.collect_root_local:
            roots.append(s.hpc.transfer.collect_root_local)
        cp = check_user_path(body.path, roots)
        run_keys: set[str] | None = None
        if body.doe_id:
            with ctx.engine.connect() as conn:
                d = train_repo.get_doe(conn, body.doe_id)
                if d is not None and d["study_id"] == study["id"]:
                    run_keys = {r["run_key"] for r in train_repo.runs_for_doe(conn, d["id"])}
        from physicsai_core.stage1_train_data.train_params import RunDirMatcher

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
