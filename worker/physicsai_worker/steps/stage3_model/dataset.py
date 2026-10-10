"""③-1 DATASET_CREATE(§8.4)."""

from __future__ import annotations

import json
import os
from typing import Any

from physicsai_core.stage3_model.dataset_split import collect_h3d, dataset_yaml, split_files
from physicsai_core.db.repositories import datasets as datasets_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json, write_text
from physicsai_core.paths import PathError, check_dataset_input, check_user_path, file_safety_problem

from ..common import path_failure


def _ds(ctx: Any) -> tuple[str, str]:
    ds_id = ctx.result().get("dataset_id")
    if not ds_id:
        raise StepFailure("INTERNAL_ERROR", "dataset_id가 없습니다")
    return ds_id, ctx.abs(f"03_dataset/{ds_id}")


def ds_scan(ctx: Any) -> None:
    p, s = ctx.params, ctx.settings
    ds_id, D = _ds(ctx)
    try:
        cp = check_user_path(p["input_path"], [s.storage.ai_root])
        exclude = check_dataset_input(cp.path, s.storage.ai_root)
    except PathError as exc:
        raise path_failure(exc) from None
    files = collect_h3d(cp.path, exclude)
    bad = [(f, why) for f in files if (why := file_safety_problem(f, cp.path))]
    if bad:
        listing = ", ".join(f"{os.path.relpath(f, cp.path)}({w})" for f, w in bad[:10])
        raise StepFailure("INPUT_INVALID", f"경로 규칙 위반 파일 {len(bad)}개: {listing}")
    if len(files) < s.dataset.min_h3d_files:
        raise StepFailure("INPUT_INVALID", f"h3d 파일이 {len(files)}개입니다(최소 {s.dataset.min_h3d_files}개)")
    sp = split_files(files, float(p["holdout_ratio"]), int(p["seed"]), p["split_group"])
    if sp.n_groups < 2 or not sp.train or not sp.eval:
        raise StepFailure("INPUT_INVALID", "학습용·평가용으로 나눌 그룹이 2개 이상 필요합니다")
    os.makedirs(D, exist_ok=True)
    split_path = os.path.join(D, "split.json")
    ctx.backup([split_path])
    write_json(split_path, {"seed": int(p["seed"]), "holdout_ratio": float(p["holdout_ratio"]),
                            "split_group": p["split_group"], "train": sp.train, "eval": sp.eval})
    ctx.log(f"h3d {len(files)}개 → 학습 {len(sp.train)} / 평가 {len(sp.eval)} (seed {p['seed']})")
    ctx.ex.db(lambda c: datasets_repo.set_values(c, ds_id, h3d_count=len(files), train_count=len(sp.train),
                                                 eval_count=len(sp.eval)))
    ctx.patch_result({"h3d_count": len(files), "train_count": len(sp.train), "eval_count": len(sp.eval)})


def ds_yaml(ctx: Any) -> None:
    _ds_id, D = _ds(ctx)
    with open(os.path.join(D, "split.json"), encoding="utf-8") as fh:
        split = json.load(fh)
    hooks = os.path.join(D, "hooks")
    os.makedirs(hooks, exist_ok=True)
    opts = ctx.params.get("options") or {}
    for part in ("train", "eval"):
        y = os.path.join(D, part, "dataset.yaml")
        ctx.backup([y])
        write_text(y, dataset_yaml(split[part], hooks, opts))
        ctx.add_output(y)


def _edspy(ctx: Any, part: str) -> None:
    _ds_id, D = _ds(ctx)
    out = os.path.join(D, part, "dataset.psdata")
    spec = os.path.join(D, part, "dataset.yaml")
    ctx.run_local("edspy_create_dataset", {"out_psdata": out, "spec_yaml": spec}, cwd=os.path.join(D, part),
                  outputs_to_backup=[out])
    if not os.path.isfile(out):
        raise StepFailure("OUTPUT_MISSING", f"{part}/dataset.psdata가 만들어지지 않았습니다")
    size = os.path.getsize(out)
    if size < ctx.settings.dataset.min_psdata_bytes:
        raise StepFailure("OUTPUT_TOO_SMALL", f"{part}/dataset.psdata 크기가 {size} bytes로 너무 작습니다")
    ctx.add_output(out)


def edspy_train(ctx: Any) -> None:
    _edspy(ctx, "train")


def edspy_eval(ctx: Any) -> None:
    _edspy(ctx, "eval")


def ds_register(ctx: Any) -> None:
    ds_id, D = _ds(ctx)
    tr, ev = os.path.join(D, "train", "dataset.psdata"), os.path.join(D, "eval", "dataset.psdata")
    ctx.ex.db(lambda c: datasets_repo.set_values(c, ds_id, status="READY", train_psdata_size=os.path.getsize(tr),
                                                 eval_psdata_size=os.path.getsize(ev)))
    ctx.register_artifact("SPLIT_JSON", os.path.join(D, "split.json"))
    r = ctx.result()
    ctx.patch_result({"dataset_id": ds_id, "h3d_count": r.get("h3d_count"), "train_count": r.get("train_count"),
                      "eval_count": r.get("eval_count")})


HANDLERS = {
    ("DATASET_CREATE", "DS_SCAN"): ds_scan,
    ("DATASET_CREATE", "DS_YAML"): ds_yaml,
    ("DATASET_CREATE", "EDSPY_DATASET_TRAIN"): edspy_train,
    ("DATASET_CREATE", "EDSPY_DATASET_EVAL"): edspy_eval,
    ("DATASET_CREATE", "DS_REGISTER"): ds_register,
}

