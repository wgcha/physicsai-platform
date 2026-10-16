"""e2e(V3-S9-15, 가짜 도구): 일괄 예측 B 3조합 — 입력 생성(동시 2) → 하위 예측 3개(FIFO) → 응답 추출(원본 ⑤ m_4 방식) →
배치 DONE·행 응답·완료 알림 1건. assembly·mesh_only 각각."""

from __future__ import annotations

import os

import pytest

TCL_NAME = "H3D_StaticMinMax_to_CSV_FAST.tcl"
ROWS = "THK_1,N_RIB\n2.5,3\n3.0,4\n3.5,5\n"
RESP = [{"name": "MaxStress", "unit": "MPa",
         "spec": {"source": "H3D", "subcase": 1, "datatype": "Stress", "component": "vonMises", "layer": "", "stat": "MAX"}}]


@pytest.mark.parametrize("kind", ["assembly", "mesh_only"])
def test_v3_s9_15_batch_end_to_end(predict_env, tmp_path, monkeypatch, kind):
    from physicsai_core.db.repositories import predict_batches as pb

    tcl = tmp_path / "res" / TCL_NAME
    tcl.parent.mkdir(parents=True)
    tcl.write_text("# fake\n")
    env = predict_env(commands={"response_extract": ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"]},
                      resources={"extract_minmax_tcl": str(tcl)})
    ps = env.param_set()
    env.set_responses(ps["id"], RESP)
    if kind == "mesh_only":
        env.to_mesh_only(ps["id"])
    bid, pj = env.make_batch(ps["id"], ROWS, multi=2)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(pj)
    b = env.batch(bid)
    assert b["status"] == "PREDICTING" and [pb.row_state(r, r["job_state"]) for r in b["runs"]] == ["QUEUED"] * 3
    child_ids = [r["predict_job_id"] for r in b["runs"]]
    fail_last = kind == "assembly"                                     # assembly: 마지막 하위 예측 실패 → 완료 2 · 실패 1
    for i, cid in enumerate(child_ids):
        if fail_last and i == 2:
            monkeypatch.setenv("FAKE_TOOL_MODE_EDSPY", "fail")
        state = env.w.run_once_slot()
        assert state == ("FAILED" if fail_last and i == 2 else "SUCCEEDED"), env.job(cid)
        assert env.job(cid)["id"] == cid                                # FIFO: doe_no 순
        if i < 2:
            assert env.batch(bid)["status"] == "PREDICTING"
    assert env.w.run_once_slot() is None                                # 대기열 비었음
    b = env.batch(bid)
    assert b["status"] == "DONE" and b["finished_at"] is not None
    states = [pb.row_state(r, r["job_state"]) for r in b["runs"]]
    assert states == (["SUCCEEDED", "SUCCEEDED", "FAILED"] if fail_last else ["SUCCEEDED"] * 3)
    assert [r["responses"] for r in b["runs"]][:2] == [{"MaxStress": 100.0}] * 2
    notes = env.sql("select title from notifications where event='PREDICT_BATCH_DONE'")
    assert [n[0] for n in notes] == [f"일괄 예측 B-001 완료 — 완료 {2 if fail_last else 3} · 실패 {1 if fail_last else 0}"]
    # 하위 예측 결과: 입력값 = run 행, 입력 = run 폴더 사본, 응답 표
    B = env.sroot / b["dir_rel"]
    for r, cid in zip(b["runs"][:2], child_ids[:2]):
        cj = env.job(cid)
        assert cj["result"]["values"] == r["values"] and cj["result"]["out_of_range"] == r["out_of_range"]
        assert cj["result"]["response_table"][0]["predicted"] == 100.0
        inp = env.predict_dir(cid) / "INPUT"
        src = B / r["input_rel"]
        if kind == "mesh_only":
            assert sorted(os.listdir(inp)) == ["EPS_mesh_0000.rad"]
            assert (inp / "EPS_mesh_0000.rad").read_bytes() == src.read_bytes()
        else:
            assert sorted(os.listdir(inp)) == sorted(os.listdir(src))
    st = env.sql("select count(*) from jobs where job_type='PREDICT' and params->'batch_run'->>'batch_id' = :b", b=bid)
    assert st[0][0] == 3
