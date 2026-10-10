"""③-4 MODEL_REGISTER(§8.6). pscfg는 경로·sha256만 기록하고 열지 않는다."""

from __future__ import annotations

import fnmatch
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from physicsai_core.db.repositories import datasets as datasets_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, sha256_file, write_json
from physicsai_core.stage3_model.loss import as_db_values, parse_loss_file
from physicsai_core.paths import allowed_roots, check_user_path, is_link_or_reparse, PathError, real, unsafe_reason

from ..common import path_failure


def _direct(folder: str, patterns: list[str]) -> list[str]:
    return sorted(
        n for n in os.listdir(folder)
        if os.path.isfile(os.path.join(folder, n)) and any(fnmatch.fnmatch(n.lower(), p.lower()) for p in patterns)
    )


def _under_dir(fp: str, folder: str) -> bool:
    return os.path.dirname(real(fp)) == real(folder)


def mr_validate(ctx: Any) -> None:
    s, p = ctx.settings, ctx.params
    try:
        cp = check_user_path(p["model_path"], allowed_roots(s, imports=True))
    except PathError as exc:
        raise path_failure(exc) from None
    psmdl, pscfg = _direct(cp.path, ["*.psmdl"]), _direct(cp.path, ["*.pscfg"])
    if len(psmdl) != 1:
        raise StepFailure("INPUT_INVALID", f".psmdl 파일이 정확히 1개 있어야 합니다(현재 {len(psmdl)}개)")
    if len(pscfg) != 1:
        raise StepFailure("INPUT_INVALID", f".pscfg 파일이 정확히 1개 있어야 합니다(현재 {len(pscfg)}개)")
    logs = _direct(cp.path, s.training_log.log_globs)
    log_file = p.get("log_file")
    if log_file:
        # API 검증과 별개로 워커에서도 다시 확인: 파일 이름만, 직계 일반 파일, 링크·위험 문자 금지
        if (not isinstance(log_file, str) or log_file in (".", "..") or os.path.basename(log_file) != log_file
                or "/" in log_file or "\\" in log_file or unsafe_reason(log_file)):
            raise StepFailure("INPUT_INVALID", f"로그 파일 이름이 올바르지 않습니다: {log_file}")
        if log_file not in os.listdir(cp.path):
            raise StepFailure("INPUT_INVALID", f"지정한 로그 파일이 없습니다: {log_file}")
        chosen = log_file
    elif len(logs) == 0:
        chosen = None
    elif len(logs) == 1:
        chosen = logs[0]
    else:
        raise StepFailure("INPUT_INVALID", "학습 로그 후보가 여러 개입니다. 로그 파일을 지정하세요: " + ", ".join(logs[:20]))
    for n in (psmdl[0], pscfg[0], chosen):
        if not n:
            continue
        fp = os.path.join(cp.path, n)
        if is_link_or_reparse(fp) or not os.path.isfile(fp) or unsafe_reason(n):
            raise StepFailure("INPUT_INVALID", f"모델 폴더 파일이 링크이거나 이름이 안전하지 않습니다: {n}")
        if not _under_dir(fp, cp.path):
            raise StepFailure("INPUT_INVALID", f"모델 폴더 밖을 가리키는 파일입니다: {n}")
    ctx.patch_result({"files": {"psmdl": psmdl[0], "pscfg": pscfg[0], "log": chosen}, "source_path": cp.path})


def mr_copy(ctx: Any) -> None:
    r = ctx.result()
    files, src = r["files"], r["source_path"]
    model_id = r.get("model_id") or str(uuid.uuid4())
    dest = ctx.abs(f"03_model/models/{model_id}")
    os.makedirs(dest, exist_ok=True)
    names = [n for n in (files["psmdl"], files["pscfg"], files.get("log")) if n]
    total = sum(os.path.getsize(os.path.join(src, n)) for n in names) or 1
    done = [0]
    copied: dict[str, Any] = {}
    for n in names:
        d = os.path.join(dest, n)
        ctx.backup([d])
        base = done[0]
        copy_file(os.path.join(src, n), d,
                  progress=lambda x, base=base: ctx.progress(100.0 * (base + x) / total, f"복사 {n}"),
                  checkpoint=ctx.checkpoint)
        done[0] += os.path.getsize(d)
        copied[n] = {"sha256": sha256_file(d, ctx.checkpoint), "size": os.path.getsize(d)}
        ctx.add_output(d)
    write_json(os.path.join(dest, "source.json"), {
        "source_path": src, "copied_at": datetime.now(timezone.utc).isoformat(),
        "files": {n: copied[n]["sha256"] for n in names},
    })
    ctx.patch_result({"model_id": model_id, "copied": copied, "stored_rel": f"03_model/models/{model_id}/"})


def mr_parse_log(ctx: Any) -> None:
    r = ctx.result()
    s = ctx.settings
    log_name = r["files"].get("log")
    if not log_name:
        ctx.patch_result({"log": {"log_status": "MISSING"}})
        ctx.log("학습 로그 없음")
        return
    path = ctx.abs(f"{r['stored_rel']}{log_name}")
    total = os.path.getsize(path) or 1
    res = parse_loss_file(path, [(p.name, p.pattern) for p in s.training_log.parsers], s.training_log.max_curve_points,
                          progress=lambda n: ctx.progress(100.0 * n / total, "로그 읽는 중"))
    if res.status != "PARSED":
        ctx.log("로그 형식 미확인 — 등록은 계속합니다")
    else:
        ctx.log(f"파서 {res.parser}: epoch {res.last_epoch}/{res.epochs_total}, 최종 loss {res.final_loss}, 최소 {res.min_loss}")
    ctx.patch_result({"log": as_db_values(res)})


def mr_register(ctx: Any) -> None:
    r = ctx.result()
    p = ctx.params
    files, copied, model_id = r["files"], r["copied"], r["model_id"]
    study_id = ctx.study["id"]
    logv = dict(r.get("log") or {"log_status": "MISSING"})
    stored = r["stored_rel"]

    def _do(conn: Any) -> dict[str, Any]:
        if models_repo.get(conn, model_id) is not None:
            return {"model_id": model_id}
        ds_id = p.get("dataset_id")
        if ds_id is None:
            d = datasets_repo.latest_ready(conn, study_id)
            ds_id = d["id"] if d else None
        version = models_repo.next_version(conn, study_id, p["name"])
        models_repo.insert(conn, {
            "id": model_id, "study_id": study_id, "name": p["name"], "version": version, "label": p.get("label"),
            "dataset_id": ds_id, "source_path": r["source_path"], "stored_rel": stored,
            "psmdl_rel": stored + files["psmdl"], "psmdl_sha256": copied[files["psmdl"]]["sha256"],
            "psmdl_size": copied[files["psmdl"]]["size"],
            "pscfg_rel": stored + files["pscfg"], "pscfg_sha256": copied[files["pscfg"]]["sha256"],
            "log_rel": stored + files["log"] if files.get("log") else None,
            "log_status": logv.get("log_status", "MISSING"), "log_parser": logv.get("log_parser"),
            "epochs_total": logv.get("epochs_total"), "last_epoch": logv.get("last_epoch"),
            "final_loss": logv.get("final_loss"), "min_loss": logv.get("min_loss"),
            "min_loss_epoch": logv.get("min_loss_epoch"), "loss_curve": logv.get("loss_curve"),
            "eval_status": "NONE", "status": "ACTIVE",
            "registered_by": ctx.job["created_by"], "registered_by_name": ctx.job["created_by_name"],
        })
        return {"model_id": model_id, "name": p["name"], "version": version, "dataset_id": ds_id,
                "log_status": logv.get("log_status", "MISSING")}

    out = ctx.ex.db(_do)
    log_summary = {k: v for k, v in logv.items() if k != "loss_curve"}
    ctx.patch_result({**out, "log": log_summary})


HANDLERS = {
    ("MODEL_REGISTER", "MR_VALIDATE"): mr_validate,
    ("MODEL_REGISTER", "MR_COPY"): mr_copy,
    ("MODEL_REGISTER", "MR_PARSE_LOG"): mr_parse_log,
    ("MODEL_REGISTER", "MR_REGISTER"): mr_register,
}
