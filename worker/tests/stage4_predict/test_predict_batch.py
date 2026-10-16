"""④ 일괄 예측 입력 생성 PREDICT_BATCH(phase3 §14.5, V3-S9-7·8·9(워커)): BP_PREP·BP_GEN(run_parallel)·BP_ENQUEUE.

배치·부모 작업은 저장소 함수로 만든다(API 생성 경로는 Impl-Backend) — 같은 batch_matrix·create_batch를 쓴다.
"""

from __future__ import annotations

import csv
import json
import os
import threading
import time
from pathlib import Path

import psutil
from physicsai_test_support import API, MESH_INC, H, read_record

PW = H("tok-power", write=True)
ROWS3 = "THK_1\tN_RIB\n2.5\t3\n3.0\t4\n3.5\t5\n"
ROWS4 = ROWS3 + "4.0\t6\n"


def _trace(tmp_path, monkeypatch) -> Path:
    t = tmp_path / "trace.jsonl"
    monkeypatch.setenv("FAKE_TOOL_TRACE", str(t))
    return t


def _events(trace: Path) -> list[dict]:
    return [json.loads(x) for x in trace.read_text().splitlines() if x.strip()] if trace.exists() else []


def _peak_concurrency(trace: Path) -> int:
    """가짜 도구가 남긴 시작·끝 시각으로 관측 동시 실행 수(프로세스 수 최대)를 센다."""
    ev = sorted(((e["t"], 1 if e["ev"] == "start" else -1) for e in _events(trace) if e["ev"] in ("start", "end")),
                key=lambda x: (x[0], x[1]))
    cur = peak = 0
    for _t, d in ev:
        cur += d
        peak = max(peak, cur)
    return peak


def _B(env, bid) -> Path:
    return env.sroot / env.batch(bid)["dir_rel"]


def _children(env, bid) -> list[dict]:
    rows = env.sql("select j.id, j.queue_seq, j.state, j.params, r.doe_no from predict_batch_runs r join jobs j "
                   "on j.id = r.predict_job_id where r.batch_id=:b order by r.doe_no", b=bid)
    return [dict(r._mapping) for r in rows]


def test_v3_s9_7_assembly_parallel_folders_and_enqueue(predict_env, fake_record, tmp_path, monkeypatch):
    trace = _trace(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_SIMLAB_SLEEP_S", "0.6")
    env = predict_env()
    ps = env.param_set()
    bid, pj = env.make_batch(ps["id"], ROWS4, multi=2)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(pj)
    # 동시 실행 수 ≤ M 이고 M=2에서 실제로 2개가 겹침(SimLab·HyperMesh 프로세스 기준)
    assert _peak_concurrency(trace) == 2
    st = env.steps(pj)["BP_GEN"]
    assert st["state"] == "SUCCEEDED" and "입력 생성" in (st["progress_label"] or "") and "(동시 2)" in st["progress_label"]
    B = _B(env, bid)
    assert B == env.sroot / "04_batch" / "B-001"
    for n in range(1, 5):
        R = B / f"run__{n:05d}"
        assert sorted(os.listdir(R)) == ["m_1", "m_2", "m_3"]
        assert (R / "m_1" / "EPS_mesh_0000.rad").is_file() and (R / "m_1" / "bracket.x_t").is_file()
        assert (R / "m_2" / MESH_INC).is_file() and "COMPLETE HM BATCHRUN" in (R / "m_2" / "log_batch.txt").read_text()
        assert sorted(os.listdir(R / "m_3")) == sorted([MESH_INC, "material.inc", "model0_0000.rad", "model_0001.rad"])
        assert (R / "m_3" / MESH_INC).read_bytes() == (R / "m_2" / MESH_INC).read_bytes()
    # 렌더 스크립트는 run 반영값(정수 형식 N_RIB)
    assert '"   5"' in (B / "run__00003" / "m_1" / "simlab_parametered_mesh.py").read_text() or \
        "5" in (B / "run__00003" / "m_1" / "simlab_parametered_mesh.py").read_text()
    rows = list(csv.reader((B / "samples.csv").open()))
    assert rows[0] == ["doe_no", "run_key", "THK_1", "N_RIB"] and rows[1][:2] == ["1", "run__00001"] and len(rows) == 5
    bj = json.loads((B / "batch.json").read_text())
    assert bj["label"] == "B-001" and bj["input_kind"] == "assembly" and len(bj["rows"]) == 4
    # HyperMesh 골든 argv·cwd(m_2)
    hm = [r for r in read_record(fake_record) if r["tool"] == "hw" and "hwfepre.dat" in r["argv"]]
    one = next(r for r in hm if "run__00001" in r["cwd"])
    S = env.sroot / "04_params" / ps["id"]
    assert one["argv"][1:] == ["-clientconfig", "hwfepre.dat", "-b", "-tcl", env.lc.settings.resources.hypermesh_include_tcl,
                               str(B / "run__00001" / "m_1" / "EPS_mesh_0000.rad"), str(B / "run__00001" / "m_2" / MESH_INC),
                               str(S / "radioss_assem" / "RENUM_INIT.csv")]
    assert one["cwd"] == str(B / "run__00001" / "m_2")
    sim = next(r for r in read_record(fake_record) if r["tool"] == "simlab" and "run__00002" in r["cwd"])
    assert sim["argv"][1:] == ["-auto", str(B / "run__00002" / "m_1" / "simlab_parametered_mesh.py"), "-nographics"]
    # BP_ENQUEUE(V3-S9-9 워커): doe_no 순 연속 queue_seq, prepared 하위, 입력 = run m_3
    b = env.batch(bid)
    assert b["status"] == "PREDICTING" and [r["gen_state"] for r in b["runs"]] == ["DONE"] * 4
    ch = _children(env, bid)
    seqs = [c["queue_seq"] for c in ch]
    assert [c["doe_no"] for c in ch] == [1, 2, 3, 4] and seqs == list(range(seqs[0], seqs[0] + 4))
    for c in ch:
        p = c["params"]
        assert c["state"] == "QUEUED" and p["input_mode"] == "prepared" and p["batch_run"] == {"batch_id": bid, "doe_no": c["doe_no"]}
        assert p["input_path"] == str(B / f"run__{c['doe_no']:05d}" / "m_3") and p["param_set_id"] == ps["id"]
    jd = env.job(pj)
    assert jd["result"]["enqueued"] == 4 and jd["warnings"] == []
    # 하위 1개 실행: run 행의 입력값이 결과에, INPUT = m_3 복사
    assert env.w.run_once_slot() == "SUCCEEDED"
    cj = env.job(ch[0]["id"])
    assert cj["result"]["values"] == b["runs"][0]["values"] and cj["result"]["applied_values"] == b["runs"][0]["applied_values"]
    assert cj["result"]["starter"] == "model0_0000.rad" and cj["result"]["nearest"] is None


def test_v3_s9_7_mesh_only_m1_only(predict_env, tmp_path, monkeypatch):
    trace = _trace(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_SIMLAB_SLEEP_S", "0.5")
    env = predict_env()
    ps = env.param_set()
    env.to_mesh_only(ps["id"])
    bid, pj = env.make_batch(ps["id"], ROWS3, multi=3)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(pj)
    assert _peak_concurrency(trace) == 3
    B = _B(env, bid)
    for n in range(1, 4):
        assert os.listdir(B / f"run__{n:05d}") == ["m_1"]
    ch = _children(env, bid)
    assert [c["params"]["input_path"] for c in ch] == [str(B / f"run__{n:05d}" / "m_1" / "EPS_mesh_0000.rad") for n in (1, 2, 3)]
    assert env.w.run_once_slot() == "SUCCEEDED"
    cj = env.job(ch[0]["id"])
    assert cj["result"]["starter"] == "EPS_mesh_0000.rad"


def test_v3_s9_7_multi_capped_by_max_multi_execution(predict_env, tmp_path, monkeypatch):
    trace = _trace(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_SIMLAB_SLEEP_S", "0.3")
    env = predict_env(train_data={"max_multi_execution": 1})
    ps = env.param_set()
    env.to_mesh_only(ps["id"])
    bid, pj = env.make_batch(ps["id"], ROWS3, multi=3)
    assert env.w.run_once_slot() == "SUCCEEDED"
    assert _peak_concurrency(trace) == 1 and env.job(pj)["result"]["multi_execution"] == 1


def test_v3_s9_7_run_failure_isolated_partial_and_rerun_failed_only(predict_env, fake_record, monkeypatch):
    env = predict_env()
    ps = env.param_set()
    monkeypatch.setenv("FAKE_SIMLAB_FAIL_MATCH", "run__00002")
    bid, pj = env.make_batch(ps["id"], ROWS3, multi=2)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(pj)
    jd = env.job(pj)
    assert [w["code"] for w in jd["warnings"]] == ["PARTIAL_OUTPUT"]
    b = env.batch(bid)
    assert [(r["gen_state"], r["gen_code"]) for r in b["runs"]] == [("DONE", None), ("FAILED", "EXIT_NONZERO"), ("DONE", None)]
    assert "종료코드 1" in b["runs"][1]["gen_message"]
    assert [c["doe_no"] for c in _children(env, bid)] == [1, 3]
    # 하위 2개 완료 → 생성 실패 run 포함 모두 끝 → DONE + 알림 1건(완료 2 · 실패 1)
    assert env.w.run_once_slot() == "SUCCEEDED" and env.w.run_once_slot() == "SUCCEEDED"
    assert env.batch(bid)["status"] == "DONE"
    notes = env.sql("select title from notifications where event='PREDICT_BATCH_DONE' and user_id='u-power'")
    assert [n[0] for n in notes] == ["일괄 예측 B-001 완료 — 완료 2 · 실패 1"]
    # 부모 재시도(retry-failed가 만드는 새 PREDICT_BATCH, params = {batch_id}) → 실패 run만 다시
    from physicsai_core.db.repositories import jobs as jobs_repo
    from physicsai_core.db.repositories import predict_batches as pb
    from physicsai_core.db.repositories import studies as studies_repo

    monkeypatch.delenv("FAKE_SIMLAB_FAIL_MATCH")
    B = _B(env, bid)
    m1_mtime = (B / "run__00001" / "m_1" / "EPS_mesh_0000.rad").stat().st_mtime_ns
    n_sim = len([r for r in read_record(fake_record) if r["tool"] == "simlab"])
    with env.engine.begin() as conn:
        study = studies_repo.require(conn, env.sid)
        nj = jobs_repo.insert_job(conn, study=study, job_type="PREDICT_BATCH", params={"batch_id": bid}, user_id="u-power",
                                  user_name="파워")
        pb.set_parent_job(conn, bid, nj["id"])
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(nj["id"])
    sims = [r for r in read_record(fake_record) if r["tool"] == "simlab"][n_sim:]
    assert [Path(r["cwd"]).parent.name for r in sims] == ["run__00002"]
    assert (B / "run__00001" / "m_1" / "EPS_mesh_0000.rad").stat().st_mtime_ns == m1_mtime
    assert list((env.sroot / "_backup").rglob("run__00002"))                       # 실패 run 폴더는 _backup으로
    b = env.batch(bid)
    assert [r["gen_state"] for r in b["runs"]] == ["DONE"] * 3 and b["status"] == "PREDICTING" and b["job_id"] == nj["id"]
    ch = _children(env, bid)
    assert [c["doe_no"] for c in ch] == [1, 2, 3] and ch[1]["state"] == "QUEUED" and ch[1]["queue_seq"] is not None


def test_v3_s9_7_all_runs_fail(predict_env, monkeypatch):
    env = predict_env()
    ps = env.param_set()
    monkeypatch.setenv("FAKE_TOOL_MODE_HM", "no_output")
    bid, pj = env.make_batch(ps["id"], ROWS3, multi=2)
    assert env.w.run_once_slot() == "FAILED"
    jd = env.job(pj)
    assert jd["failure_code"] == "OUTPUT_MISSING" and jd["current_step_key"] == "BP_GEN"
    assert "모두 입력 생성 실패" in jd["failure_message"]
    b = env.batch(bid)
    assert b["status"] == "FAILED" and {r["gen_state"] for r in b["runs"]} == {"FAILED"}
    assert not _children(env, bid)


def test_v3_s9_8_cancel_during_gen_kills_all_processes(predict_env, tmp_path, monkeypatch):
    trace = _trace(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_TOOL_MODE_SIMLAB", "hang")
    env = predict_env()
    ps = env.param_set()
    bid, pj = env.make_batch(ps["id"], ROWS4, multi=2)
    out: list = []
    t = threading.Thread(target=lambda: out.append(env.w.run_once_slot()), daemon=True)
    t.start()
    end = time.time() + 20
    while time.time() < end and len([e for e in _events(trace) if e["ev"] == "hang"]) < 2:
        time.sleep(0.1)
    hangs = [e for e in _events(trace) if e["ev"] == "hang"]
    assert len(hangs) == 2                                                          # M=2만 시작(나머지 2개는 대기)
    r = env.c.post(f"{API}/jobs/{pj}/cancel", headers=H("tok-admin", write=True))
    assert r.status_code == 202, r.text
    t.join(timeout=30)
    assert out == ["CANCELED"]
    pids = [p for e in hangs for p in (e["pid"], e["child"])]
    deadline = time.time() + 10
    while time.time() < deadline and any(_alive(p) for p in pids):
        time.sleep(0.1)
    assert not [p for p in pids if _alive(p)]                                       # 프로세스 트리 잔존 없음
    b = env.batch(bid)
    assert b["status"] == "CANCELED" and {r["gen_state"] for r in b["runs"]} == {"PENDING"}
    assert len([e for e in _events(trace) if e["ev"] == "start"]) == 2              # 대기 run은 시작하지 않음
    assert env.steps(pj)["BP_GEN"]["state"] == "CANCELED"


def _alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def test_v3_s9_13_run_parallel_uses_one_group_null_limiter(settings_dict, predict_env, monkeypatch):
    """Linux 구조 시험: null 제한기로 BP_GEN — 그룹 1개, 모든 launch가 그 그룹, 끝나면 그룹 닫힘."""
    from physicsai_worker.limiter import null as null_mod

    settings_dict["worker"] = {**settings_dict["worker"], "limiter": "null"}
    groups: list = []
    launches: list = []
    orig_open, orig_launch = null_mod.NullLimiter.open_group, null_mod.NullLimiter.launch

    def spy_open(self, limits, size):
        g = orig_open(self, limits, size)
        groups.append(g)
        return g

    def spy_launch(self, argv, cwd, env, limits, group=None):
        launches.append(group)
        return orig_launch(self, argv, cwd, env, limits, group=group)

    monkeypatch.setattr(null_mod.NullLimiter, "open_group", spy_open)
    monkeypatch.setattr(null_mod.NullLimiter, "launch", spy_launch)
    env = predict_env()
    assert env.w.limiter.name == "null"
    ps = env.param_set()
    bid, pj = env.make_batch(ps["id"], "THK_1\tN_RIB\n2.5\t3\n3.0\t4\n3.5\t5\n", multi=2)
    launches.clear()
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(pj)
    assert len(groups) == 1 and groups[0].size == 2 and groups[0].closed
    assert len(launches) == 6 and all(g is groups[0] for g in launches)          # 3 run × (SimLab + HyperMesh)
