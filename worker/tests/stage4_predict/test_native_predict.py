"""④ native 단건 예측·엔진 분리 E2E(geometry-engine.md §7.3.5, §7.7, V-GE-7·12): paicad update→morph→check, 준비본 STALE·엔진 불일치·사용 불가 차단."""

from __future__ import annotations

import json

import pytest
from helpers_native import native_set
from physicsai_test_support import API, H, MESH_INC, read_record

PW = H("tok-power", write=True)
P = H("tok-power")
VALUES = {"values": {"A_THK_1": 10.2, "B_RIB_H_1": 20.0, "C_HOLE_R_1": 4.0}, "value_source": "manual"}


def test_native_predict_chain_and_layout(native_env, fake_record):
    env = native_env()
    ps = native_set(env)
    j = env.submit("PREDICT", VALUES)
    jd0 = env.job(j["id"])
    assert jd0["params"]["engine"] == "native" and [w["code"] for w in jd0["warnings"]] == ["ENGINE_UNKNOWN"]
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    Pd = env.predict_dir(j["id"])
    for rel in ("geom/values.json", "geom/options.json", "geom/update/update.json", "geom/morph/morph.json",
                "geom/check/check.json", f"geom/{MESH_INC}"):
        assert (Pd / rel).is_file(), rel
    v = json.loads((Pd / "geom" / "values.json").read_text())
    assert v["engine"] == "native" and v["values"]["A_THK_1"] == 10.2 and v["source"]["kind"] == "predict"
    cmds = [r["argv"][1] for r in read_record(fake_record) if r["tool"] == "paicad"]
    assert cmds[-4:] == ["version", "update", "morph", "check"]
    st = env.steps(j["id"])
    assert st["TPL_RENDER"]["state"] == "SUCCEEDED" and st["MESH"]["state"] == "SUCCEEDED"
    assert (Pd / "INPUT" / MESH_INC).is_file()
    assert env.job(j["id"])["result"]["template_kind"] == "assembly"
    # 세트 행·사본은 읽기 전용으로 쓰인다(준비본 불변)
    assert env.c.get(f"{API}/param-sets/{ps['id']}", headers=P).json()["native"]["prep_status"] == "READY"


def test_native_predict_fail_code_is_korean(native_env, monkeypatch):
    env = native_env()
    native_set(env)
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "check:GEOM_QUALITY")
    j = env.submit("PREDICT", VALUES)
    assert env.w.run_once_slot() == "FAILED"
    jd = env.job(j["id"])
    assert jd["failure_code"] == "GEOM_QUALITY" and "품질 미달" in jd["failure_message"] and jd["current_step_key"] == "MESH"


def test_native_predict_blocked_when_stale_or_unavailable(native_env):
    env = native_env()
    ps = native_set(env)
    (env.sroot / "04_params" / ps["id"] / "radioss_assem" / MESH_INC).write_text("/NODE\n3000001 1 1 1\n")  # 입력 변경
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "PREDICT", "params": VALUES})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "GEOM_PREP_STALE", r.text
    env2 = native_env(geometry={"paicad_path": "/nonexistent/paicad"}, folder="p2")
    # 사용 불가 환경에서는 세트가 없으므로 altair 세트로는 막히지 않고, native 세트(DB 직접 표시)는 409
    alt = env2.param_set()
    env2.sql("update param_sets set engine='native' where id=:i", i=alt["id"])
    r = env2.c.post(f"{API}/studies/{env2.sid}/jobs", headers=PW, json={"job_type": "PREDICT", "params": VALUES})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "GEOM_NATIVE_UNAVAILABLE", r.text


@pytest.mark.parametrize("model_engine,set_engine,ok", [("altair", "native", False), ("native", "native", True), ("native", "altair", False)])
def test_engine_mismatch_blocks_predict(native_env, model_engine, set_engine, ok):
    env = native_env()
    ps = native_set(env) if set_engine == "native" else env.param_set()
    env.sql("update models set engine=:e where id=:i", e=model_engine, i=env.model_id)
    vals = VALUES if set_engine == "native" else {"values": {"THK_1": 3.0, "N_RIB": 4}, "value_source": "manual"}
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "PREDICT", "params": {**vals, "param_set_id": ps["id"]}})
    if ok:
        assert r.status_code == 201, r.text
        assert [w["code"] for w in r.json()["warnings"]] == []
    else:
        assert r.status_code == 409 and r.json()["detail"]["code"] == "ENGINE_MISMATCH", r.text


def test_native_original_optimize_and_tpl_blocked(native_env, monkeypatch):
    env = native_env()
    ps = native_set(env)
    # 원본 최적화는 기능 확인(altair 템플릿)이 먼저라, 그 확인을 건너뛰고 엔진 차단만 본다
    monkeypatch.setattr("physicsai_api.services.job_params.check_feature", lambda *a, **k: None)
    body = {"param_set_id": ps["id"], "responses": [{"name": "r", "goal": "MINIMIZE"}]}
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "OPTIMIZE", "params": body})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ENGINE_NATIVE_UNSUPPORTED", r.text
    r = env.c.post(f"{API}/studies/{env.sid}/train/tpl", headers=PW, json={"version": 0})
    assert r.status_code in (409, 404), r.text
