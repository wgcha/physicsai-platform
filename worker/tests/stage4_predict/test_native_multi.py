"""단계 4B 다중 baseline E2E(geometry-engine.md §4.10·§7.3.8·§11.4, V-GE-17·18): baseline 추가(BL_MAP) → 매칭표 draft·결정·확정
게이트(DOE·일괄 409, 단건 예측 허용) → 확정 → baseline별 층화 LHS DOE(baseline_id 열·N/A·지시 열·원-핫·원 이름 values.json)·
remap 승계·일괄 생성·range 배정(BASELINE_NO_COVER)·삭제/단일로 되돌리기. 가짜 paicad."""

from __future__ import annotations

import csv
import json

from helpers_native import make_project, native_set
from physicsai_test_support import API, H, read_record

PW = H("tok-power", write=True)
P = H("tok-power")


def _feat(name, typ, nominal, lo, hi, feasible=None):
    f = {"name": name, "type": typ, "body": "A", "nominal": nominal, "unit": "mm", "range": {"min": lo, "max": hi, "ratio": 0.05},
         "group": None, "ref": {"rule": "contact_fixed", "provisional": True, "locked": False}}
    if feasible:
        f["feasible"] = {"min": feasible[0], "max": feasible[1], "source": "envelope"}
    return f


B2_TOPO = [_feat("A_THK_1", "THICKNESS", 10.0, 9.5, 10.5), _feat("B_RIB_H_1", "RIB_HEIGHT", 20.0, 19.0, 21.0),
           _feat("D_POCKET_D_1", "POCKET_DEPTH", 5.0, 4.75, 5.25)]


def _add(env, psid, bid, features, monkeypatch, expect="SUCCEEDED", **kw):
    monkeypatch.setenv("FAKE_PAICAD_FEATURES", json.dumps(features))
    proj = make_project(env.imports / f"proj_{bid}")
    r = env.c.post(f"{API}/param-sets/{psid}/baselines", headers=PW, json={"id": bid, "path": str(proj), "label": f"L{bid}", **kw})
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]
    assert env.w.run_once_slot() == expect, env.job(jid)
    monkeypatch.delenv("FAKE_PAICAD_FEATURES")
    return jid


def _map(env, psid):
    r = env.c.get(f"{API}/param-sets/{psid}/param-map", headers=P)
    assert r.status_code == 200, r.text
    return r.json()


def _rows(pm):
    return {r["proposed"]["name"]: r for r in pm["common"]}


def _put(env, psid, decisions, expect=200):
    r = env.c.put(f"{API}/param-sets/{psid}/param-map", headers=PW, json={"decisions": decisions})
    assert r.status_code == expect, r.text
    return r.json()


def _confirm(env, psid, expect=200):
    r = env.c.post(f"{API}/param-sets/{psid}/param-map/confirm", headers=PW)
    assert r.status_code == expect, r.text
    return r.json()


def _snap(env, doe_id):
    return [p["name"] for p in env.sql("select parameters_snapshot from train_does where id=:i", i=doe_id)[0][0]]


def _doe(env, psid, n=5, seed=2):
    j = env.submit("TD_DOE_GEN", {"doe_label": "LHS", "num_runs": n, "seed": seed, "param_set_id": psid})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    jd = env.job(j["id"])
    return jd, env.sroot / "01_train" / "doe" / jd["result"]["doe_id"]


def test_topology_add_confirm_gate_doe_remap(native_env, monkeypatch, fake_record):
    env = native_env()
    ps = native_set(env)
    S = env.sroot / "04_params" / ps["id"]
    assert ps["baselines"] is None and ps["param_map_status"] is None and not (S / "param_map.json").exists()
    monkeypatch.setenv("FAKE_PAICAD_MAP_GRADE", "B_RIB_H_1:check")
    jid = _add(env, ps["id"], "B2", B2_TOPO, monkeypatch)
    st = env.steps(jid)
    assert [st[k]["state"] for k in ("NP_PREP", "NP_EXTRACT", "NP_TAG", "BL_MAP", "NP_REGISTER")] == ["SUCCEEDED"] * 5
    for rel in ("baselines/B2/cad/bracket.step", "baselines/B2/radioss_assem/model0_0000.rad", "baselines/B2/native/prep.json",
                "baselines/B2/native/tag/tag.json", "baselines/B2/baseline.json", "param_map.json", "baselines/single_parameters.json"):
        assert (S / rel).is_file(), rel
    bj = json.loads((S / "baselines" / "B2" / "baseline.json").read_text())
    assert bj["id"] == "B2" and bj["label"] == "LB2" and bj["usage_role"] == "topology" and bj["nominal"]["D_POCKET_D_1"] == 5.0
    mp = [r for r in read_record(fake_record) if r["tool"] == "paicad" and r["argv"][1] == "map"][-1]["argv"]
    assert "--user-map" not in mp and "--split-param" not in mp and mp[mp.index("--usage") + 1] == "topology"
    out = env.c.get(f"{API}/param-sets/{ps['id']}", headers=P).json()
    assert [b["id"] for b in out["baselines"]] == ["base", "B2"] and out["param_map_status"] == "draft"
    assert all(b["prep_status"] == "READY" for b in out["baselines"]) and out["baselines"][1]["label"] == "LB2"
    pm = _map(env, ps["id"])
    rows = _rows(pm)
    assert pm["status"] == "draft" and pm["confirmed_by"] is None and pm["usage"] == "topology"
    assert all(r["decision"] is None for r in pm["common"])                               # 점수 ≥0.7이어도 결정 없음
    assert rows["A_THK_1"]["proposed"]["grade"] == "recommend" and rows["B_RIB_H_1"]["requires_decision"]
    assert rows["C_HOLE_R_1"]["proposed"]["map"] == {"base": "C_HOLE_R_1", "B2": None}
    assert pm["unresolved_rows"] == [rows["B_RIB_H_1"]["row_id"]]
    # 확정 게이트: DOE·일괄 생성 409, 단건 예측은 대상 아님
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW,
                   json={"job_type": "TD_DOE_GEN", "params": {"doe_label": "LHS", "num_runs": 4, "param_set_id": ps["id"]}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PARAM_MAP_UNCONFIRMED", r.text
    assert "미결정 행 4개" in r.json()["detail"]["message"]
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "PREDICT_BATCH", "params": {
        "param_set_id": ps["id"], "model_id": env.model_id, "multi_execution": 1, "source": {"kind": "lhs", "count": 3}}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PARAM_MAP_UNCONFIRMED", r.text
    j = env.submit("PREDICT", {"values": {"A_THK_1": 10.1, "B_RIB_H_1": 20.0, "C_HOLE_R_1": 4.0}, "value_source": "manual"})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    # 확정: check 등급 행 미결정 → 422
    bad = _confirm(env, ps["id"], expect=422)
    assert bad["detail"]["code"] == "GEOM_INPUT_INVALID" and bad["detail"]["problems"][0]["row_id"] == rows["B_RIB_H_1"]["row_id"]
    # 결정 충돌·예약어 → 422 PARAM_NAME_CONFLICT(매칭표 불변)
    c = _put(env, ps["id"], [{"row_id": rows["C_HOLE_R_1"]["row_id"], "decision": {"action": "rename", "name": "A_THK_1",
                                                                                   "map": {"base": "C_HOLE_R_1", "B2": None}}},
                             {"row_id": rows["A_THK_1"]["row_id"], "decision": {"action": "accept"}}], expect=422)
    assert c["detail"]["code"] == "PARAM_NAME_CONFLICT"
    c = _put(env, ps["id"], [{"row_id": rows["C_HOLE_R_1"]["row_id"], "decision": {"action": "rename", "name": "baseline",
                                                                                   "map": {"base": "C_HOLE_R_1"}}}], expect=422)
    assert c["detail"]["code"] == "PARAM_NAME_CONFLICT"
    assert all(r["decision"] is None for r in _map(env, ps["id"])["common"])
    pm = _put(env, ps["id"], [{"row_id": rows["B_RIB_H_1"]["row_id"], "decision": {"action": "accept"}},
                              {"row_id": rows["D_POCKET_D_1"]["row_id"], "decision": {"action": "rename", "name": "POCKET_D",
                                                                                     "map": {"base": None, "B2": "D_POCKET_D_1"}}}])
    assert pm["status"] == "draft" and pm["unresolved_rows"] == []
    pm = _confirm(env, ps["id"])
    assert pm["status"] == "confirmed" and pm["confirmed_by"] == "u-power" and pm["confirmed_at"]
    assert pm["variables"] == ["A_THK_1", "B_RIB_H_1", "C_HOLE_R_1", "POCKET_D"]
    assert all(r["decision"] for r in pm["common"]) and _rows(pm)["A_THK_1"]["decision"]["action"] == "accept"
    out = env.c.get(f"{API}/param-sets/{ps['id']}", headers=P).json()
    prm = {p["name"]: p for p in out["parameters"]}
    assert list(prm) == ["A_THK_1", "B_RIB_H_1", "C_HOLE_R_1", "POCKET_D"] and out["param_map_status"] == "confirmed"
    assert prm["POCKET_D"]["baselines"]["base"] is None and prm["POCKET_D"]["baselines"]["B2"]["param"] == "D_POCKET_D_1"
    # 층화 DOE(N=5, B=2 → 3·2), 같은 seed 같은 행렬
    jd, D = _doe(env, ps["id"])
    text = (D / "doe_matrix.csv").read_text()
    rows_m = list(csv.DictReader(text.splitlines()))
    assert list(rows_m[0])[:3] == ["doe_no", "run_key", "baseline_id"]
    assert [r["baseline_id"] for r in rows_m] == ["base", "base", "base", "B2", "B2"]
    assert all(r["POCKET_D"] == "" for r in rows_m[:3]) and all(r["C_HOLE_R_1"] == "" for r in rows_m[3:])
    for r in rows_m:
        R = D / "approaches" / "native_lhs" / r["run_key"]
        v = json.loads((R / "m_1" / "values.json").read_text())
        assert v["baseline_id"] == r["baseline_id"]
        if r["baseline_id"] == "B2":
            assert set(v["values"]) == {"A_THK_1", "B_RIB_H_1", "D_POCKET_D_1"} and v["common_values"]["C_HOLE_R_1"] is None
            assert v["values"]["D_POCKET_D_1"] == float(r["POCKET_D"])
        else:
            assert set(v["values"]) == {"A_THK_1", "B_RIB_H_1", "C_HOLE_R_1"} and v["common_values"]["POCKET_D"] is None
        xml = (R / "m_1" / "native_params.xml").read_text()
        na = "1.0" if r["baseline_id"] == "B2" else "0.0"
        assert f'Name="C_HOLE_R_1__na" NewValue="{na}"' in xml and 'Name="baseline__B2"' in xml
        assert (R / "m_3" / "model0_0000.rad").is_file()
    upd = [x for x in read_record(fake_record) if x["tool"] == "paicad" and x["argv"][1] in ("update", "run")]
    assert any(str(S / "baselines" / "B2" / "cad") in a for x in upd for a in x["argv"])     # B2 run은 B2 준비본으로
    assert jd["result"]["run_count"] == 5 and jd["result"]["sample_status"] == "PARSED"
    snap = _snap(env, jd["result"]["doe_id"])
    assert snap == ["A_THK_1", "B_RIB_H_1", "C_HOLE_R_1", "POCKET_D", "C_HOLE_R_1__na", "POCKET_D__na", "baseline__base", "baseline__B2"]
    _jd2, D2 = _doe(env, ps["id"])
    assert (D2 / "doe_matrix.csv").read_text() == text
    # remap: BL_MAP·NP_REGISTER만, 서명 같은 행 결정 승계 → draft
    r = env.c.post(f"{API}/param-sets/{ps['id']}/remap", headers=PW, json={})
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(jid)
    st = env.steps(jid)
    assert [st[k]["state"] for k in ("NP_EXTRACT", "NP_TAG", "BL_MAP")] == ["SKIPPED", "SKIPPED", "SUCCEEDED"]
    mp = [x for x in read_record(fake_record) if x["tool"] == "paicad" and x["argv"][1] == "map"][-1]["argv"]
    assert mp[mp.index("--user-map") + 1] == str(S / "param_map.json")
    pm = _map(env, ps["id"])
    assert pm["status"] == "draft" and pm["confirmed_by"] is None
    assert all(r["decision"] is not None and not r["needs_review"] for r in pm["common"])
    assert _rows(pm)["D_POCKET_D_1"]["decision"]["name"] == "POCKET_D"
    assert list((env.sroot / "_backup").glob("*/04_params/*/param_map.json"))
    assert _confirm(env, ps["id"])["status"] == "confirmed"


def test_multi_batch_lhs_and_delete_disable(native_env, monkeypatch):
    env = native_env()
    ps = native_set(env)
    _add(env, ps["id"], "B2", B2_TOPO, monkeypatch)
    _add(env, ps["id"], "B3", B2_TOPO, monkeypatch)
    pm = _map(env, ps["id"])
    assert [b["id"] for b in pm["baselines"]] == ["base", "B2", "B3"]
    assert _rows(pm)["A_THK_1"]["needs_review"] and not _rows(pm)["C_HOLE_R_1"]["needs_review"]  # 서명이 바뀐 행만 재확인
    assert _confirm(env, ps["id"], expect=422)["detail"]["code"] == "GEOM_INPUT_INVALID"
    _put(env, ps["id"], [{"row_id": r["row_id"], "decision": {"action": "accept"}} for r in pm["common"]])
    _confirm(env, ps["id"])
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "PREDICT_BATCH", "params": {
        "param_set_id": ps["id"], "model_id": env.model_id, "multi_execution": 1, "source": {"kind": "table", "text": "A_THK_1\n10\n"}}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "BATCH_SOURCE_INVALID", r.text
    j = env.submit("PREDICT_BATCH", {"param_set_id": ps["id"], "model_id": env.model_id, "multi_execution": 2,
                                     "source": {"kind": "lhs", "count": 4, "seed": 3}})
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(j["id"])
    b = env.batch(env.job(j["id"])["params"]["batch_id"])
    meta = b["source_meta"]["multi_baseline"]
    assert meta["stratum"] == {"1": "base", "2": "base", "3": "B2", "4": "B3"} and meta["assign"] == meta["stratum"]
    B = env.sroot / b["dir_rel"]
    v3 = json.loads((B / "run__00003" / "m_1" / "values.json").read_text())
    assert v3["baseline_id"] == "B2" and "D_POCKET_D_1" in v3["values"] and v3["source"]["kind"] == "batch"
    assert all(r["gen_state"] == "DONE" for r in b["runs"])
    # 삭제: 3개 → 2개(매칭표 draft), 남은 추가 baseline 1개는 삭제 불가, base 삭제 불가 → disable로 단일
    r = env.c.delete(f"{API}/param-sets/{ps['id']}/baselines/B3", headers=PW)
    assert r.status_code == 200 and [x["id"] for x in r.json()["baselines"]] == ["base", "B2"] and r.json()["param_map_status"] == "draft"
    r = env.c.delete(f"{API}/param-sets/{ps['id']}/baselines/B2", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "BASELINE_LAST"
    r = env.c.delete(f"{API}/param-sets/{ps['id']}/baselines/base", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "BASELINE_BASE"
    r = env.c.post(f"{API}/param-sets/{ps['id']}/baselines/disable", headers=PW)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["baselines"] is None and [p["name"] for p in out["parameters"]] == ["A_THK_1", "B_RIB_H_1", "C_HOLE_R_1"]
    S = env.sroot / "04_params" / ps["id"]
    assert not (S / "param_map.json").exists() and not (S / "baselines").exists()
    assert list((env.sroot / "_backup").glob("*/04_params/*/baselines/B3"))
    r = env.c.get(f"{API}/param-sets/{ps['id']}/param-map", headers=P)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NOT_MULTI_BASELINE"


def test_range_usage_assignment_no_cover(native_env, monkeypatch):
    env = native_env()
    ps = native_set(env)
    b2 = [_feat("A_THK_1", "THICKNESS", 15.0, 14.25, 15.75, feasible=(14.5, 15.5)),
          _feat("B_RIB_H_1", "RIB_HEIGHT", 20.0, 19.0, 21.0, feasible=(19.99, 20.01)),
          _feat("C_HOLE_R_1", "HOLE_RADIUS", 4.0, 3.8, 4.2)]
    r = env.c.post(f"{API}/param-sets/{ps['id']}/baselines", headers=PW,
                   json={"id": "B2", "path": str(env.imports), "usage": "topology", "split_param": "A_THK_1"})
    assert r.status_code == 422, r.text                                       # 위상+범위 혼합 금지
    _add(env, ps["id"], "B2", b2, monkeypatch, usage="range", split_param="A_THK_1")
    pm = _map(env, ps["id"])
    assert pm["usage"] == "range" and pm["discrete"] is None
    assert pm["range_split"] == {"param": "A_THK_1", "intervals": [{"baseline": "base", "nominal": 10.0}, {"baseline": "B2", "nominal": 15.0}]}
    pm = _confirm(env, ps["id"])
    assert any(w["code"] == "BASELINE_RANGE_GAP" for w in pm["warnings"])     # base feasible ≤14 · B2 ≥14.5 틈
    jd, D = _doe(env, ps["id"], n=6, seed=5)
    rows = list(csv.DictReader((D / "doe_matrix.csv").open(encoding="utf-8")))
    base_rows = rows[:3]
    assert all(r["baseline_id"] == "base" and 6.0 <= float(r["A_THK_1"]) <= 12.5 for r in base_rows)   # 담당 구간(중점 12.5)·feasible
    nc = [r["run_key"] for r in rows if r["baseline_id"] == ""]
    assert nc, rows                                                            # B2 층 샘플은 B2 feasible(B_RIB 20±0.01) 밖 → 미커버
    sk = {s["run_key"]: s for s in jd["result"]["skipped_runs"]}
    assert set(sk) == set(nc) and all(s["reason"] == "BASELINE_NO_COVER" and s["category"] == "BASELINE" for s in sk.values())
    for rk in nc:
        sj = json.loads((D / "approaches" / "native_lhs" / rk / "SKIPPED.json").read_text())
        assert sj["code"] == "BASELINE_NO_COVER" and sj["step"] == "assign" and "baseline" in sj["message"]
    assert "baseline__base" not in _snap(env, jd["result"]["doe_id"]) and "A_THK_1" in _snap(env, jd["result"]["doe_id"])
