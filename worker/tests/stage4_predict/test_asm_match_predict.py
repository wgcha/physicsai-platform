"""조립 매칭 세트(방식 M, asm-match.md §6.4·V-AM-10) ④ 단건·일괄 예측 · 쿠션 단독 rad · from-train · FEM 검증(입력 재사용) E2E — 가짜 paicad.
기준본 `{mesh_include_name}` 파일은 어디에도 만들어지지 않고(AM-1) 입력은 include 트리 사본 + 노드 패치(`asm write`)다."""

from __future__ import annotations

import json
import shutil

from helpers_asm import STARTER, _confirmed, make_tree
from helpers_native import make_project
from physicsai_test_support import API, H, MESH_INC, read_record

PW, P = H("tok-power", write=True), H("tok-power")
VALUES = {"values": {"A_THK_1": 10.2, "B_RIB_H_1": 20.0, "C_HOLE_R_1": 4.0}, "value_source": "manual"}


def matched_set(env):
    """프로젝트 폴더(STEP + include 트리 조립, 기준본·RENUM 없음)를 조립 매칭으로 확정해 ④ 세트로 등록한다 → (세트, 폴더)."""
    proj = make_project(env.imports, include_base=False, renum_csv=False)
    shutil.rmtree(proj / "assem")
    asm = make_tree(proj / "assem")
    # ① Native 추출 없이도 되는 path 출처(④ 새 템플릿): STEP 경로를 직접 준다
    mid = _confirmed(env.c, env.w, env.sid, asm, {"kind": "path", "path": str(proj / "bracket.step")})
    r = env.c.post(f"{API}/studies/{env.sid}/param-sets", headers=PW,
                   json={"path": str(proj), "mode": "discover", "engine": "native", "label": "M", "asm_match_id": mid})
    assert r.status_code == 202, r.text
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(r.json()["job_id"])
    ps = env.c.get(f"{API}/param-sets/{env.job(r.json()['job_id'])['result']['param_set_id']}", headers=P).json()
    return ps, proj


def test_matched_single_predict_writes_tree_copy_and_patch(native_env, fake_record):
    env = native_env()
    ps, _proj = matched_set(env)
    assert ps["native"]["prep_status"] == "READY"
    j = env.submit("PREDICT", VALUES)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    Pd = env.predict_dir(j["id"])
    assert (Pd / "geom" / "node_patch.npz").is_file() and (Pd / "geom" / "morph" / "node_xyz.npz").is_file()
    assert not (Pd / "geom" / MESH_INC).exists() and not (Pd / "INPUT" / MESH_INC).exists()  # 기준본 파일 이름에 기대지 않는다
    assert (Pd / "INPUT" / STARTER).is_file() and (Pd / "INPUT" / "nodes" / "102_nodes.inc").is_file()
    assert "#FAKE_PATCH" in (Pd / "INPUT" / STARTER).read_text() and not (Pd / "INPUT" / "unused.inc").exists()
    tools = [r["argv"] for r in read_record(fake_record) if r["tool"] == "paicad"]
    last = {sub: next(x for x in reversed(tools) if x[1] == sub) for sub in ("morph", "check")}
    assert "--asm-match" in last["morph"] and "--baseline-inc" not in last["morph"] and "--assem-dir" in last["morph"]
    assert "--out-patch" in last["check"] and "--out-inc" not in last["check"] and "--renum-csv" not in last["check"]
    wr = next(x for x in reversed(tools) if x[1:3] == ["asm", "write"])
    assert "--patch" in wr and "--asm-match" in wr
    # 세트 조립 폴더가 바뀌면 준비본 STALE → 예측 409 GEOM_PREP_STALE
    S = env.sroot / "04_params" / ps["id"]
    (S / "radioss_assem" / "101_parts.inc").write_text("/PART/3000001\nCUSH_A\nedited\n")
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "PREDICT", "params": VALUES})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "GEOM_PREP_STALE", r.text


def test_matched_cushion_rad_uses_patch(native_env, fake_record):
    """쿠션 단독 rad(IK): 방식 M은 `cushion write --asm-match … --patch <node_patch>`(기준본 --inc 없음). 형상 값이 있으면 패치 적용."""
    env = native_env()
    ps, _proj = matched_set(env)
    assert ps["input_capability"] == ["assembly", "cushion"]
    j = env.submit("PREDICT", {**VALUES, "param_set_id": ps["id"], "input": "cushion"})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    cw = [x["argv"] for x in read_record(fake_record) if x["tool"] == "paicad" and x["argv"][1:3] == ["cushion", "write"]][-1]
    assert "--asm-match" in cw and "--patch" in cw and "--inc" not in cw and "--renum-csv" not in cw
    files = sorted(p.name for p in (env.predict_dir(j["id"]) / "INPUT").iterdir())
    assert len(files) == 1
    assert "patch=1" in (env.predict_dir(j["id"]) / "INPUT" / files[0]).read_text()


def test_matched_set_rejects_multi_baseline(native_env):
    env = native_env()
    ps, _proj = matched_set(env)
    other = make_project(env.imports / "o", include_base=True)
    r = env.c.post(f"{API}/param-sets/{ps['id']}/baselines", headers=PW, json={"id": "B2", "path": str(other)})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ASM_MATCH_UNSUPPORTED"
    r = env.c.post(f"{API}/param-sets/{ps['id']}/native-prepare", headers=PW)  # 다시 준비는 가능(같은 방식 M)
    assert r.status_code == 202, r.text
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(r.json()["job_id"])
    assert env.c.get(f"{API}/param-sets/{ps['id']}", headers=P).json()["native"]["prep_status"] == "READY"


def test_matched_batch_generation_and_children(native_env, fake_record):
    """일괄 예측: run마다 m_1(update)·m_2(morph + node_patch.npz)·m_3(트리 사본 + 패치), 기준본 include 없음. 하위 PREDICT는 m_3 사용."""
    env = native_env()
    ps, _proj = matched_set(env)
    rows = "A_THK_1,B_RIB_H_1,C_HOLE_R_1\n9.6,20,3.9\n10.0,20,4.0\n"
    pj = env.submit("PREDICT_BATCH", {"param_set_id": ps["id"], "multi_execution": 2, "source": {"kind": "table", "text": rows}})
    bid = pj["params"]["batch_id"]
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(pj["id"])
    run_dir = env.sql("select dir_rel from predict_batches where id=:i", i=bid)[0][0]
    b = env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()
    assert [r["state"] for r in b["rows"]] == ["QUEUED", "QUEUED"]
    for r in b["rows"]:
        R = env.sroot / run_dir / r["run_key"]
        assert (R / "m_2" / "node_patch.npz").is_file() and (R / "m_2" / "morph" / "node_xyz.npz").is_file()
        assert (R / "m_3" / STARTER).is_file() and (R / "m_3" / "nodes" / "102_nodes.inc").is_file()
        assert "#FAKE_PATCH" in (R / "m_3" / STARTER).read_text()
        assert not any(p.name == MESH_INC for p in R.rglob("*"))
    tools = [x["argv"] for x in read_record(fake_record) if x["tool"] == "paicad"]
    assert any(x[1] == "run" and "--out-patch" in x and "--asm-match" in x for x in tools)
    for cid in [r["job_id"] for r in b["rows"]]:
        assert env.w.run_once_slot() == "SUCCEEDED", env.job(cid)
    assert env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()["status"] == "DONE"


def test_from_train_matched_copies_tree_and_confirmed_doc(native_env, fake_record):
    """①-3 DOE(asm_match_id) → ④ 세트(from-train): D/cad/asm_match.json·include 트리(하위 폴더 포함) 복사, prep READY, paicad 미실행."""
    from helpers_asm import ROWS as _ROWS  # noqa: F401
    from helpers_stage1 import job, submit

    env = native_env(final_model=False)
    c, w, sid = env.c, env.w, env.sid
    proj = make_project(env.imports, include_base=False, renum_csv=False)
    shutil.rmtree(proj / "assem")
    asm = make_tree(proj / "assem")
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(proj / "bracket.step"), "engine": "native"})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    mid = _confirmed(c, w, sid, asm)
    j = submit(c, sid, "TD_DOE_GEN", {"doe_label": "LHS", "num_runs": 3, "seed": 3, "radioss_assem_path": str(asm), "asm_match_id": mid})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    doe_id = job(c, j["id"])["result"]["doe_id"]
    before = len(read_record(fake_record))
    r = c.post(f"{API}/studies/{sid}/param-sets/from-train", headers=PW, json={"doe_id": doe_id, "runs": "all"})
    assert r.status_code == 201, r.text
    ps = r.json()
    assert ps["engine"] == "native" and ps["native"]["prep_status"] == "READY"
    S = env.sroot / "04_params" / ps["id"]
    assert (S / "cad" / "asm_match.json").is_file() and (S / "radioss_assem" / "nodes" / "102_nodes.inc").is_file()
    assert not (S / "radioss_assem" / "unused.inc").exists()
    prep = json.loads((S / "native" / "prep.json").read_text())
    assert prep["inputs"]["asm_match"]["rel"] == "cad/asm_match.json" and prep["inputs"]["baseline_inc"] is None
    assert len(read_record(fake_record)) == before
