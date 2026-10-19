"""④ native 일괄 예측·①→④ 변환(geometry-engine.md §7.3.6~§7.3.7, V-GE-8·10): 입력 생성(run 레이아웃)·스킵(gen_category)·
하위 PREDICT는 R의 m_3 사용·값 반올림 없음, ①→④ native 세트 복사."""

from __future__ import annotations

import json

from helpers_native import make_project, native_set
from physicsai_test_support import API, H, MESH_INC, read_record

PW = H("tok-power", write=True)
P = H("tok-power")
ROWS = "A_THK_1,B_RIB_H_1,C_HOLE_R_1\n9.6,20,3.9\n10.0,20,4.0\n10.4,20,4.1\n"


def _batch(env, ps, rows=ROWS):
    pj = env.submit("PREDICT_BATCH", {"param_set_id": ps["id"], "multi_execution": 2, "source": {"kind": "table", "text": rows}})
    return pj, pj["params"]["batch_id"]


def test_native_batch_generation_and_children(native_env, fake_record):
    env = native_env()
    ps = native_set(env)
    pj, bid = _batch(env, ps)
    assert pj["params"]["engine"] == "native" and pj["params"]["template_kind"] == "assembly"
    assert "ENGINE_UNKNOWN" in [w["code"] for w in pj["warnings"]]
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(pj["id"])
    b = env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()
    assert b["status"] == "PREDICTING" and b["gen"]["done"] == 3 and [r["state"] for r in b["rows"]] == ["QUEUED"] * 3
    assert all(r["applied_values"] == r["values"] for r in b["rows"]) and all(r["code"] is None for r in b["rows"])
    B = env.sroot / "05_predict_batches" if False else None
    rows = b["rows"]
    run_dir = env.sql("select dir_rel from predict_batches where id=:i", i=bid)[0][0]
    for r in rows:
        R = env.sroot / run_dir / r["run_key"]
        for rel in ("m_1/values.json", "m_1/update/update.json", "m_2/morph/morph.json", "m_2/check/check.json", f"m_2/{MESH_INC}"):
            assert (R / rel).is_file(), (r["run_key"], rel)
    ev = {x[0] for x in env.sql("select engine_version from predict_batch_runs where batch_id=:i", i=bid)}
    assert ev == {"0.5.0"}
    cmds = [x["argv"][1] for x in read_record(fake_record) if x["tool"] == "paicad"]
    assert cmds.count("run") == 3
    for cid in [r["job_id"] for r in rows]:
        assert env.w.run_once_slot() == "SUCCEEDED", env.job(cid)
    assert env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()["status"] == "DONE"


def test_native_batch_skips_failed_runs_with_category(native_env, monkeypatch):
    env = native_env()
    ps = native_set(env)
    monkeypatch.setenv("FAKE_PAICAD_FAIL_WHEN", "check:GEOM_QUALITY:A_THK_1>10.2")
    pj, bid = _batch(env, ps)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(pj["id"])          # 일부 run 실패는 작업 성공(기존 규칙)
    rows = env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()["rows"]
    bad = [r for r in rows if r["state"] == "GEN_FAILED"]
    assert [r["values"]["A_THK_1"] for r in bad] == [10.4]
    assert bad[0]["code"] == "GEOM_QUALITY" and bad[0]["gen_category"] == "QUALITY" and "품질 미달" in bad[0]["message"]
    assert len(bad[0]["message"]) <= 500
    assert [r["state"] for r in rows if r is not bad[0]] == ["QUEUED", "QUEUED"]


def test_native_batch_blocked_when_stale(native_env):
    env = native_env()
    ps = native_set(env)
    (env.sroot / "04_params" / ps["id"] / "radioss_assem" / MESH_INC).write_text("/NODE\n3000001 1 1 1\n")
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "PREDICT_BATCH", "params": {
        "param_set_id": ps["id"], "multi_execution": 1, "source": {"kind": "table", "text": ROWS}}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "GEOM_PREP_STALE", r.text


def test_from_train_native_copies_prepared_set(native_env, fake_record):
    """native DOE → 세트: cad/·조립/·native/ 복사, prep.json은 세트 기준 해시, 준비본 READY, paicad 실행 없음."""
    from helpers_stage1 import job, submit

    env = native_env(final_model=False)
    c, w, sid = env.c, env.w, env.sid
    proj = make_project(env.imports)
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(proj / "bracket.step"), "engine": "native"})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    j = submit(c, sid, "TD_DOE_GEN", {"doe_label": "LHS", "num_runs": 3, "seed": 3, "radioss_assem_path": str(proj / "assem")})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    doe_id = job(c, j["id"])["result"]["doe_id"]
    before = len(read_record(fake_record))
    r = c.post(f"{API}/studies/{sid}/param-sets/from-train", headers=PW, json={"doe_id": doe_id, "runs": "all"})
    assert r.status_code == 201, r.text
    ps = r.json()
    assert ps["engine"] == "native" and ps["origin"] == "TRAIN_DOE" and ps["native"]["prep_status"] == "READY"
    assert [p["name"] for p in ps["parameters"]] == ["A_THK_1", "C_HOLE_R_1"]       # DOE에서 쓴(use) 파라미터만
    S = env.sroot / "04_params" / ps["id"]
    assert (S / "native" / "tag" / "tag.json").is_file() and (S / "cad" / "bracket.step").is_file()
    assert json.loads((S / "native" / "prep.json").read_text())["inputs"]["step"]["rel"] == "cad/bracket.step"
    assert len(read_record(fake_record)) == before                                       # paicad 미실행
