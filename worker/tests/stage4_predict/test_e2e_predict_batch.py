"""e2e(V3-S9-15 + V3-S10, 가짜 도구 + API): 일괄 예측 B 3조합 — API 생성 → 입력 생성(동시 2) → 하위 예측 3개(FIFO) → 응답 추출
(원본 ⑤ m_4 방식) → 컨투어 캡처(S10, 하위 예측 끝 step) → 배치 DONE·결과 표·media_views·완료 알림 1건.
assembly(마지막 하위 실패 → retry-failed로 복구)·mesh_only 각각."""

from __future__ import annotations

import os

import pytest

from physicsai_test_support import API, H, read_record

PW = H("tok-power", write=True)
P = H("tok-power")
TCL_NAME = "H3D_StaticMinMax_to_CSV_FAST.tcl"
ROWS = "THK_1,N_RIB\n2.5,3\n3.0,4\n3.5,5\n"
RESP = [{"name": "MaxStress", "unit": "MPa",
         "spec": {"source": "H3D", "subcase": 1, "datatype": "Stress", "component": "vonMises", "layer": "", "stat": "MAX"}},
        {"name": "Disp", "unit": "mm", "spec": None}]                  # 실측 열(지울 수 없음), 추출 정의 없음 → null·경고 없음


@pytest.mark.parametrize("kind", ["assembly", "mesh_only"])
def test_v3_s9_15_batch_end_to_end(predict_env, fake_record, tmp_path, monkeypatch, kind):
    tcl = tmp_path / "res" / TCL_NAME
    tcl.parent.mkdir(parents=True)
    tcl.write_text("# fake\n")
    env = predict_env(commands={"response_extract": ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"]},
                      resources={"extract_minmax_tcl": str(tcl)})
    ps = env.param_set()
    r = env.c.put(f"{API}/param-sets/{ps['id']}/responses", headers=PW, json={"responses": RESP})
    assert r.status_code == 200, r.text
    if kind == "mesh_only":
        env.to_mesh_only(ps["id"])
    pj = env.submit("PREDICT_BATCH", {"param_set_id": ps["id"], "multi_execution": 2, "source": {"kind": "table", "text": ROWS}})
    bid = pj["params"]["batch_id"]
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(pj["id"])
    b = env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()
    assert b["status"] == "PREDICTING" and b["gen"]["done"] == 3 and [x["state"] for x in b["rows"]] == ["QUEUED"] * 3
    child_ids = [x["job_id"] for x in b["rows"]]
    fail_last = kind == "assembly"                                     # assembly: 마지막 하위 예측 실패 → 완료 2 · 실패 1
    for i, cid in enumerate(child_ids):
        if fail_last and i == 2:
            monkeypatch.setenv("FAKE_TOOL_MODE_EDSPY", "fail")
        state = env.w.run_once_slot()
        assert state == ("FAILED" if fail_last and i == 2 else "SUCCEEDED"), env.job(cid)
    assert env.w.run_once_slot() is None                                # 대기열 비었음(하위는 doe_no 순 FIFO로 모두 실행)
    b = env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()
    assert b["status"] == "DONE"
    assert [x["state"] for x in b["rows"]] == (["SUCCEEDED", "SUCCEEDED", "FAILED"] if fail_last else ["SUCCEEDED"] * 3)
    assert [x["responses"] for x in b["rows"]][:2] == [{"MaxStress": 100.0, "Disp": None}] * 2
    notes = env.sql("select title from notifications where event='PREDICT_BATCH_DONE'")
    assert [n[0] for n in notes] == [f"일괄 예측 B-001 완료 — 완료 {2 if fail_last else 3} · 실패 {1 if fail_last else 0}"]
    assert not env.sql("select 1 from notifications n join jobs j on j.id = n.job_id where j.params ? 'batch_run'")  # 하위 알림 0
    # 하위 예측 결과: 입력값 = run 행, 입력 = run 폴더 사본, 응답 표
    for row, cid in zip(b["rows"][:2], child_ids[:2]):
        cj = env.job(cid)
        assert cj["result"]["values"] == row["values"] and cj["result"]["response_table"][0]["predicted"] == 100.0
        assert cj["result"]["response_errors"] == {"Disp": "NOT_DEFINED"}
        assert "RESPONSE_NO_VALUE" not in [w["code"] for w in cj["warnings"]]
        inp = env.predict_dir(cid) / "INPUT"
        if kind == "mesh_only":
            assert sorted(os.listdir(inp)) == ["EPS_mesh_0000.rad"]
        else:
            assert sorted(os.listdir(inp)) == sorted(os.listdir(os.path.join(row["folder"], "m_3")))
    # S10: 하위 예측마다 응답 추출 뒤 컨투어 캡처(방향 4개 PNG·동영상), B 행 media_views, GET /jobs/{id}/media
    views4 = ["iso", "front", "top", "right"]
    caps = [r for r in read_record(fake_record) if r["tool"] == "hw_capture"]
    assert len(caps) == (2 if fail_last else 3)
    for row, cid in zip(b["rows"][:2], child_ids[:2]):
        steps = env.steps(cid)
        keys = list(steps)
        assert keys[-1] == "CONTOUR_CAPTURE" and keys.index("RESPONSE_EXTRACT") < keys.index("CONTOUR_CAPTURE")
        assert steps["RESPONSE_EXTRACT"]["state"] == steps["CONTOUR_CAPTURE"]["state"] == "SUCCEEDED"
        cap = env.job(cid)["result"]["capture"]
        assert cap["status"] == "OK" and cap["failed_views"] == []
        assert row["media_views"] == views4
        m = env.c.get(f"{API}/jobs/{cid}/media", headers=P).json()
        assert m["status"] == "OK" and [i["view"] for i in m["items"]] == views4 and all(i["video"] for i in m["items"])
    if fail_last:
        assert b["rows"][2]["media_views"] == []
    csv_text = env.c.get(f"{API}/predict-batches/{bid}/table.csv", headers=P).content.decode("utf-8-sig")
    assert csv_text.splitlines()[0].startswith("doe_no,run_key,folder,THK_1,N_RIB,MaxStress,Disp")
    if fail_last:                                                       # 실패만 다시 실행 → 하위 재시도 → 다시 DONE(알림 2번째)
        monkeypatch.delenv("FAKE_TOOL_MODE_EDSPY")
        r = env.c.post(f"{API}/predict-batches/{bid}/retry-failed", headers=PW)
        assert r.status_code == 201, r.text
        assert r.json()["parent_job_id"] is None and len(r.json()["retried_job_ids"]) == 1
        assert env.w.run_once_slot() == "SUCCEEDED"
        b = env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()
        assert b["status"] == "DONE" and [x["state"] for x in b["rows"]] == ["SUCCEEDED"] * 3
        assert b["rows"][2]["responses"] == {"MaxStress": 100.0, "Disp": None}
