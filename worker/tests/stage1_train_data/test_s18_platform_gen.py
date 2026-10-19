"""S18 ① 학습 DOE 플랫폼 동시 생성(phase3 §23, D3-66): V3-S18-4·5·6·7·9(워커).

동시 실행 하한은 가짜 SimLab barrier(FAKE_SIMLAB_BARRIER)로 결정적으로 증명한다 — 순차면 barrier timeout(종료코드 9)으로
run이 실패한다. 상한은 trace 구간(가짜 도구 시작·끝)으로만 확인한다. 시각 비율 단언 없음(§23.11).
"""

from __future__ import annotations

import csv
import json
import os
import threading
import time
from pathlib import Path

import psutil
from sqlalchemy import text

from helpers_stage1 import _write_results, extract_and_tpl, job, make_inputs, study, submit
from physicsai_test_support import API, H, _p2_env, read_record

PW, P, AW = H("tok-power", write=True), H("tok-power"), H("tok-admin", write=True)
INC = "104_replace_node_elem.inc"
HST_FILES = {"DATA_doe_design_type.json", "BATCHRUN_create_include_node_elem.tcl", "INPUT_HST_RUN.json"}


def _prepare(c, w, ai: Path, name: str) -> str:
    sid = study(c, name)
    cad, _assem = make_inputs(ai / name)
    extract_and_tpl(c, w, sid, cad)
    return sid


def _gen(c, sid, ai: Path, name: str, sampling: dict, **kw) -> dict:
    return submit(c, sid, "TD_DOE_GEN", {"sampling": sampling, "radioss_assem_path": str(ai / name / "00_inbox" / "radioss_assem"),
                                         **kw})


def _events(trace: Path) -> list[dict]:
    return [json.loads(x) for x in trace.read_text().splitlines() if x.strip()] if trace.exists() else []


def _peak(trace: Path, tool: str = "simlab") -> int:
    ev = sorted(((e["t"], 1 if e["ev"] == "start" else -1) for e in _events(trace)
                 if e["ev"] in ("start", "end") and e["tool"] == tool), key=lambda x: (x[0], x[1]))
    cur = peak = 0
    for _t, d in ev:
        cur += d
        peak = max(peak, cur)
    return peak


def _points(engine, doe_id: str) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(text("select run_key, gen_state from train_doe_points where doe_id=:d order by doe_no"),
                            {"d": doe_id}).all()
    return {r[0]: r[1] for r in rows}


def _step(c, jid: str, key: str) -> dict:
    return next(s for s in job(c, jid)["steps"] if s["step_key"] == key)


def _step_outputs(engine, jid: str, key: str) -> dict:
    with engine.connect() as conn:
        return conn.execute(text("select outputs from job_steps where job_id=:j and step_key=:k"), {"j": jid, "k": key}).scalar()


def test_v3_s18_4_platform_parallel_barrier_folders_scan(p2_env, engine, tmp_path, monkeypatch):
    """N = 4, M = 4, barrier n = 4: 4개가 실제로 동시에 떠 있어야 성공(순차면 barrier timeout). 폴더·doe.json·DG_SCAN·samples."""
    c, mk, ai, lc, _d = p2_env
    w = mk()
    sid = _prepare(c, w, ai, "pg1")
    monkeypatch.setenv("FAKE_SIMLAB_BARRIER", f"{tmp_path / 'barrier'}:4")
    monkeypatch.setenv("FAKE_SIMLAB_BARRIER_TIMEOUT_S", "90")
    j = _gen(c, sid, ai, "pg1", {"kind": "lhs_opt", "count": 4, "seed": 1}, multi_execution=4)
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    assert len(os.listdir(tmp_path / "barrier")) == 4                         # SimLab 4개가 모두 barrier에 도착(동시)
    jd = job(c, j["id"])
    doe_id = jd["result"]["doe_id"]
    D = ai / "pg1" / "01_train" / "doe" / doe_id
    # D 직계: tpl·CAD·doe.json·samples.csv·runs.json·run 상위만(HyperStudy 파일 없음)
    top = set(os.listdir(D)) - {"_backup"}
    assert top == {"simlab_parametered_mesh.tpl", "cushion_parametric.prt", "doe.json", "samples.csv", "runs.json", "approaches"}
    assert not HST_FILES & top and not list(D.glob("BATCHRUN_*"))
    R = D / "approaches" / "doe_1"
    assert sorted(os.listdir(R)) == [f"run__{n:05d}" for n in range(1, 5)]
    for n in range(1, 5):
        X = R / f"run__{n:05d}"
        assert sorted(os.listdir(X)) == ["m_1", "m_2", "m_3"]
        assert sorted(os.listdir(X / "m_1")) == ["EPS_mesh_0000.rad", "cushion_parametric.prt", "simlab_parametered_mesh.py"]
        assert (X / "m_2" / INC).is_file() and "COMPLETE HM BATCHRUN" in (X / "m_2" / "log_batch.txt").read_text()
        assert sorted(os.listdir(X / "m_3")) == sorted(["drop_0000.rad", "drop_0001.rad", "mat.inc", INC])  # eps_mesh·csv 제외
        assert (X / "m_3" / INC).read_bytes() == (X / "m_2" / INC).read_bytes()
    # 진행 라벨·동시 실행 기록
    st = _step(c, j["id"], "HST_GEN_RADIOSS")
    assert st["state"] == "SUCCEEDED" and "입력 생성" in st["progress_label"] and "(동시 4)" in st["progress_label"]
    par = _step_outputs(engine, j["id"], "HST_GEN_RADIOSS")["parallel"]
    assert par["max_parallel"] == 4 and par["items"] == 4 and par["ok"] == 4
    assert jd["result"]["gen_done"] == 4 and jd["result"]["gen_failed"] == [] and jd["result"]["multi_execution"] == 4
    # doe.json·DB 표본
    dj = json.loads((D / "doe.json").read_text())
    assert dj["generator"] == "platform" and dj["sampling"]["kind"] == "lhs_opt" and dj["sampling"]["label"] == "최적화 LHS"
    assert dj["parameters"] == ["THK_1", "RIB_H"] and dj["run_root"] == "approaches/doe_1"
    assert dj["sampling"]["meta"]["quality"] and [r["run_key"] for r in dj["rows"]] == [f"run__{n:05d}" for n in range(1, 5)]
    assert _points(engine, doe_id) == {f"run__{n:05d}": "DONE" for n in range(1, 5)}
    # DG_SCAN: train_runs 4개(input_rel = m_3, starter), samples.csv = DB applied_values, PARSED
    runs = c.get(f"{API}/train-does/{doe_id}/runs", headers=P).json()
    assert [r["run_key"] for r in runs] == [f"run__{n:05d}" for n in range(1, 5)]
    assert all(r["starter_name"] == "drop_0000.rad" and r["state"] == "GENERATED" for r in runs)
    with engine.connect() as conn:
        rels = conn.execute(text("select input_rel from train_runs where doe_id=:d order by run_key"), {"d": doe_id}).scalars().all()
    assert rels == [f"01_train/doe/{doe_id}/approaches/doe_1/run__{n:05d}/m_3" for n in range(1, 5)]
    rows = list(csv.reader((D / "samples.csv").open()))
    assert rows[0] == ["run_key", "THK_1", "RIB_H"] and len(rows) == 5
    by = {r["run_key"]: r for r in dj["rows"]}
    for row in rows[1:]:
        assert [float(x) for x in row[1:]] == [float(by[row[0]]["applied_values"][n]) for n in ("THK_1", "RIB_H")]
    doe = c.get(f"{API}/train-does/{doe_id}", headers=P).json()
    assert doe["status"] == "READY" and doe["sample_status"] == "PARSED" and doe["run_count"] == 4
    assert doe["generator"] == "platform" and doe["doe_type"] == "LHS_OPT" and doe["doe_label"] == "최적화 LHS"
    assert doe["gen"] == {"total": 4, "pending": 0, "running": 0, "done": 4, "failed": 0}
    assert doe["sampling"]["kind"] == "lhs_opt" and doe["sampling"]["desc_id"] == "td_lhs_opt" and doe["sampling"]["meta"]
    assert doe["options"] == {"count": 4, "seed": 1, "criterion": "maximin"} and doe["num_runs_requested"] == 4
    # 렌더 스크립트 = run 반영값(정수 형식 %3i)
    script = (R / "run__00002" / "m_1" / "simlab_parametered_mesh.py").read_text()
    assert f"{int(by['run__00002']['applied_values']['RIB_H']):3d}" in script


def test_v3_s18_5_upper_bound_trace_and_cap(p2_env, tmp_path, monkeypatch):
    """N = 6, M = 2: 관측 동시 수 ≤ 2(하한 단언 없음)."""
    c, mk, ai, _lc, _d = p2_env
    w = mk()
    sid = _prepare(c, w, ai, "pg2")
    trace = tmp_path / "trace.jsonl"
    monkeypatch.setenv("FAKE_TOOL_TRACE", str(trace))
    j = _gen(c, sid, ai, "pg2", {"kind": "lhs", "count": 6, "seed": 3}, multi_execution=2)
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    assert 1 <= _peak(trace) <= 2 and _peak(trace, "hw") <= 2
    assert len([e for e in _events(trace) if e["ev"] == "start" and e["tool"] == "simlab"]) == 6
    assert job(c, j["id"])["result"]["multi_execution"] == 2


def test_v3_s18_5_max_multi_execution_one(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch):
    """max_multi_execution = 1이면 M = 1(작업 생성 상한도 1)."""
    gen = _p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, {"train_data": {"max_multi_execution": 1}})
    c, mk, ai, _lc, _d = next(gen)
    try:
        w = mk()
        sid = _prepare(c, w, ai, "pg3")
        bad = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "TD_DOE_GEN", "params": {
            "sampling": {"kind": "lhs", "count": 3}, "multi_execution": 2,
            "radioss_assem_path": str(ai / "pg3" / "00_inbox" / "radioss_assem")}})
        assert bad.status_code == 422
        trace = tmp_path / "trace1.jsonl"
        monkeypatch.setenv("FAKE_TOOL_TRACE", str(trace))
        j = _gen(c, sid, ai, "pg3", {"kind": "lhs", "count": 3})  # 기본 = min(4, 1) = 1
        assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
        assert _peak(trace) == 1 and job(c, j["id"])["result"]["multi_execution"] == 1
        assert job(c, j["id"])["params"]["multi_execution"] == 1
    finally:
        for _ in gen:
            pass


def test_v3_s18_6_partial_failure_fail_then_retry_failed_only(p2_env, engine, fake_record, monkeypatch):
    c, mk, ai, _lc, _d = p2_env
    w = mk()
    sid = _prepare(c, w, ai, "pg4")
    monkeypatch.setenv("FAKE_SIMLAB_FAIL_MATCH", "run__00003")
    j = _gen(c, sid, ai, "pg4", {"kind": "lhs", "count": 4, "seed": 5}, multi_execution=2)
    assert w.run_once_slot() == "FAILED"
    jd = job(c, j["id"])
    doe_id = jd["result"]["doe_id"]
    assert jd["failure_code"] == "GEN_PARTIAL_FAILED" and "run__00003" in jd["failure_message"]
    assert "재시도하면 실패한 run만" in jd["failure_message"]
    assert _points(engine, doe_id) == {"run__00001": "DONE", "run__00002": "DONE", "run__00003": "FAILED", "run__00004": "DONE"}
    doe = c.get(f"{API}/train-does/{doe_id}", headers=P).json()
    assert doe["status"] == "FAILED" and doe["gen"] == {"total": 4, "pending": 0, "running": 0, "done": 3, "failed": 1}
    with engine.connect() as conn:
        code = conn.execute(text("select gen_code from train_doe_points where doe_id=:d and run_key='run__00003'"),
                            {"d": doe_id}).scalar()
    assert code == "EXIT_NONZERO"
    # 환경변수 지우고 재시도 → run__00003만 다시 실행
    monkeypatch.delenv("FAKE_SIMLAB_FAIL_MATCH")
    before = len([r for r in read_record(fake_record) if r["tool"] == "simlab"])
    r = c.post(f"{API}/jobs/{j['id']}/retry", headers=PW, json={})
    assert r.status_code == 201, r.text
    nj = r.json()
    assert w.run_once_slot() == "SUCCEEDED", job(c, nj["id"])
    again = [r for r in read_record(fake_record) if r["tool"] == "simlab"][before:]
    assert len(again) == 1 and "run__00003" in again[0]["cwd"]
    doe = c.get(f"{API}/train-does/{doe_id}", headers=P).json()
    assert doe["status"] == "READY" and doe["run_count"] == 4 and doe["sample_status"] == "PARSED"
    assert doe["gen"]["done"] == 4


def test_v3_s18_6_continue_registers_successful_runs(p2_env, engine, monkeypatch):
    c, mk, ai, _lc, _d = p2_env
    w = mk()
    sid = _prepare(c, w, ai, "pg5")
    monkeypatch.setenv("FAKE_SIMLAB_FAIL_MATCH", "run__00003")
    j = _gen(c, sid, ai, "pg5", {"kind": "lhs", "count": 4, "seed": 5}, multi_execution=2, on_run_failure="continue")
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    jd = job(c, j["id"])
    doe_id = jd["result"]["doe_id"]
    assert any(x["code"] == "PARTIAL_OUTPUT" for x in jd["warnings"])
    doe = c.get(f"{API}/train-does/{doe_id}", headers=P).json()
    assert doe["status"] == "READY" and doe["run_count"] == 3 and doe["sample_status"] == "PARTIAL"
    D = ai / "pg5" / "01_train" / "doe" / doe_id
    rows = list(csv.reader((D / "samples.csv").open()))
    assert [r[0] for r in rows[1:]] == ["run__00001", "run__00002", "run__00004"]


def _alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def test_v3_s18_7_cancel_kills_group_and_resets_running(p2_env, engine, tmp_path, monkeypatch):
    c, mk, ai, _lc, _d = p2_env
    w = mk()
    sid = _prepare(c, w, ai, "pg6")
    trace = tmp_path / "trace.jsonl"
    monkeypatch.setenv("FAKE_TOOL_TRACE", str(trace))
    monkeypatch.setenv("FAKE_TOOL_MODE_SIMLAB", "hang")
    j = _gen(c, sid, ai, "pg6", {"kind": "lhs", "count": 4}, multi_execution=2)
    out: list = []
    t = threading.Thread(target=lambda: out.append(w.run_once_slot()), daemon=True)
    t.start()
    end = time.time() + 60
    while time.time() < end and len([e for e in _events(trace) if e["ev"] == "hang"]) < 2:
        time.sleep(0.1)
    hangs = [e for e in _events(trace) if e["ev"] == "hang"]
    assert len(hangs) == 2                                                          # M = 2만 시작
    r = c.post(f"{API}/jobs/{j['id']}/cancel", headers=AW)
    assert r.status_code == 202, r.text
    t.join(timeout=60)
    assert out == ["CANCELED"]
    pids = [p for e in hangs for p in (e["pid"], e["child"])]
    deadline = time.time() + 30
    while time.time() < deadline and any(_alive(p) for p in pids):
        time.sleep(0.1)
    assert not [p for p in pids if _alive(p)]                                       # 프로세스 트리 잔존 없음
    doe_id = job(c, j["id"])["result"]["doe_id"]
    states = _points(engine, doe_id)
    assert "RUNNING" not in states.values() and set(states.values()) == {"PENDING"}
    assert _step(c, j["id"], "HST_GEN_RADIOSS")["state"] == "CANCELED"


def test_v3_s18_9_downstream_samples_result_table_from_train(p2_env, engine, monkeypatch):
    """플랫폼 DOE → ①-5 결과 지정 → ①→④ 파라미터 세트·train_doe 미리보기 행 = samples.csv, result-table sampling td_*."""
    c, mk, ai, lc, _d = p2_env
    w = mk()
    sid = _prepare(c, w, ai, "pg7")
    j = _gen(c, sid, ai, "pg7", {"kind": "pb"}, multi_execution=3)
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    doe_id = job(c, j["id"])["result"]["doe_id"]
    doe = c.get(f"{API}/train-does/{doe_id}", headers=P).json()
    assert doe["doe_type"] == "PB" and doe["sampling"]["desc_id"] == "td_pb"
    keys = [r["run_key"] for r in c.get(f"{API}/train-does/{doe_id}/runs", headers=P).json()]
    src = Path(lc.settings.storage.allowed_import_roots[0]) / "pb_results"
    _write_results(ai, "pg7", doe_id, keys, base=src)
    ri = submit(c, sid, "TD_RESULT_IMPORT", {"doe_id": doe_id, "source_path": str(src)})
    assert w.run_once_light() == "SUCCEEDED", job(c, ri["id"])
    rt = c.get(f"{API}/train-does/{doe_id}/result-table", headers=P).json()
    assert rt["sampling"] == {"method": "PB", "label": "Plackett–Burman", "desc_id": "td_pb", "options": {}}
    assert [r["run_id"] for r in rt["rows"]] == keys
    ps = c.post(f"{API}/studies/{sid}/param-sets/from-train", headers=PW, json={"doe_id": doe_id})
    assert ps.status_code == 201, ps.text
    ps = ps.json()
    assert ps["starter_name"] == "drop_0000.rad" and ps["sample_count"] == len(keys)
    pv = c.post(f"{API}/studies/{sid}/predict-batches/preview", headers=PW,
                json={"param_set_id": ps["id"], "source": {"kind": "train_doe", "doe_id": doe_id}})
    assert pv.status_code == 200, pv.text
    D = ai / "pg7" / "01_train" / "doe" / doe_id
    rows = list(csv.reader((D / "samples.csv").open()))
    got = {r["run_key"]: r["values"] for r in pv.json()["rows"]}
    assert sorted(got) == [r[0] for r in rows[1:]]
    for r in rows[1:]:
        assert [got[r[0]][n] for n in ("THK_1", "RIB_H")] == [float(x) for x in r[1:]]


def test_v3_s18_9_td_solve_argv_uses_m3(p2_pbs, fake_record, monkeypatch):
    """플랫폼 DOE로 TD_SOLVE(가짜 qsub): 제출 입력 = run 폴더 m_3의 starter."""
    c, mk, ai, _lc, _d = p2_pbs
    w = mk()
    sid = _prepare(c, w, ai, "pg8")
    j = _gen(c, sid, ai, "pg8", {"kind": "lhs", "count": 2}, multi_execution=2)
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    doe_id = job(c, j["id"])["result"]["doe_id"]
    s = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id})
    assert w.run_once_slot() == "WAITING_HPC", job(c, s["id"])
    subs = [r["argv"] for r in read_record(fake_record) if r["tool"] == "qsub"]
    assert len(subs) == 2
    v = subs[0][subs[0].index("-v") + 1]
    assert f"/pg8/01_train/doe/{doe_id}/approaches/doe_1/run__00001/m_3/drop_0000.rad" in v
