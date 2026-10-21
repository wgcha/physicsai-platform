"""extract-filter.md §6.7 ④ native 세트 등록(V-EF-11·V-EF-12): extract_filter 요청 → NP_PREP가 폴더의 준비 피처 파일·parameters.json을
쓰지 않고 NP_EXTRACT 실행(PARAMS_JSON_IGNORED), 조건은 S/native/extract/parameter_features.json filter에만 기록, ParamSet.native.extract_filter·
features 응답 filter, reprep·baselines 요청의 extract_filter 422, baseline 추가 조건 승계, from-train 승계, tag 해시·STALE 불변. 가짜 paicad."""

from __future__ import annotations

import json

from helpers_native import make_project
from helpers_stage1 import job, submit
from physicsai_test_support import API, H, read_record

PW = H("tok-power", write=True)
P = H("tok-power")

FILTER = {"groups": ["thickness", "position"], "conditions": {"thickness_mm": {"min": 2, "max": 30}, "fillet_radius_min_mm": 1},
          "draft_max_deg": 5}
NORM = {"groups": ["thickness", "position"], "conditions": {"thickness_mm": {"min": 2.0, "max": 30.0}}, "draft_max_deg": 5.0}
PARAMS_JSON = {"parameters": [{"name": "A_THK_1", "nominal": 10, "min": 8, "max": 12}, {"name": "B_RIB_H_1", "nominal": 20, "min": 18, "max": 22},
                              {"name": "C_HOLE_R_1", "nominal": 4, "min": 3, "max": 5}]}


def _reg(env, proj, expect=202, **kw):
    r = env.c.post(f"{API}/studies/{env.sid}/param-sets", headers=PW, json={"path": str(proj), "mode": "discover", "engine": "native", **kw})
    assert r.status_code == expect, r.text
    return r.json()


def _run(env, out):
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(out["job_id"])
    return env.job(out["job_id"])


def _ps(env, jd):
    return env.c.get(f"{API}/param-sets/{jd['result']['param_set_id']}", headers=P).json()


def _json(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _filtered_set(env, **kw):
    proj = make_project(env.imports, **kw)
    out = _reg(env, proj, extract_filter=FILTER)
    return proj, _run(env, out), out


def test_register_with_filter_extracts_and_records(native_env, fake_record):
    env = native_env()
    proj = make_project(env.imports, params_json=PARAMS_JSON)
    first = _reg(env, proj)  # 필터 없이 한 번 등록해 준비 피처 파일을 폴더에 둔다
    jd0 = _run(env, first)
    ext0 = env.sroot / "04_params" / jd0["result"]["param_set_id"] / "native" / "extract"
    for n in ("parameter_features.json", "parameter_extracted.xml"):
        (proj / n).write_bytes((ext0 / n).read_bytes())
    ps0 = _ps(env, jd0)
    assert ps0["native"]["extract_filter"] is None and "PARAMS_JSON_IGNORED" not in [w["code"] for w in env.job(first["job_id"])["warnings"]]
    out = _reg(env, proj, extract_filter=FILTER)
    jd = _run(env, out)
    assert jd["params"]["extract_filter"] == NORM  # 서버 정규화(미선택 그룹 fillet 조건 제거)
    st = env.steps(out["job_id"])
    assert st["NP_EXTRACT"]["state"] == "SUCCEEDED" and st["NP_TAG"]["state"] == "SUCCEEDED"  # 준비 피처 파일이 있어도 항상 실행
    assert "PARAMS_JSON_IGNORED" in [w["code"] for w in jd["warnings"]]
    ps = _ps(env, jd)
    assert ps["native"]["extract_filter"] == {"groups": ["thickness", "position"], "draft_max_deg": 5.0,
                                               "conditions": {"thickness_mm": {"min": 2.0, "max": 30.0}, "face_area_min_mm2": None,
                                                              "height_mm": None, "position_min_size_mm": None, "hole_radius_min_mm": None,
                                                              "fillet_radius_min_mm": None}}
    # parameters.json 범위를 쓰지 않았다(features range) — 이름 집합 불일치(PARAM_FEATURE_MISMATCH) 없이 등록됨
    by = {p["name"]: p for p in ps["parameters"]}
    assert set(by) == {"A_THK_1", "B_RIB_U_1", "B_RIB_V_1"} and (by["A_THK_1"]["min"], by["A_THK_1"]["max"]) == (9.5, 10.5)
    S = env.sroot / "04_params" / ps["id"]
    feats = _json(S / "native" / "extract" / "parameter_features.json")
    assert feats["filter"] == {"types": ["THICKNESS", "RIB_THICKNESS", "POCKET_WIDTH", "HOLE_POS_U", "HOLE_POS_V", "RIB_POS_U", "RIB_POS_V"],
                               "thickness_mm": {"min": 2.0, "max": 30.0}, "draft_max_deg": 5.0}
    assert (S / "native" / "extract" / "extract_stats.json").is_file()
    run = _json(S / "native" / "options_run.json")["extract"]
    assert run["filter"] == {k: v for k, v in feats["filter"].items() if k != "draft_max_deg"} and run["draft_max_deg"] == 5.0
    assert "filter" not in _json(S / "native" / "options.json") and "filter" not in _json(S / "native" / "options.json").get("extract", {})
    f = env.c.get(f"{API}/param-sets/{ps['id']}/features", headers=P).json()
    assert f["filter"]["groups"] == ["thickness", "position"] and f["filter"]["draft_max_deg"] == 5.0
    assert [x["name"] for x in f["features"]] == ["A_THK_1", "A_THK_2", "B_RIB_U_1", "B_RIB_V_1"]
    # DB에는 조건 열 없음(세트 행) — 조건은 파일이 단일 출처
    cols = {r[0] for r in env.sql("select column_name from information_schema.columns where table_name='param_sets'")}
    assert not any("filter" in c for c in cols)
    # 한국어 로그 요약 + 작업 result
    assert jd["result"]["extract_summary"]["types"]["THICKNESS"]["kept"] == 2
    log = (env.sroot / "logs" / out["job_id"] / "step_02_NP_EXTRACT.log").read_text(encoding="utf-8")
    assert "두께: 판정 2 · 채택 2" in log and "하이라이트 PNG 4장" in log
    nplog = (env.sroot / "logs" / out["job_id"] / "step_01_NP_PREP.log").read_text(encoding="utf-8")
    assert "추출 조건이 지정되어 준비된 피처 파일을 쓰지 않습니다" in nplog


def test_tag_hash_and_stale_unchanged_by_filter(native_env):
    """tag 절 sha256은 영향 없음 → 같은 입력의 필터 있음·없음 세트가 같은 tag_options_sha256, STALE 판정 불변."""
    env = native_env()
    plain = _ps(env, _run(env, _reg(env, make_project(env.imports / "a"))))
    _proj, jd, _out = _filtered_set(env)
    filt = _ps(env, jd)
    hash_of = lambda ps: _json(env.sroot / "04_params" / ps["id"] / "native" / "prep.json")["tag_options_sha256"]  # noqa: E731
    assert hash_of(plain) == hash_of(filt)
    assert filt["native"]["prep_status"] == "READY"
    r = env.c.patch(f"{API}/param-sets/{filt['id']}", headers=PW, json={"geom_options": {"tag": {"tol_abs_mm": 0.08}}})
    assert r.json()["native"]["prep_status"] == "STALE"
    # 조건 자체는 STALE 사유가 아니다
    r = env.c.get(f"{API}/param-sets/{plain['id']}", headers=P)
    assert r.json()["native"]["prep_status"] == "READY"


def test_no_filter_registration_is_current_behavior(native_env, fake_record):
    """V-EF-1·11: extract_filter 생략 → options_run.json에 filter 없음, 준비 피처 파일·parameters.json 현행 사용."""
    env = native_env()
    proj = make_project(env.imports, params_json=PARAMS_JSON)
    jd = _run(env, _reg(env, proj))
    S = env.sroot / "04_params" / jd["result"]["param_set_id"]
    assert "filter" not in _json(S / "native" / "options_run.json")["extract"] and "filter" not in _json(S / "native" / "extract" / "parameter_features.json")
    assert "extract_filter" not in jd["params"] and _ps(env, jd)["native"]["extract_filter"] is None
    assert "PARAMS_JSON_IGNORED" not in [w["code"] for w in jd["warnings"]]
    assert {p["name"]: (p["min"], p["max"]) for p in _ps(env, jd)["parameters"]}["A_THK_1"] == (8, 12)  # parameters.json 범위 사용


def test_422_codes(native_env):
    """altair·shell·shell_only → EXTRACT_FILTER_UNSUPPORTED, 값 오류 → EXTRACT_FILTER_INVALID, geom_options.extract.filter → GEOM_OPTIONS_INVALID,
    reprep·baselines 요청의 extract_filter → EXTRACT_FILTER_INVALID. 어느 것도 작업을 만들지 않는다."""
    env = native_env()
    proj = make_project(env.imports)
    for kw in ({"engine": "altair"}, {"engine": "altair", "mode": "folder"}, {"kind": "shell"}, {"shell_only": True}):
        body = {"path": str(proj), "mode": "discover", "engine": "native", "extract_filter": FILTER, **kw}
        r = env.c.post(f"{API}/studies/{env.sid}/param-sets", headers=PW, json=body)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "EXTRACT_FILTER_UNSUPPORTED", (kw, r.text)
    r = env.c.post(f"{API}/studies/{env.sid}/param-sets", headers=PW,
                   json={"path": str(proj), "mode": "discover", "engine": "native", "extract_filter": {"groups": []}})
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "EXTRACT_FILTER_INVALID" and d["problems"] == [{"key": "groups", "message": "찾을 종류를 하나 이상 고르세요"}]
    r = env.c.post(f"{API}/studies/{env.sid}/param-sets", headers=PW,
                   json={"path": str(proj), "mode": "discover", "engine": "native", "geom_options": {"extract": {"filter": {"types": ["THICKNESS"]}}}})
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "GEOM_OPTIONS_INVALID"
    assert any(p["key"] == "extract.filter" and "geom_options가 아니라 등록 요청의 extract_filter" in p["message"] for p in d["problems"])
    jd = _run(env, _reg(env, proj))
    psid = jd["result"]["param_set_id"]
    r = env.c.patch(f"{API}/param-sets/{psid}", headers=PW, json={"geom_options": {"extract": {"filter": {"types": ["THICKNESS"]}}}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "GEOM_OPTIONS_INVALID"
    fixed = "등록된 세트의 추출 조건은 바꿀 수 없습니다 — 새 세트로 등록하세요"
    r = env.c.post(f"{API}/param-sets/{psid}/native-prepare", headers=PW, json={"extract_filter": FILTER})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "EXTRACT_FILTER_INVALID" and r.json()["detail"]["message"] == fixed
    r = env.c.post(f"{API}/param-sets/{psid}/baselines", headers=PW,
                   json={"id": "B2", "path": str(proj), "extract_filter": {"groups": ["fillet"]}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "EXTRACT_FILTER_INVALID"
    # 본문 없는 native-prepare는 현행 그대로 202
    r = env.c.post(f"{API}/param-sets/{psid}/native-prepare", headers=PW)
    assert r.status_code == 202, r.text
    assert env.w.run_once_slot() == "SUCCEEDED"
    assert not any(j["job_type"] == "PARAM_SET_NATIVE" and j["state"] == "FAILED" for j in env.c.get(f"{API}/jobs", params={"study_id": env.sid}, headers=P).json())


def test_add_baseline_inherits_base_filter(native_env, monkeypatch):
    env = native_env()
    _proj, jd, _out = _filtered_set(env)
    psid = jd["result"]["param_set_id"]
    feats = [
        {"name": "A_THK_1", "type": "THICKNESS", "body": "A", "nominal": 10.0, "unit": "mm", "range": {"min": 9.5, "max": 10.5, "ratio": 0.05},
         "group": None, "ref": {"rule": "contact_fixed", "provisional": True, "locked": False}},
        {"name": "B_RIB_H_1", "type": "RIB_HEIGHT", "body": "A", "nominal": 20.0, "unit": "mm", "range": {"min": 19.0, "max": 21.0, "ratio": 0.05},
         "group": None, "ref": {"rule": "contact_fixed", "provisional": True, "locked": False}},
        {"name": "C_HOLE_R_1", "type": "HOLE_RADIUS", "body": "A", "nominal": 4.0, "unit": "mm", "range": {"min": 3.8, "max": 4.2, "ratio": 0.05},
         "group": None, "ref": {"rule": "contact_fixed", "provisional": True, "locked": False}},
    ]
    monkeypatch.setenv("FAKE_PAICAD_FEATURES", json.dumps(feats))
    proj2 = make_project(env.imports / "p2", params_json=PARAMS_JSON)
    r = env.c.post(f"{API}/param-sets/{psid}/baselines", headers=PW, json={"id": "B2", "path": str(proj2)})
    assert r.status_code == 202, r.text
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(r.json()["job_id"])
    S = env.sroot / "04_params" / psid
    B = S / "baselines" / "B2" / "native"
    f2 = _json(B / "extract" / "parameter_features.json")
    base = _json(S / "native" / "extract" / "parameter_features.json")
    assert f2["filter"] == base["filter"]  # 기준 baseline 조건 그대로(draft 포함)
    assert [f["type"] for f in f2["features"]] == ["THICKNESS"]  # 높이·구멍 반경은 제외(선택 안 한 그룹)
    assert _json(B / "options_run.json")["extract"]["draft_max_deg"] == 5.0
    assert env.job(r.json()["job_id"])["result"]["extract_summary"]["filter_applied"] is True


def test_add_baseline_without_base_filter_keeps_current(native_env, monkeypatch):
    env = native_env()
    ps = _ps(env, _run(env, _reg(env, make_project(env.imports))))
    proj2 = make_project(env.imports / "p2")
    r = env.c.post(f"{API}/param-sets/{ps['id']}/baselines", headers=PW, json={"id": "B2", "path": str(proj2)})
    assert r.status_code == 202, r.text
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(r.json()["job_id"])
    B = env.sroot / "04_params" / ps["id"] / "baselines" / "B2" / "native"
    assert "filter" not in _json(B / "options_run.json")["extract"] and "filter" not in _json(B / "extract" / "parameter_features.json")


def test_from_train_inherits_train_filter(native_env, fake_record):
    """①→④ from-train: D/native/extract/ 복사로 ①-1 조건 승계(paicad 실행 없음)."""
    env = native_env(final_model=False)
    c, w, sid = env.c, env.w, env.sid
    proj = make_project(env.imports)
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(proj / "bracket.step"), "engine": "native", "extract_filter": FILTER})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    j = submit(c, sid, "TD_DOE_GEN", {"doe_label": "LHS", "num_runs": 3, "seed": 3, "radioss_assem_path": str(proj / "assem")})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    doe_id = job(c, j["id"])["result"]["doe_id"]
    before = len(read_record(fake_record))
    r = c.post(f"{API}/studies/{sid}/param-sets/from-train", headers=PW, json={"doe_id": doe_id, "runs": "all"})
    assert r.status_code == 201, r.text
    ps = r.json()
    assert ps["native"]["extract_filter"]["groups"] == ["thickness", "position"] and ps["native"]["extract_filter"]["draft_max_deg"] == 5.0
    assert len(read_record(fake_record)) == before
    f = c.get(f"{API}/param-sets/{ps['id']}/features", headers=P).json()
    assert f["filter"]["groups"] == ["thickness", "position"]
