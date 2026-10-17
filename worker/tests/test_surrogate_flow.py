"""V3-S13-3~8: 내장 최적화 전체 흐름(가짜 도구 + API + 워커) — 탐색 → 반복 작업(SO_COLLECT~SO_NEXT) → 검증 배치 연쇄(job_end)
→ DONE·알림 1건, 취소(반복 작업·배치 부모·하위), 이어서 실행 2경로, Study당 진행 중 1개, 최적화 소유 배치 409, 이슈 #4.

가짜 hw의 RESPONSES 값은 run마다 같으므로(흐름 확인용) `run_metrics.load_run_metrics`를 감싸 목적 값을 그 run의 입력값 함수로 바꾼다
(파일 읽기·지표 문법·LRU는 실제 경로 그대로 — 값만 바꿈). 수렴 품질은 test_surrogate_math(V3-S13-2).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from physicsai_test_support import API, H

pytest.importorskip("numpy")
pytest.importorskip("scipy")

_spec = importlib.util.spec_from_file_location("_s4_predict_conftest", Path(__file__).parent / "stage4_predict" / "conftest.py")
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules[_spec.name] = _mod  # type: ignore[union-attr]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
predict_env = _mod.predict_env  # 일괄 예측 시험과 같은 앱·워커·Study·Final 모델 준비

PW = H("tok-power", write=True)
P = H("tok-power")
TCL_NAME = "H3D_StaticMinMax_to_CSV_FAST.tcl"
RESP = [{"name": "MaxStress", "unit": "MPa",
         "spec": {"source": "H3D", "subcase": 1, "datatype": "Stress", "component": "vonMises", "layer": "", "stat": "MAX"}},
        {"name": "Disp", "unit": "mm", "spec": None}]
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def objective_of(v: dict[str, float]) -> float:
    return 100.0 + 20.0 * (v["THK_1"] - 3.4) ** 2 + 3.0 * (v["N_RIB"] - 5) ** 2


@pytest.fixture()
def so_env(predict_env, tmp_path, monkeypatch):
    from physicsai_core.stage4_predict import run_metrics

    tcl = tmp_path / "res" / TCL_NAME
    tcl.parent.mkdir(parents=True)
    tcl.write_text("# fake\n")
    env = predict_env(commands={"response_extract": ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"]},
                      resources={"extract_minmax_tcl": str(tcl)})
    orig = run_metrics.load_run_metrics

    def load(files: Any, *, max_bytes: int) -> Any:
        m = orig(files, max_bytes=max_bytes)
        if m.resp is None or not files.result_dir:
            return m
        jid = UUID_RE.findall(files.result_dir.replace("\\", "/"))[-1]
        vals = env.sql("select result -> 'values' from jobs where id=:i", i=jid)[0][0]
        return run_metrics.RunMetrics(curve=m.curve, resp={**m.resp, "MaxStress_MAX": objective_of(vals)})

    monkeypatch.setattr(run_metrics, "load_run_metrics", load)
    ps = env.param_set()
    r = env.c.put(f"{API}/param-sets/{ps['id']}/responses", headers=PW, json={"responses": RESP})
    assert r.status_code == 200, r.text
    env.ps = ps  # type: ignore[attr-defined]
    return env


def _body(**kw: Any) -> dict[str, Any]:
    b = {"explore": {"kind": "new", "count": 6, "seed": 1}, "objective": {"metric": "resp:MaxStress_MAX", "sense": "min"},
         "iterations": 2, "candidates": 2, "tol_rel": 1e-6, "seed": 1, "multi_execution": 2}
    b.update(kw)
    return b


def _drain(env: Any, limit: int = 80) -> list[tuple[str, str | None]]:
    """대기열이 빌 때까지 SLOT 작업 실행 → [(job_type, 상태)]."""
    seen = []
    for _ in range(limit):
        q = env.sql("select id, job_type from jobs where state='QUEUED' and lane='SLOT' order by queue_seq limit 1")
        if not q:
            return seen
        st = env.w.run_once_slot()
        seen.append((q[0][1], st))
    raise AssertionError("대기열이 끝나지 않았습니다")


@pytest.mark.parametrize("kind", ["mesh_only", "assembly"])
def test_v3_s13_8_full_loop(so_env, kind):
    env = so_env
    if kind == "mesh_only":
        env.to_mesh_only(env.ps["id"])
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json=_body())
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["free_variables"] == ["THK_1", "N_RIB"] and pv["integer_variables"] == ["N_RIB"]
    assert pv["explore_count"] == 6 and pv["max_total_runs"] == 10 and pv["problems"] == []
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json=_body())
    assert r.status_code == 201, r.text
    opt = r.json()
    assert opt["label"] == "SO-001" and opt["status"] == "EXPLORING" and opt["progress_text"].startswith("탐색 B-001")
    seen = _drain(env)
    types = [t for t, _ in seen]
    assert all(st == "SUCCEEDED" for _, st in seen), seen
    d = env.c.get(f"{API}/surrogate-opts/{opt['id']}", headers=P).json()
    assert d["status"] == "DONE", d["progress_text"]
    assert d["stop_reason"] in ("MAX_ITER", "CONVERGED") and d["progress_text"].startswith("완료 — ")
    n_iter = len(d["iterations"])
    assert [it["kind"] for it in d["iterations"]] == ["EXPLORE", *["VERIFY"] * (n_iter - 1)]
    assert types.count("SURROGATE_OPT") == n_iter and types.count("PREDICT_BATCH") == n_iter
    if d["stop_reason"] == "MAX_ITER":
        assert n_iter == 3 and types.count("PREDICT") == 6 + 2 * 2
    # FIFO: 탐색 부모 → 하위 6 → 반복 1 → 검증 부모 → 하위 2 → 반복 2 …
    assert types[:8] == ["PREDICT_BATCH", *["PREDICT"] * 6, "SURROGATE_OPT"]
    # 반복별 적합 품질·후보(정수 변수 정수, 예측·실제 값)
    for it in d["iterations"][1:]:
        assert it["fit"]["n_train"] >= 6 and it["fit"]["kind"] in ("gp", "rbf") and it["fit"]["pred_vs_verified_mae"] is not None
        assert len(it["candidates"]) == 2 and all(c["values"]["N_RIB"] == int(c["values"]["N_RIB"]) for c in it["candidates"])
        assert all(c["state"] == "SUCCEEDED" and c["verified"] is not None for c in it["candidates"])
    # 최적 설계 = 검증 run 중 목적 최소(실제 예측 체인 값)
    ok = [x for x in d["runs"] if x["state"] == "SUCCEEDED"]
    assert d["best"]["objective"] == min(x["objective"] for x in ok)
    assert d["best"]["objective"] == pytest.approx(objective_of(d["best"]["values"]))
    assert d["best"]["feasible"] is True and d["best"]["job_id"]
    # 검증 배치 params: 표 조합·캡처 끔·surrogate_opt 키
    vb = d["iterations"][1]["batch"]
    pj = env.sql("select params from jobs where job_type='PREDICT_BATCH' and params->>'batch_id'=:b", b=vb["id"])[0][0]
    assert pj["source"]["kind"] == "table" and pj["capture"] == {"enabled": False}
    assert pj["surrogate_opt"] == {"id": opt["id"], "opt_no": 1, "iter_no": 1} and pj["template_kind"] == kind
    ex = env.sql("select params from jobs where job_type='PREDICT_BATCH' and params->'surrogate_opt'->>'iter_no'='0'")[0][0]
    assert ex["source"]["kind"] == "lhs" and ex["source"]["count"] == 6
    # 알림: 배치 완료 없음, 최적화 완료 1건
    assert not env.sql("select 1 from notifications where event='PREDICT_BATCH_DONE'")
    notes = env.sql("select title, body from notifications where event='SURROGATE_OPT_DONE'")
    assert len(notes) == 1 and notes[0][0].startswith("내장 최적화 SO-001 완료 — 최적 MaxStress_MAX ")
    assert f"반복 {n_iter - 1} · 검증 {2 * (n_iter - 1)} run" in notes[0][0]
    # 폴더·파일
    O = env.sroot / "05_opt" / "surrogate" / "SO-001"
    for f in ("opt.json", "convergence.csv", "verified_runs.csv", "summary.json", "iter_00/dataset.csv",
              "iter_01/surrogate.json", "iter_01/loo.csv", "iter_01/candidates.csv"):
        assert (O / f).is_file(), f
    # runs.csv
    r = env.c.get(f"{API}/surrogate-opts/{opt['id']}/runs.csv", headers=P)
    text = r.content.decode("utf-8")
    assert text.startswith("﻿iter,batch,doe_no,run_key,THK_1,N_RIB,objective,predicted,feasible,state\r\n")
    assert len(text.strip().splitlines()) == 1 + len(d["runs"])
    lst = env.c.get(f"{API}/studies/{env.sid}/surrogate-opts", headers=P).json()
    assert lst[0]["label"] == "SO-001" and lst[0]["best_value"] == d["best"]["objective"]


def test_reuse_batch_and_rules(so_env):
    env = so_env
    bid, _pj = env.make_batch(env.ps["id"], "THK_1,N_RIB\n" + "".join(f"{2 + 0.4 * i},{2 + i % 6}\n" for i in range(7)))
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW,
                   json=_body(explore={"kind": "reuse", "batch_id": bid}))
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "NOT_DONE"
    _drain(env)
    # 지표 없음·범위 밖·정수 범위 비어 있음·변수 상한 → problems
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json=_body(
        explore={"kind": "reuse", "batch_id": bid}, objective={"metric": "resp:Nope_MAX"},
        bounds={"THK_1": [1.0, 4.0], "N_RIB": [3.2, 3.8]}, iterations=99, candidates=0,
        constraints=[{"metric": "curve:bad", "op": "<=", "value": 1}]))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "SURROGATE_OPT_INVALID"
    codes = {p["code"] for p in r.json()["detail"]["problems"]}
    assert codes >= {"METRIC_UNKNOWN", "BOUNDS_OUT_OF_RANGE", "BOUNDS_INVALID", "ITERATIONS_RANGE", "CANDIDATES_RANGE",
                     "CONSTRAINT_INVALID"}
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW,
                   json=_body(explore={"kind": "new", "count": 10}, bounds={"THK_1": [3, 3], "N_RIB": [4, 4]}))
    assert {p["code"] for p in r.json()["problems"]} == {"NO_FREE_VARIABLE"}
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json=_body(explore={"kind": "new", "count": 3}))
    assert {p["code"] for p in r.json()["problems"]} == {"EXPLORE_TOO_FEW"}
    # 재사용(고정 변수 없음) → 반복 작업 바로, 커브 지표도 가능
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW,
                   json=_body(explore={"kind": "reuse", "batch_id": bid}, iterations=1, candidates=1))
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["status"] == "FITTING" and o["iterations"][0]["kind"] == "REUSE"
    assert env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json=_body()).json()["detail"]["code"] == \
        "SURROGATE_OPT_ACTIVE"
    # 재사용 배치는 최적화 소유가 아니다 → 배치 취소·실패만 다시 가드 없음(DONE이라 다시 실행할 것 없음 409 JOB_NOT_RETRYABLE)
    assert env.c.post(f"{API}/predict-batches/{bid}/retry-failed", headers=PW).json()["detail"]["code"] == "JOB_NOT_RETRYABLE"
    _drain(env)
    d = env.c.get(f"{API}/surrogate-opts/{o['id']}", headers=P).json()
    assert d["status"] == "DONE" and len(d["iterations"]) == 2 and d["iterations"][0]["best_value"] is not None
    # 다른 템플릿 배치 재사용 거부
    ps2 = env.param_set()
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW,
                   json=_body(param_set_id=ps2["id"], explore={"kind": "reuse", "batch_id": bid}))
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "TEMPLATE_MISMATCH"


def test_cancel_resume_and_owned_batch_guard(so_env, monkeypatch):
    env = so_env
    o = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json=_body()).json()
    bid = o["iterations"][0]["batch"]["id"]
    for path in ("cancel", "retry-failed"):
        r = env.c.post(f"{API}/predict-batches/{bid}/{path}", headers=PW)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "BATCH_OWNED_BY_OPT"
        assert "내장 최적화 SO-001의 배치입니다" in r.json()["detail"]["message"]
    b = env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()
    assert b["can_cancel"] is False and b["can_retry_failed"] is False
    # 사용자 수동 배치와 최적화 배치는 함께 대기할 수 있다(활성 인덱스 제외)
    man = env.submit("PREDICT_BATCH", {"param_set_id": env.ps["id"], "multi_execution": 1,
                                       "source": {"kind": "table", "text": "THK_1,N_RIB\n3,4\n"}})
    assert man["state"] == "QUEUED"
    # 취소 권한: 일반 member 403, 등록자가 아닌 power 403 / 조회는 member 200
    assert env.c.post(f"{API}/surrogate-opts/{o['id']}/cancel", headers=H("tok-general", write=True)).status_code == 403
    r = env.c.post(f"{API}/surrogate-opts/{o['id']}/cancel", headers=H("tok-power2", write=True))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "PERMISSION_DENIED"
    assert env.c.get(f"{API}/surrogate-opts/{o['id']}", headers=H("tok-general")).status_code == 200
    assert env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=H("tok-general", write=True), json=_body()).status_code == 403
    # 탐색 입력 생성 + 하위 2개 실행 후 취소 → 부모·대기 하위 전부 취소, 끝난 run 결과는 남음
    assert env.w.run_once_slot() == "SUCCEEDED"  # 탐색 부모
    assert env.w.run_once_slot() == "SUCCEEDED"  # 하위 1
    r = env.c.post(f"{API}/surrogate-opts/{o['id']}/cancel", headers=PW)
    assert r.status_code == 202, r.text
    d = r.json()
    assert d["status"] == "CANCELED" and d["progress_text"] == "취소됨" and d["can_cancel"] is False
    left = env.sql("select count(*) from jobs where params->'batch_run'->>'batch_id'=:b and state='QUEUED'", b=bid)[0][0]
    assert left == 0
    assert env.c.post(f"{API}/surrogate-opts/{o['id']}/cancel", headers=PW).status_code == 202  # 멱등
    assert not env.sql("select 1 from notifications where event in ('JOB_CANCELED','PREDICT_BATCH_DONE')"
                       " and job_id in (select id from jobs where params ? 'surrogate_opt')")
    assert env.c.post(f"{API}/surrogate-opts/{o['id']}/resume", headers=PW).json()["detail"]["code"] == \
        "SURROGATE_OPT_NOT_RESUMABLE"
    _drain(env)  # 수동 배치
    # 새 opt: 반복 작업 실패(SO_FIT에서 시간 초과) → FAILED → 이어서 실행(반복 작업 재시도) → DONE
    o2 = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json=_body(iterations=1, candidates=1)).json()
    assert o2["label"] == "SO-002"
    monkeypatch.setattr(env.lc.settings.surrogate_opt, "fit_timeout_s", -1)
    seen = _drain(env)
    assert seen[-1] == ("SURROGATE_OPT", "FAILED")
    d = env.c.get(f"{API}/surrogate-opts/{o2['id']}", headers=P).json()
    assert d["status"] == "FAILED" and d["stop_reason"] == "SURROGATE_TIMEOUT" and d["can_resume"] is True
    assert d["progress_text"].startswith("실패 — 대리모델 학습 시간을 넘었습니다")
    monkeypatch.setattr(env.lc.settings.surrogate_opt, "fit_timeout_s", 600)
    r = env.c.post(f"{API}/surrogate-opts/{o2['id']}/resume", headers=PW)
    assert r.status_code == 201, r.text
    assert r.json()["job_id"] and r.json()["batch_retry"] is None
    assert env.c.get(f"{API}/surrogate-opts/{o2['id']}", headers=P).json()["status"] == "FITTING"
    _drain(env)
    assert env.c.get(f"{API}/surrogate-opts/{o2['id']}", headers=P).json()["status"] == "DONE"


def test_batch_parent_failure_then_resume(so_env, monkeypatch):
    env = so_env
    o = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json=_body(iterations=1, candidates=1)).json()
    monkeypatch.setenv("FAKE_TOOL_MODE_SIMLAB", "fail")  # 탐색 입력 생성 전부 실패 → 부모 FAILED
    assert env.w.run_once_slot() == "FAILED"
    d = env.c.get(f"{API}/surrogate-opts/{o['id']}", headers=P).json()
    assert d["status"] == "FAILED" and d["stop_reason"] == "BATCH_FAILED"
    monkeypatch.delenv("FAKE_TOOL_MODE_SIMLAB")
    r = env.c.post(f"{API}/surrogate-opts/{o['id']}/resume", headers=PW)
    assert r.status_code == 201, r.text
    assert r.json()["batch_retry"]["parent_job_id"]
    assert env.c.get(f"{API}/surrogate-opts/{o['id']}", headers=P).json()["status"] == "EXPLORING"
    np_ = env.sql("select params from jobs where id=:i", i=r.json()["batch_retry"]["parent_job_id"])[0][0]
    assert np_["surrogate_opt"]["id"] == o["id"]  # 새 부모도 최적화 소유
    _drain(env)
    assert env.c.get(f"{API}/surrogate-opts/{o['id']}", headers=P).json()["status"] == "DONE"


def test_surrogate_job_type_not_creatable_and_retry_rules(so_env):
    env = so_env
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW,
                   json={"job_type": "SURROGATE_OPT", "params": {"surrogate_opt_id": "x", "opt_no": 1, "round": 1}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS"
    s = env.c.get(f"{API}/status", headers=P).json()
    assert s["features"]["optimize_builtin"] == {"enabled": True, "missing": []}
    assert s["surrogate_opt"]["defaults"] == {"iterations": 3, "candidates": 4, "tol_rel": 0.01, "surrogate": "gp"}


def test_batch_done_hook_never_enqueues_twice(so_env, monkeypatch):
    """Verifier A: 이미 DONE인 탐색 배치의 재시도 하위가 (관리자 이동으로) 반복 작업보다 먼저 끝나도 반복 작업을 또 넣지 않고,
    훅 실패가 하위 종료 트랜잭션을 되돌리지 않는다(하위가 RUNNING에 멈추지 않음)."""
    from physicsai_core.db.repositories import jobs as jobs_repo
    from physicsai_core.db.repositories import predict_batches as pb_repo
    from physicsai_core.db.repositories import surrogate_opts as so_repo

    env = so_env
    o = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json=_body(iterations=1, candidates=1)).json()
    bid = o["iterations"][0]["batch"]["id"]
    assert env.w.run_once_slot() == "SUCCEEDED"  # 탐색 부모
    for i in range(6):
        if i == 5:
            monkeypatch.setenv("FAKE_TOOL_MODE_EDSPY", "fail")
        env.w.run_once_slot()
    monkeypatch.delenv("FAKE_TOOL_MODE_EDSPY")

    def rounds() -> int:
        return env.sql("select count(*) from jobs where job_type='SURROGATE_OPT'")[0][0]

    assert rounds() == 1 and env.c.get(f"{API}/surrogate-opts/{o['id']}", headers=P).json()["status"] == "FITTING"
    failed = env.sql("select predict_job_id from predict_batch_runs where batch_id=:b and doe_no=6", b=bid)[0][0]
    r = env.c.post(f"{API}/jobs/{failed}/retry", headers=PW)
    assert r.status_code == 201, r.text
    child = r.json()["id"]
    with env.engine.begin() as conn:
        jobs_repo.move_in_queue(conn, child, 1)  # 반복 작업보다 먼저
    assert env.w.run_once_slot() == "SUCCEEDED"
    assert env.job(child)["state"] == "SUCCEEDED" and rounds() == 1
    # 훅을 직접 다시 불러도(EXPLORING·현재 반복 작업 진행 중 / 넣기 실패) 예외 없이 건너뛴다
    env.sql("update surrogate_opts set status='EXPLORING' where id=:i", i=o["id"])
    with env.engine.begin() as conn:
        assert so_repo.on_batch_done(conn, pb_repo.get(conn, bid)) is True
    assert rounds() == 1
    env.sql("update surrogate_opts set current_job_id=null where id=:i", i=o["id"])

    def boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(so_repo, "enqueue_round", boom)
    with env.engine.begin() as conn:
        assert so_repo.on_batch_done(conn, pb_repo.get(conn, bid)) is True
    assert rounds() == 1


def _fail_after_so_next(monkeypatch, times: int = 1):
    from physicsai_core.errors import StepFailure
    from physicsai_worker.steps import HANDLERS

    orig = HANDLERS[("SURROGATE_OPT", "SO_NEXT")]
    left = {"n": times}

    def wrapped(ctx):
        orig(ctx)
        if left["n"] > 0 and not ctx.result().get("finished"):
            left["n"] -= 1
            raise StepFailure("INTERNAL_ERROR", "SO_NEXT 커밋 뒤 실패(시험)")

    monkeypatch.setitem(HANDLERS, ("SURROGATE_OPT", "SO_NEXT"), wrapped)


def test_round_fails_after_verify_batch_registered_continues(so_env, monkeypatch):
    """Verifier B: SO_NEXT가 검증 배치를 커밋한 뒤 반복 작업이 실패해도 opt는 VERIFYING 유지 → 배치 완료 훅이 다음 반복 → DONE."""
    env = so_env
    _fail_after_so_next(monkeypatch)
    o = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json=_body(iterations=1, candidates=1)).json()
    seen = _drain(env)
    assert ("SURROGATE_OPT", "FAILED") in seen
    d = env.c.get(f"{API}/surrogate-opts/{o['id']}", headers=P).json()
    assert d["status"] == "DONE" and [it["kind"] for it in d["iterations"]] == ["EXPLORE", "VERIFY"]


def test_resume_after_verify_batch_registered_does_not_rerun_round(so_env, monkeypatch):
    """Verifier B: 예전 동작으로 FAILED(ROUND_FAILED)가 된 opt — 이어서 실행은 반복을 다시 돌리지 않고 VERIFYING 복원
    (검증 배치 완료 훅이 다음 반복 투입), 반복 작업 직접 재시도는 409(검증 배치 중복 등록·UniqueViolation 없음)."""
    env = so_env
    _fail_after_so_next(monkeypatch)
    n = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json=_body(iterations=1, candidates=1)).json()
    for _ in range(10):  # 탐색 부모 + 하위 6 + 반복 1(SO_NEXT 커밋 뒤 실패)
        q = env.sql("select job_type from jobs where state='QUEUED' and lane='SLOT' order by queue_seq limit 1")
        st = env.w.run_once_slot()
        if q[0][0] == "SURROGATE_OPT":
            assert st == "FAILED"
            break
    env.sql("update surrogate_opts set status='FAILED', stop_reason='ROUND_FAILED', finished_at=now() where id=:i", i=n["id"])
    round1 = env.c.get(f"{API}/surrogate-opts/{n['id']}", headers=P).json()["current_job_id"]
    r = env.c.post(f"{API}/jobs/{round1}/retry", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SURROGATE_OPT_NOT_RESUMABLE"
    r = env.c.post(f"{API}/surrogate-opts/{n['id']}/resume", headers=PW)
    assert r.status_code == 201, r.text
    assert r.json()["batch_retry"]["restored_batch_id"]
    assert env.c.get(f"{API}/surrogate-opts/{n['id']}", headers=P).json()["status"] == "VERIFYING"
    _drain(env)
    d = env.c.get(f"{API}/surrogate-opts/{n['id']}", headers=P).json()
    assert d["status"] == "DONE" and len(d["iterations"]) == 2
    assert env.sql("select count(*) from surrogate_opt_iters where opt_id=:i", i=n["id"])[0][0] == 2

