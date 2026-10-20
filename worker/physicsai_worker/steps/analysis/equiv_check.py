"""⑤ EQ_CHECK step 1~4(equiv-check.md §4.5): EQ_PREP · EQ_EXTRACT · EQ_COMPUTE · EQ_REPORT.

폴더 `E = <study>/{equiv_check.dir_name}/EQ-NNN/`: recipe.json(스냅숏)·pairs.json·metrics.csv·curves/<pair>/<metric>.json·
extract/<a|b>/<run>/(추출 작업 폴더)·result.json. 원본 run 폴더·SPDM에는 쓰지 않는다(EQ-6) — 추출은 h3d 사본으로 E/extract 안에서만,
T01은 원본을 읽어 출력만 E/extract에. 재시도는 같은 스냅숏으로 처음부터(기존 E 내용은 _backup).
"""

from __future__ import annotations

import json
import os
from typing import Any

from physicsai_core.db.repositories import equiv_check as eq_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.equiv import compute as cmp_mod
from physicsai_core.equiv import pairing as pairing_mod
from physicsai_core.equiv import plan as plan_mod
from physicsai_core.equiv.sides import Side, resolve_side, runs_for_pairing
from physicsai_core.errors import StepFailure
from physicsai_core.features import feature_status
from physicsai_core.fileutil import copy_file, write_json, write_text
from physicsai_core.stage2_curation import curation as cu
from physicsai_core.stage4_predict import responses as resp_mod
from physicsai_core.stage4_predict.xydata import parse_xydata

from ...limiter.base import LimiterError
from ...signals import StepSkipped
from ..response_tcl import extract_requests

FILES = ("recipe.json", "pairs.json", "metrics.csv", "result.json")


# ---- 공용 ------------------------------------------------------------------------------------------------


def row(ctx: Any) -> dict[str, Any]:
    with ctx.ex.engine.connect() as conn:
        r = eq_repo.get_check(conn, ctx.params["eq_id"])
    if r is None or r["study_id"] != ctx.study["id"]:
        raise StepFailure("INPUT_INVALID", "판정 이력 행을 찾을 수 없습니다")
    return r


def eq_dir(ctx: Any, r: dict[str, Any]) -> str:
    return ctx.abs(r["dir_rel"])


def _sides(ctx: Any, r: dict[str, Any]) -> tuple[Side, Side]:
    s = ctx.settings
    with ctx.ex.engine.connect() as conn:
        study = studies_repo.require(conn, r["study_id"])
        a = resolve_side(conn, s, study, ctx.root, r["side_a"].get("request") or r["side_a"])
        b = resolve_side(conn, s, study, ctx.root, r["side_b"].get("request") or r["side_b"])
    for side, tag in ((a, "A"), (b, "B")):
        if side.problems:
            p = side.problems[0]
            raise StepFailure("INPUT_CHANGED", f"{tag} 쪽 결과 집합을 다시 읽을 수 없습니다: {p['message']}")
    return a, b


def _pairs(ctx: Any, r: dict[str, Any], a: Side, b: Side) -> pairing_mod.PairResult:
    s = ctx.settings
    pg = r.get("pairing") or {}
    ra, rb = runs_for_pairing(a), runs_for_pairing(b)
    pr = pairing_mod.match(str(pg.get("mode") or "by_name"), ra, rb, rel_tol=s.equiv_check.param_match_rel_tol,
                           integer_names=list(set(a.integer_names) | set(b.integer_names)), manual=pg.get("manual"),
                           max_pairs=s.equiv_check.max_pairs)
    if pg.get("mode", "by_name") == "by_name" and not pr.pairs and len(ra) == 1 and len(rb) == 1:  # EQ-C1
        pr = pairing_mod.PairResult(pairs=[(ra[0]["name"], rb[0]["name"])])
    if pr.problems:
        raise StepFailure("INPUT_CHANGED", f"쌍을 다시 확정할 수 없습니다: {pr.problems[0]['message']}")
    return pr


def _definition(r: dict[str, Any]) -> dict[str, Any]:
    snap = r["recipe_snapshot"]
    return {k: snap[k] for k in ("schema_version", "metrics", "pair_rule", "verdict_rule") if k in snap}


def _load(path: str) -> Any:
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def _side_from_json(d: dict[str, Any]) -> Side:
    from physicsai_core.equiv.sides import Run

    side = Side(d["kind"], d["ref"], d["label"], responses=d.get("responses") or [], integer_names=d.get("integer_names") or [])
    side.runs = [Run(**{k: v for k, v in x.items() if k in Run.__dataclass_fields__}) for x in d.get("runs") or []]
    return side


# ---- 1 EQ_PREP ---------------------------------------------------------------------------------------------


def eq_prep(ctx: Any) -> None:
    r = row(ctx)
    s = ctx.settings
    E = eq_dir(ctx, r)
    if os.path.isdir(E) and os.listdir(E):  # 재시도: 이전 산출물은 _backup으로(삭제 금지)
        ctx.backup([os.path.join(E, n) for n in os.listdir(E)])
    os.makedirs(os.path.join(E, "extract"), exist_ok=True)
    a, b = _sides(ctx, r)
    pr = _pairs(ctx, r, a, b)
    defn = _definition(r)
    resolved, warnings = plan_mod.resolve(defn, a, b)
    for w in warnings:
        ctx.add_warning(w["code"], w["message"])
    snap = dict(r["recipe_snapshot"])
    snap["resolved"] = resolved
    write_json(os.path.join(E, "recipe.json"), snap)
    write_json(os.path.join(E, "pairs.json"), {"mode": (r.get("pairing") or {}).get("mode"),
                                               "pairs": [{"no": i, "a": x, "b": y} for i, (x, y) in enumerate(pr.pairs, 1)],
                                               "unmatched_a": pr.unmatched_a, "unmatched_b": pr.unmatched_b})
    ex = plan_mod.extraction_plan(defn, resolved, a, b, pr.pairs, extract_root=os.path.join(E, "extract"), max_bytes=s.ui.max_artifact_bytes)
    if ex.copy_bytes > s.equiv_check.max_extract_copy_bytes:
        raise StepFailure("EQ_EXTRACT_TOO_LARGE", f"추출용 h3d 사본 합계 {ex.copy_bytes} B가 상한을 넘습니다 — ①-6 run 응답 추출 또는 "
                                                  "④ 성능 다시 추출을 먼저 실행하면 사본 없이 재사용합니다")
    curve_defs: list[dict[str, str]] = []
    if ex.t01:
        with ctx.ex.engine.connect() as conn:
            fallback = plan_mod.curve_definitions(conn, r["study_id"], b.model_id or a.model_id)
        curve_defs = plan_mod.t01_requests(defn, fallback)
        if not curve_defs:
            ctx.add_warning("EQ_CURVE_DEFS_MISSING", "T01 곡선 추출 요청(레시피 t01 또는 ②-4 곡선 정의)이 없어 해석 곡선 지표는 NA가 됩니다")
    # side 스냅숏(run·파일 위치)을 result에 두어 뒤 step이 DB·파일을 다시 훑지 않게 한다(경로·상태만)
    ctx.patch_result({"eq_id": r["id"], "eq_rel": r["dir_rel"], "n_pairs": len(pr.pairs),
                      "sides": {"a": _side_json(a), "b": _side_json(b)}, "pairs": [list(p) for p in pr.pairs],
                      "extract_plan": {"h3d": ex.h3d, "t01": ex.t01, "copy_bytes": ex.copy_bytes}, "curve_defs": curve_defs})
    ctx.log(f"쌍 {len(pr.pairs)}개(짝 없음 A {len(pr.unmatched_a)} · B {len(pr.unmatched_b)}), 추출 필요 h3d {len(ex.h3d)} · T01 {len(ex.t01)}")


def _side_json(side: Side) -> dict[str, Any]:
    return {"kind": side.kind, "ref": side.ref, "label": side.label, "responses": side.responses, "integer_names": side.integer_names,
            "runs": [r.as_dict() for r in side.runs], "model_id": side.model_id}


# ---- 2 EQ_EXTRACT ------------------------------------------------------------------------------------------


def _extract_available(ctx: Any) -> tuple[bool, bool]:
    """(H3D minmax 가능, T01 곡선 추출 가능)."""
    s = ctx.settings
    st = feature_status(s, False)
    h3d_ok = s.commands.response_extract is not None and bool(s.resources.extract_minmax_tcl) and os.path.isfile(s.resources.extract_minmax_tcl)
    t01_ok = s.commands.t01_curve_export is not None and bool(s.resources.curate_hg_tcl) and os.path.isfile(s.resources.curate_hg_tcl)
    hw = "altair.hw_exe_path" not in (st.get("equiv_check_extract") or {}).get("missing", [])
    return h3d_ok and hw, t01_ok and hw


def eq_extract(ctx: Any) -> None:
    res = ctx.result()
    plan = res.get("extract_plan") or {}
    items_h3d, items_t01 = list(plan.get("h3d") or []), list(plan.get("t01") or [])
    if not items_h3d and not items_t01:
        raise StepSkipped("추출할 값 없음 — 기존 응답·곡선 재사용")
    E = ctx.abs(res["eq_rel"])
    h3d_ok, t01_ok = _extract_available(ctx)
    if (items_h3d and not h3d_ok) or (items_t01 and not t01_ok):
        ctx.add_warning("EQ_EXTRACT_UNAVAILABLE", "추출 도구(hw·응답 TCL·T01 곡선 추출)가 없어 추출이 필요한 지표는 NA가 됩니다")
    done = failed = 0
    total = (len(items_h3d) if h3d_ok else 0) + (1 if items_t01 and t01_ok else 0)
    if h3d_ok:
        for it in items_h3d:
            ctx.checkpoint_cancel()
            d = os.path.join(E, "extract", it["side"], it["run"])
            os.makedirs(d, exist_ok=True)
            dst = os.path.join(d, os.path.basename(it["h3d"]))
            reqs, _skipped = resp_mod.build_requests(it["responses"])
            try:
                copy_file(it["h3d"], dst, checkpoint=ctx.checkpoint)
                extract_requests(ctx, reqs, d, dst)
                done += 1
            except (StepFailure, LimiterError, OSError) as exc:
                failed += 1
                code = getattr(exc, "code", "OSError")
                ctx.add_warning("EQ_EXTRACT_FAILED", f"{it['side'].upper()} {it['run']}: 응답 추출 실패({code}) — 그 값은 NA"[:480])
            ctx.progress((done + failed) / max(1, total) * 100.0, f"응답 추출 {done + failed}/{total}", force=True)
    if items_t01 and t01_ok:
        curves = res.get("curve_defs") or []
        if not curves:
            ctx.add_warning("EQ_EXTRACT_FAILED", "T01 곡선 추출 요청이 없어 해석 곡선을 추출하지 않았습니다")
        else:
            _extract_t01(ctx, E, items_t01, curves)
    ctx.patch_result({"extracted": {"h3d_done": done, "h3d_failed": failed, "t01": len(items_t01) if t01_ok else 0}})


def _extract_t01(ctx: Any, E: str, items: list[dict[str, Any]], curves: list[dict[str, str]]) -> None:
    C = os.path.join(E, "extract")
    targets = [(it["t01"], f"{it['side']}/{it['run']}") for it in items]
    for _t01, sub in targets:
        os.makedirs(os.path.join(C, sub), exist_ok=True)
    data = cu.curve_input_json(curves, targets, C)
    cfg = os.path.join(C, "INPUT_CURATE_CURVE.json")
    write_json(cfg, data)
    try:
        ctx.run_local("t01_curve_export", {"curate_tcl": ctx.settings.resources.curate_hg_tcl, "config_json": cfg}, cwd=C,
                      check_log_errors=False)
    except (StepFailure, LimiterError) as exc:
        ctx.add_warning("EQ_EXTRACT_FAILED", f"T01 곡선 추출 실패({exc.code}): {exc.message}"[:480])
        return
    n_ok = 0
    for job, (_t01, sub) in zip(data["jobs"], targets):
        out = job["outputFile"]
        final = os.path.join(C, sub, plan_mod.CURVE_JSON)
        if not os.path.isfile(out):
            continue
        try:
            d = _load(out)
            ok = isinstance(d, dict) and isinstance(d.get("series"), list)
        except (OSError, ValueError):
            ok = False
        if not ok:  # JSON이 아니면 xydata로 해석
            raw = os.path.join(C, sub, "curve.xy")
            os.replace(out, raw)
            write_json(final, parse_xydata(raw, display_name=os.path.basename(_t01)))
        else:
            os.replace(out, final)
        n_ok += 1
    if n_ok < len(targets):
        ctx.add_warning("EQ_EXTRACT_FAILED", f"T01 곡선 {len(targets) - n_ok}개가 만들어지지 않았습니다 — 그 쌍의 곡선 지표는 NA")


# ---- 3 EQ_COMPUTE ------------------------------------------------------------------------------------------


def eq_compute(ctx: Any) -> None:
    res = ctx.result()
    E = ctx.abs(res["eq_rel"])
    snap = _load(os.path.join(E, "recipe.json"))
    defn = {k: snap[k] for k in ("schema_version", "metrics", "pair_rule", "verdict_rule") if k in snap}
    a, b = _side_from_json(res["sides"]["a"]), _side_from_json(res["sides"]["b"])
    pairs = [(p[0], p[1]) for p in res["pairs"]]
    out = cmp_mod.compute(defn, snap.get("resolved") or {}, a, b, pairs, settings=ctx.settings, extract_root=os.path.join(E, "extract"))
    for w in out.warnings:
        ctx.add_warning(w["code"], w["message"])
    csv_path = os.path.join(E, "metrics.csv")
    write_text(csv_path, cmp_mod.csv_text(out.rows))
    ctx.add_output(csv_path)
    for (no, mid), data in out.curves.items():
        p = os.path.join(E, "curves", str(no), f"{mid}.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        write_json(p, data)
    n_na = sum(1 for r in out.rows if r["status"] == "NA")
    ctx.patch_result({"compute": {"rows": len(out.rows), "na": n_na, "curves": len(out.curves)}})
    ctx.log(f"지표 행 {len(out.rows)}개(NA {n_na}), 곡선 {len(out.curves)}개")


# ---- 4 EQ_REPORT -------------------------------------------------------------------------------------------


def _warnings_count(ctx: Any) -> int:
    from physicsai_core.db.repositories import jobs as jobs_repo

    with ctx.ex.engine.connect() as conn:
        j = jobs_repo.get_job(conn, ctx.ex.job_id) or {}
    return len(j.get("warnings") or [])


def eq_report(ctx: Any) -> None:
    res = ctx.result()
    E = ctx.abs(res["eq_rel"])
    snap = _load(os.path.join(E, "recipe.json"))
    defn = {k: snap[k] for k in ("schema_version", "metrics", "pair_rule", "verdict_rule") if k in snap}
    with open(os.path.join(E, "metrics.csv"), encoding="utf-8-sig") as fh:
        rows = cmp_mod.parse_csv_text(fh.read())
    agg = cmp_mod.aggregate_all(defn, rows)
    for mid, ag in agg["metrics"].items():
        if ag.get("partial"):
            lab = next((m["label"] for m in defn["metrics"] if m["id"] == mid), mid)
            ctx.add_warning("EQ_PARTIAL_PAIRS", f"{lab}: 판정 가능 쌍 중 일부({ag['n_na']}개)가 NA입니다")
    summary = {"metrics": agg["metrics"], "verdict": agg["verdict"], "n_pairs": int(res.get("n_pairs") or 0),
               "n_rows": len(rows), "warnings_count": _warnings_count(ctx)}
    verdict = agg["verdict"]["verdict"]
    result = {"eq_id": res["eq_id"], "verdict": verdict, "summary": summary, "pairs": res.get("pairs"),
              "sides": {k: {"kind": v["kind"], "ref": v["ref"], "label": v["label"]} for k, v in (res.get("sides") or {}).items()}}
    rp = os.path.join(E, "result.json")
    write_json(rp, result)
    ctx.add_output(rp)
    raw = json.dumps(summary, ensure_ascii=False).encode("utf-8")
    if len(raw) > ctx.settings.equiv_check.snapshot_max_bytes:  # V-EQ-9: DB 요약 상한 — 지표 집계만 남긴다
        summary = {"verdict": agg["verdict"], "n_pairs": summary["n_pairs"], "n_rows": len(rows), "truncated": True,
                   "metrics": {k: {"status": v.get("status"), "n_pass": v.get("n_pass"), "n_fail": v.get("n_fail"), "n_na": v.get("n_na")}
                               for k, v in agg["metrics"].items()}}
    ctx.ex.db(lambda c: eq_repo.set_check(c, res["eq_id"], summary=summary, verdict=verdict))
    ctx.patch_result({"verdict": verdict, "summary": summary["verdict"]})
    ctx.log(f"종합 판정 {verdict} — 필수 {agg['verdict']['required_pass']}/{agg['verdict']['required_total']} · 참고 미달 {agg['verdict']['reference_fail']}")


HANDLERS = {
    ("EQ_CHECK", "EQ_PREP"): eq_prep,
    ("EQ_CHECK", "EQ_EXTRACT"): eq_extract,
    ("EQ_CHECK", "EQ_COMPUTE"): eq_compute,
    ("EQ_CHECK", "EQ_REPORT"): eq_report,
}
