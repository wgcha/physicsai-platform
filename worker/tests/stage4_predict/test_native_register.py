"""④ native 세트 등록 E2E(geometry-engine.md §7.3.4, V-GE-5·6·7·9): discover → 202 job → NP_* → 세트 행·폴더·PNG artifact,
기존 피처 재사용(NP_EXTRACT SKIPPED)·reprep·실패 코드·엔진 설정 차단. 가짜 paicad."""

from __future__ import annotations

import json

from physicsai_test_support import API, H, read_record

from helpers_native import make_project

PW = H("tok-power", write=True)
P = H("tok-power")


def _discover(env, proj, **kw):
    r = env.c.post(f"{API}/studies/{env.sid}/param-sets/discover", headers=PW, json={"path": str(proj), **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _register(env, proj, expect=202, **kw):
    body = {"path": str(proj), "mode": "discover", "engine": "native", **kw}
    r = env.c.post(f"{API}/studies/{env.sid}/param-sets", headers=PW, json=body)
    assert r.status_code == expect, r.text
    return r.json()


def test_discover_native_candidates_and_problems(native_env):
    env = native_env()
    proj = make_project(env.imports)
    d = _discover(env, proj)
    assert d["engine"] == "native" and d["tpl"] == [] and d["problems"] == []
    assert [c["name"] for c in d["cad"]] == ["bracket.step"] and d["cad"][0]["kind"] == "file"
    assert [a["rel"] for a in d["radioss_assem"]] == ["assem"]
    proj2 = make_project(env.imports / "x", renum_csv=False)
    assert "RENUM_CSV_MISSING" in [p["code"] for p in _discover(env, proj2)["problems"]]
    proj3 = make_project(env.imports / "y", include_base=False)
    assert "BASELINE_INC_MISSING" in [p["code"] for p in _discover(env, proj3)["problems"]]
    proj4 = make_project(env.imports / "z", parts=True)
    assert [(c["name"], c["kind"]) for c in _discover(env, proj4)["cad"]] == [("parts", "parts")]


def test_register_new_runs_chain_and_creates_set(native_env, fake_record):
    env = native_env()
    proj = make_project(env.imports)
    out = _register(env, proj, label="N1")
    assert set(out) == {"job_id"}
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(out["job_id"])
    steps = env.steps(out["job_id"])
    assert [steps[k]["state"] for k in ("NP_PREP", "NP_EXTRACT", "NP_TAG", "BL_MAP", "NP_REGISTER")] == \
        ["SUCCEEDED", "SUCCEEDED", "SUCCEEDED", "SKIPPED", "SUCCEEDED"]
    psid = env.job(out["job_id"])["result"]["param_set_id"]
    ps = env.c.get(f"{API}/param-sets/{psid}", headers=P).json()
    assert ps["engine"] == "native" and ps["label"] == "N1" and ps["input_kind"] == "assembly" and ps["engine_version"] == "0.5.0"
    assert [p["name"] for p in ps["parameters"]] == ["A_THK_1", "B_RIB_H_1", "C_HOLE_R_1"]
    assert ps["native"]["prep_status"] == "READY" and ps["native"]["feature_count"] == 4
    assert ps["geom_options_effective"]["tag"] and ps["cad_file_name"] == "bracket.step" and ps["tpl_params"] == []
    S = env.sroot / "04_params" / psid
    for rel in ("native/prep.json", "native/extract/parameter_features.json", "native/tag/tag.json", "cad/bracket.step",
                "radioss_assem/104_replace_node_elem.inc", "parameters.json"):
        assert (S / rel).is_file(), rel
    assert not (env.sroot / "logs" / "_paramset_tmp" / out["job_id"]).exists()
    cmds = [r["argv"][1] for r in read_record(fake_record) if r["tool"] == "paicad"]
    assert cmds == ["version", "extract", "tag", "view"]  # NP_VIEW(geometry-view.md §6.3)
    f = env.c.get(f"{API}/param-sets/{psid}/features", headers=P).json()
    assert [x["name"] for x in f["features"]] == ["A_THK_1", "A_THK_2", "B_RIB_H_1", "C_HOLE_R_1"]
    assert all(x["png_artifact_id"] for x in f["features"]) and f["groups"][0]["members"] == ["A_THK_1", "A_THK_2"]
    assert [w["code"] for w in f["warnings"]] == ["REF_BOTH_CONTACT"]
    lst = env.c.get(f"{API}/studies/{env.sid}/param-sets", headers=P).json()
    assert [x["id"] for x in lst] == [psid]


def test_register_reuses_provided_features_and_parameters(native_env, fake_record):
    """프로젝트 폴더에 features·xml 둘 다 있으면 NP_EXTRACT SKIPPED, parameters.json의 min·max 사용(이름 집합이 같을 때)."""
    env = native_env()
    proj = make_project(env.imports, params_json={"parameters": [
        {"name": "A_THK_1", "nominal": 10, "min": 8, "max": 12}, {"name": "B_RIB_H_1", "nominal": 20, "min": 18, "max": 22},
        {"name": "C_HOLE_R_1", "nominal": 4, "min": 3, "max": 5}]})
    first = _register(env, proj)
    assert env.w.run_once_slot() == "SUCCEEDED"
    psid = env.job(first["job_id"])["result"]["param_set_id"]
    ext = env.sroot / "04_params" / psid / "native" / "extract"
    for n in ("parameter_features.json", "parameter_extracted.xml"):
        (proj / n).write_bytes((ext / n).read_bytes())
    ps = env.c.get(f"{API}/param-sets/{psid}", headers=P).json()
    assert {p["name"]: (p["min"], p["max"]) for p in ps["parameters"]}["A_THK_1"] == (8, 12)
    notes = [n["code"] for n in _discover(env, proj)["notes"]]
    assert "FEATURES_FOUND" in notes
    second = _register(env, proj)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(second["job_id"])
    assert env.steps(second["job_id"])["NP_EXTRACT"]["state"] == "SKIPPED"
    assert [r["argv"][1] for r in read_record(fake_record) if r["tool"] == "paicad"][-3:] == ["version", "tag", "view"]


def test_register_feature_mismatch_fails_without_set(native_env):
    env = native_env()
    proj = make_project(env.imports, params_json={"parameters": [{"name": "OTHER", "nominal": 1, "min": 0, "max": 2}]})
    out = _register(env, proj)
    assert env.w.run_once_slot() == "FAILED"
    jd = env.job(out["job_id"])
    assert jd["failure_code"] == "PARAM_FEATURE_MISMATCH" and jd["current_step_key"] == "NP_REGISTER"
    assert env.c.get(f"{API}/studies/{env.sid}/param-sets", headers=P).json() == []


def test_register_extract_failure_maps_code(native_env, monkeypatch):
    env = native_env()
    proj = make_project(env.imports)
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "extract:GEOM_EXTRACT_EMPTY")
    out = _register(env, proj)
    assert env.w.run_once_slot() == "FAILED"
    jd = env.job(out["job_id"])
    assert jd["failure_code"] == "GEOM_EXTRACT_EMPTY" and jd["current_step_key"] == "NP_EXTRACT"
    assert "인식된 피처 없음" in jd["failure_message"]
    assert env.c.get(f"{API}/studies/{env.sid}/param-sets", headers=P).json() == []


def test_reprep_after_tag_option_change_and_stale(native_env, fake_record):
    env = native_env()
    proj = make_project(env.imports)
    first = _register(env, proj)
    assert env.w.run_once_slot() == "SUCCEEDED"
    psid = env.job(first["job_id"])["result"]["param_set_id"]
    r = env.c.patch(f"{API}/param-sets/{psid}", headers=PW, json={"geom_options": {"tag": {"tol_abs_mm": 0.08}}})
    assert r.status_code == 200, r.text
    assert r.json()["native"]["prep_status"] == "STALE" and "경계 분류" in r.json()["native"]["prep_reason"]
    r = env.c.post(f"{API}/param-sets/{psid}/native-prepare", headers=PW)
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(jid)
    st = env.steps(jid)
    assert st["NP_EXTRACT"]["state"] == "SKIPPED" and st["NP_TAG"]["state"] == "SUCCEEDED" and st["BL_MAP"]["state"] == "SKIPPED"
    ps = env.c.get(f"{API}/param-sets/{psid}", headers=P).json()
    assert ps["native"]["prep_status"] == "READY" and ps["geom_options"] == {"tag": {"tol_abs_mm": 0.08}}
    assert list((env.sroot / "_backup").glob("*/04_params/*/native"))  # 이전 native/는 _backup으로


def test_geom_options_validation_and_altair_patch_rejected(native_env, predict_env):
    env = native_env()
    proj = make_project(env.imports)
    r = env.c.post(f"{API}/studies/{env.sid}/param-sets", headers=PW,
                   json={"path": str(proj), "mode": "discover", "engine": "native", "geom_options": {"nope": 1}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "GEOM_OPTIONS_INVALID", r.text
    assert json.dumps(r.json()).count("nope")
    alt = env.param_set()  # altair 세트
    r = env.c.patch(f"{API}/param-sets/{alt['id']}", headers=PW, json={"geom_options": {}})
    assert r.status_code == 422, r.text
    assert env.c.get(f"{API}/param-sets/{alt['id']}", headers=P).json()["engine"] == "altair"


def test_native_unavailable_blocks_register(native_env):
    env = native_env(geometry={"paicad_path": "/nonexistent/paicad"})
    proj = make_project(env.imports)
    r = env.c.post(f"{API}/studies/{env.sid}/param-sets", headers=PW,
                   json={"path": str(proj), "mode": "discover", "engine": "native"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "GEOM_NATIVE_UNAVAILABLE", r.text
    st = env.c.get(f"{API}/status", headers=P).json()
    assert st["geometry"]["native_available"] is False and st["features"]["geometry_native"]["enabled"] is False
