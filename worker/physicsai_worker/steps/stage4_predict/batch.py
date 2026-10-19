"""④ 일괄 예측 입력 생성 PREDICT_BATCH(phase3 §14.5 S9): BP_PREP → BP_GEN → BP_ENQUEUE.

배치 폴더 `B = <study>/04_batch/B-003/`: `batch.json`·`samples.csv`·`run__N/{m_1,m_2,m_3}/`(원본 ① hstbatch 배치와 같은 이름).
- BP_PREP: 모델 무결성, 세트 파일 확인, `gen_state≠DONE` run 폴더만 `_backup` 후 다시 — `m_1/`에 CAD 사본 + 렌더 스크립트.
- BP_GEN: `run_parallel`로 최대 M개 동시(모든 프로세스는 제한기 그룹 1개 = Windows Job Object 1개). run마다 순차
  m_1 GEOM_UPDATE → (assembly) m_2 MESH → m_3 조립(RAD_ASSEMBLE ①~④) → 하위 입력 검사(`prepared_input.plan_copy`).
  판정·경고는 단일 예측(§11.4)과 같은 함수. run 실패는 행 상태(gen_state FAILED·code·message)로 남기고 계속.
- BP_ENQUEUE: 성공 run마다 하위 PREDICT(prepared)를 doe_no 순 연속 queue_seq로(`predict_batches.enqueue_children`).
하위·부모 종료 후 배치 갱신(응답 복사·완료 판정·PREDICT_BATCH_DONE 알림)은 종료 훅 `job_end.batch_on_job_end`(모든 종료 경로)가 한다.
작업 params는 `batch_id`만 믿는다 — 나머지(모델·템플릿·동시 수·종류)는 배치 행에서 읽는다.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, sha256_file, write_json, write_text
from physicsai_core.naming import TPL_NAME
from physicsai_core.stage4_predict.batch_matrix import (
    BatchRow,
    batch_label,
    samples_csv_text,
)
from physicsai_core.tpl_render import render_tpl

from ...signals import StepSkipped
from ..common import hst_run_label, load_model, verify_model_integrity
from . import batch_native
from .predict_inputs import (
    LOG_BATCH,
    MESH_ONLY,
    assemble_into,
    judge_output,
    mesh_log_warning,
    mesh_preflight,
)

M1, M2, M3 = "m_1", "m_2", "m_3"


# ---- 공용 ----------------------------------------------------------------------------------------


def _batch(ctx: Any) -> dict[str, Any]:
    bid = ctx.params.get("batch_id")
    with ctx.ex.engine.connect() as conn:
        b = pb_repo.get(conn, bid) if isinstance(bid, str) else None
    if b is None or b["study_id"] != ctx.study["id"]:
        raise StepFailure("INPUT_INVALID", "일괄 예측 배치를 찾을 수 없습니다")
    return b


def _param_set(ctx: Any, b: dict[str, Any]) -> tuple[dict[str, Any], str]:
    with ctx.ex.engine.connect() as conn:
        ps = ps_repo.get(conn, b["param_set_id"])
    if ps is None or ps["study_id"] != ctx.study["id"]:
        raise StepFailure("INPUT_INVALID", "템플릿(파라미터 세트)을 찾을 수 없습니다")
    return ps, ctx.abs(ps["stored_rel"])


def _B(ctx: Any, b: dict[str, Any]) -> str:
    return ctx.abs(b["dir_rel"])


def _set_run(ctx: Any, b: dict[str, Any], doe_no: int, **values: Any) -> None:
    ctx.ex.db(lambda c: pb_repo.set_run(c, b["id"], doe_no, **values))


def _pending(ctx: Any, b: dict[str, Any]) -> list[dict[str, Any]]:
    with ctx.ex.engine.connect() as conn:
        return [r for r in pb_repo.runs(conn, b["id"]) if r["gen_state"] != "DONE"]


# ---- BP_PREP -------------------------------------------------------------------------------------


def bp_prep(ctx: Any) -> None:
    b = _batch(ctx)
    m = load_model(ctx, b["model_id"])
    verify_model_integrity(ctx, m)
    ps, S = _param_set(ctx, b)
    if ps.get("engine") == "native":  # geometry-engine.md §7.3.7
        return batch_native.bp_prep(ctx, b, m, ps, S, _B(ctx, b))
    needs = [TPL_NAME, os.path.join("cad", ps["cad_file_name"])]
    if b["input_kind"] != MESH_ONLY:
        if not ps.get("starter_name"):
            raise StepFailure("INPUT_INVALID", "조립 폴더가 없는 템플릿으로 조립(assembly) 일괄 예측을 할 수 없습니다")
        needs.append(os.path.join("radioss_assem", ps["starter_name"]))
    for need in needs:
        if not os.path.isfile(os.path.join(S, need)):
            raise StepFailure("INPUT_CHANGED", f"템플릿 파일이 없습니다: {need}")
    with open(os.path.join(S, TPL_NAME), encoding="utf-8-sig") as fh:
        tpl_text = fh.read()
    B = _B(ctx, b)
    os.makedirs(B, exist_ok=True)
    ctx.ex.db(lambda c: pb_repo.reset_failed_gen(c, b["id"]))  # 실패·중단 run → PENDING(사유 지움)
    with ctx.ex.engine.connect() as conn:
        rows = pb_repo.runs(conn, b["id"])
    cad_src = os.path.join(S, "cad", ps["cad_file_name"])
    script_name = ctx.settings.predict.rendered_script_name
    todo = [r for r in rows if r["gen_state"] != "DONE"]
    for k, r in enumerate(todo, 1):
        ctx.checkpoint()
        run_dir = os.path.join(B, r["run_key"])
        if os.path.lexists(run_dir):
            ctx.backup([run_dir])  # 재실행: 실패·미완료 run 폴더만 _backup으로(완료 run은 그대로)
        m1 = os.path.join(run_dir, M1)
        os.makedirs(m1, exist_ok=True)
        copy_file(cad_src, os.path.join(m1, ps["cad_file_name"]), checkpoint=ctx.checkpoint)  # tpl dir_file_prt = ./<CAD>
        write_text(os.path.join(m1, script_name), render_tpl(tpl_text, r["values"], r["applied_values"]))
        ctx.progress(k / len(todo) * 100.0, f"run 폴더 준비 {k}/{len(todo)}")
    bj = os.path.join(B, "batch.json")
    sc = os.path.join(B, "samples.csv")
    ctx.backup([bj, sc])
    names = [str(p["name"]) for p in ps["parameters"]]
    write_json(bj, {
        "batch_id": b["id"], "label": batch_label(b["batch_no"]), "input_kind": b["input_kind"],
        "param_set": {"id": ps["id"], "label": ps.get("label"), "tpl_sha256": sha256_file(os.path.join(S, TPL_NAME)),
                      "cad_file_name": ps["cad_file_name"], "cad_sha256": sha256_file(cad_src)},
        "model": {"id": m["id"], "name": m.get("name"), "version": m.get("version"), "psmdl_sha256": m.get("psmdl_sha256")},
        "source": {"kind": b["source_kind"], "meta": b["source_meta"]}, "multi_execution": b["multi_execution"],
        "parameters": names,
        "rows": [{"doe_no": r["doe_no"], "run_key": r["run_key"], "values": r["values"], "applied_values": r["applied_values"],
                  "out_of_range": r["out_of_range"], "input_rel": r["input_rel"]} for r in rows],
    })
    write_text(sc, samples_csv_text(names, [BatchRow(r["doe_no"], r["run_key"], r["values"], r["applied_values"],
                                                     list(r["out_of_range"] or [])) for r in rows]))
    ctx.add_output(bj)
    ctx.add_output(sc)
    ctx.patch_result({"batch_id": b["id"], "batch_no": b["batch_no"], "batch_label": batch_label(b["batch_no"]),
                      "dir_rel": b["dir_rel"], "run_count": len(rows), "gen_todo": len(todo)})


# ---- BP_GEN --------------------------------------------------------------------------------------


def _gen_one(ctx: Any, b: dict[str, Any], ps: dict[str, Any], S: str, B: str) -> Callable[[Any, dict[str, Any]], None]:
    """run 1개 입력 생성(작업 스레드에서 실행). 실패는 StepFailure로 — run_parallel이 그 run만 실패로 기록."""
    s = ctx.settings
    if ps.get("engine") == "native":
        return batch_native.gen_one(ctx, b, S, B)
    pr = s.predict
    assembly = b["input_kind"] != MESH_ONLY
    assem = os.path.join(S, "radioss_assem")

    def gen(runner: Any, r: dict[str, Any]) -> None:
        run_dir = os.path.join(B, r["run_key"])
        m1, m2, m3 = (os.path.join(run_dir, x) for x in (M1, M2, M3))
        _set_run(ctx, b, r["doe_no"], gen_state="RUNNING", gen_code=None, gen_message=None)
        simlab_mesh = os.path.join(m1, pr.simlab_mesh_name)
        v = {"rendered_script": os.path.join(m1, pr.rendered_script_name), "cad_file": os.path.join(m1, ps["cad_file_name"]),
             "work_dir": m1, "include_tcl": s.resources.hypermesh_include_tcl, "simlab_mesh": simlab_mesh,
             "mesh_inc": os.path.join(m2, pr.mesh_include_name), "renum_csv": os.path.join(assem, pr.renum_csv_name)}
        # m_1: SimLab 형상 갱신·메싱(cwd m_1) — 성공 = EPS_mesh_0000.rad(§11.4)
        rc = runner.run("geom_update", v, cwd=m1, outputs_to_backup=[simlab_mesh])
        w = judge_output(rc, simlab_mesh, "형상 갱신", runner.last_line)
        if w:
            runner.warn(*w)
        if not assembly:
            input_path = simlab_mesh  # mesh_only: m_1 메시가 곧 예측 입력(§14.3 input_rel)
        else:
            if s.commands.mesh is not None:  # m_2: HyperMesh include 변환(cwd m_2)
                os.makedirs(m2, exist_ok=True)
                for w in mesh_preflight(s, v["renum_csv"]):
                    runner.warn(*w)
                v2 = {**v, "work_dir": m2}
                log_batch = os.path.join(m2, LOG_BATCH)
                rc = runner.run("mesh", v2, cwd=m2, outputs_to_backup=[v["mesh_inc"], log_batch])
                text = ""
                if os.path.isfile(log_batch):
                    with open(log_batch, encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                w = mesh_log_warning(s, text)
                if w:
                    runner.warn(*w)
                w = judge_output(rc, v["mesh_inc"], "메시 변환", runner.last_line)
                if w:
                    runner.warn(*w)
                new_inc = v["mesh_inc"]
            else:  # MESH null: SimLab이 include를 직접 작성(cwd m_1)
                new_inc = os.path.join(m1, pr.mesh_include_name)
            # m_3: 조립 폴더 사본 + 새 include(RAD_ASSEMBLE ①~④). 재시도로 남은 이전 내용은 _backup(D3-36과 같은 이유)
            if os.path.isdir(m3) and os.listdir(m3):
                with runner.pool.fs_lock:
                    ctx.backup([m3])
            os.makedirs(m3, exist_ok=True)
            _starter, warns = assemble_into(s, assem, new_inc, m3, checkpoint=runner.check)
            for w in warns:
                runner.warn(*w)
            input_path = m3
        batch_native.check_child_input(s, input_path)  # 하위 PREDICT(prepared)가 PR_PREP에서 다시 하는 검사를 먼저
        _set_run(ctx, b, r["doe_no"], gen_state="DONE", gen_code=None, gen_message=None)

    return gen


def _aggregate_warnings(ctx: Any, outcomes: list[Any]) -> None:
    """run별 경고를 코드마다 1건으로(200 run이 같은 경고를 반복하지 않게)."""
    by_code: dict[str, list[tuple[str, str]]] = {}
    for o in outcomes:
        for code, msg in o.warnings:
            by_code.setdefault(code, []).append((o.item_id, msg))
    for code, items in by_code.items():
        keys = sorted({k for k, _ in items})
        ctx.add_warning(code, f"run {len(keys)}개({', '.join(keys[:5])}{' …' if len(keys) > 5 else ''}): {items[0][1]}"[:480])


def bp_gen(ctx: Any) -> None:
    b = _batch(ctx)
    ps, S = _param_set(ctx, b)
    if ps.get("engine") != "native" and ctx.settings.commands.geom_update is None:
        raise StepFailure("TEMPLATE_NOT_CONFIGURED", "형상 갱신 명령 템플릿(geom_update)이 설정되지 않았습니다")
    todo = _pending(ctx, b)
    if not todo:
        raise StepSkipped("생성할 run 없음")
    cap = max(1, int(ctx.settings.train_data.max_multi_execution))
    m = max(1, min(int(b["multi_execution"] or 1), cap))
    B = _B(ctx, b)
    n = len(todo)

    def label(running: int, done: int, failed: int, total: int, mm: int) -> str:
        lbl = "입력 생성 " + hst_run_label(running, max(total - done - failed - running, 0), done + failed, total, mm)
        return lbl + (f" · 실패 {failed}" if failed else "")

    ctx.log(f"입력 생성 {n}개 run, 동시 {m}개(요청 {b['multi_execution']}, 상한 {cap}) — {b['input_kind']}")
    try:
        outcomes = ctx.run_parallel(todo, _gen_one(ctx, b, ps, S, B), item_id=lambda r: r["run_key"], max_parallel=m,
                                    label=label)
    except BaseException:
        # 취소·lease 상실: 진행 중이던 run은 다음 재실행이 다시 만들도록 PENDING으로(쓸 수 있을 때만)
        try:
            ctx.ex.db(lambda c: [pb_repo.set_run(c, b["id"], r["doe_no"], gen_state="PENDING")
                                 for r in pb_repo.runs(c, b["id"], gen_states=["RUNNING"])])
        except Exception:  # noqa: BLE001 - lease 상실 등으로 쓸 수 없으면 다음 BP_PREP이 PENDING으로 되돌린다
            ctx.log("[WARN] 진행 중 run 상태를 되돌리지 못했습니다(다음 재실행 때 정리)")
        raise
    by_key = {r["run_key"]: r for r in todo}
    failed = [o for o in outcomes if not o.ok]
    for o in failed:
        _set_run(ctx, b, by_key[o.item_id]["doe_no"], gen_state="FAILED", gen_code=o.code, gen_message=o.message)
    _aggregate_warnings(ctx, outcomes)
    ctx.patch_result({"gen_done": n - len(failed), "gen_failed": [{"run_key": o.item_id, "code": o.code, "message": o.message}
                                                                    for o in failed][:200],
                      "multi_execution": m})
    if failed and len(failed) == n:
        f0 = failed[0]
        raise StepFailure(f0.code or "EXIT_NONZERO", f"run {n}개 모두 입력 생성 실패: {f0.item_id} — {f0.message}")
    if failed:
        ctx.add_warning("PARTIAL_OUTPUT", f"입력 생성 {n}개 중 {len(failed)}개 실패 — 성공한 run만 예측합니다")


# ---- BP_ENQUEUE ----------------------------------------------------------------------------------


def bp_enqueue(ctx: Any) -> None:
    """성공 run마다 하위 PREDICT(prepared)를 한 트랜잭션에서 doe_no 순으로. 배치 CANCELED면 만들지 않는다(enqueue_children).
    등록할 하위가 없고 모두 끝난 경우의 완료 판정·알림은 부모 성공 종료 훅(job_end.batch_on_job_end)이 한다."""
    b = _batch(ctx)
    B = _B(ctx, b)
    created = ctx.ex.db(lambda c: pb_repo.enqueue_children(c, b["id"], batch_dir=B))
    for j in created:
        ctx.log(f"하위 예측 등록 doe {j['params']['batch_run']['doe_no']}: {j['id']}")
    ctx.patch_result({"child_job_ids": [j["id"] for j in created], "enqueued": len(created)})


HANDLERS: dict[tuple[str, str], Callable[[Any], None]] = {
    ("PREDICT_BATCH", "BP_PREP"): bp_prep,
    ("PREDICT_BATCH", "BP_GEN"): bp_gen,
    ("PREDICT_BATCH", "BP_ENQUEUE"): bp_enqueue,
}
