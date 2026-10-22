"""④ 입력 종류(조립·쿠션) 워커 체인(input-kind.md §4.1·§4.2, V-IK-2·3·4·5(워커 부분), GE-C19).

실행 종류는 내부 값 `template_kind`(assembly|mesh_only)로 분기한다 — API가 `input`을 이 값으로 바꿔 기록하는 부분은 Backend #1 소관이라
여기서는 작업 params·배치 행에 같은 값을 직접 기록한다. Altair·Native × 조립·쿠션의 단계 상태, P/INPUT 파일·크기, 배치 산출 폴더 구조.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from helpers_native import native_set
from physicsai_test_support import API, MESH_INC, H, read_record

PW = H("tok-power", write=True)
P = H("tok-power")
MESH = "EPS_mesh_0000.rad"
ALT = {"values": {"THK_1": 3.0, "N_RIB": 4}, "value_source": "manual"}
NAT = {"values": {"A_THK_1": 10.2, "B_RIB_H_1": 20.0, "C_HOLE_R_1": 4.0}, "value_source": "manual"}
RA = {"rad_assemble": ["{hw}", "-h3d", "{starter}", "-result", "{work_dir}/rad_assemble_ran.json"]}  # 실행 여부 표지(P/rad_assemble_ran.json)
ROWS3 = "THK_1\tN_RIB\n2.5\t3\n3.0\t4\n3.5\t5\n"
NROWS = "A_THK_1,B_RIB_H_1,C_HOLE_R_1\n9.6,20,3.9\n10.0,20,4.0\n10.4,20,4.1\n"


def _cushion(env, jid):
    """서버가 `input: cushion`을 `template_kind: mesh_only`로 확정 기록하는 것과 같은 값을 작업 params에 넣는다."""
    env.sql("update jobs set params = params || cast('{\"template_kind\": \"mesh_only\"}' as jsonb) where id=:i", i=jid)


def _run(env, params, *, cushion):
    j = env.submit("PREDICT", params)
    if cushion:
        _cushion(env, j["id"])
    state = env.w.run_once_slot()
    return j["id"], state


def _summary(env, jid):
    """단계 상태·P/INPUT 파일(이름→크기)·예측 입력 요약·edspy 입력 인자 — 같은 실행 종류끼리 비교하는 값."""
    jd = env.job(jid)
    Pd = env.predict_dir(jid)
    inp = {n: (Pd / "INPUT" / n).stat().st_size for n in sorted(os.listdir(Pd / "INPUT"))}
    return {"steps": {k: v["state"] for k, v in env.steps(jid).items()}, "input": inp, "predict_input": jd["result"]["predict_input"],
            "starter": jd["result"]["starter"], "template_kind": jd["result"]["template_kind"], "input_kind": jd["result"]["input"],
            "pred": sorted(os.listdir(Pd / "RESULT"))}


def _edspy_input(rec, jid_dir: Path):
    ed = [r for r in rec if r["tool"] == "edspy"][-1]["argv"]
    return Path(ed[ed.index("--input-file") + 1])


# ---- Altair 단건 --------------------------------------------------------------------------------------------------


def test_ik_altair_single_cushion_same_as_mesh_only_template_and_smaller_than_assembly(predict_env, fake_record):
    env = predict_env(commands=RA)
    ps = env.param_set()                              # 조립 가능 템플릿(assembly)
    Pa = lambda jid: env.predict_dir(jid)  # noqa: E731
    # 조립 입력(현행 그대로)
    ja, st = _run(env, ALT, cushion=False)
    assert st == "SUCCEEDED", env.job(ja)
    sa = _summary(env, ja)
    assert sa["steps"]["MESH"] == "SUCCEEDED" and (Pa(ja) / "rad_assemble_ran.json").is_file()
    assert sa["starter"] == "model0_0000.rad" and sa["input_kind"] == "assembly" and MESH not in sa["input"]
    assert sa["predict_input"] == {"input": "assembly", "starter": "model0_0000.rad", "bytes": sum(sa["input"].values()), "files": 4}
    # 쿠션 입력(조립 가능 템플릿 + cushion) — 단계·산출물이 mesh_only 템플릿과 같다
    jc, st = _run(env, ALT, cushion=True)
    assert st == "SUCCEEDED", env.job(jc)
    sc = _summary(env, jc)
    steps = env.steps(jc)
    assert steps["MESH"]["state"] == "SKIPPED" and steps["MESH"]["progress_label"] == "쿠션 입력 — 메시 연결 불필요"
    assert steps["RAD_ASSEMBLE"]["state"] == "SUCCEEDED"
    assert not (Pa(jc) / "rad_assemble_ran.json").exists()                                  # commands.rad_assemble 미실행
    assert list(sc["input"]) == [MESH] and sc["starter"] == MESH and sc["template_kind"] == "mesh_only" and sc["input_kind"] == "cushion"
    assert (Pa(jc) / "INPUT" / MESH).read_bytes() == (Pa(jc) / "geom" / MESH).read_bytes()
    assert sc["predict_input"] == {"input": "cushion", "starter": MESH, "bytes": sc["input"][MESH], "files": 1}
    assert sc["predict_input"]["files"] == 1 < sa["predict_input"]["files"]          # 예측 입력 파일 수(GPU 메모리 대리 지표)
    assert not [n for n in sc["input"] if n in sa["input"] and n != MESH] and "EPS_mesh_0000_pred.h3d" in sc["pred"]
    rec = read_record(fake_record)
    assert _edspy_input(rec, Pa(jc)) == Pa(jc) / "INPUT" / MESH
    assert len([r for r in rec if r["tool"] == "hw" and "hwfepre.dat" in r["argv"]]) == 1     # HyperMesh m_2는 조립 실행 때만
    # 같은 세트를 mesh_only 템플릿으로 바꿔 params 없이 돌려도 쿠션 실행과 같다(일원화)
    env.to_mesh_only(ps["id"])
    jm, st = _run(env, ALT, cushion=False)
    assert st == "SUCCEEDED", env.job(jm)
    assert _summary(env, jm) == sc
    assert (Path(env.job(jm)["result"]["pred_h3d_rel"]).name) == "EPS_mesh_0000_pred.h3d"


# ---- Native 단건 --------------------------------------------------------------------------------------------------


def test_ik_native_single_assembly_unchanged_and_cushion_writes_one_file(native_env, fake_record):
    env = native_env()
    native_set(env)
    ja, st = _run(env, NAT, cushion=False)
    assert st == "SUCCEEDED", env.job(ja)
    sa = _summary(env, ja)
    assert sa["input_kind"] == "assembly" and sa["template_kind"] == "assembly" and MESH_INC in sa["input"] and MESH not in sa["input"]
    assert [x["argv"][1] for x in read_record(fake_record) if x["tool"] == "paicad"][-4:] == ["version", "update", "morph", "check"]
    n0 = len(read_record(fake_record))
    jc, st = _run(env, NAT, cushion=True)
    assert st == "SUCCEEDED", env.job(jc)
    Pd = env.predict_dir(jc)
    cmds = [x["argv"][1:3] for x in read_record(fake_record)[n0:] if x["tool"] == "paicad"]
    assert cmds[-4:] == [["update", "--cad"], ["morph", "--baseline-inc"], ["check", "--baseline-inc"], ["cushion", "write"]]
    cw = [x for x in read_record(fake_record) if x["tool"] == "paicad" and x["argv"][1:3] == ["cushion", "write"]][-1]["argv"]
    arg = lambda k: cw[cw.index(k) + 1]  # noqa: E731
    assert arg("--inc") == str(Pd / "geom" / MESH_INC) and arg("--out-rad") == str(Pd / "geom" / MESH)
    assert arg("--out-dir") == str(Pd / "geom" / "cushion") and arg("--assem-dir").endswith("radioss_assem")
    assert arg("--renum-csv").endswith("RENUM_INIT.csv")
    assert json.loads((Pd / "geom" / "cushion" / "cushion.json").read_text())["status"] == "OK"
    st = env.steps(jc)
    assert [st[k]["state"] for k in ("GEOM_UPDATE", "MESH", "RAD_ASSEMBLE", "EDSPY_PREDICT")] == ["SUCCEEDED"] * 4
    sc = _summary(env, jc)
    assert list(sc["input"]) == [MESH] and sc["starter"] == MESH and sc["template_kind"] == "mesh_only" and sc["input_kind"] == "cushion"
    assert not (Pd / "INPUT" / MESH_INC).exists()                                     # 모핑 include·조립 파일은 복사하지 않는다
    assert sc["predict_input"] == {"input": "cushion", "starter": MESH, "bytes": sc["input"][MESH], "files": 1}
    assert sc["predict_input"]["files"] < sa["predict_input"]["files"]
    # V-IK-5: 단일 파일·#include 없음·/BEGIN … /END, 노드 줄(ID·좌표) = 모핑 include
    rad = (Pd / "INPUT" / MESH).read_text()
    inc = (Pd / "geom" / MESH_INC).read_text().splitlines()
    assert rad == (Pd / "geom" / MESH).read_text() and "#include" not in rad and rad.rstrip().endswith("/END") and "/BEGIN" in rad
    assert all(ln in rad.splitlines() for ln in inc)
    assert _edspy_input(read_record(fake_record), Pd) == Pd / "INPUT" / MESH
    # 보고 경고는 한국어로
    assert [w["code"] for w in env.job(jc)["warnings"] if w["code"].startswith("CUSHION")] == []


def test_ik_native_cushion_part_def_warning_and_failures(native_env, monkeypatch):
    env = native_env()
    native_set(env)
    monkeypatch.setenv("FAKE_PAICAD_CUSHION_WARN", "1")
    jc, st = _run(env, NAT, cushion=True)
    assert st == "SUCCEEDED", env.job(jc)
    w = [x for x in env.job(jc)["warnings"] if x["code"] == "CUSHION_PART_DEF_MISSING"]
    assert len(w) == 1 and "쿠션 부품 정의(PART·PROP·MAT) 일부를 조립 폴더에서 찾지 못했습니다" in w[0]["message"]
    monkeypatch.delenv("FAKE_PAICAD_CUSHION_WARN")
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "cushion_write:GEOM_UNSUPPORTED_ELEMENT")
    jf, st = _run(env, NAT, cushion=True)
    jd = env.job(jf)
    assert st == "FAILED" and jd["failure_code"] == "GEOM_UNSUPPORTED_ELEMENT" and jd["current_step_key"] == "MESH"
    assert "tetra4가 아닌 쿠션 요소" in jd["failure_message"]
    # 같은 실패여도 조립 입력은 cushion write를 부르지 않으므로 성공(현행 그대로)
    ja, st = _run(env, NAT, cushion=False)
    assert st == "SUCCEEDED", env.job(ja)


def test_ik_native_cushion_command_not_configured_blocks_prep(native_env):
    env = native_env(commands={"paicad_cushion_write": None})
    native_set(env)
    jc, st = _run(env, NAT, cushion=True)
    jd = env.job(jc)
    assert st == "FAILED" and jd["failure_code"] == "TEMPLATE_NOT_CONFIGURED" and jd["current_step_key"] == "PR_PREP"
    assert "commands.paicad_cushion_write" in jd["failure_message"]
    ja, st = _run(env, NAT, cushion=False)                                           # 조립 입력은 영향 없음
    assert st == "SUCCEEDED", env.job(ja)


def test_ik_native_cushion_rejects_shell_thickness_values(native_env):
    env = native_env()
    ps = native_set(env)
    r = env.c.post(f"{API}/param-sets/{ps['id']}/props/scan", headers=PW)
    assert r.status_code == 202, r.text
    assert env.w.run_once_slot() == "SUCCEEDED"
    r = env.c.put(f"{API}/param-sets/{ps['id']}/props", headers=PW, json={"selected": [{"name": "BRACKET_SHELL_T", "min": 1.0, "max": 1.5}]})
    assert r.status_code == 200, r.text
    jc, st = _run(env, {"values": {**NAT["values"], "BRACKET_SHELL_T": 1.3}, "value_source": "manual"}, cushion=True)
    jd = env.job(jc)
    assert st == "FAILED" and jd["failure_code"] == "INPUT_KIND_UNSUPPORTED" and jd["current_step_key"] == "PR_PREP"


# ---- ④ 일괄 ------------------------------------------------------------------------------------------------------


def _children(env, bid):
    rows = env.sql("select j.id, j.params, r.doe_no, r.input_rel from predict_batch_runs r join jobs j on j.id = r.predict_job_id "
                   "where r.batch_id=:b order by r.doe_no", b=bid)
    return [dict(r._mapping) for r in rows]


def test_ik_altair_batch_cushion_on_assembly_template(predict_env, fake_record):
    env = predict_env()
    ps = env.param_set()                              # 조립 가능 템플릿 + 쿠션 입력 일괄
    bid, pj = env.make_batch(ps["id"], ROWS3, multi=2, input_kind="mesh_only")
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(pj)
    B = env.sroot / env.batch(bid)["dir_rel"]
    for n in (1, 2, 3):
        assert sorted(os.listdir(B / f"run__{n:05d}")) == ["m_1"]                       # m_2·m_3 미생성
        assert (B / f"run__{n:05d}" / "m_1" / MESH).is_file()
    assert not [r for r in read_record(fake_record) if r["tool"] == "hw" and "hwfepre.dat" in r["argv"]]
    ch = _children(env, bid)
    assert [c["input_rel"] for c in ch] == [f"run__{n:05d}/m_1/{MESH}" for n in (1, 2, 3)]
    assert [c["params"]["input_path"] for c in ch] == [str(B / f"run__{n:05d}" / "m_1" / MESH) for n in (1, 2, 3)]
    bj = json.loads((B / "batch.json").read_text())
    assert bj["input_kind"] == "mesh_only" and bj["input"] == "cushion"
    assert env.w.run_once_slot() == "SUCCEEDED"
    cj = env.job(ch[0]["id"])
    assert cj["result"]["starter"] == MESH and cj["result"]["predict_input"] == {
        "input": "cushion", "starter": MESH, "bytes": (B / "run__00001" / "m_1" / MESH).stat().st_size, "files": 1}


def _native_batch(env, ps, *, input_kind):
    return env.make_batch(ps["id"], NROWS, multi=2, input_kind=input_kind)


def test_ik_native_batch_cushion_layout_and_children(native_env, fake_record):
    env = native_env()
    ps = native_set(env)
    bid, pj = _native_batch(env, ps, input_kind="mesh_only")
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(pj)
    B = env.sroot / env.batch(bid)["dir_rel"]
    for n in (1, 2, 3):
        R = B / f"run__{n:05d}"
        assert sorted(os.listdir(R)) == ["m_1", "m_2", "options.json"]                  # m_3 없음
        for rel in ("m_1/values.json", "m_1/update/update.json", f"m_2/{MESH_INC}", "m_2/morph/morph.json", "m_2/check/check.json",
                    "m_2/cushion/cushion.json", f"m_1/{MESH}"):
            assert (R / rel).is_file(), rel
        rad = (R / "m_1" / MESH).read_text()
        assert "#include" not in rad and rad.rstrip().endswith("/END")
        assert all(ln in rad.splitlines() for ln in (R / "m_2" / MESH_INC).read_text().splitlines())
    cmds = [x["argv"][1] for x in read_record(fake_record) if x["tool"] == "paicad"]
    assert cmds.count("run") == 3 and cmds.count("cushion") == 3                         # paicad run(update→morph→check) 뒤 cushion write
    cw = [x["argv"] for x in read_record(fake_record) if x["tool"] == "paicad" and x["argv"][1] == "cushion"][0]
    R1 = next(Path(cw[cw.index("--out-rad") + 1]).parents[1] for _ in [0])
    assert cw[cw.index("--out-dir") + 1] == str(R1 / "m_2" / "cushion") and cw[cw.index("--inc") + 1] == str(R1 / "m_2" / MESH_INC)
    ch = _children(env, bid)
    assert [c["input_rel"] for c in ch] == [f"run__{n:05d}/m_1/{MESH}" for n in (1, 2, 3)]
    assert json.loads((B / "batch.json").read_text())["input"] == "cushion"
    for c in ch:
        assert env.w.run_once_slot() == "SUCCEEDED", env.job(c["id"])
    cj = env.job(ch[0]["id"])
    Pd = env.predict_dir(ch[0]["id"])
    assert cj["result"]["starter"] == MESH and sorted(os.listdir(Pd / "INPUT")) == [MESH]
    assert cj["result"]["predict_input"]["files"] == 1 and cj["result"]["predict_input"]["input"] == "cushion"
    assert env.batch(bid)["status"] == "DONE"


def test_ik_native_batch_assembly_unchanged(native_env, fake_record):
    env = native_env()
    ps = native_set(env)
    bid, pj = _native_batch(env, ps, input_kind="assembly")
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(pj)
    B = env.sroot / env.batch(bid)["dir_rel"]
    assert sorted(os.listdir(B / "run__00001")) == ["m_1", "m_2", "m_3", "options.json"]
    assert not (B / "run__00001" / "m_2" / "cushion").exists()
    assert "cushion" not in [x["argv"][1] for x in read_record(fake_record) if x["tool"] == "paicad"]
    assert [c["input_rel"] for c in _children(env, bid)][0] == "run__00001/m_3"
    assert json.loads((B / "batch.json").read_text())["input"] == "assembly"


def test_ik_native_batch_cushion_failure_writes_skipped_and_missing_command(native_env, monkeypatch):
    env = native_env()
    ps = native_set(env)
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "cushion_write:GEOM_UNSUPPORTED_ELEMENT")
    bid, pj = _native_batch(env, ps, input_kind="mesh_only")
    assert env.w.run_once_slot() == "FAILED"
    jd = env.job(pj)
    assert jd["failure_code"] == "GEOM_UNSUPPORTED_ELEMENT" and jd["current_step_key"] == "BP_GEN"
    B = env.sroot / env.batch(bid)["dir_rel"]
    sk = json.loads((B / "run__00001" / "SKIPPED.json").read_text())
    assert sk["code"] == "GEOM_UNSUPPORTED_ELEMENT" and sk["step"] == "cushion"
    assert [r["gen_state"] for r in env.batch(bid)["runs"]] == ["FAILED"] * 3
    monkeypatch.delenv("FAKE_PAICAD_FAIL")
    env2 = native_env(commands={"paicad_cushion_write": None}, folder="p2")
    ps2 = native_set(env2)
    bid2, pj2 = _native_batch(env2, ps2, input_kind="mesh_only")
    assert env2.w.run_once_slot() == "FAILED"
    jd = env2.job(pj2)
    assert jd["failure_code"] == "TEMPLATE_NOT_CONFIGURED" and jd["current_step_key"] == "BP_PREP"
