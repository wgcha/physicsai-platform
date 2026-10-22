"""v0.2.4 NV(native-vars.md V-NV-1·3~8): 세트 변수 정의 저장·리비전, ⑥·④ 그 자리 편집(`vars`) 스냅숏, Altair 경계."""

from __future__ import annotations

import json

import pytest
from helpers_native import native_set
from physicsai_test_support import API, H, pbs_command_cfg

from .fv_support import RESPS, resources

PW = H("tok-power", write=True)
P = H("tok-power")
NEW_CMD = ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"]
T01_CMD = ["{hw}", "-clientconfig", "hwplot.dat", "-b", "-c", "-tcl", "{curate_tcl}", "-config", "{config_json}"]


@pytest.fixture()
def nenv(native_env, fake_tools, tmp_path, monkeypatch):
    from physicsai_worker.steps import _collect

    monkeypatch.setattr(_collect, "COLLECT_STABLE_INTERVAL_S", 0.02)
    env = native_env(hpc=pbs_command_cfg(fake_tools, str(tmp_path / "ai_root")),
                     commands={"response_extract": NEW_CMD, "t01_curve_export": T01_CMD}, resources=resources(tmp_path))
    ps = native_set(env)
    env.set_responses(ps["id"], RESPS)
    env.ps = ps
    return env


def _S(env, ps):
    return env.sroot / "04_params" / ps["id"]


def _url(ps, q=""):
    return f"{API}/param-sets/{ps['id']}/variables{q}"


def _get(env, ps, q=""):
    r = env.c.get(_url(ps, q), headers=P)
    assert r.status_code == 200, r.text
    return r.json()


def _put(env, ps, rev, items, expect=200):
    r = env.c.put(_url(ps), headers=PW, json={"base_revision": rev, "variables": [{"name": n, "min": a, "max": b} for n, a, b in items]})
    assert r.status_code == expect, r.text
    return r.json()


def _db_params(env, ps):
    return env.sql("select parameters from param_sets where id=:i", i=ps["id"])[0][0]


# ---- V-NV-1 ---------------------------------------------------------------------------------------------


def test_v_nv_1_get_put_revisions_conflict_and_problems(nenv):
    env, ps = nenv, nenv.ps
    g = _get(env, ps)
    names = [v["name"] for v in g["variables"]]
    assert g["revision"] == 0 and g["editable"] is True and g["history"] == [] and g["train_source"] is None
    pool = {p["name"]: p for p in g["pool"]}
    assert set(names) <= set(pool) and "A_THK_1" in pool and pool["B_RIB_H_1"]["ref_locked"] is True
    assert pool["A_THK_1"]["feasible"]["min"] == 6 and pool["A_THK_1"]["train"] is None
    # 저장: 일부만 + 범위 변경
    r = _put(env, ps, 0, [("A_THK_1", 9.0, 11.0), ("C_HOLE_R_1", 3.9, 4.1)])
    assert r["revision"] == 1 and [v["name"] for v in r["variables"]] == ["A_THK_1", "C_HOLE_R_1"]
    assert [h["revision"] for h in r["history"]][0] == 1 or [h["revision"] for h in r["history"]] == [0, 1]
    S = _S(env, ps)
    assert (S / "vars" / "history" / "rev_0000.json").is_file() and (S / "vars" / "history" / "rev_0001.json").is_file()
    cur = json.loads((S / "vars" / "vars.json").read_text())
    assert cur["revision"] == 1 and [v["name"] for v in cur["variables"]] == ["A_THK_1", "C_HOLE_R_1"]
    pj = json.loads((S / "parameters.json").read_text())["parameters"]
    assert [(x["name"], x["min"], x["max"]) for x in pj] == [("A_THK_1", 9.0, 11.0), ("C_HOLE_R_1", 3.9, 4.1)]
    assert pj == _db_params(env, ps)                                             # 파일 = DB
    assert env.sql("select count(*) from audit_events where action='PARAM_SET_UPDATE' and target_id=:i", i=ps["id"])[0][0] >= 1
    # 이전 리비전 조회, 세트 요약
    old = _get(env, ps, "?revision=0")
    assert [v["name"] for v in old["variables"]] == names
    assert env.c.get(f"{API}/param-sets/{ps['id']}", headers=P).json()["native"]["vars_revision"] == 1
    assert env.c.get(_url(ps, "?revision=99"), headers=P).json()["detail"]["code"] == "NATIVE_VARS_REVISION_NOT_FOUND"
    # 낡은 base_revision → 409
    r = env.c.put(_url(ps), headers=PW, json={"base_revision": 0, "variables": [{"name": "A_THK_1", "min": 9, "max": 11}]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NATIVE_VARS_CONFLICT" and r.json()["detail"]["revision"] == 1
    # 검증 4종
    for items, code in ([([("NOPE", 1, 2)], "VAR_UNKNOWN"), ([("A_THK_1", 1, 2), ("A_THK_1", 1, 2)], "VAR_DUPLICATE"),
                         ([("A_THK_1", 5, 2)], "VAR_RANGE_INVALID"), ([], "VARS_EMPTY")]):
        r = env.c.put(_url(ps), headers=PW, json={"base_revision": 1, "variables": [{"name": n, "min": a, "max": b} for n, a, b in items]})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "NATIVE_VARS_INVALID", r.text
        assert code in [p["code"] for p in r.json()["detail"]["problems"]]
    # 일반 사용자 쓰기 금지
    r = env.c.put(_url(ps), headers=H("tok-general", write=True), json={"base_revision": 1, "variables": [{"name": "A_THK_1", "min": 9, "max": 11}]})
    assert r.status_code in (403, 404)
    # 범위가 학습·가능 범위 밖이어도 저장은 되고 경고만(PUT 응답 warnings)
    r = _put(env, ps, 1, [("A_THK_1", 1.0, 30.0)])
    assert r["revision"] == 2 and {w["code"] for w in r["warnings"]} >= {"VAR_OUT_OF_FEASIBLE"}
    # 복원: 리비전 0 정의를 새 리비전으로 저장
    r = _put(env, ps, 2, [(v["name"], v["min"], v["max"]) for v in old["variables"]])
    assert r["revision"] == 3 and [v["name"] for v in r["variables"]] == names


def _prepare(env, ps, expect="SUCCEEDED"):
    r = env.c.post(f"{API}/param-sets/{ps['id']}/native-prepare", headers=PW)
    assert r.status_code == 202, r.text
    assert env.w.run_once_slot() == expect, env.job(r.json()["job_id"])
    return env.job(r.json()["job_id"])


def test_v_nv_1_reprep_keeps_vars_subset_passes_and_missing_name_fails(nenv):
    env, ps = nenv, nenv.ps
    r = env.c.patch(f"{API}/param-sets/{ps['id']}", headers=PW, json={"geom_options": {"tag": {"tol_abs_mm": 0.08}}})
    assert r.status_code == 200, r.text
    _put(env, ps, 0, [("A_THK_1", 9.0, 11.0)])
    before = (_S(env, ps) / "vars" / "vars.json").read_bytes()
    _prepare(env, ps)                                                       # 부분집합 세트도 다시 준비 가능(같음 → 포함)
    assert (_S(env, ps) / "vars" / "vars.json").read_bytes() == before
    assert [x["name"] for x in _db_params(env, ps)] == ["A_THK_1"]
    assert _get(env, ps)["revision"] == 1
    # 풀에 없는 이름이 세트에 있으면 실패하고 세트는 그대로
    rows = _db_params(env, ps)
    env.sql("update param_sets set parameters=cast(:p as jsonb) where id=:i", i=ps["id"],
            p=json.dumps([*rows, {"name": "ZZ_GONE_1", "nominal": 1.0, "min": 0.5, "max": 2.0, "unit": "mm"}]))
    env.c.patch(f"{API}/param-sets/{ps['id']}", headers=PW, json={"geom_options": {"tag": {"tol_abs_mm": 0.09}}})
    jd = _prepare(env, ps, "FAILED")
    assert jd["failure_code"] == "PARAM_FEATURE_MISMATCH" and "ZZ_GONE_1" in jd["failure_message"]


# ---- ④ 일괄 예측(V-NV-3·5) --------------------------------------------------------------------------------

ALL3 = "A_THK_1,B_RIB_H_1,C_HOLE_R_1\n9.6,20,3.9\n10.0,20,4.0\n10.4,20,4.1\n"


def _prev(env, ps, source, vars_=None, expect=200, **kw):
    body = {"param_set_id": ps["id"], "source": source, **({"vars": vars_} if vars_ is not None else {}), **kw}
    r = env.c.post(f"{API}/studies/{env.sid}/predict-batches/preview", headers=PW, json=body)
    assert r.status_code == expect, r.text
    return r.json()


def _job(env, ps, source, vars_=None, expect=201):
    p = {"param_set_id": ps["id"], "multi_execution": 2, "source": source, **({"vars": vars_} if vars_ is not None else {})}
    return env.submit("PREDICT_BATCH", p, expect=expect)


def _codes(items):
    return [x["code"] for x in items]


def test_v_nv_5_batch_without_vars_is_unchanged_and_vars_edit_rows(nenv):
    env, ps = nenv, nenv.ps
    base = _prev(env, ps, {"kind": "table", "text": ALL3})
    assert base["problems"] == [] and base["count"] == 3 and base["excluded"] == []
    assert [v["name"] for v in base["var_rows"]] == ["A_THK_1", "B_RIB_H_1", "C_HOLE_R_1"] and {v["origin"] for v in base["var_rows"]} == {"set"}
    same = _prev(env, ps, {"kind": "table", "text": ALL3}, {})
    assert same["rows"] == base["rows"] and same["problems"] == []
    # exclude: 표 헤더 = 유효 변수만, 제외한 변수는 공칭
    ex = _prev(env, ps, {"kind": "table", "text": "A_THK_1,B_RIB_H_1\n9.6,20\n10.4,20\n"}, {"exclude": ["C_HOLE_R_1"]})
    assert ex["problems"] == [] and ex["excluded"] == ["C_HOLE_R_1"] and [v["name"] for v in ex["var_rows"]] == ["A_THK_1", "B_RIB_H_1"]
    bad = _prev(env, ps, {"kind": "table", "text": ALL3}, {"exclude": ["C_HOLE_R_1"]})            # 헤더에 제외 변수가 남음
    assert bad["problems"], bad
    # 세트 정의에 없는 이름 제외·추가는 problem
    assert _prev(env, ps, {"kind": "lhs", "count": 4}, {"exclude": ["NOPE"]})["problems"]
    assert _prev(env, ps, {"kind": "lhs", "count": 4}, {"add": ["NOPE"]})["problems"]
    # add: 세트를 줄인 뒤 풀 변수를 이 실행에만 추가(범위 = 피처 기본 범위, 세트 정의는 그대로)
    _put(env, ps, 0, [("A_THK_1", 9.0, 11.0)])
    ad = _prev(env, ps, {"kind": "lhs", "count": 4, "seed": 3}, {"add": ["C_HOLE_R_1"]})
    assert ad["problems"] == [] and [(v["name"], v["origin"]) for v in ad["var_rows"]] == [("A_THK_1", "set"), ("C_HOLE_R_1", "added")]
    assert set(ad["rows"][0]["values"]) == {"A_THK_1", "C_HOLE_R_1"}
    assert [x["name"] for x in _db_params(env, ps)] == ["A_THK_1"]                                   # 세트 정의 불변
    only = _prev(env, ps, {"kind": "lhs", "count": 4, "seed": 3})
    assert set(only["rows"][0]["values"]) == {"A_THK_1"} and only["excluded"] == []
    # 추가 + 제외 겹침·같은 이름 중복은 problem
    assert _prev(env, ps, {"kind": "lhs", "count": 4}, {"add": ["A_THK_1"]})["problems"]
    assert _prev(env, ps, {"kind": "lhs", "count": 4}, {"add": ["C_HOLE_R_1"], "exclude": ["C_HOLE_R_1"]})["problems"]


def test_v_nv_5_batch_range_warnings_and_out_of_range_basis(nenv):
    env, ps = nenv, nenv.ps
    # 모델의 학습 범위를 알 수 없음 → 안내(TRAIN_RANGE_UNKNOWN)만, 막지 않음
    p = _prev(env, ps, {"kind": "lhs", "count": 4, "seed": 1})
    assert "TRAIN_RANGE_UNKNOWN" in _codes(p["notes"]) and p["problems"] == []
    # 모핑 가능 범위(6~14) 밖 범위 → VAR_OUT_OF_FEASIBLE 경고(BOUNDS_OUT_OF_RANGE 아님), 값은 그대로
    p = _prev(env, ps, {"kind": "lhs", "count": 6, "seed": 1, "ranges": {"A_THK_1": [5.0, 15.0]}})
    assert p["problems"] == [] and "VAR_OUT_OF_FEASIBLE" in _codes(p["notes"]) and "RUNS_OUT_OF_FEASIBLE" in _codes(p["notes"])
    assert any(n.get("message") for n in p["notes"] if n["code"] == "VAR_OUT_OF_FEASIBLE")
    assert max(r["values"]["A_THK_1"] for r in p["rows"]) > 14
    # Native 일괄의 out_of_range 기준은 학습 범위 — 학습 범위를 모르면 세트 범위 밖 값만으로는 표시하지 않는다
    assert all(r["out_of_range"] == [] for r in p["rows"])


def test_v_nv_3_batch_snapshot_survives_set_edit_and_retry(nenv):
    env, ps = nenv, nenv.ps
    src = {"kind": "table", "text": "A_THK_1,B_RIB_H_1\n9.6,20\n10.4,20\n"}
    pj = _job(env, ps, src, {"exclude": ["C_HOLE_R_1"]})
    snap = pj["params"]["vars"]
    assert snap["excluded"] == ["C_HOLE_R_1"] and [v["name"] for v in snap["variables"]] == ["A_THK_1", "B_RIB_H_1"]
    bid = pj["params"]["batch_id"]
    # 작업이 돌기 전에 세트 정의를 바꿔도(리비전 1) 실행은 스냅숏을 쓴다
    _put(env, ps, 0, [("A_THK_1", 9.0, 11.0), ("C_HOLE_R_1", 3.9, 4.1)])
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(pj["id"])
    b = env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()
    assert b["parameters"] == ["A_THK_1", "B_RIB_H_1"] and b["vars"]["excluded"] == ["C_HOLE_R_1"] and b["vars"]["set_revision"] == 0
    assert b["status"] == "PREDICTING" and b["gen"]["done"] == 2
    run_dir = env.sql("select dir_rel from predict_batches where id=:i", i=bid)[0][0]
    for r in b["rows"]:
        v = json.loads((env.sroot / run_dir / r["run_key"] / "m_1" / "values.json").read_text())
        assert set(v["values"]) == {"A_THK_1", "B_RIB_H_1"}          # 제외 변수는 값 없음 = 공칭 유지(세트가 그 사이 C_HOLE_R_1을 넣었어도)
    # 하위 예측도 스냅숏 기준으로 끝까지 성공한다(세트 정의가 바뀐 뒤에도)
    for r in b["rows"]:
        assert env.w.run_once_slot() == "SUCCEEDED", env.job(r["job_id"])
    done = env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()
    assert done["status"] == "DONE" and done["parameters"] == ["A_THK_1", "B_RIB_H_1"]
    # 배치 목록 sampling 정보에는 vars 스냅숏이 새지 않는다(상세에만)
    assert "vars" not in (b["sampling"] or {}).get("meta", {})


def test_v_nv_8_altair_vars_rejected_and_unchanged(nenv):
    """Altair 부분 tpl(옛 것): v0.2.8부터 NATIVE_VARS_UNSUPPORTED는 폐지 — 같은 자리에서 TPL_SCOPE_PARTIAL(altair-vars.md AV-10)."""
    env = nenv
    alt = env.param_set()
    assert alt["engine"] == "altair"
    names = [p["name"] for p in alt["parameters"]]
    src = {"kind": "lhs", "count": 3}
    base = _prev(env, alt, src)
    assert base["problems"] == [] and base["var_rows"] == [] and base["excluded"] == [] and "TRAIN_RANGE_UNKNOWN" not in _codes(base["notes"])
    p = _prev(env, alt, src, {"exclude": [names[0]]})
    assert "TPL_SCOPE_PARTIAL" in _codes(p["problems"])
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "PREDICT_BATCH", "params": {
        "param_set_id": alt["id"], "multi_execution": 1, "source": src, "vars": {"exclude": [names[0]]}}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "TPL_SCOPE_PARTIAL", r.text
    g = env.c.get(f"{API}/param-sets/{alt['id']}/variables", headers=P)             # 조회는 허용(편집 불가 + 사유)
    assert g.status_code == 200 and g.json()["editable"] is False and g.json()["reason"] == "TPL_SCOPE_PARTIAL" and g.json()["engine"] == "altair"
    x = env.c.put(f"{API}/param-sets/{alt['id']}/variables", headers=PW, json={"base_revision": 0, "variables": []})
    assert x.status_code == 422 and x.json()["detail"]["code"] == "TPL_SCOPE_PARTIAL"


# ---- ⑥ 내장 최적화(V-NV-4) ---------------------------------------------------------------------------------


def _opt_body(env, ps, **kw):
    perfs = [*RESPS, {"name": "CornerStress", "unit": "MPa", "spec": {**RESPS[0]["spec"], "datatype": "Stress", "component": "vonMises"}}]
    env.set_responses(ps["id"], perfs)
    return {"param_set_id": ps["id"], "explore": {"kind": "new", "count": 5, "seed": 1},
            "objectives": [{"metric": "perf:MaxStress", "sense": "min"}, {"metric": "perf:MinDisp", "sense": "max"}],
            "weights": [50, 50], "iterations": 1, "candidates": 1, "tol_rel": 1e-9, "seed": 1, "multi_execution": 2, **kw}


def _opt_prev(env, body, expect=200):
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json=body)
    assert r.status_code == expect, r.text
    return r.json()


def test_v_nv_4_opt_preview_bounds_warnings_fixed_vs_excluded(nenv):
    env, ps = nenv, nenv.ps
    body = _opt_body(env, ps)
    base = _opt_prev(env, body)
    assert base["problems"] == [] and base["excluded"] == [] and set(base["free_variables"]) == {"A_THK_1", "B_RIB_H_1", "C_HOLE_R_1"}
    rows = {v["name"]: v for v in base["var_rows"]}
    assert rows["A_THK_1"]["base"] == {"min": 9.5, "max": 10.5} and rows["A_THK_1"]["feasible"]["max"] == 14 and rows["A_THK_1"]["train"] is None
    assert "TRAIN_RANGE_UNKNOWN" in _codes(base["var_notes"])
    assert [n["name"] for n in base["var_notes"] if n["code"] == "TRAIN_RANGE_UNKNOWN"] == [None]              # 안내는 name 없음
    assert [n["name"] for n in base["var_notes"] if n["code"] == "VAR_REF_LOCKED"] == ["B_RIB_H_1"]
    # 세트 범위 밖이지만 모핑 가능 범위 안: 막지 않고(BOUNDS_OUT_OF_RANGE 없음) 경고도 없다(학습 범위를 모르면 비교 안 함)
    p = _opt_prev(env, {**body, "bounds": {"A_THK_1": [7.0, 13.0]}})
    assert p["problems"] == [] and "VAR_OUT_OF_FEASIBLE" not in _codes(p["var_notes"])
    # 모핑 가능 범위 밖: 경고(이름 포함)만
    p = _opt_prev(env, {**body, "bounds": {"A_THK_1": [5.0, 15.0]}})
    assert p["problems"] == [] and [(n["code"], n.get("name")) for n in p["var_notes"] if n["code"] == "VAR_OUT_OF_FEASIBLE"] == [("VAR_OUT_OF_FEASIBLE", "A_THK_1")]
    # 고정(lo=hi)은 변수로 남고 fixed에 들어가며, 제외는 변수 목록에서 빠져 공칭 유지(fixed 아님)
    p = _opt_prev(env, {**body, "bounds": {"B_RIB_H_1": [20.0, 20.0]}, "vars": {"exclude": ["C_HOLE_R_1"]}})
    assert p["problems"] == [] and p["fixed"] == {"B_RIB_H_1": 20.0} and p["excluded"] == ["C_HOLE_R_1"]
    assert "C_HOLE_R_1" not in p["free_variables"] and "C_HOLE_R_1" not in p["fixed"] and "B_RIB_H_1" in [v["name"] for v in p["var_rows"]]
    # 잘못된 편집은 problem(코드 BOUNDS_INVALID 계열), 두 번 쓴 이름도
    assert _opt_prev(env, {**body, "vars": {"exclude": ["NOPE"]}})["problems"]
    assert _opt_prev(env, {**body, "vars": {"add": ["A_THK_1"]}})["problems"]
    # add: 세트를 줄이면 추가한 변수의 기본 범위는 피처 범위
    _put(env, ps, 0, [("A_THK_1", 9.0, 11.0)])
    p = _opt_prev(env, {**_opt_body(env, ps), "vars": {"add": ["C_HOLE_R_1"]}})
    assert p["problems"] == [] and set(p["free_variables"]) == {"A_THK_1", "C_HOLE_R_1"}
    assert {v["name"]: v["origin"] for v in p["var_rows"]} == {"A_THK_1": "set", "C_HOLE_R_1": "added"}
    assert _opt_prev(env, _opt_body(env, ps))["free_variables"] == ["A_THK_1"]


def test_v_nv_4_opt_create_snapshot_run_and_verify_warnings(nenv):
    env, ps = nenv, nenv.ps
    body = _opt_body(env, ps, vars={"exclude": ["C_HOLE_R_1"]}, bounds={"A_THK_1": [5.0, 15.0]})
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json=body)
    assert r.status_code == 201, r.text
    opt = r.json()
    assert opt["settings"]["vars"]["excluded"] == ["C_HOLE_R_1"] and "C_HOLE_R_1" not in opt["settings"]["names"]
    assert opt["settings"]["bounds"]["A_THK_1"] == [5.0, 15.0] and "VAR_OUT_OF_FEASIBLE" in _codes(opt["warnings"])
    _put(env, ps, 0, [("A_THK_1", 9.0, 11.0)])                     # 실행 중 세트 정의가 바뀌어도 스냅숏 기준
    for _ in range(60):
        if not env.sql("select id from jobs where state='QUEUED' and lane='SLOT' order by queue_seq limit 1"):
            break
        env.w.run_once_slot()
    d = env.c.get(f"{API}/surrogate-opts/{opt['id']}", headers=P).json()
    assert d["status"] == "DONE", (d["status"], d.get("progress_text"))
    assert [p["name"] for p in d["parameters"]] == ["A_THK_1", "B_RIB_H_1"] and d["settings"]["vars"]["set_revision"] == 0
    pb = env.batch(env.sql("select id from predict_batches where study_id=:s", s=env.sid)[0][0])
    assert pb["source_meta"]["vars"]["excluded"] == ["C_HOLE_R_1"]                  # 소유 배치에도 스냅숏
    R = env.sroot / pb["dir_rel"] / pb["runs"][0]["run_key"]
    assert set(json.loads((R / "m_1" / "values.json").read_text())["values"]) == {"A_THK_1", "B_RIB_H_1"}
    # 추가 검증: Native는 최적화 범위·가능 범위 밖 점도 막지 않고 경고
    pt = {"A_THK_1": 15.0, "B_RIB_H_1": 20.0}
    r = env.c.post(f"{API}/surrogate-opts/{opt['id']}/verify", headers=PW, json={"points": [{"values": pt}]})
    assert r.status_code == 201, r.text
    assert "VAR_OUT_OF_FEASIBLE" in _codes(r.json()["warnings"]) or "VAR_OUT_OF_BOUNDS" in _codes(r.json()["warnings"])
    assert {w["name"] for w in r.json()["warnings"]} >= {"A_THK_1"}


def test_v_nv_4_multi_baseline_vars_rejected(nenv, monkeypatch):
    from .test_native_multi import B2_TOPO, _add

    env, ps = nenv, nenv.ps
    _add(env, ps["id"], "B2", B2_TOPO, monkeypatch)
    # 다중 baseline: 세트 정의 편집·실행 편집 모두 불가(NV-C0), 범위 경고 전환만
    r = env.c.put(_url(ps), headers=PW, json={"base_revision": 0, "variables": [{"name": "A_THK_1", "min": 9, "max": 11}]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NATIVE_VARS_MULTI_UNSUPPORTED", r.text
    g = _get(env, ps)
    assert g["editable"] is False and g["reason"]


def test_v_nv_8_altair_opt_unchanged_and_vars_rejected(nenv):
    env = nenv
    alt = env.param_set()
    env.set_responses(alt["id"], RESPS)
    names = [p["name"] for p in alt["parameters"]]
    lo, hi = alt["parameters"][0]["min"], alt["parameters"][0]["max"]
    body = {"param_set_id": alt["id"], "explore": {"kind": "new", "count": 5, "seed": 1},
            "objective": {"metric": "perf:MaxStress", "sense": "min"}, "iterations": 1, "candidates": 1, "seed": 1}
    ok = _opt_prev(env, body)
    assert ok["problems"] == [] and ok["var_rows"] == [] and ok["var_notes"] == [] and ok["excluded"] == []
    out = _opt_prev(env, {**body, "bounds": {names[0]: [lo - 1.0, hi + 1.0]}})                    # Altair: 기존 BOUNDS_OUT_OF_RANGE 그대로
    assert "BOUNDS_OUT_OF_RANGE" in _codes(out["problems"]) and out["var_notes"] == []
    v = _opt_prev(env, {**body, "vars": {"exclude": [names[0]]}})
    assert "TPL_SCOPE_PARTIAL" in _codes(v["problems"]) and v["var_rows"] == []
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json={**body, "vars": {"exclude": [names[0]]}})
    assert r.status_code == 422 and "TPL_SCOPE_PARTIAL" in _codes(r.json()["detail"]["problems"]), r.text


# ---- ①-3 세트 DOE(V-NV-7) -----------------------------------------------------------------------------------


def test_v_nv_7_set_doe_records_vars_snapshot_and_ignores_later_edit(nenv):
    import csv

    env, ps = nenv, nenv.ps
    _put(env, ps, 0, [("A_THK_1", 9.0, 11.0), ("C_HOLE_R_1", 3.9, 4.1)])
    j = env.submit("TD_DOE_GEN", {"doe_label": "LHS", "num_runs": 4, "seed": 1, "param_set_id": ps["id"]})
    assert [v["name"] for v in j["params"]["vars"]["variables"]] == ["A_THK_1", "C_HOLE_R_1"] and j["params"]["vars"]["set_revision"] == 1
    _put(env, ps, 1, [("B_RIB_H_1", 19.0, 21.0)])                  # 작업 실행 전에 세트 정의가 바뀐다
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    jd = env.job(j["id"])
    D = env.sroot / "01_train" / "doe" / jd["result"]["doe_id"]
    rows = list(csv.DictReader((D / "doe_matrix.csv").open(encoding="utf-8")))
    assert {"A_THK_1", "C_HOLE_R_1"} <= set(rows[0]) and "B_RIB_H_1" not in rows[0]
    assert all(9.0 <= float(r["A_THK_1"]) <= 11.0 and 3.9 <= float(r["C_HOLE_R_1"]) <= 4.1 for r in rows)


# ---- 학습 범위(V-NV-6) --------------------------------------------------------------------------------------


def _set_doe(env, ps, items):
    """세트 정의(items) 저장 → ①-3 세트 DOE 1개(READY, 피처 파일 + 범위 스냅숏 보유) → doe_id."""
    _put(env, ps, _get(env, ps)["revision"], items)
    j = env.submit("TD_DOE_GEN", {"doe_label": "LHS", "num_runs": 4, "seed": 1, "param_set_id": ps["id"]})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    return env.job(j["id"])["result"]["doe_id"]


def _link_dataset(env, source_path):
    """데이터셋 행을 만들어 Final 모델에 연결(학습 범위 추적 경로: 모델 → 데이터셋.source_path → DOE)."""
    env.sql("insert into datasets(id, study_id, source_path, seed, split_group, options_json, status, created_by, created_by_name)"
            " values ('ds-nv', :s, :p, 1, 'file', cast('{}' as jsonb), 'READY', 'u-power', '파워')", s=env.sid, p=str(source_path))
    env.sql("update models set dataset_id='ds-nv' where id=:m", m=env.model_id)


def test_v_nv_6_train_range_from_dataset_doe_union_and_warnings(nenv):
    """모델 → 데이터셋 → ① DOE 합집합(같은 피처만). 학습 범위 밖 범위·값은 VAR_OUT_OF_TRAIN·out_of_range(학습 범위 기준)."""
    env, ps = nenv, nenv.ps
    g0 = _get(env, ps, f"?model_id={env.model_id}")
    assert "TRAIN_RANGE_UNKNOWN" in _codes(g0["notes"]) and g0["train_source"] is None and all(p["train"] is None for p in g0["pool"])
    d1 = _set_doe(env, ps, [("A_THK_1", 9.0, 11.0), ("C_HOLE_R_1", 3.9, 4.1)])
    d2 = _set_doe(env, ps, [("A_THK_1", 12.0, 13.0)])
    _link_dataset(env, env.sroot / "01_train" / "doe" / d1)                                  # DOE 폴더 하나 = 그 DOE만
    g = _get(env, ps, f"?model_id={env.model_id}")
    tr = {p["name"]: p["train"] for p in g["pool"]}
    assert g["train_source"]["doe_ids"] == [d1] and tr["A_THK_1"] == {"min": 9.0, "max": 11.0} 
    assert tr["B_RIB_H_1"] == {"min": 20.0, "max": 20.0}                                     # DOE에서 움직이지 않은 변수 = 공칭 고정
    assert tr["C_HOLE_R_1"] == {"min": 3.9, "max": 4.1}
    env.sql("update datasets set source_path=:p where id='ds-nv'", p=str(env.sroot / "01_train" / "doe"))   # doe 폴더 자체 = 전체 합집합
    g = _get(env, ps, f"?model_id={env.model_id}")
    assert sorted(g["train_source"]["doe_ids"]) == sorted([d1, d2])
    assert {p["name"]: p["train"] for p in g["pool"]}["A_THK_1"] == {"min": 9.0, "max": 13.0}
    assert "TRAIN_RANGE_UNKNOWN" not in _codes(g["notes"])
    # ⑥: 학습 범위(9~13) 밖 범위 → VAR_OUT_OF_TRAIN(이름 포함), 막지 않음. 범위 안이면 경고 없음
    _put(env, ps, _get(env, ps)["revision"], [("A_THK_1", 9.5, 10.5)])
    body = _opt_body(env, ps)
    p = _opt_prev(env, {**body, "bounds": {"A_THK_1": [8.0, 12.0]}})
    assert p["problems"] == [] and [n["name"] for n in p["var_notes"] if n["code"] == "VAR_OUT_OF_TRAIN"] == ["A_THK_1"]
    assert {v["name"]: v["train"] for v in p["var_rows"]}["A_THK_1"] == {"min": 9.0, "max": 13.0}
    assert "VAR_OUT_OF_TRAIN" not in _codes(_opt_prev(env, {**body, "bounds": {"A_THK_1": [9.5, 12.0]}})["var_notes"])
    # ④: 일괄 out_of_range = 학습 범위 기준(세트 범위 9.5~10.5 안인 값도 학습 범위 밖이면 표시)
    _put(env, ps, _get(env, ps)["revision"], [("A_THK_1", 6.0, 14.0), ("C_HOLE_R_1", 3.9, 4.1)])
    pv = _prev(env, ps, {"kind": "table", "text": "A_THK_1,C_HOLE_R_1\n8.5,4.0\n10.0,4.0\n13.5,4.0\n"})
    assert [r["out_of_range"] for r in pv["rows"]] == [["A_THK_1"], [], ["A_THK_1"]]
    assert "VAR_OUT_OF_TRAIN" in _codes(pv["notes"]) and pv["problems"] == []
    pm = _prev(env, ps, {"kind": "table", "text": "A_THK_1,C_HOLE_R_1\n8.5,4.0\n"}, model_id=env.model_id)
    assert pm["rows"][0]["out_of_range"] == ["A_THK_1"]


def test_v_nv_5_train_doe_uses_doe_header_and_rejects_vars(nenv):
    env, ps = nenv, nenv.ps
    doe_id = _set_doe(env, ps, [("A_THK_1", 9.0, 11.0), ("C_HOLE_R_1", 3.9, 4.1)])
    rel = env.sql("select dir_rel from train_does where id=:i", i=doe_id)[0][0]
    (env.sroot / rel / "samples.csv").write_text("run_key,A_THK_1,C_HOLE_R_1\nrun__1,9.5,4.0\nrun__2,10.5,4.05\n", encoding="utf-8")
    env.sql("update train_does set sample_status='PARSED', samples_rel=:r where id=:i", r=rel + "samples.csv", i=doe_id)
    _put(env, ps, _get(env, ps)["revision"], [("A_THK_1", 9.0, 11.0), ("B_RIB_H_1", 19.0, 21.0)])      # 세트 정의 ≠ DOE 변수
    src = {"kind": "train_doe", "doe_id": doe_id}
    p = _prev(env, ps, src)
    assert p["problems"] == [] and p["count"] == 2 and "VARS_FROM_DOE" in _codes(p["notes"])
    assert [v["name"] for v in p["var_rows"]] == ["A_THK_1", "C_HOLE_R_1"] and p["excluded"] == ["B_RIB_H_1"]
    assert set(p["rows"][0]["values"]) == {"A_THK_1", "C_HOLE_R_1"}
    assert _prev(env, ps, src, {"exclude": ["A_THK_1"]})["problems"]                                   # 그 자리 편집은 거부
    j = _job(env, ps, src)
    assert [v["name"] for v in j["params"]["vars"]["variables"]] == ["A_THK_1", "C_HOLE_R_1"]
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    b = env.c.get(f"{API}/predict-batches/{j['params']['batch_id']}", headers=P).json()
    assert b["parameters"] == ["A_THK_1", "C_HOLE_R_1"] and b["gen"]["done"] == 2
    # DOE 헤더에 형상 변수가 아닌 이름이 있으면 problem
    (env.sroot / rel / "samples.csv").write_text("run_key,A_THK_1,ZZ_NOPE_1\nrun__1,9.5,1\n", encoding="utf-8")
    assert _prev(env, ps, src)["problems"]


@pytest.mark.parametrize("src", [{"kind": "lhs", "count": 6, "seed": 7}, {"kind": "lhs_opt", "count": 6, "seed": 7},
                                 {"kind": "sobol", "count": 8, "seed": 7}, {"kind": "fullfact"}, {"kind": "fracfact"},
                                 {"kind": "pb"}, {"kind": "bbd"}, {"kind": "ccd"}])
def test_v_nv_5_no_edit_rows_identical_for_all_sampling_kinds(nenv, src):
    """`vars` 없음 = 빈 편집 = 세트 정의 그대로 — 같은 seed에서 행 값이 같고(out_of_range는 학습 범위 기준이라 제외), 세트 변수 3개 전부 사용."""
    env, ps = nenv, nenv.ps
    a, b = _prev(env, ps, src), _prev(env, ps, src, {"add": [], "exclude": []})
    assert a["problems"] == [] and a["count"] > 0
    va = [(r["run_key"], r["values"]) for r in a["rows"]]
    assert va == [(r["run_key"], r["values"]) for r in b["rows"]] and set(va[0][1]) == {"A_THK_1", "B_RIB_H_1", "C_HOLE_R_1"}
