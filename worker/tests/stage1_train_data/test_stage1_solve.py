"""①-4 해석 제출(PBS command): run별 제출·폴러·T10b, 실패 처리(on_run_failure·제출 실패), 대기 중 취소.

V2-TD-5, V2-HPC-1, V2-NT-1(일부). 회수 모드(V2-TD-6)는 test_stage1_train.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from helpers_stage1 import (
    _ready_doe,
    _write_results,
    job,
    submit,
)
from physicsai_test_support import API, H, read_record

PW, P, AW = H("tok-power", write=True), H("tok-power"), H("tok-admin", write=True)


def test_solve_pbs_full_and_partial(p2_pbs, fake_record, engine, monkeypatch):
    """V2-TD-5·V2-HPC-1·V2-NT-1: run별 제출, 폴러 다중 run, T10b(일부 실패 → 회수 + HPC_PARTIAL_FAILED), hpc_summary."""
    c, mk, ai, lc, d = p2_pbs
    w = mk()
    sid, doe_id = _ready_doe(c, w, ai, "sv1")
    monkeypatch.setenv("FAKE_TOOL_MODE_PBS", "exit1_one")
    monkeypatch.setenv("FAKE_PBS_FAIL_MATCH", "run__00002")
    j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id, "hpc": {"ncpus": 4}})
    assert w.run_once_slot() == "WAITING_HPC", job(c, j["id"])
    subs = [r["argv"] for r in read_record(fake_record) if r["tool"] == "qsub"]
    assert len(subs) == 3
    names = [a[a.index("-N") + 1] for a in subs]
    assert names[0] == f"sv1_{doe_id[:8]}_run__00001_a1".replace("-", "_") or names[0].endswith("run__00001_a1")
    v = subs[0][subs[0].index("-v") + 1]
    assert f"INPUT_FILE=/shared/AI_WORK/sv1/01_train/doe/{doe_id}/approaches/doe_1/run__00001/m_3/drop_0000.rad" in v
    assert v.endswith(f"RESULT_DIR=/shared/AI_WORK/sv1/01_train/results/{doe_id}/run__00001")
    hj = c.get(f"{API}/jobs/{j['id']}/hpc-jobs", headers=P).json()
    assert sorted(h["external_job_id"] for h in hj) == ["12345.pbs01", "12346.pbs01", "12347.pbs01"]
    assert [r["state"] for r in c.get(f"{API}/train-does/{doe_id}/runs", headers=P).json()] == ["SUBMITTED"] * 3
    q = c.get(f"{API}/queue", headers=P).json()
    assert q["waiting_hpc"][0]["hpc_summary"] == {"total": 3, "queued": 3, "running": 0, "succeeded": 0, "failed": 0, "collected": 0}
    assert q["waiting_hpc"][0]["stage_label"] == "①-4"
    for _ in range(3):
        w.poll_hpc_once()
    _write_results(ai, "sv1", doe_id, ["run__00001", "run__00003"])
    jd = job(c, j["id"])
    assert jd["state"] == "COLLECTING" and jd["attention_code"] == "HPC_RUN_FAILED"  # T10b
    assert any(x["code"] == "HPC_PARTIAL_FAILED" for x in jd["warnings"])
    runs = {r["run_key"]: r["state"] for r in c.get(f"{API}/train-does/{doe_id}/runs", headers=P).json()}
    assert runs == {"run__00001": "SOLVED", "run__00002": "SOLVE_FAILED", "run__00003": "SOLVED"}
    assert w.run_once_collect() == "QUEUED"
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    jd = job(c, j["id"])
    assert jd["result"]["collected"] == 2 and jd["result"]["failed"] == 1 and jd["result"]["submitted"] == 3
    runs = {r["run_key"]: r for r in c.get(f"{API}/train-does/{doe_id}/runs", headers=P).json()}
    assert runs["run__00001"]["state"] == "COLLECTED" and runs["run__00001"]["result"] == {"h3d": 1, "t01": 1, "files": 4, "total_bytes": runs["run__00001"]["result"]["total_bytes"]}
    assert runs["run__00002"]["state"] == "SOLVE_FAILED"
    col = json.loads((ai / "sv1" / "01_train" / "results" / doe_id / "collected.json").read_text())
    assert [x["run_key"] for x in col["runs"]] == ["run__00001", "run__00003"]
    with engine.connect() as conn:
        ev = conn.execute(text("select event, title from notifications where job_id=:j order by seq"), {"j": j["id"]}).all()
    events = [e for e, _ in ev]
    assert events == ["JOB_STARTED", "HPC_PARTIAL_FAILED", "HPC_COLLECTED", "JOB_SUCCEEDED"]
    titles = dict(ev)
    assert titles["HPC_PARTIAL_FAILED"] == "PBS 해석 일부 실패 — 3개 중 1개 실패, 나머지 회수 진행"
    assert titles["HPC_COLLECTED"] == "PBS 결과 회수 완료 — 3개 중 2개 회수"
    assert titles["JOB_SUCCEEDED"] == "완료: PBS 해석 (sv1)"
    # ①-4 회수 결과 → ② 큐레이션 → ③-1 데이터셋(자동 연결)
    src = {"kind": "TRAIN_DOE", "doe_id": doe_id}
    pj = submit(c, sid, "CU_H3D_PREVIEW", {"source": src})
    assert w.run_once_slot() == "SUCCEEDED", job(c, pj["id"])
    sel = {"items": [{"datatype": "Stress", "component": "P1"}], "parts": {"shell": [], "solid": [3], "rbody": []}, "time_increment": 1}
    cj = submit(c, sid, "CU_H3D_CURATE", {"source": src, "preview_job_id": pj["id"], "selection": sel})
    assert w.run_once_slot() == "SUCCEEDED", job(c, cj["id"])
    assert job(c, cj["id"])["result"]["missing_run_count"] == 1
    dj = submit(c, sid, "DATASET_CREATE", {"curation_id": cj["result"]["curation_id"]})
    assert w.run_once_slot() == "SUCCEEDED", job(c, dj["id"])
    assert job(c, dj["id"])["result"]["h3d_count"] == 2
    # 재제출 대상 = SOLVE_FAILED만, attempt 2
    monkeypatch.setenv("FAKE_TOOL_MODE_PBS", "ok")
    j2 = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id})
    assert w.run_once_slot() == "WAITING_HPC"
    assert job(c, j2["id"])["result"]["run_keys"] == ["run__00002"] and job(c, j2["id"])["result"]["attempt"] == 2
    # 전부 실패(on_run_failure=fail 아님이어도 성공 0개) → T13
    monkeypatch.setenv("FAKE_TOOL_MODE_PBS", "exit1")
    for _ in range(3):
        w.poll_hpc_once()
    jd2 = job(c, j2["id"])
    assert jd2["state"] == "FAILED" and jd2["failure_code"] == "HPC_RUN_FAILED"
    assert jd2["can_download_error_bundle"] is True


def test_solve_on_run_failure_fail_and_submit_failure(p2_pbs, fake_record, monkeypatch):
    """V2-TD-5: on_run_failure=fail → T13, 제출 중 실패 → 이미 제출분 qdel + HPC_SUBMIT_FAILED."""
    c, mk, ai, lc, d = p2_pbs
    w = mk()
    sid, doe_id = _ready_doe(c, w, ai, "sv2")
    monkeypatch.setenv("FAKE_PBS_SUBMIT_FAIL_AT", "3")
    j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id})
    assert w.run_once_slot() == "FAILED"
    jd = job(c, j["id"])
    assert jd["failure_code"] == "HPC_SUBMIT_FAILED"
    dels = [r["argv"][-1] for r in read_record(fake_record) if r["tool"] == "qdel"]
    assert sorted(dels) == ["12345.pbs01", "12346.pbs01"]
    states = [h["state"] for h in c.get(f"{API}/jobs/{j['id']}/hpc-jobs", headers=P).json()]
    assert states == ["CANCELED", "CANCELED"]
    monkeypatch.delenv("FAKE_PBS_SUBMIT_FAIL_AT")
    monkeypatch.setenv("FAKE_TOOL_MODE_PBS", "exit1_one")
    monkeypatch.setenv("FAKE_PBS_FAIL_MATCH", "run__00001")
    j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id, "run_keys": ["run__00001", "run__00002"], "on_run_failure": "fail"})
    assert w.run_once_slot() == "WAITING_HPC"
    for _ in range(3):
        w.poll_hpc_once()
    assert job(c, j["id"])["state"] == "FAILED"
    # 재시도는 항상 TS_PREP부터(HPC 제출 재사용 안 함)
    r = c.post(f"{API}/jobs/{j['id']}/retry", headers=PW, json={"from_step": 3})
    assert r.status_code == 201 and all(s["state"] == "PENDING" for s in r.json()["steps"])
    # 검증 오류
    assert submit(c, sid, "TD_SOLVE", {"doe_id": doe_id, "run_keys": ["nope"]}, expect=422)["detail"]["code"] == "INVALID_PARAMS"
    assert submit(c, sid, "TD_SOLVE", {"doe_id": "x"}, expect=409)["detail"]["code"] == "DOE_NOT_READY"


def test_solve_cancel_multi_run(p2_pbs, fake_record):
    """V2-HPC-1: 다중 run 대기 중 취소(T12) → 모든 hpc_job qdel, run SOLVE_FAILED(재제출 대상)."""
    c, mk, ai, lc, d = p2_pbs
    w = mk()
    sid, doe_id = _ready_doe(c, w, ai, "sv3", num_runs=2)
    j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id})
    assert w.run_once_slot() == "WAITING_HPC"
    assert c.post(f"{API}/jobs/{j['id']}/cancel", headers=AW).status_code == 202
    w.poll_hpc_once()
    assert job(c, j["id"])["state"] == "CANCELED"
    assert sorted(r["argv"][-1] for r in read_record(fake_record) if r["tool"] == "qdel") == ["12345.pbs01", "12346.pbs01"]
    assert [r["state"] for r in c.get(f"{API}/train-does/{doe_id}/runs", headers=P).json()] == ["SOLVE_FAILED"] * 2
