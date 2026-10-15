"""④ parametric 예측 원본 일치(phase3 §11.4, V3-S6-1~5·14): SimLab 출력 판정, HyperMesh m_2 include 변환, RAD_ASSEMBLE 규칙, 가짜 도구 형식."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from physicsai_test_support import API, H, MESH_INC, read_record

VALUES = {"values": {"THK_1": 3.0, "N_RIB": 4}, "value_source": "manual"}


def _run(env, **params):
    j = env.submit("PREDICT", {**VALUES, **params})
    state = env.w.run_once_slot()
    return j["id"], state, env.job(j["id"])


def test_v3_s6_1_golden_argv_and_cwd(predict_env, fake_record):
    env = predict_env()
    ps = env.param_set()
    jid, state, jd = _run(env)
    assert state == "SUCCEEDED", jd
    s = env.lc.settings
    Pd, S = env.predict_dir(jid), env.sroot / "04_params" / ps["id"]
    rec = read_record(fake_record)
    sim = [r for r in rec if r["tool"] == "simlab"][-1]
    assert sim["argv"][1:] == ["-auto", str(Pd / "geom" / "simlab_parametered_mesh.py"), "-nographics"]
    assert sim["cwd"] == str(Pd / "geom")
    hm = [r for r in rec if r["tool"] == "hw" and "hwfepre.dat" in r["argv"]][-1]
    assert hm["argv"][1:] == ["-clientconfig", "hwfepre.dat", "-b", "-tcl", s.resources.hypermesh_include_tcl,
                              str(Pd / "geom" / "EPS_mesh_0000.rad"), str(Pd / "geom" / MESH_INC),
                              str(S / "radioss_assem" / "RENUM_INIT.csv")]
    assert hm["cwd"] == str(Pd / "geom")
    adm = env.c.get(f"{API}/jobs/{jid}?include=commands", headers=H("tok-admin")).json()
    cmds = {st["step_key"]: st["command"] for st in adm["steps"]}
    assert cmds["GEOM_UPDATE"]["argv"][0] == s.altair.simlab_path and cmds["MESH"]["argv"][0] == s.altair.hw_exe_path
    assert cmds["GEOM_UPDATE"]["cwd"] == cmds["MESH"]["cwd"] == str(Pd / "geom")
    assert jd["warnings"] == []


def test_v3_s6_2_input_has_new_include_and_no_eps_mesh(predict_env):
    env = predict_env()
    ps = env.param_set()
    S = env.sroot / "04_params" / ps["id"] / "radioss_assem"
    assert not (S / "EPS_mesh_0000.rad").exists() and (S / MESH_INC).is_file()     # 등록 사본에서 eps_mesh 무시
    for n in ("EPS_mesh_0000.rad", "Eps_Mesh_extra.inc", "eps_mesh_1.inc"):          # 예전에 등록된 세트 흉내(대소문자 변형)
        (S / n).write_text("old\n")
    jid, state, jd = _run(env)
    assert state == "SUCCEEDED", jd
    Pd = env.predict_dir(jid)
    inputs = sorted(os.listdir(Pd / "INPUT"))
    assert not [n for n in inputs if n.lower().startswith("eps_mesh")]
    assert inputs == sorted([MESH_INC, "material.inc", "model0_0000.rad", "model_0001.rad"])
    assert (Pd / "INPUT" / MESH_INC).read_bytes() == (Pd / "geom" / MESH_INC).read_bytes() != (S / MESH_INC).read_bytes()
    assert jd["result"]["starter"] == "model0_0000.rad"
    rec = env.steps(jid)
    assert rec["MESH"]["state"] == rec["RAD_ASSEMBLE"]["state"] == "SUCCEEDED"


def test_v3_s6_3_missing_include_fails_and_simlab_direct_include(predict_env, monkeypatch):
    env = predict_env(commands={"mesh": None})
    env.param_set()
    jid, state, jd = _run(env)
    assert state == "FAILED" and jd["failure_code"] == "OUTPUT_MISSING", jd
    assert jd["current_step_key"] == "RAD_ASSEMBLE" and "새 메시 include" in jd["failure_message"]
    assert env.steps(jid)["MESH"]["state"] == "SKIPPED"
    # MESH null + SimLab이 include를 직접 작성하는 변형 → 성공
    monkeypatch.setenv("FAKE_TOOL_MODE_SIMLAB", "with_include")
    jid, state, jd = _run(env)
    assert state == "SUCCEEDED", jd
    assert env.steps(jid)["MESH"]["state"] == "SKIPPED"
    assert (env.predict_dir(jid) / "INPUT" / MESH_INC).read_text() == "/NODE\n3000001 0 0 0\n"


def test_v3_s6_4_output_file_decides_success(predict_env, monkeypatch):
    env = predict_env()
    env.param_set()
    monkeypatch.setenv("FAKE_TOOL_MODE_SIMLAB", "nonzero_with_output")
    jid, state, jd = _run(env)
    assert state == "SUCCEEDED", jd
    assert [w["code"] for w in jd["warnings"]] == ["EXIT_NONZERO_IGNORED"]
    assert env.steps(jid)["GEOM_UPDATE"]["exit_code"] == 3
    monkeypatch.setenv("FAKE_TOOL_MODE_SIMLAB", "no_output")                       # rc 0 + 출력 없음
    jid, state, jd = _run(env)
    assert state == "FAILED" and jd["failure_code"] == "OUTPUT_MISSING" and jd["current_step_key"] == "GEOM_UPDATE"
    monkeypatch.setenv("FAKE_TOOL_MODE_SIMLAB", "fail")                            # rc≠0 + 출력 없음
    jid, state, jd = _run(env)
    assert state == "FAILED" and jd["failure_code"] == "EXIT_NONZERO" and jd["current_step_key"] == "GEOM_UPDATE"
    monkeypatch.delenv("FAKE_TOOL_MODE_SIMLAB")
    monkeypatch.setenv("FAKE_TOOL_MODE_HM", "nonzero_with_output")
    jid, state, jd = _run(env)
    assert state == "SUCCEEDED" and [w["code"] for w in jd["warnings"]] == ["EXIT_NONZERO_IGNORED"], jd
    monkeypatch.setenv("FAKE_TOOL_MODE_HM", "no_output")
    jid, state, jd = _run(env)
    assert state == "FAILED" and jd["failure_code"] == "OUTPUT_MISSING" and jd["current_step_key"] == "MESH"
    monkeypatch.setenv("FAKE_TOOL_MODE_HM", "fail")
    jid, state, jd = _run(env)
    assert state == "FAILED" and jd["failure_code"] == "EXIT_NONZERO" and jd["current_step_key"] == "MESH"


def test_v3_s6_5_mesh_warnings(predict_env, monkeypatch):
    env = predict_env()
    env.param_set(renum_csv=False, include_base=False)
    monkeypatch.setenv("FAKE_TOOL_MODE_HM", "no_marker")
    jid, state, jd = _run(env)
    assert state == "SUCCEEDED", jd
    assert sorted(w["code"] for w in jd["warnings"]) == ["MESH_INCLUDE_NOT_IN_ASSEM", "MESH_LOG_INCOMPLETE", "RENUM_CSV_MISSING"]
    log = env.c.get(f"{API}/jobs/{jid}/steps/4/log", headers=H("tok-power")).json()["text"]
    assert "log_batch.txt" in log and "renum csv missing" in log
    # 표식이 있으면 MESH_LOG_INCOMPLETE 없음, 재실행 시 이전 log_batch.txt는 _backup으로(표식 판정이 새 로그 기준)
    monkeypatch.delenv("FAKE_TOOL_MODE_HM")
    env.param_set()
    jid, state, jd = _run(env)
    assert state == "SUCCEEDED" and jd["warnings"] == [], jd


def test_v3_s6_14_fake_tools_real_format(fake_tools, tmp_path):
    simlab, hw = fake_tools["fake_simlab"], fake_tools["fake_hw"]
    env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_")}
    work = tmp_path / "geom"
    work.mkdir()
    script = work / "simlab_parametered_mesh.py"
    script.write_text('dir_file_prt = r"./part.prt"\ndir_file_export = "MY_mesh_0000.rad"\n', encoding="utf-8")
    r = subprocess.run([simlab, "-auto", str(script), "-nographics"], cwd=work, env=env, capture_output=True, text=True)
    assert r.returncode == 2 and not (work / "MY_mesh_0000.rad").exists()              # 상대 CAD 없음
    (work / "part.prt").write_text("cad")
    r = subprocess.run([simlab, "-auto", str(script), "-nographics"], cwd=work, env=env, capture_output=True, text=True)
    assert r.returncode == 0 and (work / "MY_mesh_0000.rad").stat().st_size > 0
    script.write_text('dir_file_prt = r"./part.prt"\n', encoding="utf-8")                # 기본 이름
    r = subprocess.run([simlab, "-auto", str(script), "-nographics"], cwd=work, env={**env, "FAKE_TOOL_MODE_SIMLAB": "nonzero_with_output"},
                       capture_output=True, text=True)
    assert r.returncode == 3 and (work / "EPS_mesh_0000.rad").is_file()
    tcl = tmp_path / "inc.tcl"
    tcl.write_text("#")
    argv = [hw, "-clientconfig", "hwfepre.dat", "-b", "-tcl", str(tcl), str(work / "nope.rad"), str(work / MESH_INC), str(work / "R.csv")]
    assert subprocess.run(argv, cwd=work, env=env, capture_output=True).returncode == 2              # 입력 메시 없음
    argv[6] = str(work / "EPS_mesh_0000.rad")
    assert subprocess.run(argv, cwd=work, env=env, capture_output=True).returncode == 0
    assert (work / MESH_INC).is_file() and "COMPLETE HM BATCHRUN" in (work / "log_batch.txt").read_text()
    for mode, rc, inc, marker in (("fail", 1, False, False), ("no_output", 0, False, True), ("no_marker", 0, True, False)):
        for f in (work / MESH_INC, work / "log_batch.txt"):
            f.unlink(missing_ok=True)
        assert subprocess.run(argv, cwd=work, env={**env, "FAKE_TOOL_MODE_HM": mode}, capture_output=True).returncode == rc, mode
        assert (work / MESH_INC).exists() is inc, mode
        log = work / "log_batch.txt"
        assert (log.exists() and "COMPLETE HM BATCHRUN" in log.read_text()) is marker, mode
    # 미리보기 JSON = 원본 TCL 형식(phase3 §11.1)
    h3d, out = work / "x_pred.h3d", work / "H3D_PREVIEW.json"
    h3d.write_text("h3d")
    pv = [hw, "-clientconfig", "hwpost.dat", "-b", "-tcl", str(tcl), "-input", str(h3d), "-output", str(out)]
    assert subprocess.run(pv, cwd=work, env=env, capture_output=True).returncode == 0
    data = json.loads(out.read_text())
    assert set(data) == {"h3d", "num_time_step", "subcases"} and set(data["subcases"][0]) == {"id", "label", "datatypes"}
    assert set(data["subcases"][0]["datatypes"][0]) == {"name", "format", "binding", "components", "layers"}
    assert Path(data["h3d"]).name == "x_pred.h3d"
