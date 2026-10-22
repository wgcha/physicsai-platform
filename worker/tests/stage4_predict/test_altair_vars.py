"""v0.2.8 Altair 변수 공간(altair-vars.md V-AV-4~8): 전체 tpl 템플릿의 변수 정의 API·⑥④ 그 자리 편집·학습 범위·회귀.

Native와 같은 정의·API(native-vars.md)를 Altair 전체 tpl 세트가 쓴다 — 풀 = tpl 선언, 렌더 = 실행 변수 값 ∪ 나머지 공칭(fill_nominal).
"""

from __future__ import annotations

import json
import re
from uuid import uuid4

import pytest
from physicsai_test_support import API, H, pbs_command_cfg

from .fv_support import RESPS, resources

PW = H("tok-power", write=True)
P = H("tok-power")

# 전체 tpl: 사용(THK_1 연속·N_RIB 정수) + 미사용 고정(RIB_H·HOLE_R). 세트 정의(parameters.json)는 THK_1·N_RIB.
FULL_TPL = """﻿{parameter(var_1, "THK_1", 3.0, 2.0, 5.0)}
{parameter(var_2, "N_RIB", 4, 2, 8)}
{parameter(var_3, "RIB_H", 20.0, 20.0, 20.0)}
{parameter(var_4, "HOLE_R", 4.0, 4.0, 4.0)}
# physicsai-tpl scope=full v=1
#***************************************************************
dir_file_prt = r"./bracket.x_t"
dir_file_export = "EPS_mesh_0000.rad"
thickness = {var_1, %8.4f}
<paramitem Name="N_RIB" NewValue="{var_2, %3i}" Value="4"/>
<paramitem Name="RIB_H" NewValue="{var_3, %8.4f}" Value="20.0"/>
<paramitem Name="HOLE_R" NewValue="{var_4, %8.4f}" Value="4.0"/>
"""
POOL = ["THK_1", "N_RIB", "RIB_H", "HOLE_R"]


NEW_CMD = ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"]
T01_CMD = ["{hw}", "-clientconfig", "hwplot.dat", "-b", "-c", "-tcl", "{curate_tcl}", "-config", "{config_json}"]


@pytest.fixture()
def aenv(predict_env, fake_tools, tmp_path):
    env = predict_env(hpc=pbs_command_cfg(fake_tools, str(tmp_path / "ai_root")),
                      commands={"response_extract": NEW_CMD, "t01_curve_export": T01_CMD}, resources=resources(tmp_path))
    ps = env.param_set(tpl=FULL_TPL)
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


def _put_raw(env, ps, rev, items):
    return env.c.put(_url(ps), headers=PW, json={"base_revision": rev, "variables": [{"name": n, "min": a, "max": b} for n, a, b in items]})


def _put(env, ps, rev, items):
    r = _put_raw(env, ps, rev, items)
    assert r.status_code == 200, r.text
    return r.json()


def _codes(items):
    return [x["code"] for x in items]


def _prev(env, ps, source, vars_=None, expect=200, **kw):
    body = {"param_set_id": ps["id"], "source": source, **({"vars": vars_} if vars_ is not None else {}), **kw}
    r = env.c.post(f"{API}/studies/{env.sid}/predict-batches/preview", headers=PW, json=body)
    assert r.status_code == expect, r.text
    return r.json()


def _job(env, ps, source, vars_=None, expect=201):
    p = {"param_set_id": ps["id"], "multi_execution": 2, "source": source, **({"vars": vars_} if vars_ is not None else {})}
    return env.submit("PREDICT_BATCH", p, expect=expect)


def _scripts(env, j) -> list[str]:
    """실행한 ④ 일괄의 run별 렌더 스크립트 본문(run 순서)."""
    bid = j["params"]["batch_id"]
    b = env.c.get(f"{API}/predict-batches/{bid}", headers=P).json()
    rel = env.sql("select dir_rel from predict_batches where id=:i", i=bid)[0][0]
    name = env.lc.settings.predict.rendered_script_name
    return [(env.sroot / rel / r["run_key"] / "m_1" / name).read_text() for r in b["rows"]]


def _items(text: str) -> dict[str, str]:
    return {k: v.strip() for k, v in re.findall(r'<paramitem\s+Name="([^"]*)"\s+NewValue="([^"]*)"', text)}


# ---- V-AV-4: 변수 정의 API ------------------------------------------------------------------------------------


def test_v_av_4_full_set_get_pool_put_revision_and_integer_check(aenv):
    env, ps = aenv, aenv.ps
    s0 = env.c.get(f"{API}/param-sets/{ps['id']}", headers=P).json()
    assert s0["engine"] == "altair" and (s0["vars_scope"], s0["vars_revision"], s0["vars_count"]) == ("full", 0, 2)
    g = _get(env, ps)
    assert g["engine"] == "altair" and g["editable"] is True and g["reason"] is None and g["revision"] == 0 and g["history"] == []
    pool = {p["name"]: p for p in g["pool"]}
    assert [p["name"] for p in g["pool"]] == POOL                                   # 풀 = tpl 선언 순서
    assert [v["name"] for v in g["variables"]] == ["THK_1", "N_RIB"]
    assert pool["THK_1"]["default_range"] == {"min": 2.0, "max": 5.0} and pool["THK_1"]["range_unset"] is False
    assert pool["N_RIB"]["integer"] is True and pool["THK_1"]["integer"] is False
    assert pool["RIB_H"]["range_unset"] is True and pool["RIB_H"]["default_range"] == {"min": 20.0, "max": 20.0}
    assert all(p["type"] is None and p["body"] is None and p["feasible"] is None and p["train"] is None for p in g["pool"])
    # 저장: 일부만 + 미사용 변수 추가 + 범위 변경
    r = _put(env, ps, 0, [("THK_1", 2.5, 4.0), ("RIB_H", 18.0, 22.0)])
    assert r["revision"] == 1 and [v["name"] for v in r["variables"]] == ["THK_1", "RIB_H"] and r["engine"] == "altair"
    S = _S(env, ps)
    assert (S / "vars" / "history" / "rev_0000.json").is_file() and (S / "vars" / "history" / "rev_0001.json").is_file()
    cur = json.loads((S / "vars" / "vars.json").read_text())
    assert cur["revision"] == 1 and [v["name"] for v in cur["variables"]] == ["THK_1", "RIB_H"]
    pj = json.loads((S / "parameters.json").read_text())["parameters"]
    assert [(x["name"], x["nominal"], x["min"], x["max"]) for x in pj] == [("THK_1", 3.0, 2.5, 4.0), ("RIB_H", 20.0, 18.0, 22.0)]
    db = env.sql("select parameters, tpl_params from param_sets where id=:i", i=ps["id"])[0]
    assert db[0] == pj and [t["name"] for t in db[1]] == POOL                      # 파일 = DB, tpl 기록은 그대로
    assert env.sql("select count(*) from audit_events where action='PARAM_SET_UPDATE' and target_id=:i", i=ps["id"])[0][0] >= 1
    s = env.c.get(f"{API}/param-sets/{ps['id']}", headers=P).json()
    assert (s["vars_scope"], s["vars_revision"], s["vars_count"]) == ("full", 1, 2)
    assert [v["name"] for v in _get(env, ps, "?revision=0")["variables"]] == ["THK_1", "N_RIB"]
    assert _get(env, ps)["features_sha256"] == g["features_sha256"]                # 풀 출처(tpl) 불변
    # 검증: 낡은 리비전 409, 미지 이름·중복·범위 역전·빈 목록·정수 형식 변수의 비정수 범위 422
    r = _put_raw(env, ps, 0, [("THK_1", 2.5, 4.0)])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NATIVE_VARS_CONFLICT" and r.json()["detail"]["revision"] == 1
    for items, code in ([([("NOPE", 1, 2)], "VAR_UNKNOWN"), ([("THK_1", 1, 2), ("THK_1", 1, 2)], "VAR_DUPLICATE"),
                         ([("THK_1", 5, 2)], "VAR_RANGE_INVALID"), ([], "VARS_EMPTY"), ([("N_RIB", 2.5, 8.0)], "VAR_RANGE_INVALID")]):
        r = _put_raw(env, ps, 1, items)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "NATIVE_VARS_INVALID", r.text
        assert code in _codes(r.json()["detail"]["problems"])
    r = env.c.put(_url(ps), headers=H("tok-general", write=True), json={"base_revision": 1, "variables": [{"name": "THK_1", "min": 2, "max": 3}]})
    assert r.status_code in (403, 404)
    assert _put(env, ps, 1, [("N_RIB", 2, 8)])["revision"] == 2                    # 정수 범위는 저장됨
    # 선언·표 범위 밖이어도 저장은 되고 모핑 가능 범위 경고는 없다(Altair는 범위 제한 없음)
    r = _put(env, ps, 2, [("THK_1", 0.5, 30.0)])
    assert r["revision"] == 3 and "VAR_OUT_OF_FEASIBLE" not in _codes(r["warnings"])


def test_v_av_4_partial_tpl_set_is_read_only_with_reason(predict_env):
    env = predict_env()
    ps = env.param_set()                                                           # 옛 부분 tpl(표지 줄 없음)
    assert env.c.get(f"{API}/param-sets/{ps['id']}", headers=P).json()["vars_scope"] == "partial"
    g = _get(env, ps)
    assert g["editable"] is False and g["reason"] == "TPL_SCOPE_PARTIAL" and g["engine"] == "altair"
    assert [p["name"] for p in g["pool"]] == ["THK_1", "N_RIB"] and [v["name"] for v in g["variables"]] == ["THK_1", "N_RIB"]
    r = _put_raw(env, ps, 0, [("THK_1", 2.5, 4.0)])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "TPL_SCOPE_PARTIAL"
    assert "tpl" in r.json()["detail"]["message"]                                  # 재생성 안내
    assert not (_S(env, ps) / "vars" / "history" / "rev_0001.json").exists()


# ---- V-AV-5: ④ 일괄 예측 그 자리 편집·렌더, ⑥ 최적화 ---------------------------------------------------------


def test_v_av_5_batch_vars_add_exclude_snapshot_and_render_nominal(aenv, monkeypatch, tmp_path):
    env, ps = aenv, aenv.ps
    pit = tmp_path / "paramitems.jsonl"
    monkeypatch.setenv("FAKE_SIMLAB_PARAMITEMS", str(pit))
    # vars 없음 = 세트 정의 그대로(THK_1·N_RIB)
    base = _prev(env, ps, {"kind": "lhs", "count": 4, "seed": 3})
    assert base["problems"] == [] and [v["name"] for v in base["var_rows"]] == ["THK_1", "N_RIB"] and base["excluded"] == []
    # add(미사용 RIB_H)·exclude(N_RIB): 유효 변수 = THK_1, RIB_H. 풀 밖 이름은 problem
    v = {"add": ["RIB_H"], "exclude": ["N_RIB"]}
    p = _prev(env, ps, {"kind": "lhs", "count": 4, "seed": 3}, v)
    assert p["problems"] == [] and p["excluded"] == ["N_RIB"]
    assert [(r["name"], r["origin"]) for r in p["var_rows"]] == [("THK_1", "set"), ("RIB_H", "added")]
    assert set(p["rows"][0]["values"]) == {"THK_1", "RIB_H"}
    assert _prev(env, ps, {"kind": "lhs", "count": 4}, {"add": ["NOPE"]})["problems"]
    assert _prev(env, ps, {"kind": "lhs", "count": 4}, {"exclude": ["NOPE"]})["problems"]
    # 표 붙여넣기: 범위(THK_1 2~5, RIB_H 선언 20~20) 밖 값도 막지 않음
    src = {"kind": "table", "text": "THK_1,RIB_H\n3.5,19.0\n9.0,50.0\n"}
    tv = _prev(env, ps, src, v)
    assert tv["problems"] == [] and tv["count"] == 2
    j = _job(env, ps, src, v)
    snap = j["params"]["vars"]
    assert snap["excluded"] == ["N_RIB"] and [x["name"] for x in snap["variables"]] == ["THK_1", "RIB_H"] and snap["set_revision"] == 0
    _put(env, ps, 0, [("N_RIB", 2, 8)])                                            # 작업이 돌기 전에 세트 정의가 바뀌어도 실행은 스냅숏
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    b = env.c.get(f"{API}/predict-batches/{j['params']['batch_id']}", headers=P).json()
    assert b["parameters"] == ["THK_1", "RIB_H"] and b["vars"]["excluded"] == ["N_RIB"] and b["gen"]["done"] == 2
    first, second = _scripts(env, j)
    assert _items(first) == {"N_RIB": "4", "RIB_H": "19.0000", "HOLE_R": "4.0000"}      # 제외한 N_RIB·열에 없는 HOLE_R = 공칭
    assert _items(second) == {"N_RIB": "4", "RIB_H": "50.0000", "HOLE_R": "4.0000"}
    assert re.search(r"thickness = +3\.5000", first) and re.search(r"thickness = +9\.0000", second) and "{var_" not in first + second
    rec = [json.loads(x)["paramitems"] for x in pit.read_text().splitlines()]       # fake_simlab: 미치환 참조 없음(있으면 종료코드 5)
    assert len(rec) == 2 and all(set(r) == {"N_RIB", "RIB_H", "HOLE_R"} and not any("{" in x for x in r.values()) for r in rec)


def test_v_av_5_opt_vars_bounds_warnings_only_and_snapshot(aenv):
    env, ps = aenv, aenv.ps
    perfs = [*RESPS, {"name": "CornerStress", "unit": "MPa", "spec": {**RESPS[0]["spec"], "datatype": "Stress", "component": "vonMises"}}]
    env.set_responses(ps["id"], perfs)
    body = {"param_set_id": ps["id"], "explore": {"kind": "new", "count": 5, "seed": 1},
            "objectives": [{"metric": "perf:MaxStress", "sense": "min"}, {"metric": "perf:MinDisp", "sense": "max"}],
            "weights": [50, 50], "iterations": 1, "candidates": 1, "tol_rel": 1e-9, "seed": 1, "multi_execution": 2}

    def prev(extra):
        r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json={**body, **extra})
        assert r.status_code == 200, r.text
        return r.json()

    base = prev({})
    assert base["problems"] == [] and set(base["free_variables"]) == {"THK_1", "N_RIB"} and base["excluded"] == []
    v = prev({"vars": {"add": ["RIB_H"], "exclude": ["N_RIB"]}, "bounds": {"THK_1": [1.0, 9.0], "RIB_H": [10.0, 30.0]}})
    assert v["problems"] == [] and set(v["free_variables"]) == {"THK_1", "RIB_H"} and v["excluded"] == ["N_RIB"]
    assert [x["name"] for x in v["var_rows"]] == ["THK_1", "RIB_H"]                 # 전체 tpl: BOUNDS_OUT_OF_RANGE 없이 경고만
    assert prev({"vars": {"exclude": ["NOPE"]}})["problems"]
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW,
                   json={**body, "vars": {"add": ["RIB_H"], "exclude": ["N_RIB"]}, "bounds": {"RIB_H": [18.0, 22.0]}})
    assert r.status_code == 201, r.text
    opt = r.json()
    assert opt["settings"]["vars"]["excluded"] == ["N_RIB"] and "N_RIB" not in opt["settings"]["names"]
    assert {x["name"] for x in opt["settings"]["vars"]["variables"]} == {"THK_1", "RIB_H"} and opt["settings"]["bounds"]["RIB_H"] == [18.0, 22.0]
    _put(env, ps, 0, [("N_RIB", 2, 8)])                                            # 실행 중 세트 정의가 바뀌어도 스냅숏 기준
    for _ in range(60):
        if not env.sql("select id from jobs where state='QUEUED' and lane='SLOT' order by queue_seq limit 1"):
            break
        env.w.run_once_slot()
    d = env.c.get(f"{API}/surrogate-opts/{opt['id']}", headers=P).json()
    assert d["status"] == "DONE", (d["status"], d.get("progress_text"))
    assert [p["name"] for p in d["parameters"]] == ["THK_1", "RIB_H"] and d["settings"]["vars"]["set_revision"] == 0
    pb = env.batch(env.sql("select id from predict_batches where study_id=:s", s=env.sid)[0][0])
    assert pb["source_meta"]["vars"]["excluded"] == ["N_RIB"]                       # 소유 배치에도 스냅숏
    name = env.lc.settings.predict.rendered_script_name
    for run in pb["runs"]:
        t = (env.sroot / pb["dir_rel"] / run["run_key"] / "m_1" / name).read_text()
        assert _items(t)["N_RIB"] == "4" and _items(t)["HOLE_R"] == "4.0000" and "{var_" not in t   # 제외·열 밖 파라미터 = 공칭


def test_v_av_4_integer_range_shared_check_on_put_batch_and_opt(aenv):
    """정수(%i) 파라미터의 비정수 범위 = 공용 검사(`nearest.is_integer_range`) — PUT variables·④ 일괄(미리보기·생성)·⑥(미리보기·생성) 모두 VAR_RANGE_INVALID."""
    from physicsai_core.stage4_predict import nearest

    assert nearest.is_integer_range(2.0, 8) and not nearest.is_integer_range(2.5, 7.5) and not nearest.is_integer_range(3, 3.2)
    tp = [{"name": "N_RIB", "format": "%3i"}, {"name": "THK_1", "format": "%8.4f"}]
    assert nearest.integer_range_violations({"N_RIB": [2.5, 7.5], "THK_1": [0.5, 1.5], "X": [0.1, 0.2]}, tp) == ["N_RIB"]
    assert nearest.integer_range_violations({"N_RIB": [2, 7], "THK_1": [0.5, 1.5]}, tp) == []
    assert nearest.integer_range_violations({"N_RIB": "bad"}, tp) == [] and nearest.integer_range_violations({"N_RIB": [float("nan"), 3]}, tp) == []

    env, ps = aenv, aenv.ps
    assert "VAR_RANGE_INVALID" in _codes(_put_raw(env, ps, 0, [("N_RIB", 2.5, 7.5)]).json()["detail"]["problems"])
    bad = {"kind": "lhs", "count": 4, "seed": 3, "ranges": {"N_RIB": [2.5, 7.5]}}
    ok = {"kind": "lhs", "count": 4, "seed": 3, "ranges": {"N_RIB": [3, 7], "THK_1": [2.25, 4.75]}}   # 정수 범위 + 연속 변수의 소수 범위는 통과
    rng = {"N_RIB": [2.5, 7.5]}
    for src in (bad, {"kind": "lhs_opt", "count": 4, "ranges": rng}, {"kind": "sobol", "count": 4, "ranges": rng},
                {"kind": "fullfact", "ranges": rng}):
        pv = _prev(env, ps, src)                                                       # 미리보기 = 200 + problems
        assert "VAR_RANGE_INVALID" in _codes(pv["problems"]), (src["kind"], pv["problems"])
    assert _prev(env, ps, ok)["problems"] == []
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "PREDICT_BATCH", "params": {
        "param_set_id": ps["id"], "multi_execution": 2, "source": bad}})
    assert r.status_code == 422 and "VAR_RANGE_INVALID" in _codes(r.json()["detail"]["problems"]), r.text   # 생성 = 422
    assert not env.sql("select id from predict_batches where study_id=:s", s=env.sid)
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "PREDICT_BATCH", "params": {
        "param_set_id": ps["id"], "multi_execution": 2, "source": bad, "vars": {"exclude": ["THK_1"]}}})
    assert r.status_code == 422 and "VAR_RANGE_INVALID" in _codes(r.json()["detail"]["problems"]), r.text
    _job(env, ps, ok)
    body = {"param_set_id": ps["id"], "explore": {"kind": "new", "count": 5, "seed": 1}, "objective": {"metric": "perf:MaxStress", "sense": "min"},
            "iterations": 1, "candidates": 1, "seed": 1}
    for path in ("surrogate-opts/preview", "surrogate-opts"):
        r = env.c.post(f"{API}/studies/{env.sid}/{path}", headers=PW, json={**body, "bounds": {"N_RIB": [2.5, 7.5]}})
        probs = r.json()["problems"] if path.endswith("preview") else r.json()["detail"]["problems"]
        assert r.status_code == (200 if path.endswith("preview") else 422), r.text
        assert "VAR_RANGE_INVALID" in _codes(probs), (path, probs)
        assert [x["field"] for x in probs if x["code"] == "VAR_RANGE_INVALID"] == ["bounds.N_RIB"]
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json={**body, "bounds": {"N_RIB": [3, 7]}})
    assert r.status_code == 201, r.text


# ---- V-AV-6: 학습 범위(① DOE parameters_snapshot) -------------------------------------------------------------


def _doe_dir(env, name, tpl_text, snapshot):
    """READY Altair ① DOE 1개(tpl 사본 + parameters_snapshot) → (doe_id, DOE 폴더)."""
    did = str(uuid4())
    rel = f"01_train/doe/{did}"
    D = env.sroot / rel
    D.mkdir(parents=True)
    (D / "simlab_parametered_mesh.tpl").write_text(tpl_text, encoding="utf-8")
    jid = env.sql("select id from jobs where study_id=:s order by created_at limit 1", s=env.sid)[0][0]
    env.sql("insert into train_does(id, study_id, job_id, doe_label, doe_type, radioss_assem_source_path, dir_rel, assem_rel,"
            " parameters_snapshot, status, created_by, created_by_name, engine) values (:i,:s,:j,:l,'LHS','/src',:d,:a,"
            " cast(:ps as jsonb),'READY','u-power','파워','altair')",
            i=did, s=env.sid, j=jid, l=name, d=rel, a=rel + "/radioss_assem", ps=json.dumps(snapshot))
    return did, D


def _link_dataset(env, source_path):
    env.sql("insert into datasets(id, study_id, source_path, seed, split_group, options_json, status, created_by, created_by_name)"
            " values ('ds-av', :s, :p, 1, 'file', cast('{}' as jsonb), 'READY', 'u-power', '파워')", s=env.sid, p=str(source_path))
    env.sql("update models set dataset_id='ds-av' where id=:m", m=env.model_id)


def _train(env, ps):
    g = _get(env, ps, f"?model_id={env.model_id}")
    return g, {p["name"]: p["train"] for p in g["pool"]}


def test_v_av_6_train_range_from_altair_doe_snapshot(aenv):
    env, ps = aenv, aenv.ps
    g0 = _get(env, ps, f"?model_id={env.model_id}")
    assert "TRAIN_RANGE_UNKNOWN" in _codes(g0["notes"]) and g0["train_source"] is None and all(p["train"] is None for p in g0["pool"])
    snap = [{"name": "THK_1", "nominal": 3.0, "min": 2.5, "max": 4.0}, {"name": "N_RIB", "nominal": 4, "min": 3, "max": 6}]
    did, D = _doe_dir(env, "DOE-A", FULL_TPL, snap)
    _link_dataset(env, D)
    g, tr = _train(env, ps)
    assert g["train_source"]["doe_ids"] == [did] and "TRAIN_RANGE_UNKNOWN" not in _codes(g["notes"])
    assert tr["THK_1"] == {"min": 2.5, "max": 4.0} and tr["N_RIB"] == {"min": 3.0, "max": 6.0}
    assert tr["RIB_H"] == {"min": 20.0, "max": 20.0} and tr["HOLE_R"] == {"min": 4.0, "max": 4.0}   # DOE 밖 = [그 DOE tpl 공칭, 공칭]
    # ④ 일괄: out_of_range = 학습 범위 기준(경고만)
    pv = _prev(env, ps, {"kind": "table", "text": "THK_1,N_RIB\n2.0,4\n3.0,4\n"}, model_id=env.model_id)
    assert pv["problems"] == [] and [r["out_of_range"] for r in pv["rows"]] == [["THK_1"], []] and "VAR_OUT_OF_TRAIN" in _codes(pv["notes"])
    # 같은 파라미터가 아니면(공칭 불일치) 그 이름은 학습 범위 모름 + 안내
    env.sql("update train_does set parameters_snapshot=cast(:ps as jsonb) where id=:i", i=did,
            ps=json.dumps([{**snap[0], "nominal": 3.5}, snap[1]]))
    g, tr = _train(env, ps)
    assert tr["THK_1"] is None and tr["N_RIB"] == {"min": 3.0, "max": 6.0} and "TRAIN_RANGE_UNMATCHED" in _codes(g["notes"])
    # 옛 부분 tpl DOE: 미사용 행은 DOE 기록이 없어 모름(사용 행만 범위가 있음)
    env.sql("update train_does set parameters_snapshot=cast(:ps as jsonb) where id=:i", i=did, ps=json.dumps(snap))
    (D / "simlab_parametered_mesh.tpl").write_text(FULL_TPL.replace("# physicsai-tpl scope=full v=1\n", ""), encoding="utf-8")
    _g, tr = _train(env, ps)
    assert tr["THK_1"] == {"min": 2.5, "max": 4.0} and tr["RIB_H"] is None and tr["HOLE_R"] is None
    # 엔진이 다른 DOE는 쓰지 않는다
    env.sql("update train_does set engine='native' where id=:i", i=did)
    g, _tr = _train(env, ps)
    assert g["train_source"] is None and "TRAIN_RANGE_UNKNOWN" in _codes(g["notes"])


# ---- V-AV-8: 회귀 ---------------------------------------------------------------------------------------------


def test_v_av_8_partial_tpl_set_unchanged_and_no_native_code(predict_env):
    env = predict_env()
    ps = env.param_set()
    env.set_responses(ps["id"], RESPS)
    names = [p["name"] for p in ps["parameters"]]
    lo, hi = ps["parameters"][0]["min"], ps["parameters"][0]["max"]
    base = _prev(env, ps, {"kind": "lhs", "count": 3})
    assert base["problems"] == [] and base["var_rows"] == [] and base["excluded"] == [] and "TRAIN_RANGE_UNKNOWN" not in _codes(base["notes"])
    body = {"param_set_id": ps["id"], "explore": {"kind": "new", "count": 5, "seed": 1},
            "objective": {"metric": "perf:MaxStress", "sense": "min"}, "iterations": 1, "candidates": 1, "seed": 1}
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json={**body, "bounds": {names[0]: [lo - 1.0, hi + 1.0]}})
    out = r.json()
    assert r.status_code == 200 and "BOUNDS_OUT_OF_RANGE" in _codes(out["problems"]) and out["var_notes"] == []   # 부분 tpl: 기존 규칙 그대로
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "PREDICT_BATCH", "params": {
        "param_set_id": ps["id"], "multi_execution": 1, "source": {"kind": "lhs", "count": 3}, "vars": {"exclude": [names[0]]}}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "TPL_SCOPE_PARTIAL" and "NATIVE_VARS_UNSUPPORTED" not in r.text


def test_v_av_8_full_tpl_without_vars_renders_nominal_for_unused(predict_env):
    """vars 없는 일괄: 전체 tpl 세트는 세트 정의 변수만 움직이고 나머지는 공칭으로 렌더 — 부분 tpl 세트와 같은 값."""
    env = predict_env()
    full = env.param_set(tpl=FULL_TPL)
    part = env.param_set()
    out = {}
    for tag, ps in (("full", full), ("part", part)):
        j = _job(env, ps, {"kind": "table", "text": "THK_1,N_RIB\n3.5,5\n"})
        for _ in range(4):                                                         # 앞 일괄의 하위 예측 작업이 먼저 잡힐 수 있다
            env.w.run_once_slot()
            if env.job(j["id"])["state"] == "SUCCEEDED":
                break
        assert env.job(j["id"])["state"] == "SUCCEEDED", env.job(j["id"])
        out[tag] = _items(_scripts(env, j)[0])
    assert out["part"] == {"N_RIB": "5"} and out["full"] == {"N_RIB": "5", "RIB_H": "20.0000", "HOLE_R": "4.0000"}
