"""①-3 TD_DOE_GEN native — 파라미터 세트 기준 DOE(params.param_set_id, geometry-engine.md §7.3.6·§7.3.8·§11.1).

세트 S의 준비본(tag 포함)을 그대로 쓴다(tag 재실행 없음). 조합은 세트 파라미터 표(형상 + 쉘 두께) 범위의 LHS,
확정 다중 baseline 세트면 baseline별 층화 LHS(`doe_matrix.csv`에 baseline_id 열, N/A 빈 값) + 배정(range는 배정 규칙,
덮는 baseline 없음 = BASELINE_NO_COVER 스킵). run 메타(`m_1/values.json`)에는 baseline_id·원 이름 값·공통 이름 값(N/A null),
샘플 표 추출용 `native_params.xml`에는 학습 입력 열(공통 변수 N/A → 0 + `<이름>__na` 지시 열 + topology면 `baseline__<id>` 원-핫).
기존 ①-1 기반 흐름·FEM 검증·①→④가 쓰는 `01_train/radioss_assem/<doe_id>`·`D/cad`·`D/native`는 base 준비본 사본으로 둔다.
"""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, copy_tree, write_text
from physicsai_core.geometry import baselines as bl
from physicsai_core.geometry import shell as sh
from physicsai_core.geometry.messages import korean_message
from physicsai_core.geometry.native_files import doe_matrix_csv, doe_matrix_csv_multi, read_doe_matrix
from physicsai_core.geometry.prep import is_shell_only
from physicsai_core.geometry.shell_native import read_kind
from physicsai_core.paths import is_link_or_reparse
from physicsai_core.stage4_predict.batch_matrix import lhs_values, run_key_for

from ..common import hst_run_label
from ..geometry_native import effective_opts, set_opts, engine_version, ensure_prep_ready, native_inputs, read_json, write_native_options
from ..geometry_sample import backup_path, generate_sample, write_no_cover, write_sample_inputs
from . import doe_native
from ._shared import _D, _doe
from .doe_platform_gen import run_root



def _set(ctx: Any) -> tuple[dict[str, Any], str]:
    with ctx.ex.engine.connect() as conn:
        ps = ps_repo.get(conn, ctx.params["param_set_id"])
    if ps is None or ps["study_id"] != ctx.study["id"] or ps.get("engine") != "native":
        raise StepFailure("INPUT_INVALID", "native 파라미터 세트를 찾을 수 없습니다")
    return ps, ctx.abs(ps["stored_rel"])


def _map(ctx: Any, S: str) -> dict[str, Any] | None:
    try:
        pm = bl.load(S, ctx.settings.geometry.max_report_bytes)
    except bl.MapError as exc:
        raise StepFailure(exc.code, exc.message) from None
    if pm is not None and pm.get("status") != "confirmed":
        raise StepFailure("PARAM_MAP_UNCONFIRMED", "다중 baseline 매칭표가 확정되지 않았습니다 — 확정 후 다시 만드세요")
    return pm


def _row_meta(r: dict[str, Any]) -> dict[str, Any]:
    return {k: r[k] for k in ("name", "nominal", "min", "max") if k in r} | {"unit": r.get("unit", "")}


def dg_prep(ctx: Any) -> None:
    s, p = ctx.settings, ctx.params
    doe_id = p["doe_id"]
    ps, S = _set(ctx)
    opts = set_opts(s, S, ps.get("geom_options"))
    ver, ocp, shown = engine_version(ctx)
    ctx.log(f"형상 엔진: {shown}")
    ensure_prep_ready(s, S, opts, ver)
    pm = _map(ctx, S)
    for bid in bl.baseline_ids(pm or {}):
        ensure_prep_ready(s, bl.baseline_root(S, pm, bid), opts, ver)  # type: ignore[arg-type]
    D, A = _D(ctx), ctx.abs(f"01_train/radioss_assem/{doe_id}")
    os.makedirs(D, exist_ok=True)
    ctx.backup([x for x in (A, os.path.join(D, "cad"), os.path.join(D, "native"), os.path.join(D, "doe_matrix.csv")) if os.path.lexists(x)])
    assem = os.path.join(S, "radioss_assem")
    for n in sorted(os.listdir(assem)):  # base 조립 폴더 사본(FEM 검증·①→④ 호환, 원본 = 세트 사본)
        src = os.path.join(assem, n)
        if os.path.isfile(src) and not is_link_or_reparse(src):
            copy_file(src, os.path.join(A, n), checkpoint=ctx.checkpoint)
    for sub in ("cad", "native"):
        if os.path.isdir(os.path.join(S, sub)):
            copy_tree(os.path.join(S, sub), os.path.join(D, sub), checkpoint=ctx.checkpoint)
    write_native_options(os.path.join(D, "native"), opts, ver, read_kind(S))
    doe = _doe(ctx)
    num_runs = doe["num_runs_requested"] if doe["num_runs_requested"] is not None else int(p.get("num_runs") or 2)
    seed = int(p.get("seed") if p.get("seed") is not None else 1)
    params = list(ps["parameters"])
    if pm is not None:
        extra = {str(r["name"]): (float(r["min"]), float(r["max"])) for r in sh.prop_rows(params)}
        raw = bl.stratified_lhs(pm, params, num_runs, seed, lhs_values, run_key_for, extra)
        rows = [(no, rk, (b if pm.get("usage") == "topology" else bl.assign_baseline(pm, params, vals)), vals) for no, rk, b, vals in raw]
        names = [str(r["name"]) for r in params]
        write_text(os.path.join(D, "doe_matrix.csv"), doe_matrix_csv_multi(names, rows))
        snap = bl.training_snapshot(pm, params, sh.prop_rows(params))
        nc = sum(1 for r in rows if r[2] is None)
        if nc:
            ctx.add_warning(bl.NO_COVER, f"{nc}개 조합은 덮는 baseline이 없어 스킵됩니다")
        per = {b: sum(1 for r in raw if r[2] == b) for b in bl.baseline_ids(pm)}
        ctx.log("baseline별 샘플 수(층화): " + ", ".join(f"{b} {n}" for b, n in per.items()))
    else:
        names = [str(r["name"]) for r in params]
        vals = lhs_values(names, {str(r["name"]): (float(r["min"]), float(r["max"])) for r in params}, num_runs, seed)
        write_text(os.path.join(D, "doe_matrix.csv"), doe_matrix_csv(names, [(i, run_key_for(i), v) for i, v in enumerate(vals, 1)]))
        snap = [_row_meta(r) for r in params]
    ctx.ex.db(lambda c: train_repo.set_doe(c, doe_id, parameters_snapshot=snap, tpl_sha256=None, engine_version=ver, geom_options=opts))
    ctx.patch_result({"doe_id": doe_id, "num_runs": num_runs, "seed": seed, "engine_version": ver, "ocp_version": ocp,
                      "param_set_id": ps["id"], "multi_baseline": pm is not None})


def hst_gen(ctx: Any) -> None:
    s, r = ctx.settings, ctx.result()
    ps, S = _set(ctx)
    pm = _map(ctx, S)
    D, doe = _D(ctx), _doe(ctx)
    ver = r.get("engine_version")
    opts = doe["geom_options"] or set_opts(s, S, ps.get("geom_options"))
    params = list(ps["parameters"])
    shell_only = is_shell_only(S)
    roots = {b: bl.baseline_root(S, pm, b) for b in bl.baseline_ids(pm)} if pm else {}
    inps = {b: native_inputs(s, root, os.path.join(root, "radioss_assem")) for b, root in roots.items()}
    inp0 = native_inputs(s, S, os.path.join(S, "radioss_assem"), need_cad=not shell_only)
    nominals = {str(x["name"]): float(x["nominal"]) for x in params}
    for f in read_json(inp0.features, s.geometry.max_report_bytes).get("features", []) if os.path.isfile(inp0.features) else []:
        if isinstance(f, dict) and isinstance(f.get("name"), str) and "nominal" in f:
            nominals.setdefault(f["name"], float(f["nominal"]))
    props_json = os.path.join(S, *sh.PROPS_JSON.split("/"))
    with open(os.path.join(D, "doe_matrix.csv"), encoding="utf-8", newline="") as fh:
        rows = read_doe_matrix(fh.read())
    cap = max(1, int(s.train_data.max_multi_execution))
    m = max(1, min(int(doe["multi_execution"] or 1), cap))
    ctx.log(f"[MULTIEXEC] 동시 실행 수 {m}, run {len(rows)}개 — 세트 {ps['id'][:8]}" + (" · 다중 baseline" if pm else ""))
    per = {x["name"]: x for x in params if isinstance(x.get("baselines"), dict)}

    def gen(runner: Any, row: tuple[int, str, str | None, dict[str, float | None]]) -> None:
        doe_no, run_key, bid, vals = row
        R = os.path.join(run_root(ctx), run_key)  # S18 platform_run_root(run_dir_glob과 맞음이 설정 검증됨)
        if os.path.lexists(R):
            backup_path(runner, R)
        geo, shell = sh.split_values(params, {k: v for k, v in vals.items() if v is not None})  # type: ignore[misc]
        if pm is not None:
            if bid is None:
                write_no_cover(R, ver)
                raise StepFailure(bl.NO_COVER, korean_message(bl.NO_COVER, None))
            common = {n: vals.get(n) for n in per}
            orig = bl.original_values(params, bid, geo)
            extra = {"baseline_id": bid, "common_values": common, "shell_values": shell}
            xml = bl.training_values(pm, params, bid, common, shell)
            inp = inps[bid]
        else:
            orig, extra, xml, inp = geo, ({"shell_values": shell} if shell else None), {**geo, **shell}, inp0
        write_sample_inputs(R, orig, {"kind": "doe", "id": doe["id"], "doe_no": doe_no}, opts, nominals, ver, extra, xml_values=xml)
        generate_sample(runner, s, inp, R, engine_version=ver, geometry=bool(orig) and not shell_only, shell=shell,
                        props_json=props_json, props_work=os.path.join(D, "native", "props_apply", run_key), baseline_id=bid)

    def label(running: int, done: int, failed: int, total: int, mm: int) -> str:
        return f"run {done + failed}/{total} 완료 · 스킵 {failed} · " + hst_run_label(running, None, done, total, mm)

    outcomes = ctx.run_parallel(rows, gen, item_id=lambda t: t[1], max_parallel=m, label=label)
    doe_native.finish_outcomes(ctx, outcomes)
