"""④ PREDICT_BATCH(B)의 native 분기(geometry-engine.md §7.3.7): BP_PREP·BP_GEN.

run마다 `R = B/run__N`에 §7.3.6 샘플 생성(m_1 values.json·native_params.xml, paicad, m_3 조립). tpl·CAD 사본·렌더 스크립트 없음.
단계 3S(§11.1): 쉘 두께 값은 values.json에서 빼고 m_3에 props apply(작업 폴더 `B/props_apply/<run>`), 형상 값이 없으면 형상 단계 생략.
단계 4B(§7.3.8): 확정 다중 baseline 세트는 배치 source_meta.multi_baseline의 배정 baseline 준비본으로 만들고 values.json 키는 그
baseline 원 이름(공통 이름 값·baseline_id는 메타로). 배정 없음 → SKIPPED.json BASELINE_NO_COVER(그 run만 생성 실패).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import sha256_file, write_json, write_text
from physicsai_core.stage4_predict.batch_matrix import BatchRow, batch_label, samples_csv_text

from physicsai_core.geometry import baselines as bl
from physicsai_core.geometry import native_vars as nv
from physicsai_core.geometry import shell as sh
from physicsai_core.geometry.messages import korean_message
from physicsai_core.geometry.prep import is_shell_only

from .. import geometry_cushion as cushion
from ..geometry_native import effective_opts, set_opts, engine_version, ensure_prep_ready, native_inputs, read_json
from ..geometry_sample import backup_path, generate_sample, write_cushion_rad, write_no_cover, write_sample_inputs
from .child_input import check_child_input
from .predict_inputs import MESH_ONLY, input_of

M1 = "m_1"


def _features(settings: Any, S: str) -> dict[str, Any]:
    p = bl.features_path(S)
    return read_json(p, settings.geometry.max_report_bytes) if os.path.isfile(p) else {"features": []}


def multi_of(ctx: Any, b: dict[str, Any], S: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """(확정 매칭표 | None, 배치 source_meta.multi_baseline). 배치를 다중으로 만들었는데 매칭표가 확정이 아니면 INPUT_CHANGED."""
    meta = (b.get("source_meta") or {}).get("multi_baseline") or {}
    if not meta:
        return None, {}
    try:
        pm = bl.load(S, ctx.settings.geometry.max_report_bytes)
    except bl.MapError as exc:
        raise StepFailure(exc.code, exc.message) from None
    if pm is None or pm.get("status") != "confirmed":
        raise StepFailure("INPUT_CHANGED", "배치를 만든 뒤 다중 baseline 매칭표가 바뀌었습니다(미확정) — 확정 후 다시 만드세요")
    return pm, meta


def run_plan(ps: dict[str, Any], pm: dict[str, Any] | None, meta: dict[str, Any], r: dict[str, Any]
             ) -> tuple[str | None, dict[str, float], dict[str, float], dict[str, Any] | None, bool]:
    """run 1개 → (baseline_id|None, paicad 형상 값, 쉘 두께 값, values.json 추가 메타, 배정 실패 여부)."""
    values = {n: float(v) for n, v in r["values"].items()}
    geo, shell = sh.split_values(ps["parameters"], values)
    if pm is None:
        return None, geo, shell, ({"shell_values": shell} if shell else None), False
    bid = (meta.get("assign") or {}).get(str(r["doe_no"]))
    if bid is None:
        return None, {}, shell, None, True
    per = {x["name"]: x for x in ps["parameters"] if isinstance(x.get("baselines"), dict)}
    common = {n: (v if per.get(n, {}).get("baselines", {}).get(bid) is not None else None) for n, v in geo.items()}
    orig = bl.original_values(ps["parameters"], bid, geo)
    return bid, orig, shell, {"baseline_id": bid, "common_values": common, "shell_values": shell}, False


def bp_prep(ctx: Any, b: dict[str, Any], m: dict[str, Any], ps: dict[str, Any], S: str, B: str) -> None:
    s = ctx.settings
    if not ps.get("starter_name") or not os.path.isfile(os.path.join(S, "radioss_assem", ps["starter_name"])):
        raise StepFailure("INPUT_CHANGED", f"템플릿 파일이 없습니다: radioss_assem/{ps.get('starter_name')}")
    opts = set_opts(s, S, ps.get("geom_options"))
    ver, ocp, shown = engine_version(ctx)
    ctx.log(f"형상 엔진: {shown}")
    ensure_prep_ready(s, S, opts, ver)
    pm, meta = multi_of(ctx, b, S)
    for bid in bl.baseline_ids(pm or {}):
        ensure_prep_ready(s, bl.baseline_root(S, pm, bid), opts, ver)  # type: ignore[arg-type]
    if b["input_kind"] == MESH_ONLY:  # 쿠션 입력(input-kind.md §4.2): 명령 설정·쿠션 가능 세트 확인(쉘·쉘 두께는 불가)
        cushion.require_command(s)
        cushion.require_cushion_capable(native_inputs(s, S, os.path.join(S, "radioss_assem"), need_cad=False), None, is_shell_only(S))
    os.makedirs(B, exist_ok=True)
    ctx.ex.db(lambda c: pb_repo.reset_failed_gen(c, b["id"]))
    with ctx.ex.engine.connect() as conn:
        rows = pb_repo.runs(conn, b["id"])
    nominals = {f["name"]: float(f["nominal"]) for f in _features(s, S).get("features", [])
                if isinstance(f, dict) and isinstance(f.get("name"), str) and "nominal" in f}
    nominals.update({str(x["name"]): float(x["nominal"]) for x in ps["parameters"]})
    todo = [r for r in rows if r["gen_state"] != "DONE"]
    for k, r in enumerate(todo, 1):
        ctx.checkpoint()
        R = os.path.join(B, r["run_key"])
        if os.path.lexists(R):
            ctx.backup([R])  # 재실행: 실패·미완료 run 폴더만 _backup으로
        _bid, geo, _shell, extra, no_cover = run_plan(ps, pm, meta, r)
        if b["input_kind"] == MESH_ONLY and _shell:  # 쉘 두께 값이 있는 조합은 쿠션 입력 불가(IK-3) — 생성 전에 막는다
            cushion.require_cushion_capable(native_inputs(s, S, os.path.join(S, "radioss_assem"), need_cad=False), _shell)
        if not no_cover:  # 배정 실패 run은 BP_GEN이 SKIPPED.json(BASELINE_NO_COVER)만 쓴다
            write_sample_inputs(R, geo, {"kind": "batch", "id": b["id"], "doe_no": r["doe_no"]}, opts, nominals, ver, extra,
                                xml_values={n: float(v) for n, v in r["values"].items()})
        ctx.progress(k / len(todo) * 100.0, f"run 폴더 준비 {k}/{len(todo)}")
    bj, sc = os.path.join(B, "batch.json"), os.path.join(B, "samples.csv")
    ctx.backup([bj, sc])
    names = [str(p["name"]) for p in ps["parameters"]]
    write_json(bj, {
        "batch_id": b["id"], "label": batch_label(b["batch_no"]), "input_kind": b["input_kind"], "input": input_of(b["input_kind"]), "engine": "native",
        "engine_version": ver, "param_set": {"id": ps["id"], "label": ps.get("label"),
                                              "features_sha256": sha256_file(bl.features_path(S))},
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
    with ctx.ex.engine.connect() as conn:
        from physicsai_core.db.repositories import param_sets as ps_repo

        ps = ps_repo.get(conn, b["param_set_id"])
    ps = nv.apply(ps, nv.vars_of(b.get("source_meta")))  # native-vars.md §4.2: 스냅숏 우선
    pm, meta = multi_of(ctx, b, S)
    shell_only = is_shell_only(S)
    roots = {bid: bl.baseline_root(S, pm, bid) for bid in bl.baseline_ids(pm)} if pm else {}
    inps = {bid: native_inputs(s, root, os.path.join(root, "radioss_assem")) for bid, root in roots.items()}
    inp0 = native_inputs(s, S, os.path.join(S, "radioss_assem"), need_cad=not shell_only)
    props_json = os.path.join(S, *sh.PROPS_JSON.split("/"))
    is_cushion = b["input_kind"] == MESH_ONLY  # 쿠션 입력: m_3 조립 없음 → m_1/{simlab_mesh_name}이 하위 예측 입력

    def gen(runner: Any, r: dict[str, Any]) -> None:
        R = os.path.join(B, r["run_key"])
        _set = lambda **kw: ctx.ex.db(lambda c: pb_repo.set_run(c, b["id"], r["doe_no"], **kw))  # noqa: E731
        _set(gen_state="RUNNING", gen_code=None, gen_message=None)
        bid, geo, shell, _extra, no_cover = run_plan(ps, pm, meta, r)  # type: ignore[arg-type]
        if no_cover:
            if os.path.lexists(R):
                backup_path(runner, R)
            write_no_cover(R, ver)
            raise StepFailure(bl.NO_COVER, korean_message(bl.NO_COVER, None))
        gin = inps[bid] if bid else inp0
        if is_cushion:
            cushion.require_cushion_capable(gin, shell, shell_only)
        generate_sample(runner, s, gin, R, engine_version=ver, geometry=bool(geo) and not shell_only,
                        shell=shell, props_json=props_json, props_work=os.path.join(B, sh.APPLY_DIR + "_apply", r["run_key"]),
                        baseline_id=bid, assemble=not is_cushion)
        if is_cushion:
            input_path = write_cushion_rad(runner, s, gin, R, engine_version=ver, geometry=bool(geo) and not shell_only,
                                           baseline_id=bid)
        else:
            input_path = os.path.join(R, "m_3")
        check_child_input(s, input_path)
        _set(gen_state="DONE", gen_code=None, gen_message=None, engine_version=ver)

    return gen


