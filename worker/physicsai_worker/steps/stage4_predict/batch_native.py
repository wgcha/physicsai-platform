"""④ PREDICT_BATCH(B)의 native 분기(geometry-engine.md §7.3.7): BP_PREP·BP_GEN.

run마다 `R = B/run__N`에 §7.3.6 샘플 생성(m_1 values.json·native_params.xml, paicad, m_3 조립). tpl·CAD 사본·렌더 스크립트 없음.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import sha256_file, write_json, write_text
from physicsai_core.paths import PathError
from physicsai_core.stage4_predict import prepared_input
from physicsai_core.stage4_predict.batch_matrix import BatchRow, batch_label, samples_csv_text

from ..geometry_native import effective_opts, engine_version, ensure_prep_ready, native_inputs, read_json
from ..geometry_sample import generate_sample, write_sample_inputs

M1 = "m_1"


def check_child_input(settings: Any, input_path: str) -> None:
    """하위 PREDICT(prepared)가 PR_PREP에서 다시 하는 검사를 먼저(실패면 생성 실패로)."""
    try:
        cp = prepared_input.check_path(input_path, settings)
    except PathError as exc:
        raise StepFailure("INPUT_INVALID", f"생성된 입력을 예측 입력으로 쓸 수 없습니다: {exc.message}") from None
    plan = prepared_input.plan_copy(cp.path, settings)
    if plan.problems:
        p0 = plan.problems[0]
        raise StepFailure(p0["code"] if p0["code"] == "STARTER_COUNT" else "INPUT_INVALID", p0["message"])


def _features(settings: Any, S: str) -> dict[str, Any]:
    return read_json(os.path.join(S, "native", "extract", "parameter_features.json"), settings.geometry.max_report_bytes)


def bp_prep(ctx: Any, b: dict[str, Any], m: dict[str, Any], ps: dict[str, Any], S: str, B: str) -> None:
    s = ctx.settings
    if not ps.get("starter_name") or not os.path.isfile(os.path.join(S, "radioss_assem", ps["starter_name"])):
        raise StepFailure("INPUT_CHANGED", f"템플릿 파일이 없습니다: radioss_assem/{ps.get('starter_name')}")
    opts = effective_opts(s, ps.get("geom_options"))
    ver, ocp, shown = engine_version(ctx)
    ctx.log(f"형상 엔진: {shown}")
    ensure_prep_ready(s, S, opts, ver)
    os.makedirs(B, exist_ok=True)
    ctx.ex.db(lambda c: pb_repo.reset_failed_gen(c, b["id"]))
    with ctx.ex.engine.connect() as conn:
        rows = pb_repo.runs(conn, b["id"])
    nominals = {f["name"]: float(f["nominal"]) for f in _features(s, S).get("features", [])
                if isinstance(f, dict) and isinstance(f.get("name"), str) and "nominal" in f}
    todo = [r for r in rows if r["gen_state"] != "DONE"]
    for k, r in enumerate(todo, 1):
        ctx.checkpoint()
        R = os.path.join(B, r["run_key"])
        if os.path.lexists(R):
            ctx.backup([R])  # 재실행: 실패·미완료 run 폴더만 _backup으로
        write_sample_inputs(R, {n: float(v) for n, v in r["values"].items()}, {"kind": "batch", "id": b["id"], "doe_no": r["doe_no"]},
                            opts, nominals, ver)
        ctx.progress(k / len(todo) * 100.0, f"run 폴더 준비 {k}/{len(todo)}")
    bj, sc = os.path.join(B, "batch.json"), os.path.join(B, "samples.csv")
    ctx.backup([bj, sc])
    names = [str(p["name"]) for p in ps["parameters"]]
    write_json(bj, {
        "batch_id": b["id"], "label": batch_label(b["batch_no"]), "input_kind": b["input_kind"], "engine": "native",
        "engine_version": ver, "param_set": {"id": ps["id"], "label": ps.get("label"),
                                              "features_sha256": sha256_file(os.path.join(S, "native", "extract", "parameter_features.json"))},
        "model": {"id": m["id"], "name": m.get("name"), "version": m.get("version"), "psmdl_sha256": m.get("psmdl_sha256")},
        "source": {"kind": b["source_kind"], "meta": b["source_meta"]}, "multi_execution": b["multi_execution"], "parameters": names,
        "rows": [{"doe_no": r["doe_no"], "run_key": r["run_key"], "values": r["values"], "applied_values": r["applied_values"],
                  "out_of_range": r["out_of_range"], "input_rel": r["input_rel"]} for r in rows]})
    write_text(sc, samples_csv_text(names, [BatchRow(r["doe_no"], r["run_key"], r["values"], r["applied_values"],
                                                     list(r["out_of_range"] or [])) for r in rows]))
    ctx.add_output(bj)
    ctx.add_output(sc)
    ctx.patch_result({"batch_id": b["id"], "batch_no": b["batch_no"], "batch_label": batch_label(b["batch_no"]),
                      "dir_rel": b["dir_rel"], "run_count": len(rows), "gen_todo": len(todo), "engine": "native",
                      "engine_version": ver, "ocp_version": ocp})


def gen_one(ctx: Any, b: dict[str, Any], S: str, B: str) -> Callable[[Any, dict[str, Any]], None]:
    """run 1개 입력 생성(작업 스레드). 실패는 StepFailure(GEOM_* 코드·한국어 문구)로 — run_parallel이 그 run만 실패로 기록."""
    s = ctx.settings
    ver = ctx.result().get("engine_version")
    inp = native_inputs(s, S, os.path.join(S, "radioss_assem"))

    def gen(runner: Any, r: dict[str, Any]) -> None:
        R = os.path.join(B, r["run_key"])
        _set = lambda **kw: ctx.ex.db(lambda c: pb_repo.set_run(c, b["id"], r["doe_no"], **kw))  # noqa: E731
        _set(gen_state="RUNNING", gen_code=None, gen_message=None)
        generate_sample(runner, s, inp, R, engine_version=ver)
        check_child_input(s, os.path.join(R, "m_3"))
        _set(gen_state="DONE", gen_code=None, gen_message=None, engine_version=ver)

    return gen


