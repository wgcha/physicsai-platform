"""③-5 EVALUATE(§8.7)."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.db.repositories import datasets as datasets_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json
from physicsai_core.parsers.score import parse_scores

from ..common import load_model, verify_model_integrity


def _E(ctx: Any, m: dict[str, Any]) -> str:
    return ctx.abs(f"03_model/score/{m['id']}/{ctx.workspace_id}")


def ev_prep(ctx: Any) -> None:
    m = load_model(ctx, ctx.params["model_id"])
    verify_model_integrity(ctx, m)
    ctx.ex.db(lambda c: models_repo.set_values(c, m["id"], eval_status="RUNNING", eval_job_id=ctx.ex.job_id))
    os.makedirs(_E(ctx, m), exist_ok=True)


def edspy_score(ctx: Any) -> None:
    m = load_model(ctx, ctx.params["model_id"])
    with ctx.ex.engine.connect() as conn:
        d = datasets_repo.get(conn, m["dataset_id"]) if m["dataset_id"] else None
    if d is None or d["status"] != "READY":
        raise StepFailure("INPUT_INVALID", "모델의 데이터셋이 READY가 아닙니다")
    E = _E(ctx, m)
    score = os.path.join(E, f"{m['name']}.psscr")
    preds = os.path.join(E, "predictions.psdata")
    ctx.run_local(
        "edspy_score",
        {"score_path": score, "model_psmdl": ctx.abs(m["psmdl_rel"]), "model_pscfg": ctx.abs(m["pscfg_rel"]),
         "eval_psdata": ctx.abs(d["eval_psdata_rel"])},
        cwd=E,
        outputs_to_backup=[score, preds],
    )
    if not os.path.isfile(score):
        raise StepFailure("OUTPUT_MISSING", f"{os.path.basename(score)}가 만들어지지 않았습니다")
    ctx.add_output(score)


def ev_parse(ctx: Any) -> None:
    m = load_model(ctx, ctx.params["model_id"])
    E = _E(ctx, m)
    with ctx.ex.engine.connect() as conn:
        from physicsai_core.db.repositories import jobs as jobs_repo

        steps = {s["step_key"]: s for s in jobs_repo.get_steps(conn, ctx.ex.job_id)}
    log_path = ctx.abs(steps["EDSPY_SCORE"]["log_rel"])
    lines: list[str] = []
    if os.path.isfile(log_path):
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            lines = [ln for ln in fh if not ln.startswith(("===", "[CMD]", "[EXIT]", "[BACKUP]"))]
    status, metrics = parse_scores(lines, [(p.name, p.pattern) for p in ctx.settings.score.parsers])
    score_rel = ctx.rel(os.path.join(E, f"{m['name']}.psscr"))
    summary = os.path.join(E, "score_summary.json")
    write_json(summary, {"status": status, "metrics": metrics, "score_rel": score_rel})
    eval_score = {"status": status, "metrics": metrics, "score_rel": score_rel}
    ctx.ex.db(lambda c: models_repo.set_values(c, m["id"], eval_status="DONE", eval_score=eval_score))
    aid = ctx.register_artifact("SCORE_FILE", summary)
    ctx.patch_result({"model_id": m["id"], "eval_score": eval_score, "score_artifact_id": aid})


HANDLERS = {
    ("EVALUATE", "EV_PREP"): ev_prep,
    ("EVALUATE", "EDSPY_SCORE"): edspy_score,
    ("EVALUATE", "EV_PARSE"): ev_parse,
}
