"""①-5 결과 가져오기(gateway none 수동 지정)·F(① 결과 → ④ 파라미터 세트)·①-6 응답 추출.

V2-TD-7·8, V2-F-1.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

from sqlalchemy import text

from helpers_stage1 import (
    _ready_doe,
    _write_results,
    job,
    submit,
)
from physicsai_test_support import API, H, _p2_env

PW, P, AW = H("tok-power", write=True), H("tok-power"), H("tok-admin", write=True)


def test_result_import_none_mode_and_from_train(p2_env, monkeypatch, engine):
    """V2-TD-7(gateway none: ①-4 409·①-5 수동 결과 지정), V2-F-1(① 결과 → ④ 파라미터 세트)."""
    c, mk, ai, lc, d = p2_env
    w = mk()
    sid, doe_id = _ready_doe(c, w, ai, "ri1")
    r = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id}, expect=409)
    assert r["detail"]["code"] == "HPC_NOT_CONFIGURED"
    st = c.get(f"{API}/status", headers=P).json()
    assert st["features"]["train_solve"] == {"enabled": False, "missing": ["hpc.gateway"]}
    # F: 회수 전에는 DOE_NOT_READY
    r = c.post(f"{API}/studies/{sid}/param-sets/from-train", headers=PW, json={"doe_id": doe_id})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "DOE_NOT_READY"
    src = Path(lc.settings.storage.allowed_import_roots[0]) / "manual"
    _write_results(ai, "ri1", doe_id, ["run__00001", "RUN__00002"], base=src / "batch")
    (src / "batch" / "run__00099").mkdir()
    (src / "other").mkdir()
    insp = c.post(f"{API}/studies/{sid}/paths/inspect", headers=PW, json={"purpose": "RESULT_FOLDER", "path": str(src), "doe_id": doe_id}).json()
    assert insp["ok"] and insp["summary"]["matched_runs"] == 2
    j = submit(c, sid, "TD_RESULT_IMPORT", {"doe_id": doe_id, "source_path": str(src)})
    assert j["lane"] == "LIGHT"
    assert w.run_once_light() == "SUCCEEDED", job(c, j["id"])
    res = job(c, j["id"])["result"]
    assert res["matched"] == 2 and res["copied_files"] == 6 and res["missing_runs"] == ["run__00003"]
    assert "batch/run__00099" in res["unmatched_dirs"] and "other" in res["unmatched_dirs"]
    R = ai / "ri1" / "01_train" / "results" / doe_id / "run__00002"
    assert sorted(os.listdir(R)) == ["drop_0000.out", "drop_A001.h3d", "drop_T01"]
    doe = c.get(f"{API}/train-does/{doe_id}", headers=P).json()
    assert doe["collected_count"] == 2
    # 매칭 0개
    empty = Path(lc.settings.storage.allowed_import_roots[0]) / "empty" / "x"
    empty.mkdir(parents=True)
    j = submit(c, sid, "TD_RESULT_IMPORT", {"doe_id": doe_id, "source_path": str(empty.parent)})
    assert w.run_once_light() == "FAILED"
    jd = job(c, j["id"])
    assert jd["failure_code"] == "INPUT_INVALID" and "x" in jd["failure_message"]
    # 중복 run 폴더 → 그 run 제외
    dup = Path(lc.settings.storage.allowed_import_roots[0]) / "dup"
    _write_results(ai, "ri1", doe_id, ["run__00001"], base=dup / "a")
    _write_results(ai, "ri1", doe_id, ["run__00001", "run__00003"], base=dup / "b")
    j = submit(c, sid, "TD_RESULT_IMPORT", {"doe_id": doe_id, "source_path": str(dup)})
    assert w.run_once_light() == "SUCCEEDED"
    jd = job(c, j["id"])
    assert jd["result"]["matched"] == 1 and any("run__00001" in x["message"] for x in jd["warnings"])
    # F: 파라미터 세트 생성(정의·샘플·cad·tpl·assem) → 1차 검증기 통과, origin
    r = c.post(f"{API}/studies/{sid}/param-sets/from-train", headers=PW, json={"doe_id": doe_id, "unit_system": "mm-ton-ms"})
    assert r.status_code == 201, r.text
    ps = r.json()
    assert ps["origin"] == "TRAIN_DOE" and ps["train_doe_id"] == doe_id and ps["is_current"]
    assert ps["sample_count"] == 3 and ps["starter_name"] == "drop_0000.rad" and ps["unit_system"] == "mm-ton-ms"
    assert ps["source_path"] == f"① DOE {doe_id[:8]}" and [p["name"] for p in ps["parameters"]] == ["THK_1", "RIB_H"]
    S = ai / "ri1" / "04_params" / ps["id"]
    assert (S / "cad" / "cushion_parametric.prt").is_file() and (S / "simlab_parametered_mesh.tpl").is_file()
    assert (S / "radioss_assem" / "drop_0000.rad").is_file() and (S / "original" / "samples.csv").is_file()
    # V3-S6-6(phase3 §11.4): from-train도 RENUM csv 복사, eps_mesh는 무시
    assert sorted(os.listdir(S / "radioss_assem")) == ["RENUM_INIT.csv", "drop_0000.rad", "drop_0001.rad", "mat.inc"]
    assert list((ai / "ri1" / "logs" / "_paramset_tmp").iterdir())  # 임시 조립 폴더(삭제 호출 없음)
    smp = c.get(f"{API}/param-sets/{ps['id']}/samples", headers=P).json()
    assert [r_["run_key"] for r_ in smp["rows"]] == ["run__00001", "run__00002", "run__00003"]
    r = c.post(f"{API}/studies/{sid}/param-sets/from-train", headers=PW, json={"doe_id": doe_id, "runs": "all"})
    assert r.status_code == 201
    # 1차 폴더 등록 경로 회귀
    lst = c.get(f"{API}/studies/{sid}/param-sets", headers=P).json()
    assert len(lst) == 2 and sum(1 for x in lst if x["is_current"]) == 1


def test_samples_missing_blocks_from_train(p2_env):
    c, mk, ai, _lc, _d = p2_env
    w = mk()
    sid, doe_id = _ready_doe(c, w, ai, "sm1")
    with w.engine.begin() as conn:
        conn.execute(text("update train_does set sample_status='MISSING', samples_rel=null where id=:d"), {"d": doe_id})
    r = c.post(f"{API}/studies/{sid}/param-sets/from-train", headers=PW, json={"doe_id": doe_id})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SAMPLES_MISSING"


def test_resp_extract(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch):
    """V2-TD-8: 템플릿 null 409, 설정 시 팬아웃·run_responses.csv·F의 resp: 열."""
    gen = _p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, {})
    c, mk, ai, lc, d = next(gen)
    try:
        w = mk()
        sid, doe_id = _ready_doe(c, w, ai, "rx1", num_runs=2)
        r = submit(c, sid, "TD_RESP_EXTRACT", {"doe_id": doe_id, "responses": [{"name": "MaxStress", "unit": "MPa"}]}, expect=409)
        assert r["detail"]["code"] == "TEMPLATE_NOT_CONFIGURED"
    finally:
        for _ in gen:
            pass
    tmp2 = tmp_path / "second"
    tmp2.mkdir()
    gen = _p2_env(tmp2, fake_tools, engine, fake_dashboard, monkeypatch,
                  {"commands": {"response_extract": ["{hw}", "--responses", "{responses_json}", "--input", "{pred_h3d}", "--out", "{out_csv}"]}})
    c, mk, ai, lc, d = next(gen)
    try:
        w = mk()
        sid, doe_id = _ready_doe(c, w, ai, "rx2", num_runs=2)
        src = Path(lc.settings.storage.allowed_import_roots[0]) / "m"
        _write_results(ai, "rx2", doe_id, ["run__00001", "run__00002"], base=src)
        j = submit(c, sid, "TD_RESULT_IMPORT", {"doe_id": doe_id, "source_path": str(src)})
        assert w.run_once_light() == "SUCCEEDED"
        r = submit(c, sid, "TD_RESP_EXTRACT", {"doe_id": doe_id, "responses": [{"name": "MaxStress", "unit": "MPa"}, {"name": "Disp"}]})
        assert w.run_once_slot() == "SUCCEEDED", job(c, r["id"])
        D = ai / "rx2" / "01_train" / "doe" / doe_id
        rows = list(csv.reader((D / "run_responses.csv").open()))
        assert rows == [["run_key", "MaxStress", "Disp"], ["run__00001", "110.0", "111.0"], ["run__00002", "110.0", "111.0"]]
        jd = job(c, r["id"])
        step = next(s for s in jd["steps"] if s["step_key"] == "RESPONSE_EXTRACT_RUNS")
        assert step["state"] == "SUCCEEDED"
        cmds = (ai / "rx2" / "logs" / r["id"] / "step_02_RESPONSE_EXTRACT_RUNS.commands.jsonl").read_text().splitlines()
        assert len(cmds) == 2 and json.loads(cmds[0])["target_id"] == "run__00001"
        ps = c.post(f"{API}/studies/{sid}/param-sets/from-train", headers=PW, json={"doe_id": doe_id}).json()
        assert ps["sample_has_measured"] is True and [x["name"] for x in ps["responses"]] == ["MaxStress", "Disp"]
        assert job(c, j["id"])["state"] == "SUCCEEDED"
    finally:
        for _ in gen:
            pass
