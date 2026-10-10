"""①-6 TD_RESP_EXTRACT: run별 응답 추출·응답 표(phase2 §6.6.1)."""

from __future__ import annotations

import csv
import os
from typing import Any

from physicsai_core.commands import fwd
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json
from physicsai_core.parsers.name_value import read_name_value_csv

from ._shared import _D, _R, _doe, _match_files


def rx_prep(ctx: Any) -> None:
    doe = _doe(ctx)
    D = _D(ctx, doe["id"])
    rj = os.path.join(D, "responses.json")
    ctx.backup([rj])
    write_json(rj, {"responses": ctx.params["responses"]})
    with ctx.ex.engine.connect() as conn:
        runs = train_repo.runs_for_doe(conn, doe["id"], states=["COLLECTED"])
    targets = []
    for x in runs:
        R = _R(ctx, doe["id"], x["run_key"])
        h3ds = sorted(_match_files(R, ["*.h3d", "*.H3D"]))
        if not h3ds:
            ctx.add_warning("RUN_H3D_MISSING", f"{x['run_key']}: h3d가 없어 건너뜁니다")
            continue
        targets.append({"run_key": x["run_key"], "h3d": os.path.join(R, *h3ds[0].split("/"))})
    if not targets:
        raise StepFailure("INPUT_INVALID", "응답을 추출할 h3d가 있는 run이 없습니다")
    ctx.patch_result({"doe_id": doe["id"], "targets": targets})


def rx_extract(ctx: Any) -> None:
    doe = _doe(ctx)
    rj = os.path.join(_D(ctx, doe["id"]), "responses.json")
    targets = []
    for t in ctx.result()["targets"]:
        R = _R(ctx, doe["id"], t["run_key"])
        out = os.path.join(R, "responses_run.csv")
        ctx.backup([out])
        targets.append({"target_id": t["run_key"], "cwd": R, "out": out,
                        "values": {"pred_h3d": t["h3d"], "pred_h3d_fwd": fwd(t["h3d"]), "responses_json": rj,
                                   "out_csv": out, "work_dir": R}})
    res = ctx.run_fanout("response_extract", targets, cwd=_D(ctx, doe["id"]), success=lambda t: os.path.isfile(t["out"]))
    ctx.patch_result({"extracted_runs": res["ok"], "extract_failed": [f["target_id"] for f in res["failed"]]})


def rx_table(ctx: Any) -> None:
    doe = _doe(ctx)
    names = [r["name"] for r in ctx.params["responses"]]
    rows = []
    for rk in ctx.result().get("extracted_runs") or []:
        vals = read_name_value_csv(os.path.join(_R(ctx, doe["id"], rk), "responses_run.csv"))
        rows.append([rk, *["" if vals.get(n) is None else repr(vals[n]) for n in names]])
    out = os.path.join(_D(ctx, doe["id"]), "run_responses.csv")
    ctx.backup([out])
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["run_key", *names])
        w.writerows(rows)
    ctx.ex.db(lambda c: train_repo.set_doe(c, doe["id"], responses_rel=ctx.rel(out)))
    ctx.patch_result({"run_count": len(rows)})


HANDLERS = {
    ("TD_RESP_EXTRACT", "RX_PREP"): rx_prep,
    ("TD_RESP_EXTRACT", "RESPONSE_EXTRACT_RUNS"): rx_extract,
    ("TD_RESP_EXTRACT", "RX_TABLE"): rx_table,
}
