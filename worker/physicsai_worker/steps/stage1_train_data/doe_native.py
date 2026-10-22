"""①-3 TD_DOE_GEN의 native 분기(geometry-engine.md §7.3.3): LHS 조합 → `paicad tag` 1회 → run마다 §7.3.6 샘플 생성.

DG_PREP: 조립 폴더·STEP·①-1 산출 복사, 옵션 사용값, `D/doe_matrix.csv`. HST_GEN_RADIOSS: tag + `run_parallel`.
DG_SCAN의 SKIPPED.json 해석은 `skipped_entry`(doe_gen.dg_scan이 호출).
run 폴더 레이아웃(GE-C13): `run__N/` 직계 = 해석 입력(조립 사본), 보조 산출물 = `run__N/_paicad/`(geometry_sample.FLAT).
이전에 m_1~m_3로 만든 native run 폴더는 DG_SCAN(starter 재귀 탐색)·paramitem(재귀)·TD_SOLVE(DB input_rel)가 그대로 읽는다.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from typing import Any

from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, copy_tree, write_json, write_text
from physicsai_core.geometry.native_files import doe_matrix_csv
from physicsai_core.geometry.options import effective_options
from physicsai_core.geometry.prep import prep_document
from physicsai_core.geometry.shell_native import features_name, kind_of_features_rel
from physicsai_core.geometry.shell_options import effective_shell_options
from physicsai_core.paths import PathError, allowed_roots, check_user_path, is_link_or_reparse
from physicsai_core.stage1_train_data import doe_platform
from physicsai_core.stage1_train_data import train_params as tp
from physicsai_core.stage4_predict.batch_matrix import lhs_values, run_key_for

from ..common import hst_run_label, path_failure
from ..geometry_native import LocalRunner, engine_version, read_json, run_paicad, write_native_options
from ..geometry_sample import FLAT, SKIPPED_JSON, backup_path, generate_sample, native_inputs, write_sample_inputs
from . import doe_native_methods
from ._shared import _D, _doe
from .doe_platform_gen import run_root



def _setup(ctx: Any) -> dict[str, Any]:
    with ctx.ex.engine.connect() as conn:
        s = train_repo.get_setup(conn, ctx.study["id"])
    if s is None or not s.get("features_rel") or not s.get("cad_file_name"):
        raise StepFailure("INPUT_INVALID", "형상 피처가 없습니다(①-1 파라미터 추출을 Native로 먼저)")
    return s


def _A(ctx: Any) -> str:
    return ctx.abs(f"01_train/radioss_assem/{ctx.params['doe_id']}")


def dg_prep(ctx: Any) -> None:
    if ctx.params.get("param_set_id"):  # 세트 기준 DOE(3S·4B, §7.3.8)
        from . import doe_native_set

        return doe_native_set.dg_prep(ctx)
    s, p = ctx.settings, ctx.params
    doe_id = p["doe_id"]
    setup = _setup(ctx)
    kind = kind_of_features_rel(setup.get("features_rel"))  # shell-morph.md §8.2: ①-1 쉘 추출 → 쉘 DOE
    try:
        cp = check_user_path(p["radioss_assem_path"], allowed_roots(s, imports=True))
    except PathError as exc:
        raise path_failure(exc) from None
    pr = s.predict
    D, A = _D(ctx), _A(ctx)
    os.makedirs(D, exist_ok=True)
    copies: list[tuple[str, str]] = []
    asm_id = p.get("asm_match_id")
    if asm_id and kind != "shell":  # 조립 매칭(asm-match.md §6.4): include 트리 전체를 상대 경로 그대로 A로, 기준 메시·RENUM 파일 이름은 보지 않는다
        copies += matched_copies(ctx, p, cp.path, A, D)
    else:
        names_in = sorted(os.listdir(cp.path))
        if kind != "shell" and pr.mesh_include_name.lower() not in [n.lower() for n in names_in]:
            raise StepFailure("INPUT_INVALID", f"조립 폴더에 기준 메시({pr.mesh_include_name})가 없습니다")
        if kind != "shell" and pr.renum_csv_name.lower() not in [n.lower() for n in names_in]:
            raise StepFailure("INPUT_INVALID", f"조립 폴더에 번호 재지정 표({pr.renum_csv_name})가 없습니다 — RENUM_CSV_MISSING")
        for n in names_in:
            src = os.path.join(cp.path, n)
            if (n.lower().endswith((".rad", ".inc")) or n.lower() == pr.renum_csv_name.lower()) and os.path.isfile(src) \
                    and not is_link_or_reparse(src):
                copies.append((src, os.path.join(A, n)))
    cad_src = ctx.abs(f"01_train/cad/{setup['cad_file_name']}")
    if not os.path.isfile(cad_src):
        raise StepFailure("INPUT_CHANGED", "STEP 사본이 없습니다 — ①-1을 다시 실행하세요")
    copies.append((cad_src, os.path.join(D, "cad", setup["cad_file_name"])))
    bm = ctx.abs("01_train/cad/body_map.json")
    if os.path.isfile(bm) and not asm_id:  # 조립 매칭이 있으면 body_map.json은 쓰지 않는다(BODY_MAP_IGNORED, AM-C1)
        copies.append((bm, os.path.join(D, "cad", "body_map.json")))
    elif os.path.isfile(bm):
        ctx.add_warning("BODY_MAP_IGNORED", "조립 매칭이 있어 body_map.json은 쓰지 않습니다")
    ctx.backup([d for _s, d in copies if os.path.lexists(d)] + [os.path.join(D, "native"), os.path.join(D, "doe_matrix.csv")])
    for src, dst in copies:
        copy_file(src, dst, checkpoint=ctx.checkpoint)
    ex_src = os.path.dirname(ctx.abs(setup["features_rel"]))
    copy_tree(ex_src, os.path.join(D, "native", "extract"), checkpoint=ctx.checkpoint)
    vsrc = os.path.join(D, "native", "extract", "view")
    if os.path.isdir(vsrc):  # geometry-view.md §6.9: ①-1 공칭 뷰 X/view → D/native/view(from-train이 세트로 복사)
        os.replace(vsrc, os.path.join(D, "native", "view"))
    ver, ocp, shown = engine_version(ctx)
    ctx.log(f"형상 엔진: {shown}")
    if kind == "shell":
        opts, probs = effective_shell_options(s.geometry.shell_defaults, None)
    else:
        opts, probs = effective_options(s.geometry.defaults, None)
    if probs:
        raise StepFailure("CONFIG_INVALID", "geometry 기본 옵션 값이 범위를 벗어납니다: " + "; ".join(q["key"] for q in probs[:5]))
    write_native_options(os.path.join(D, "native"), opts, ver, kind)
    # ③ LHS 조합(use 파라미터, 표 순서) → doe_matrix.csv. INPUT_HST_RUN.json·런처 없음
    used = tp.used(setup["parameters"])
    doe = _doe(ctx)
    num_runs = doe["num_runs_requested"] if doe["num_runs_requested"] is not None else int(p.get("num_runs") or 2)
    seed = int(p.get("seed") or (doe["options"] or {}).get("seed") or 1)
    names = [q["name"] for q in used]
    feat = read_json(os.path.join(D, "native", "extract", features_name(kind)), s.geometry.max_report_bytes)
    known = {f.get("name") for f in feat.get("features", []) if isinstance(f, dict)}
    if not names or not set(names) <= known:
        raise StepFailure("INPUT_CHANGED", "파라미터 표 이름이 형상 피처와 다릅니다 — ①-1을 다시 실행하세요")
    matrix = reuse_matrix(ctx, p, names)
    record = None
    if matrix is None and (sp := doe_native_methods.method_sampling(p)) is not None:  # DM-C2: lhs 밖 표본 방식 = 공용 생성 경로(doe_platform.build)
        matrix, record = doe_native_methods.single_matrix(ctx, sp, doe_platform.design_inputs_native(setup))
        names = list(matrix[0][2])
    if matrix is None:
        rows = lhs_values(names, {q["name"]: (float(q["min"]), float(q["max"])) for q in used}, num_runs, seed)
        matrix = [(i, run_key_for(i), v) for i, v in enumerate(rows, 1)]
    num_runs = len(matrix)
    write_text(os.path.join(D, "doe_matrix.csv"), doe_matrix_csv(names, matrix))
    snap = [{"name": q["name"], "nominal": q["nominal"], "min": q["min"], "max": q["max"], "format": q.get("format"),
             "unit": q.get("unit", "")} for q in used]
    more = {"sampling": record} if record is not None else {}  # DM-C2: train_does.sampling.meta(lhs·재사용은 기존대로 기록 없음)
    ctx.ex.db(lambda c: train_repo.set_doe(c, doe_id, parameters_snapshot=snap, tpl_sha256=None, engine_version=ver,
                                           geom_options=opts, **more))
    ctx.patch_result({"doe_id": doe_id, "num_runs": num_runs, "seed": seed, "engine_version": ver, "ocp_version": ocp, "kind": kind})


def matched_copies(ctx: Any, p: dict[str, Any], assem_path: str, A: str, D: str) -> list[tuple[str, str]]:
    """조립 매칭 DOE의 복사 목록(§6.4): 확정본 사본(`D/cad/asm_match.json`, sha256 = params.asm_match_sha256) + include 트리 파일(→ A).
    확정본·조립 트리가 매칭 때와 다르면 INPUT_CHANGED(조립 폴더가 요청 뒤 바뀜), 트리 오류는 paicad와 같은 코드(ASM_INCLUDE_*)."""
    from physicsai_core.fileutil import sha256_file
    from physicsai_core.geometry import asm_match as am
    from physicsai_core.geometry.asm_tree import AsmTreeError, build

    src = ctx.abs(f"{am.MATCH_ROOT}/{p['asm_match_id']}/{am.CONFIRMED_JSON}")
    doc = am.read_json(src)
    if doc is None or sha256_file(src) != p.get("asm_match_sha256"):
        raise StepFailure("INPUT_CHANGED", "조립 매칭 확정본이 없거나 요청 이후 바뀌었습니다 — 조립 매칭을 다시 하세요")
    try:
        tree = build(assem_path, ctx.checkpoint)
    except AsmTreeError as exc:
        raise StepFailure(exc.code, exc.message) from None
    if tree.digest != (doc.get("assem") or {}).get("digest"):
        raise StepFailure("INPUT_CHANGED", "조립 폴더가 조립 매칭 이후 바뀌었습니다 — 조립 매칭을 다시 하세요")
    out = [(f.path, os.path.join(A, *f.rel.split("/"))) for f in tree.files]
    out.append((src, os.path.join(D, *am.ASM_MATCH_REL.split("/"))))
    return out


def reuse_matrix(ctx: Any, p: dict[str, Any], names: list[str]) -> list[tuple[int, str, dict[str, float]]] | None:
    """①-3 표본표 재사용(equiv-check.md Q1): params.sampling.kind == train_doe면 원본 DOE samples.csv 행(run 이름 유지), 아니면 None."""
    from physicsai_core.stage1_train_data import doe_reuse

    sp = p.get("sampling")
    if not doe_reuse.is_reuse(sp):
        return None
    with ctx.ex.engine.connect() as conn:
        samples, prob = doe_reuse.load_reuse_samples(conn, ctx.study["id"], ctx.root, str(sp.get("doe_id")))
    if prob is not None:
        raise StepFailure("INPUT_CHANGED", f"표본표를 재사용할 수 없습니다: {prob['message']}")
    mism = doe_reuse.name_mismatch(samples, names)
    if mism is not None:
        raise StepFailure("INPUT_CHANGED", f"표본표를 재사용할 수 없습니다: {mism['message']}")
    rows, skipped = doe_reuse.matrix_rows(samples, names)
    if skipped:
        ctx.add_warning("REUSE_RUN_SKIPPED", f"표본표 run {len(skipped)}개를 건너뜀(run__N 형식 아님·중복·값 없음): {', '.join(skipped[:10])}")
    if not rows:
        raise StepFailure("INPUT_INVALID", "재사용할 표본표 행이 없습니다")
    ctx.log(f"표본표 재사용: DOE {sp.get('doe_id')} run {len(rows)}개(run 이름 유지)")
    return rows


def _matrix(D: str) -> list[tuple[int, str, dict[str, float]]]:
    with open(os.path.join(D, "doe_matrix.csv"), encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        names = [h for h in (rd.fieldnames or []) if h not in ("doe_no", "run_key")]
        return [(int(r["doe_no"]), r["run_key"], {n: float(r[n]) for n in names}) for r in rd]


def hst_gen(ctx: Any) -> None:
    if ctx.params.get("param_set_id"):
        from . import doe_native_set

        return doe_native_set.hst_gen(ctx)
    s = ctx.settings
    r = ctx.result()
    D, A = _D(ctx), _A(ctx)
    doe = _doe(ctx)
    kind = "shell" if r.get("kind") == "shell" else "solid"
    inp = native_inputs(s, D, A, kind=kind)
    ver = r.get("engine_version")
    opts_run = os.path.join(D, "native", "options_run.json")
    T = os.path.join(D, "native", "tag")
    if kind == "shell":  # SM §8.2: tag 자리에서 fixed-scan → tag(조립 폴더 사본 A 기준)
        from ..geometry_shell import fixed_scan_and_tag

        scan, tag = fixed_scan_and_tag(LocalRunner(ctx), s, inp, opts_run, D)
        scan.raise_if_failed()
        tag.raise_if_failed()  # type: ignore[union-attr]
    else:
        v = run_paicad(LocalRunner(ctx), s, "paicad_tag", {**inp.base_values(s), "options_json": opts_run, "out_dir": T}, cwd=T,
                       report=os.path.join(T, "tag.json"), success=[os.path.join(T, "tag_nodes.npz")], backup=[T], body_map=inp.body_map)
        v.raise_if_failed()
    opts = doe["geom_options"] or {}
    now = datetime.now(timezone.utc).isoformat()
    pdoc = prep_document(
        D, step_exts=s.geometry.step_extensions, mesh_include_name=s.predict.mesh_include_name,
        renum_csv_name=s.predict.renum_csv_name, opts=opts, engine_version=ver, ocp_version=r.get("ocp_version"),
        job_id=ctx.ex.job_id, created_at=now, assem_dir=A, kind=kind,
        component=s.shell.default_component if kind == "shell" else None)
    from physicsai_core.geometry.view import view_result

    vr = view_result(os.path.join(D, "native", "view"), ver)
    if vr is not None:
        pdoc["view"] = vr
    write_json(os.path.join(D, "native", "prep.json"), pdoc)
    feats = read_json(inp.features, s.geometry.max_report_bytes)
    nominals = {f["name"]: float(f["nominal"]) for f in feats.get("features", []) if isinstance(f, dict) and "nominal" in f}
    rows = _matrix(D)
    cap = max(1, int(s.train_data.max_multi_execution))
    m = max(1, min(int(doe["multi_execution"] or 1), cap))
    ctx.log(f"[MULTIEXEC] 동시 실행 수 {m}, run {len(rows)}개")

    def gen(runner: Any, row: tuple[int, str, dict[str, float]]) -> None:
        doe_no, run_key, vals = row
        R = os.path.join(run_root(ctx), run_key)  # S18 platform_run_root(run_dir_glob과 맞음이 설정 검증됨)
        if os.path.lexists(R):
            backup_path(runner, R)
        write_sample_inputs(R, vals, {"kind": "doe", "id": doe["id"], "doe_no": doe_no}, opts, nominals, ver, layout=FLAT)
        generate_sample(runner, s, inp, R, engine_version=ver, layout=FLAT)  # run__N 직계 = 해석 입력(GE-C13)

    def label(running: int, done: int, failed: int, total: int, mm: int) -> str:
        return f"run {done + failed}/{total} 완료 · 스킵 {failed} · " + hst_run_label(running, None, done, total, mm)

    outcomes = ctx.run_parallel(rows, gen, item_id=lambda t: t[1], max_parallel=m, label=label)
    finish_outcomes(ctx, outcomes)


def finish_outcomes(ctx: Any, outcomes: list[Any]) -> None:
    """run별 생성 결과 판정(§7.3.3 + phase3 §23.2 G9): 전부 실패 → 첫 실패 코드로 실패.
    일부 실패: on_run_failure `continue`(native 기본) → 경고 PARTIAL_OUTPUT, `fail` → GEN_PARTIAL_FAILED(재시도 = 전체 다시 생성)."""
    failed = [o for o in outcomes if not o.ok]
    ctx.patch_result({"gen_ok": len(outcomes) - len(failed), "gen_skipped": len(failed)})
    if outcomes and len(failed) == len(outcomes):
        f0 = failed[0]
        raise StepFailure(f0.code or "GEOM_INTERNAL", f"run {len(outcomes)}개 모두 생성 실패: {f0.item_id} — {f0.message}")
    if failed and ctx.params.get("on_run_failure") == "fail":
        f0 = failed[0]
        raise StepFailure("GEN_PARTIAL_FAILED", f"run {len(outcomes)}개 중 {len(failed)}개 입력 생성 실패(첫 실패 {f0.item_id}: "
                          f"{f0.message}) — 사유는 run 폴더의 {SKIPPED_JSON}")
    if failed:
        ctx.add_warning("PARTIAL_OUTPUT", f"run {len(outcomes)}개 중 {len(failed)}개를 스킵했습니다(사유는 run 폴더의 {SKIPPED_JSON})")


def skipped_entry(run_dir: str, max_bytes: int) -> dict[str, str] | None:
    """run 폴더의 SKIPPED.json → {reason: code, category, message}. 없거나 읽을 수 없으면 None(기존 starter 규칙으로)."""
    p = os.path.join(run_dir, SKIPPED_JSON)
    if not os.path.isfile(p):
        return None
    try:
        d = read_json(p, max_bytes)
    except StepFailure:
        return None
    code = d.get("code") if isinstance(d.get("code"), str) else "GEOM_INTERNAL"
    return {"reason": code, "category": str(d.get("category") or ""), "message": str(d.get("message") or "")[:500]}
