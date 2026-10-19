"""단계 3S 쉘 두께 E2E(geometry-engine.md §11.1, V-GE-15): PROP 스캔 작업 → 결과·선택 API → 단건 예측·세트 기준 DOE에서
INPUT 복사본에 props apply(원본 불변), 두께만 있는 세트(형상 단계 생략)·쉘 두께 전용 등록, 실패 코드 한국어. 가짜 paicad."""

from __future__ import annotations

import csv
import json

from helpers_native import native_set
from physicsai_test_support import API, H, MESH_INC, make_assem_files, read_record

PW = H("tok-power", write=True)
P = H("tok-power")
GEO = {"A_THK_1": 10.2, "B_RIB_H_1": 20.0, "C_HOLE_R_1": 4.0}


def _scan(env, psid):
    r = env.c.post(f"{API}/param-sets/{psid}/props/scan", headers=PW)
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(jid)
    return jid


def _select(env, psid, selected, expect=200, **kw):
    r = env.c.put(f"{API}/param-sets/{psid}/props", headers=PW, json={"selected": selected, **kw})
    assert r.status_code == expect, r.text
    return r.json()


def test_props_scan_select_and_predict_applies_to_input_copy(native_env, fake_record):
    env = native_env()
    ps = native_set(env)
    g = env.c.get(f"{API}/param-sets/{ps['id']}/props", headers=P).json()
    assert g["scanned"] is False and g["props"] == [] and g["include_geometry"] is True
    jid = _scan(env, ps["id"])
    st = env.steps(jid)
    assert [st[k]["state"] for k in ("NP_PREP", "NP_EXTRACT", "NP_TAG", "BL_MAP", "NP_REGISTER")] == \
        ["SUCCEEDED", "SUCCEEDED", "SKIPPED", "SKIPPED", "SUCCEEDED"]
    S = env.sroot / "04_params" / ps["id"]
    assert (S / "native" / "props" / "props.json").is_file()
    g = env.c.get(f"{API}/param-sets/{ps['id']}/props", headers=P).json()
    by = {x["id"]: x for x in g["props"]}
    assert g["scanned"] and by[1]["selectable"] and by[1]["parameter"] == "BRACKET_SHELL_T" and not by[1]["selected"]
    assert by[3]["selectable"] is False and by[3]["reason_code"] == "PROP_OVERRIDDEN_BY_ELEMENT"
    assert by[4]["supported"] is False and by[4]["reason_code"] == "PROP_UNSUPPORTED_TYPE"
    assert {w["code"] for w in g["warnings"]} >= {"PROP_SHARED_BY_PARTS", "PROP_UNSUPPORTED_TYPE"}
    bad = _select(env, ps["id"], [{"name": "PANEL_SHELL_T"}], expect=422)
    assert bad["detail"]["code"] == "PROP_SELECTION_INVALID" and bad["detail"]["problems"][0]["code"] == "PROP_OVERRIDDEN_BY_ELEMENT"
    bad = _select(env, ps["id"], [{"name": "BRACKET_SHELL_T", "min": 1.3}], expect=422)  # min > 공칭
    assert bad["detail"]["problems"][0]["code"] == "PROP_THICKNESS_INVALID"
    out = _select(env, ps["id"], [{"name": "BRACKET_SHELL_T", "min": 1.0, "max": 1.5}])
    rows = {p["name"]: p for p in out["parameters"]}
    assert rows["BRACKET_SHELL_T"]["source"] == "prop" and rows["BRACKET_SHELL_T"]["prop_id"] == 1
    assert (rows["BRACKET_SHELL_T"]["min"], rows["BRACKET_SHELL_T"]["max"], rows["BRACKET_SHELL_T"]["nominal"]) == (1.0, 1.5, 1.2)
    assert rows["A_THK_1"]["source"] is None and list(rows)[-1] == "BRACKET_SHELL_T"   # 하나의 표: 형상 행 + 쉘 두께 행
    pj = json.loads((S / "parameters.json").read_text())
    assert [p["name"] for p in pj["parameters"]][-1] == "BRACKET_SHELL_T"
    orig = (S / "radioss_assem" / "material.inc").read_bytes()
    j = env.submit("PREDICT", {"values": {**GEO, "BRACKET_SHELL_T": 1.3}, "value_source": "manual"})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    Pd = env.predict_dir(j["id"])
    v = json.loads((Pd / "geom" / "values.json").read_text())
    assert "BRACKET_SHELL_T" not in v["values"] and v["values"]["A_THK_1"] == 10.2   # paicad update에는 형상 값만
    assert (Pd / "INPUT" / "material.inc").read_text().endswith("#FAKE_PROP 1 1.3\n")
    assert (S / "radioss_assem" / "material.inc").read_bytes() == orig                  # 원본 조립 폴더 불변
    apply = [r for r in read_record(fake_record) if r["tool"] == "paicad" and r["argv"][1:3] == ["props", "apply"]][-1]
    assert apply["argv"][apply["argv"].index("--assem-dir") + 1] == str(Pd / "INPUT")
    vals = json.loads((Pd / "geom" / "props" / "props_values.json").read_text())
    assert vals["values"] == {"BRACKET_SHELL_T": 1.3}
    res = env.job(j["id"])["result"]
    assert res["shell_values"] == {"BRACKET_SHELL_T": 1.3} and res["geometry_skipped"] is False


def test_props_apply_failure_is_korean_and_thickness_only_skips_geometry(native_env, monkeypatch, fake_record):
    env = native_env()
    ps = native_set(env)
    _scan(env, ps["id"])
    out = _select(env, ps["id"], [{"name": "BRACKET_SHELL_T"}, {"name": "COVER_SHELL_T"}], include_geometry=False)
    assert [p["name"] for p in out["parameters"]] == ["BRACKET_SHELL_T", "COVER_SHELL_T"]
    monkeypatch.setenv("FAKE_PAICAD_FAIL", "props_apply:PROP_OVERRIDDEN_BY_PART")
    j = env.submit("PREDICT", {"values": {"BRACKET_SHELL_T": 1.25, "COVER_SHELL_T": 0.8}, "value_source": "manual"})
    assert env.w.run_once_slot() == "FAILED"
    jd = env.job(j["id"])
    assert jd["failure_code"] == "PROP_OVERRIDDEN_BY_PART" and "/PART 카드" in jd["failure_message"]
    assert jd["current_step_key"] == "RAD_ASSEMBLE"
    monkeypatch.delenv("FAKE_PAICAD_FAIL")
    n0 = len([r for r in read_record(fake_record) if r["tool"] == "paicad"])
    j = env.submit("PREDICT", {"values": {"BRACKET_SHELL_T": 1.25, "COVER_SHELL_T": 0.8}, "value_source": "manual"})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    st = env.steps(j["id"])
    assert st["GEOM_UPDATE"]["state"] == "SKIPPED" and st["MESH"]["state"] == "SKIPPED"
    cmds = [r["argv"][1] for r in read_record(fake_record) if r["tool"] == "paicad"][n0:]
    assert "update" not in cmds and "morph" not in cmds and cmds[-1] == "props"
    Pd = env.predict_dir(j["id"])
    S = env.sroot / "04_params" / ps["id"]
    assert (Pd / "INPUT" / MESH_INC).read_bytes() == (S / "radioss_assem" / MESH_INC).read_bytes()  # 기준 메시 그대로
    txt = (Pd / "INPUT" / "material.inc").read_text()
    assert "#FAKE_PROP 1 1.25" in txt and "#FAKE_PROP 2 0.8" in txt
    # 형상 행 되살리기
    back = _select(env, ps["id"], [{"name": "BRACKET_SHELL_T"}], include_geometry=True)
    assert [p["name"] for p in back["parameters"]] == ["A_THK_1", "B_RIB_H_1", "C_HOLE_R_1", "BRACKET_SHELL_T"]


def test_shell_only_registration_and_set_doe(native_env, fake_record):
    """STEP 없는 조립 폴더만으로 쉘 두께 전용 세트(tag 생략) → 세트 기준 DOE: m_3에 두께 적용, 샘플 표에 두께 값."""
    env = native_env()
    proj = env.imports / "shell_proj"
    make_assem_files(proj / "assem", renum_csv=False)
    r = env.c.post(f"{API}/studies/{env.sid}/param-sets", headers=PW,
                   json={"path": str(proj), "mode": "discover", "engine": "native", "shell_only": True, "label": "SH"})
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(jid)
    st = env.steps(jid)
    assert st["NP_EXTRACT"]["state"] == "SUCCEEDED" and st["NP_TAG"]["state"] == "SKIPPED"
    psid = env.job(jid)["result"]["param_set_id"]
    ps = env.c.get(f"{API}/param-sets/{psid}", headers=P).json()
    assert ps["native"]["shell_only"] is True and ps["native"]["prep_status"] == "READY" and ps["cad_file_name"] == ""
    assert [p["name"] for p in ps["parameters"]] == ["BRACKET_SHELL_T", "COVER_SHELL_T"]
    cmds = [x["argv"][1:3] for x in read_record(fake_record) if x["tool"] == "paicad"]
    assert ["extract"] not in [c[:1] for c in cmds] and ["tag"] not in [c[:1] for c in cmds]
    r = env.c.post(f"{API}/param-sets/{psid}/native-prepare", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SHELL_ONLY_SET"
    r = env.c.post(f"{API}/param-sets/{psid}/baselines", headers=PW, json={"id": "B2", "path": str(proj)})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SHELL_ONLY_SET", r.text
    j = env.submit("TD_DOE_GEN", {"doe_label": "LHS", "num_runs": 3, "seed": 3, "param_set_id": psid})
    assert j["params"]["param_set_id"] == psid and j["params"]["engine"] == "native"
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    jd = env.job(j["id"])
    D = env.sroot / "01_train" / "doe" / jd["result"]["doe_id"]
    rows = list(csv.DictReader((D / "doe_matrix.csv").open(encoding="utf-8")))
    assert len(rows) == 3 and set(rows[0]) == {"doe_no", "run_key", "BRACKET_SHELL_T", "COVER_SHELL_T"}
    for row in rows:
        R = D / "approaches" / "doe_1" / row["run_key"]
        assert not (R / "m_1" / "update").exists()                                  # 형상 단계 생략
        assert f"#FAKE_PROP 1 {float(row['BRACKET_SHELL_T'])!r}" in (R / "m_3" / "material.inc").read_text()
        assert 1.14 <= float(row["BRACKET_SHELL_T"]) <= 1.26
        assert "BRACKET_SHELL_T" in (R / "m_1" / "native_params.xml").read_text()
    assert jd["result"]["run_count"] == 3


def test_set_doe_props_failure_is_skipped_run(native_env, monkeypatch):
    env = native_env()
    ps = native_set(env)
    _scan(env, ps["id"])
    _select(env, ps["id"], [{"name": "BRACKET_SHELL_T"}])
    monkeypatch.setenv("FAKE_PAICAD_FAIL_WHEN", "props_apply:PROP_THICKNESS_INVALID:BRACKET_SHELL_T>1.2")
    j = env.submit("TD_DOE_GEN", {"doe_label": "LHS", "num_runs": 4, "seed": 1, "param_set_id": ps["id"]})
    state = env.w.run_once_slot()
    jd = env.job(j["id"])
    D = env.sroot / "01_train" / "doe" / jd["result"]["doe_id"]
    rows = list(csv.DictReader((D / "doe_matrix.csv").open(encoding="utf-8")))
    hi = [r["run_key"] for r in rows if float(r["BRACKET_SHELL_T"]) > 1.2]
    assert hi and len(hi) < 4 and state == "SUCCEEDED", jd
    sk = {s["run_key"]: s for s in jd["result"]["skipped_runs"]}
    assert set(sk) == set(hi) and all(s["reason"] == "PROP_THICKNESS_INVALID" and s["category"] == "PROP" for s in sk.values())
    for rk in hi:
        R = D / "approaches" / "doe_1" / rk
        assert not (R / "m_3").exists() and json.loads((R / "SKIPPED.json").read_text())["step"] == "props"


def test_props_api_guards(native_env, predict_env):
    env = native_env()
    alt = env.param_set()
    r = env.c.get(f"{API}/param-sets/{alt['id']}/props", headers=P)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ENGINE_MISMATCH"
    ps = native_set(env)
    r = env.c.put(f"{API}/param-sets/{ps['id']}/props", headers=H("tok-general", write=True), json={"selected": []})
    assert r.status_code == 403, r.text
    r = env.c.put(f"{API}/param-sets/{ps['id']}/props", headers=PW, json={"selected": []})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PROPS_NOT_SCANNED"
