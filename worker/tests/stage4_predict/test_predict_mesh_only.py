"""④ mesh_only 템플릿 예측(phase3 §14.4, V3-S9-3): GEOM_UPDATE 그대로 → MESH SKIPPED → RAD_ASSEMBLE 복사만 → edspy 입력 = SimLab 메시."""

from __future__ import annotations

import io
import os
import zipfile

from physicsai_test_support import API, H, pbs_command_cfg, read_record

PW = H("tok-power", write=True)
P = H("tok-power")
VALUES = {"values": {"THK_1": 3.0, "N_RIB": 4}, "value_source": "manual"}
MESH = "EPS_mesh_0000.rad"


def _submit(env, **extra):
    j = env.submit("PREDICT", {**VALUES, **extra})
    return j["id"], env.w.run_once_slot()


def test_v3_s9_3_mesh_only_golden(predict_env, fake_record):
    env = predict_env()                                 # commands.mesh 설정 있음 — 그래도 MESH SKIPPED여야 함
    ps = env.param_set()
    env.to_mesh_only(ps["id"])
    jid, state = _submit(env)
    jd = env.job(jid)
    assert state == "SUCCEEDED", jd
    Pd = env.predict_dir(jid)
    rec = read_record(fake_record)
    sim = [r for r in rec if r["tool"] == "simlab"][-1]
    assert sim["argv"][1:] == ["-auto", str(Pd / "geom" / "simlab_parametered_mesh.py"), "-nographics"]
    assert sim["cwd"] == str(Pd / "geom")
    assert not [r for r in rec if r["tool"] == "hw" and "hwfepre.dat" in r["argv"]]     # HyperMesh 미실행
    steps = env.steps(jid)
    assert steps["MESH"]["state"] == "SKIPPED" and steps["MESH"]["progress_label"] == "쿠션 입력 — 메시 연결 불필요"
    assert steps["RAD_ASSEMBLE"]["state"] == "SUCCEEDED"
    assert sorted(os.listdir(Pd / "INPUT")) == [MESH]
    assert (Pd / "INPUT" / MESH).read_bytes() == (Pd / "geom" / MESH).read_bytes()
    ed = [r for r in rec if r["tool"] == "edspy"][-1]["argv"]
    assert ed[ed.index("--input-file") + 1] == str(Pd / "INPUT" / MESH)
    assert ed[ed.index("--predict-write") + 1] == str(Pd / "RESULT" / "EPS_mesh_0000_pred.h3d")
    assert [r for r in rec if r["tool"] == "edspy"][-1]["cwd"] == str(Pd / "INPUT")
    assert jd["result"]["starter"] == MESH and jd["result"]["template_kind"] == "mesh_only"
    assert not [w for w in jd["warnings"] if w["code"] in ("RENUM_CSV_MISSING", "MESH_INCLUDE_NOT_IN_ASSEM")]


def test_v3_s9_3_template_kind_param_wins(predict_env):
    """params.template_kind(서버가 확정 기록, B8)가 세트 input_kind보다 우선 — prepared의 input_kind(file|dir)와 별개."""
    env = predict_env()
    ps = env.param_set()                                # 세트는 assembly(조립 폴더 있음)
    j = env.submit("PREDICT", VALUES)
    env.sql("update jobs set params = params || cast('{\"template_kind\": \"mesh_only\"}' as jsonb) where id=:i", i=j["id"])
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    assert env.steps(j["id"])["MESH"]["state"] == "SKIPPED"
    assert sorted(os.listdir(env.predict_dir(j["id"]) / "INPUT")) == [MESH]
    # 반대로 template_kind=assembly면 세트가 mesh_only라도 조립 체인(여기서는 조립 폴더가 없어 실패)
    env.to_mesh_only(ps["id"])
    j = env.submit("PREDICT", VALUES)
    env.sql("update jobs set params = params || cast('{\"template_kind\": \"assembly\"}' as jsonb) where id=:i", i=j["id"])
    assert env.w.run_once_slot() == "FAILED"
    jd = env.job(j["id"])
    assert jd["failure_code"] == "INPUT_INVALID" and jd["current_step_key"] == "PR_PREP"


def test_v3_s9_3_mesh_only_missing_mesh_and_retry_zip_verify(predict_env, fake_tools, fake_record, pbs_state, monkeypatch,
                                                             tmp_path):
    from physicsai_worker.steps import _collect

    monkeypatch.setattr(_collect, "COLLECT_STABLE_INTERVAL_S", 0.05)
    env = predict_env(hpc=pbs_command_cfg(fake_tools, str(tmp_path / "ai_root")))
    ps = env.param_set()
    env.to_mesh_only(ps["id"])
    # SimLab 출력 없음 → GEOM_UPDATE OUTPUT_MISSING
    monkeypatch.setenv("FAKE_TOOL_MODE_SIMLAB", "no_output")
    jid, state = _submit(env)
    jd = env.job(jid)
    assert state == "FAILED" and jd["failure_code"] == "OUTPUT_MISSING" and jd["current_step_key"] == "GEOM_UPDATE"
    monkeypatch.delenv("FAKE_TOOL_MODE_SIMLAB")
    # EDSPY 실패 → RAD_ASSEMBLE(5단계)부터 재시도 → 성공, INPUT = 메시 1개
    monkeypatch.setenv("FAKE_TOOL_MODE_EDSPY", "fail")
    jid, state = _submit(env)
    assert state == "FAILED" and env.job(jid)["current_step_key"] == "EDSPY_PREDICT"
    monkeypatch.delenv("FAKE_TOOL_MODE_EDSPY")
    r = env.c.post(f"{API}/jobs/{jid}/retry", headers=PW, json={"from_step": 5})
    assert r.status_code in (200, 201), r.text
    nid = r.json()["id"]
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(nid)
    steps = env.steps(nid)
    assert [steps[k]["state"] for k in ("MESH", "RAD_ASSEMBLE", "EDSPY_PREDICT")] == ["SKIPPED", "SUCCEEDED", "SUCCEEDED"]
    Pd = env.predict_dir(jid)
    assert sorted(os.listdir(Pd / "INPUT")) == [MESH]
    z = env.c.get(f"{API}/jobs/{nid}/artifacts/input.zip", headers=P)
    assert z.status_code == 200 and zipfile.ZipFile(io.BytesIO(z.content)).namelist() == [MESH]
    # PBS 검증: P/INPUT 기준 starter = 메시
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "PREDICT_VERIFY", "params": {"predict_job_id": nid}})
    assert r.status_code == 201, r.text
    assert env.w.run_once_slot() == "WAITING_HPC", env.job(r.json()["id"])
    sub = [x for x in read_record(fake_record) if x["tool"] == "qsub"][-1]["argv"]
    assert f"/verify/1/input/{MESH}," in sub[sub.index("-v") + 1]
