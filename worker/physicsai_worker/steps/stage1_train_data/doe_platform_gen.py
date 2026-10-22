"""①-3 TD_DOE_GEN 플랫폼 생성(phase3 §23.5 S18, D3-66): DG_PREP·HST_GEN_RADIOSS("입력 생성(run별)")·DG_SCAN의 platform 분기.

- DG_PREP: 조립 사본(기존 ①)·D에 tpl·CAD 사본. 표본은 `doe_platform.build`(S15 build_matrix) → `train_doe_points`(PENDING).
  행이 이미 있으면 유지(재시도), DOE의 tpl sha가 바뀌었으면 전부 PENDING + 경고 TPL_CHANGED_REGEN. `D/doe.json`(이전 파일 _backup).
  HyperStudy 파일(DOE 유형 json·include TCL·런처·INPUT_HST_RUN.json)은 만들지 않는다.
- 입력 생성: run마다 m_1(CAD 사본·렌더 tpl) → `run_chain.build_run_inputs`(m_1 형상 → m_2 include → m_3 조립)를
  `run_parallel`로 최대 M개 동시(Job Object 1개). 실패 run만 FAILED로 남기고 계속, 끝에 on_run_failure(fail | continue)로 판정.
- DG_SCAN: DONE run만 — m_3 직계 starter 1개 확인, samples.csv = DB applied_values(PARSED, 미완료 run이 있으면 PARTIAL).
폴더: `D/{train_data.platform_run_root}/run__NNNNN/{m_1,m_2,m_3}`(DG_SCAN·TD_SOLVE·RI_SCAN이 보는 규칙만, §23.3).
"""

from __future__ import annotations

import fnmatch
import os
from typing import Any

from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, sha256_file, write_json, write_text
from physicsai_core.paths import PathError, allowed_roots, check_user_path, is_link_or_reparse
from physicsai_core.sampling import registry as sampling_registry
from physicsai_core.stage1_train_data import doe_platform, doe_samples
from physicsai_core.stage1_train_data import train_params as tp
from physicsai_core.stage1_train_data import train_tpl
from physicsai_core.stage4_predict import prepared_input
from physicsai_core.tpl_render import parse_declarations, render_tpl

from ...signals import StepSkipped
from .. import run_chain
from ..common import hst_run_label, path_failure
from ._shared import TPL_NAME, _D, _doe

M1, M3 = "m_1", "m_3"  # run_chain.M1·M3과 같음(run 폴더 하위, §23.3)


def is_platform(doe: dict[str, Any]) -> bool:
    return doe.get("generator") == "PLATFORM"


def run_root(ctx: Any, doe_id: str | None = None) -> str:
    """run 폴더 상위 `D/{platform_run_root}`."""
    return os.path.join(_D(ctx, doe_id), *ctx.settings.train_data.platform_run_root.replace("\\", "/").split("/"))


def _setup(ctx: Any) -> dict[str, Any]:
    with ctx.ex.engine.connect() as conn:
        s = train_repo.get_setup(conn, ctx.study["id"])
    if s is None:
        raise StepFailure("INPUT_INVALID", "학습 설정이 없습니다(①-1 파라미터 추출 먼저)")
    return s


def _points(ctx: Any, doe_id: str, states: list[str] | None = None) -> list[dict[str, Any]]:
    with ctx.ex.engine.connect() as conn:
        return train_repo.points(conn, doe_id, states)


def _sampling_source(doe: dict[str, Any]) -> dict[str, Any]:
    sp = doe.get("sampling") or {}
    kind = sp.get("kind") or sampling_registry.kind_of_source(doe["doe_type"])
    return {"kind": kind, **(sp.get("input") or doe.get("options") or {})}


# ---- DG_PREP --------------------------------------------------------------------------------------


def reuse_samples(ctx: Any, source: dict[str, Any]) -> Any:
    """①-3 표본표 재사용(equiv-check.md Q1): source.kind == train_doe면 원본 DOE samples.csv(헤더, 행), 아니면 None."""
    from physicsai_core.stage1_train_data import doe_reuse

    if not doe_reuse.is_reuse(source):
        return None
    with ctx.ex.engine.connect() as conn:
        samples, prob = doe_reuse.load_reuse_samples(conn, ctx.study["id"], ctx.root, str(source.get("doe_id")))
    if prob is not None:
        raise StepFailure("INPUT_CHANGED", f"표본표를 재사용할 수 없습니다: {prob['message']}")
    return samples


def dg_prep(ctx: Any) -> None:
    s = ctx.settings
    p = ctx.params
    doe_id = p["doe_id"]
    setup = _setup(ctx)
    if not setup.get("tpl_rel") or not setup.get("cad_file_name"):
        raise StepFailure("INPUT_INVALID", "tpl이 생성되지 않았습니다")
    try:
        cp = check_user_path(p["radioss_assem_path"], allowed_roots(s, imports=True))
    except PathError as exc:
        raise path_failure(exc) from None
    D = _D(ctx)
    A = ctx.abs(f"01_train/radioss_assem/{doe_id}")
    os.makedirs(D, exist_ok=True)
    # ① 조립 폴더 직계 .rad·.inc(+ RENUM csv) → Study 사본(기존 ①과 같은 규칙 — ①→④ 파라미터 세트·S16이 이어받음)
    copies: list[tuple[str, str]] = []
    renum = s.predict.renum_csv_name.lower()
    for n in sorted(os.listdir(cp.path)):
        src = os.path.join(cp.path, n)
        if (n.lower().endswith((".rad", ".inc")) or n.lower() == renum) and os.path.isfile(src) and not is_link_or_reparse(src):
            copies.append((src, os.path.join(A, n)))
    # ② D에 tpl·CAD(HyperStudy 자원·런처·INPUT_HST_RUN.json은 만들지 않음, §23.5)
    tpl_src = ctx.abs(setup["tpl_rel"])
    if not os.path.isfile(tpl_src) or (setup.get("tpl_sha256") and sha256_file(tpl_src) != setup["tpl_sha256"]):
        raise StepFailure("INPUT_CHANGED", "생성된 tpl 파일이 없거나 바뀌었습니다 — tpl을 다시 생성하세요")
    cad_src = ctx.abs(f"01_train/cad/{setup['cad_file_name']}")
    if not os.path.isfile(cad_src):
        raise StepFailure("INPUT_CHANGED", "CAD 사본이 없습니다 — ①-1을 다시 실행하세요")
    copies += [(tpl_src, os.path.join(D, TPL_NAME)), (cad_src, os.path.join(D, setup["cad_file_name"]))]
    ctx.backup([d for _s, d in copies if os.path.lexists(d)])
    for src, dst in copies:
        copy_file(src, dst, checkpoint=ctx.checkpoint)
    tpl_sha = sha256_file(os.path.join(D, TPL_NAME))
    # ③ 표본(train_doe_points): 없으면 계산, tpl이 바뀌었으면 전부 다시 생성, 그 밖은 유지(재시도)
    doe = _doe(ctx)
    source = _sampling_source(doe)
    pts = _points(ctx, doe_id)
    if not pts:
        ctx.progress(None, "표본 계산", force=True)
        plan = doe_platform.build(source, setup, s, samples=reuse_samples(ctx, source))
        if plan.problems or not plan.rows:
            p0 = (plan.problems or [{"message": "표본이 없습니다"}])[0]
            raise StepFailure("INPUT_INVALID", f"표본을 만들 수 없습니다: {p0['message']}")
        rows = [{"doe_no": r.doe_no, "run_key": r.run_key, "values": r.values, "applied_values": r.applied_values}
                for r in plan.rows]

        def ins(c: Any) -> None:
            train_repo.insert_points(c, doe_id, rows)
            train_repo.set_doe(c, doe_id, sampling=plan.sampling_record(with_meta=True), num_runs_requested=len(rows))

        ctx.ex.db(ins)
        for n in plan.notes:
            ctx.add_warning(n["code"], n["message"])
        doe = _doe(ctx)
        pts = _points(ctx, doe_id)
    elif doe.get("tpl_sha256") and doe["tpl_sha256"] != tpl_sha:
        ctx.ex.db(lambda c: train_repo.reset_points(c, doe_id, train_repo.POINT_STATES))
        ctx.add_warning("TPL_CHANGED_REGEN", "tpl이 바뀌어 모든 run 입력을 다시 생성합니다")
    # ④ D/doe.json(이전 파일 _backup)
    kind = source["kind"]
    sp = doe.get("sampling") or {}
    used = tp.used(setup["parameters"])
    names = [q["name"] for q in used]
    dj = os.path.join(D, "doe.json")
    ctx.backup([dj])
    write_json(dj, {
        "doe_id": doe_id, "generator": "platform",
        "sampling": {"kind": kind, "label": sampling_registry.METHODS[kind][1], "input": sp.get("input") or doe["options"],
                     "meta": sp.get("meta")},
        "parameters": names, "run_root": s.train_data.platform_run_root,
        "rows": [{"doe_no": r["doe_no"], "run_key": r["run_key"], "values": r["values"], "applied_values": r["applied_values"]}
                 for r in pts],
    })
    ctx.add_output(dj)
    # ⑤ 생성 시점 사용 파라미터 스냅샷·tpl sha(기존 ①과 같은 모양)
    snap = [{"name": q["name"], "nominal": q["nominal"], "min": q["min"], "max": q["max"], "format": q["format"],
             "unit": q.get("unit", "")} for q in used]
    ctx.ex.db(lambda c: train_repo.set_doe(c, doe_id, parameters_snapshot=snap, tpl_sha256=tpl_sha))
    ctx.patch_result({"doe_id": doe_id, "num_runs": len(pts), "generator": "platform",
                      "run_root_rel": ctx.rel(run_root(ctx))})


# ---- 입력 생성(run별) -------------------------------------------------------------------------------


def _gen_one(ctx: Any, doe_id: str, cad_name: str, tpl_text: str, D: str, A: str, R: str) -> Any:
    s = ctx.settings
    cad_src = os.path.join(D, cad_name)
    decl = parse_declarations(tpl_text)  # altair-vars.md AV-5: 표본에 없는 선언(전체 tpl의 미사용 행)은 공칭으로 렌더

    def gen(runner: Any, r: dict[str, Any]) -> None:
        ctx.ex.db(lambda c: train_repo.set_point(c, doe_id, r["doe_no"], gen_state="RUNNING", gen_code=None, gen_message=None))
        run_dir = os.path.join(R, r["run_key"])
        if os.path.lexists(run_dir):  # 재생성: 실패·미완료 run 폴더만 _backup으로(완료 run은 그대로)
            with runner.pool.fs_lock:
                ctx.backup([run_dir])
        m1 = os.path.join(run_dir, M1)
        os.makedirs(m1, exist_ok=True)
        copy_file(cad_src, os.path.join(m1, cad_name), checkpoint=runner.check)  # tpl dir_file_prt = ./<CAD>
        write_text(os.path.join(m1, s.predict.rendered_script_name), render_tpl(
            tpl_text, train_tpl.fill_nominal(decl, r["values"]), train_tpl.fill_nominal(decl, r["applied_values"])))
        m3 = run_chain.build_run_inputs(runner, s, run_dir=run_dir, cad_file_name=cad_name, assem_dir=A, assembly=True)
        # TD_SOLVE·SCX가 보는 입력 검사(직계 rad·inc, starter 1개)를 여기서 먼저(실패면 생성 실패로)
        try:
            cpath = prepared_input.check_path(m3, s)
        except PathError as exc:
            raise StepFailure("INPUT_INVALID", f"생성된 입력 폴더를 쓸 수 없습니다: {exc.message}") from None
        plan = prepared_input.plan_copy(cpath.path, s)
        if plan.problems:
            p0 = plan.problems[0]
            raise StepFailure(p0["code"] if p0["code"] == "STARTER_COUNT" else "INPUT_INVALID", p0["message"])
        ctx.ex.db(lambda c: train_repo.set_point(c, doe_id, r["doe_no"], gen_state="DONE", gen_code=None, gen_message=None))

    return gen


def gen_platform(ctx: Any) -> None:
    s = ctx.settings
    doe = _doe(ctx)
    doe_id = doe["id"]
    if s.commands.geom_update is None:
        raise StepFailure("TEMPLATE_NOT_CONFIGURED", "형상 갱신 명령 템플릿(geom_update)이 설정되지 않았습니다")
    D = _D(ctx)
    A = ctx.abs(f"01_train/radioss_assem/{doe_id}")
    if s.commands.mesh is not None:  # include TCL 자원 확인은 한 번만(RENUM csv 경고는 run별 → 코드별 1건으로 모음)
        run_chain.mesh_preflight(s, os.path.join(A, s.predict.renum_csv_name))
    ctx.ex.db(lambda c: train_repo.reset_points(c, doe_id, ("FAILED", "RUNNING")))
    todo = [r for r in _points(ctx, doe_id) if r["gen_state"] != "DONE"]
    if not todo:
        raise StepSkipped("생성할 run 없음 — 모두 생성됨")
    cap = max(1, int(s.train_data.max_multi_execution))
    m = max(1, min(int(doe["multi_execution"] or 1), cap))
    cad_name = _setup(ctx)["cad_file_name"]
    with open(os.path.join(D, TPL_NAME), encoding="utf-8-sig") as fh:
        tpl_text = fh.read()
    R = run_root(ctx)
    os.makedirs(R, exist_ok=True)
    n = len(todo)
    on_fail = ctx.params.get("on_run_failure") or "fail"

    def label(running: int, done: int, failed: int, total: int, mm: int) -> str:
        lbl = "입력 생성 " + hst_run_label(running, max(total - done - failed - running, 0), done + failed, total, mm)
        return lbl + (f" · 실패 {failed}" if failed else "")

    ctx.log(f"입력 생성 {n}개 run, 동시 {m}개(요청 {doe['multi_execution']}, 상한 {cap}), 실패 처리 {on_fail}")
    try:
        outcomes = ctx.run_parallel(todo, _gen_one(ctx, doe_id, cad_name, tpl_text, D, A, R), item_id=lambda r: r["run_key"],
                                    max_parallel=m, label=label)
    except BaseException:
        # 취소·lease 상실: 진행 중이던 run은 다음 재실행이 다시 만들도록 PENDING으로(쓸 수 있을 때만 — 못 쓰면 종료 훅)
        try:
            ctx.ex.db(lambda c: train_repo.reset_running_points(c, doe_id))
        except Exception:  # noqa: BLE001 - lease 상실 등으로 쓸 수 없으면 종료 훅(job_end)·다음 재실행이 정리
            ctx.log("[WARN] 진행 중 run 상태를 되돌리지 못했습니다(종료 훅·다음 재실행 때 정리)")
        raise
    by_key = {r["run_key"]: r for r in todo}
    failed = [o for o in outcomes if not o.ok]
    for o in failed:
        ctx.ex.db(lambda c, o=o: train_repo.set_point(c, doe_id, by_key[o.item_id]["doe_no"], gen_state="FAILED",
                                                      gen_code=(o.code or "")[:64] or None,
                                                      gen_message=(o.message or "")[:480] or None))
    run_chain.aggregate_warnings(ctx, outcomes)
    ctx.patch_result({"gen_done": n - len(failed),
                      "gen_failed": [{"run_key": o.item_id, "code": o.code, "message": o.message} for o in failed][:200],
                      "multi_execution": m})
    if failed and len(failed) == n:
        f0 = failed[0]
        raise StepFailure(f0.code or "EXIT_NONZERO", f"run {n}개 모두 입력 생성 실패: {f0.item_id} — {f0.message}")
    if failed and on_fail == "fail":
        f0 = failed[0]
        raise StepFailure("GEN_PARTIAL_FAILED", f"run {n}개 중 {len(failed)}개 입력 생성 실패(첫 실패 {f0.item_id}: {f0.message})"
                                                " — 재시도하면 실패한 run만 다시 만듭니다")
    if failed:
        ctx.add_warning("PARTIAL_OUTPUT", f"입력 생성 {n}개 중 {len(failed)}개 실패 — 성공한 run만 DOE에 등록합니다")


# ---- DG_SCAN --------------------------------------------------------------------------------------


def _starters(m3: str, starter_glob: str) -> list[str]:
    """m_3 직계 starter(eps_mesh 제외) — TD_SOLVE·SCX는 input_dir 직계만 본다(§23.3)."""
    if not os.path.isdir(m3):
        return []
    return [f for f in sorted(os.listdir(m3)) if os.path.isfile(os.path.join(m3, f)) and fnmatch.fnmatch(f, starter_glob)
            and not f.lower().startswith("eps_mesh")]


def dg_scan(ctx: Any) -> None:
    s = ctx.settings
    doe_id = ctx.params["doe_id"]
    D = _D(ctx)
    R = run_root(ctx)
    pts = _points(ctx, doe_id)
    done = sorted((r for r in pts if r["gen_state"] == "DONE"), key=lambda r: r["run_key"])
    runs: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for r in done:
        m3 = os.path.join(R, r["run_key"], M3)
        st = _starters(m3, s.predict.starter_glob)
        if len(st) != 1:
            skipped.append({"run_key": r["run_key"], "reason": f"starter({s.predict.starter_glob})가 {len(st)}개"})
            continue
        runs.append({"run_key": r["run_key"], "input_rel": ctx.rel(m3), "starter_name": st[0],
                     "applied": r["applied_values"]})
    for sk in skipped:
        ctx.add_warning("RUN_INPUT_INVALID", f"{sk['run_key']}: {sk['reason']}")
    if not runs:
        raise StepFailure("OUTPUT_MISSING", "입력이 생성된 run 폴더가 없습니다")
    doe = _doe(ctx)
    names = [q["name"] for q in doe["parameters_snapshot"]]
    status = "PARSED" if len(runs) == len(pts) else "PARTIAL"
    sp = os.path.join(D, "samples.csv")
    ctx.backup([sp])
    doe_samples.write_samples_csv(sp, names, [{"run_key": r["run_key"], "values": r["applied"]} for r in runs])
    ctx.register_artifact("DOE_SAMPLES", sp, "text/csv")
    samples_rel = ctx.rel(sp)
    rj = os.path.join(D, "runs.json")
    ctx.backup([rj])
    write_json(rj, [{k: r[k] for k in ("run_key", "input_rel", "starter_name")} for r in runs])

    def reg(c: Any) -> None:
        train_repo.insert_runs(c, doe_id, runs)
        train_repo.set_doe(c, doe_id, run_count=len(runs), sample_status=status, samples_rel=samples_rel, status="READY")

    ctx.ex.db(reg)
    ctx.log(f"run {len(runs)}개, 샘플 {status}")
    ctx.patch_result({"doe_id": doe_id, "run_count": len(runs), "sample_status": status, "skipped_runs": skipped})
