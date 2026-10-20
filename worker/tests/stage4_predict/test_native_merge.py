"""phase3 S16·S17 × native 세트 병합 위험 보완(geometry-engine.md §7.3.5·§7.3.7·§11.1): native 예측의 조립 FEM 검증(reuse·rebuild —
모핑 include 재사용, FV_MESH 생략), native 일괄 예측의 성능 다시 추출(PB_RESP_EXTRACT), 내장 다목적 최적화(native 세트 흐름·
다중 baseline 미확정 세트는 409). 가짜 paicad·hw·edspy·PBS."""

from __future__ import annotations

import json
import os

import pytest
from helpers_native import native_set
from physicsai_test_support import API, H, make_assem_files, pbs_command_cfg, read_record

from .fv_support import RESULT_FILES, RESPS, attempt_dir, create, finish_hpc, resources, run_until_hpc
from .test_native_multi import B2_TOPO, _add

PW = H("tok-power", write=True)
P = H("tok-power")
NEW_CMD = ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"]
T01_CMD = ["{hw}", "-clientconfig", "hwplot.dat", "-b", "-c", "-tcl", "{curate_tcl}", "-config", "{config_json}"]
GEO = {"A_THK_1": 10.2, "B_RIB_H_1": 20.0, "C_HOLE_R_1": 4.0}


@pytest.fixture(autouse=True)
def _fast_collect(monkeypatch, pbs_state):
    from physicsai_worker.steps import _collect

    monkeypatch.setattr(_collect, "COLLECT_STABLE_INTERVAL_S", 0.02)


def _env(native_env, fake_tools, tmp_path):
    env = native_env(hpc=pbs_command_cfg(fake_tools, str(tmp_path / "ai_root")),
                     commands={"response_extract": NEW_CMD, "t01_curve_export": T01_CMD}, resources=resources(tmp_path))
    ps = native_set(env)
    env.set_responses(ps["id"], RESPS)
    return env, ps


def _predict(env, values):
    j = env.submit("PREDICT", {"values": values, "value_source": "manual"})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    return j["id"]


def test_s16_fem_verify_native_reuse_keeps_shell_and_rebuild_uses_morphed_include(native_env, fake_tools, fake_record, tmp_path):
    env, ps = _env(native_env, fake_tools, tmp_path)
    r = env.c.post(f"{API}/param-sets/{ps['id']}/props/scan", headers=PW)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(r.json()["job_id"])
    assert env.c.put(f"{API}/param-sets/{ps['id']}/props", headers=PW, json={"selected": [{"name": "BRACKET_SHELL_T"}]}).status_code == 200
    pj = _predict(env, {**GEO, "BRACKET_SHELL_T": 1.22})
    d = create(env, {"source": {"kind": "predict_job", "job_id": pj}, "fem": {"component": "vonMises"}})
    assert (d["input_mode"], d["assembly"]["kind"]) == ("reuse", "PREDICT_INPUT")
    d = run_until_hpc(env, d["id"])
    A = attempt_dir(env, d)
    assert "#FAKE_PROP 1 1.22" in (A / "input" / "material.inc").read_text()            # 두께 적용된 예측 입력 그대로
    d = finish_hpc(env, d["id"], RESULT_FILES)
    assert d["status"] == "DONE", d
    # rebuild(직접 지정 조립 원본): 모핑 include = 메시 원천, HyperMesh 변환 없이 FV_MESH 생략. 두께 미적용 경고
    custom = env.imports / "fem_assem"
    make_assem_files(custom)
    d2 = create(env, {"source": {"kind": "predict_job", "job_id": pj}, "assembly": {"kind": "custom", "path": str(custom)},
                      "fem": {"component": "vonMises"}})
    assert d2["input_mode"] == "rebuild" and "SHELL_NOT_APPLIED" in [w["code"] for w in d2["warnings"]], d2
    d2 = run_until_hpc(env, d2["id"])
    A2 = attempt_dir(env, d2)
    jid = d2["job"]["id"]
    assert env.steps(jid)["FV_MESH"]["state"] == "SKIPPED" and env.steps(jid)["FV_MESH"]["progress_label"] == "native 모핑 include 재사용"
    inc = env.lc.settings.predict.mesh_include_name
    assert (A2 / "input" / inc).read_bytes() == (env.predict_dir(pj) / "geom" / inc).read_bytes()
    assert not [x for x in read_record(fake_record) if x["tool"] == "hw" and "-tcl" in x["argv"] and "mesh" in " ".join(x["argv"]).lower()
                and str(A2) in x.get("cwd", "")]
    assert finish_hpc(env, d2["id"], RESULT_FILES)["status"] == "DONE"


def test_s17_pb_resp_extract_on_native_batch(native_env, fake_tools, tmp_path):
    env, ps = _env(native_env, fake_tools, tmp_path)
    pj = env.submit("PREDICT_BATCH", {"param_set_id": ps["id"], "multi_execution": 2, "source": {
        "kind": "table", "text": "A_THK_1,B_RIB_H_1,C_HOLE_R_1\n10.0,20.0,4.0\n10.3,20.5,4.1\n"}})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(pj["id"])
    for _ in range(2):
        assert env.w.run_once_slot() == "SUCCEEDED"
    bid = pj["params"]["batch_id"]
    b = env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()
    assert b["status"] == "DONE" and all(x["responses"]["MaxStress"] == 100.0 for x in b["rows"]), b
    r = env.c.post(f"{API}/predict-batches/{bid}/extract-responses", headers=PW)
    assert r.status_code == 201, r.text
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(r.json()["id"])
    assert env.job(r.json()["id"])["result"]["summary"] == {"targets": 2, "extracted": 2, "failed": 0}


def test_multiobjective_surrogate_on_native_set_and_multi_baseline_blocked(native_env, fake_tools, tmp_path, monkeypatch):
    env, ps = _env(native_env, fake_tools, tmp_path)
    perfs = [*RESPS, {"name": "CornerStress", "unit": "MPa", "spec": {**RESPS[0]["spec"], "datatype": "Stress", "component": "vonMises"}}]
    env.set_responses(ps["id"], perfs)
    body = {"param_set_id": ps["id"], "explore": {"kind": "new", "count": 5, "seed": 1},
            "objectives": [{"metric": "perf:MaxStress", "sense": "min"}, {"metric": "perf:MinDisp", "sense": "max"}],
            "weights": [50, 50], "iterations": 1, "candidates": 1, "tol_rel": 1e-9, "seed": 1, "multi_execution": 2}
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json=body)
    assert r.status_code == 200 and r.json()["mode"] == "multi" and r.json()["problems"] == [], r.text
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json=body)
    assert r.status_code == 201, r.text
    opt = r.json()
    for _ in range(60):
        q = env.sql("select id from jobs where state='QUEUED' and lane='SLOT' order by queue_seq limit 1")
        if not q:
            break
        env.w.run_once_slot()
    batches = env.sql("select id from predict_batches where study_id=:s", s=env.sid)
    assert batches
    pb = env.batch(batches[0][0])
    assert all(x["gen_state"] == "DONE" for x in pb["runs"]), pb["runs"]           # native 생성(paicad)으로 탐색 배치 완료
    R = env.sroot / pb["dir_rel"] / pb["runs"][0]["run_key"]
    v = json.loads((R / "m_1" / "values.json").read_text())
    assert v["engine"] == "native" and set(v["values"]) == set(GEO)
    d = env.c.get(f"{API}/surrogate-opts/{opt['id']}", headers=P).json()
    assert d["status"] == "DONE" and d["mode"] == "multi", (d["status"], d.get("progress_text"))
    assert d["iterations"] and d["iterations"][0]["kind"] == "EXPLORE"
    # 다중 baseline 세트: 매칭표 미확정이면 409 PARAM_MAP_UNCONFIRMED(opt-native §7 — MULTI_BASELINE_UNSUPPORTED는 조건부 해제)
    _add(env, ps["id"], "B2", B2_TOPO, monkeypatch)
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json=body)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PARAM_MAP_UNCONFIRMED", r.text
    assert os.path.isfile(env.sroot / "04_params" / ps["id"] / "param_map.json")
