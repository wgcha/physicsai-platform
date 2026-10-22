"""doe-methods.md DM-C2·C4·C8: ①-3 Native 세트 기준 DOE — 단일 baseline 표본 방식 확대와 다중 baseline 층 안 생성기(V-DM-1 세트·다중 lhs 골든,
V-DM-2 세트 전 kind, V-DM-3 다중 baseline). 가짜 paicad."""

from __future__ import annotations

import csv
import json
import random

import pytest
from helpers_native import make_project, native_set

from physicsai_core.sampling import registry
from physicsai_core.stage1_train_data import doe_platform
from physicsai_test_support import API, H

PW = H("tok-power", write=True)
P = H("tok-power")


def _lhs_cols(names, bounds, n, seed):
    """lhs 골든 기대값 — 파라미터마다 층 순열 → run마다 random()(독립 구현)."""
    rng = random.Random(seed)
    cols = {}
    for name in names:
        lo, hi = bounds[name]
        perm = list(range(n))
        rng.shuffle(perm)
        cols[name] = [lo + (perm[i] + rng.random()) / n * (hi - lo) for i in range(n)]
    return cols


def _doe(env, params, expect="SUCCEEDED"):
    j = env.submit("TD_DOE_GEN", params)
    assert env.w.run_once_slot() == expect, env.job(j["id"])
    jd = env.job(j["id"])
    return j, jd, env.sroot / "01_train" / "doe" / jd["result"]["doe_id"]


def _row(env, doe_id):
    r = env.sql("select doe_type, doe_label, options, sampling, generator, engine, run_count from train_does where id=:i", i=doe_id)[0]
    return dict(zip(("doe_type", "doe_label", "options", "sampling", "generator", "engine", "run_count"), r))


def _post(env, params):
    return env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "TD_DOE_GEN", "params": params})


def test_v_dm_1_set_single_lhs_golden(native_env):
    env = native_env()
    ps = native_set(env)
    rows = list(ps["parameters"])
    names = [r["name"] for r in rows]
    exp = _lhs_cols(names, {r["name"]: (r["min"], r["max"]) for r in rows}, 4, 7)
    lines = ["doe_no,run_key," + ",".join(names)] + [
        f"{i + 1},run__{i + 1:05d}," + ",".join(repr(float(exp[n][i])) for n in names) for i in range(4)]
    expect = "\n".join(lines) + "\n"
    for shape in ({"num_runs": 4, "seed": 7}, {"doe_label": "LHS", "num_runs": 4, "seed": 7},
                  {"sampling": {"kind": "lhs", "count": 4, "seed": 7}}):
        j, jd, D = _doe(env, {**shape, "param_set_id": ps["id"]})
        assert j["params"]["doe_type"] == "NATIVE_LHS" and "sampling" not in j["params"] and j["params"]["seed"] == 7, shape
        assert (D / "doe_matrix.csv").read_text() == expect, shape
        row = _row(env, jd["result"]["doe_id"])
        assert row["doe_type"] == "NATIVE_LHS" and row["options"] == {"seed": 7, "param_set_id": ps["id"]} and row["sampling"] is None
        d = env.c.get(f"{API}/train-does/{jd['result']['doe_id']}", headers=P).json()
        assert d["sampling"] is None and d["gen"] is None and d["generator"] == "platform"


SET_INPUTS = {"lhs_opt": {"count": 6, "seed": 3}, "sobol": {"count": 8, "seed": 4}, "halton": {"count": 7, "seed": 5},
              "random": {"count": 5, "seed": 6}, "fullfact": {}, "fracfact": {"resolution": 5}, "pb": {}, "bbd": {}, "ccd": {"alpha": "face"}}


@pytest.mark.parametrize("kind", ["halton", "random", "sobol", "lhs_opt", "pb", "bbd"])
def test_v_dm_2_set_single_kind_matches_platform_build(native_env, kind):
    env = native_env()
    ps = native_set(env)
    names = [r["name"] for r in ps["parameters"]]
    sampling = {"kind": kind, **SET_INPUTS[kind]}
    j, jd, D = _doe(env, {"sampling": sampling, "param_set_id": ps["id"]})
    doe_type, label, _d = registry.METHODS[kind]
    assert j["params"]["doe_type"] == doe_type and j["params"]["doe_label"] == f"{label}(Native)" and j["params"]["param_set_id"] == ps["id"]
    plan = doe_platform.build(sampling, {}, env.lc.settings, inputs=doe_platform.design_inputs_from_params(ps["parameters"]))
    assert plan.ok and plan.run_count == j["params"]["num_runs"] == jd["result"]["run_count"]
    rows = list(csv.DictReader((D / "doe_matrix.csv").read_text().splitlines()))
    assert [[float(r[n]) for n in names] for r in rows] == [[r.applied_values[n] for n in names] for r in plan.rows]
    row = _row(env, jd["result"]["doe_id"])
    inp = plan.stored_input()
    assert row["options"] == {**inp, "param_set_id": ps["id"]} and row["sampling"] == {"kind": kind, "input": inp, "meta": plan.meta}
    assert row["engine"] == "native" and row["generator"] == "PLATFORM" and row["doe_type"] == doe_type
    d = env.c.get(f"{API}/train-does/{jd['result']['doe_id']}", headers=P).json()
    assert d["sampling"] == {"kind": kind, "label": label, "desc_id": f"td_{kind}", "meta": plan.meta} and d["gen"] is None
    # native_params.xml(샘플 표 추출 입력)에는 반영값이 들어간다
    xml = (D / "approaches" / "doe_1" / "run__00001" / "_paicad" / "native_params.xml").read_text()
    assert f'Name="{names[0]}" NewValue="{rows[0][names[0]]}"' in xml


def test_v_dm_5_set_table_out_of_range_uses_set_range(native_env):
    env = native_env()
    ps = native_set(env)
    rows = list(ps["parameters"])
    names = [r["name"] for r in rows]
    lo = {r["name"]: r["min"] for r in rows}
    hi = {r["name"]: r["max"] for r in rows}

    def tbl(vals):
        return ",".join(names) + "\n" + "\n".join(",".join(repr(v[n]) for n in names) for v in vals) + "\n"

    mid = {n: (lo[n] + hi[n]) / 2 for n in names}
    over = {**mid, names[0]: hi[names[0]] + 0.5}
    r = _post(env, {"param_set_id": ps["id"], "sampling": {"kind": "table", "text": tbl([lo, over])}})
    assert r.status_code == 422 and r.json()["detail"]["problems"][0]["code"] == "TABLE_OUT_OF_RANGE", r.text
    j, jd, D = _doe(env, {"param_set_id": ps["id"], "sampling": {"kind": "table", "text": tbl([lo, mid, hi])}})
    assert j["params"]["doe_type"] == "TABLE" and j["params"]["num_runs"] == 3
    got = list(csv.DictReader((D / "doe_matrix.csv").read_text().splitlines()))
    assert [[float(g[n]) for n in names] for g in got] == [[v[n] for n in names] for v in (lo, mid, hi)]
    row = _row(env, jd["result"]["doe_id"])
    assert row["options"] == {"row_count": 3, "param_set_id": ps["id"]}


# ---- 다중 baseline -----------------------------------------------------------------------------------------------


def _feat(name, typ, nominal, lo, hi):
    return {"name": name, "type": typ, "body": "A", "nominal": nominal, "unit": "mm", "range": {"min": lo, "max": hi, "ratio": 0.05},
            "group": None, "ref": {"rule": "contact_fixed", "provisional": True, "locked": False}}


B2_TOPO = [_feat("A_THK_1", "THICKNESS", 10.0, 9.5, 10.5), _feat("B_RIB_H_1", "RIB_HEIGHT", 20.0, 19.0, 21.0),
           _feat("D_POCKET_D_1", "POCKET_DEPTH", 5.0, 4.75, 5.25)]


def _confirmed_multi(env, monkeypatch):
    ps = native_set(env)
    monkeypatch.setenv("FAKE_PAICAD_FEATURES", json.dumps(B2_TOPO))
    proj = make_project(env.imports / "proj_B2")
    r = env.c.post(f"{API}/param-sets/{ps['id']}/baselines", headers=PW, json={"id": "B2", "path": str(proj), "label": "LB2"})
    assert r.status_code == 202, r.text
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(r.json()["job_id"])
    monkeypatch.delenv("FAKE_PAICAD_FEATURES")
    pm = env.c.get(f"{API}/param-sets/{ps['id']}/param-map", headers=P).json()
    rows = {x["proposed"]["name"]: x for x in pm["common"]}
    dec = [{"row_id": x["row_id"], "decision": {"action": "accept"}} for x in pm["common"] if x["proposed"]["name"] != "D_POCKET_D_1"]
    dec.append({"row_id": rows["D_POCKET_D_1"]["row_id"],
                "decision": {"action": "rename", "name": "POCKET_D", "map": {"base": None, "B2": "D_POCKET_D_1"}}})
    assert env.c.put(f"{API}/param-sets/{ps['id']}/param-map", headers=PW, json={"decisions": dec}).status_code == 200
    assert env.c.post(f"{API}/param-sets/{ps['id']}/param-map/confirm", headers=PW).status_code == 200
    return ps


LAYER_BOUNDS = {"base": {"A_THK_1": (9.5, 10.5), "B_RIB_H_1": (19.0, 21.0), "C_HOLE_R_1": (3.8, 4.2)},
                "B2": {"A_THK_1": (9.5, 10.5), "B_RIB_H_1": (19.0, 21.0), "POCKET_D": (4.75, 5.25)}}


def test_v_dm_1_multi_lhs_golden_and_v_dm_3_layer_kinds(native_env, monkeypatch):
    env = native_env()
    ps = _confirmed_multi(env, monkeypatch)
    # (1) lhs 층화 골든(N=5 → base 3 + B2 2, 층 seed = seed + 층 번호) — 독립 구현 기대값과 같은 값, doe_type NATIVE_LHS
    texts = {}
    for shape in ({"num_runs": 5, "seed": 2}, {"sampling": {"kind": "lhs", "count": 5, "seed": 2}}):
        j, jd, D = _doe(env, {**shape, "param_set_id": ps["id"]})
        assert j["params"]["doe_type"] == "NATIVE_LHS" and "sampling" not in j["params"]
        text = (D / "doe_matrix.csv").read_text()
        texts[json.dumps(shape)] = text
        got = list(csv.DictReader(text.splitlines()))
        assert [g["baseline_id"] for g in got] == ["base"] * 3 + ["B2"] * 2
        for k, (bid, n) in enumerate((("base", 3), ("B2", 2))):
            cols = _lhs_cols(list(LAYER_BOUNDS[bid]), LAYER_BOUNDS[bid], n, 2 + k)
            sel = [g for g in got if g["baseline_id"] == bid]
            for nm in LAYER_BOUNDS[bid]:
                assert [float(g[nm]) for g in sel] == cols[nm], (bid, nm)
        assert all(g["POCKET_D"] == "" for g in got[:3]) and all(g["C_HOLE_R_1"] == "" for g in got[3:])
        row = _row(env, jd["result"]["doe_id"])
        assert row["doe_type"] == "NATIVE_LHS" and row["sampling"] is None and row["options"] == {"seed": 2, "param_set_id": ps["id"]}
    assert len(set(texts.values())) == 1
    # (2) lhs 밖 층 안 생성기: 층화(개수 차 ≤ 1)·같은 seed 같은 행·방식 기록
    per_kind = {}
    for kind in ("lhs_opt", "halton", "random"):
        sampling = {"kind": kind, "count": 5, "seed": 2}
        j, jd, D = _doe(env, {"sampling": sampling, "param_set_id": ps["id"]})
        doe_type, label, _x = registry.METHODS[kind]
        assert j["params"]["doe_type"] == doe_type and j["params"]["doe_label"] == f"{label}(Native)" and j["params"]["num_runs"] == 5
        text = (D / "doe_matrix.csv").read_text()
        got = list(csv.DictReader(text.splitlines()))
        assert [g["baseline_id"] for g in got] == ["base"] * 3 + ["B2"] * 2
        for g in got:
            for nm, (lo, hi) in LAYER_BOUNDS[g["baseline_id"]].items():
                assert lo <= float(g[nm]) <= hi
        per_kind[kind] = text
        row = _row(env, jd["result"]["doe_id"])
        meta = row["sampling"]["meta"]
        assert row["sampling"]["kind"] == kind and meta["count"] == 5 and meta["seed"] == 2 and meta["layers"] == {"base": 3, "B2": 2}
        if kind == "lhs_opt":
            assert meta["criterion"] == "maximin" and row["sampling"]["input"] == {"count": 5, "seed": 2, "criterion": "maximin"}
        if kind == "halton":
            assert meta["scramble"] is True and meta["generator"].startswith("scipy ")
        assert row["options"] == {**row["sampling"]["input"], "param_set_id": ps["id"]} and row["doe_type"] == doe_type
        d = env.c.get(f"{API}/train-does/{jd['result']['doe_id']}", headers=P).json()
        assert d["sampling"]["kind"] == kind and d["sampling"]["desc_id"] == f"td_{kind}" and d["gen"] is None
        _j2, _jd2, D2 = _doe(env, {"sampling": sampling, "param_set_id": ps["id"]})
        assert (D2 / "doe_matrix.csv").read_text() == text                                  # 같은 seed 같은 행
    assert len({*per_kind.values(), next(iter(texts.values()))}) == 4                      # 방식마다 값이 다르다
    # (3) lhs_opt corr 기준
    j, jd, D = _doe(env, {"sampling": {"kind": "lhs_opt", "count": 5, "seed": 2, "criterion": "corr"}, "param_set_id": ps["id"]})
    assert _row(env, jd["result"]["doe_id"])["sampling"]["meta"]["criterion"] == "corr"
    # (4) 그 밖 방식은 422 DESIGN_UNSUPPORTED(DM-C4 문구), 상한 문구
    for sampling in ({"kind": "sobol", "count": 8}, {"kind": "fullfact"}, {"kind": "fracfact"}, {"kind": "pb"}, {"kind": "bbd"},
                     {"kind": "ccd"}, {"kind": "table", "text": "A_THK_1\n1\n2\n"}):
        r = _post(env, {"param_set_id": ps["id"], "sampling": sampling})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "DOE_SAMPLING_INVALID", (sampling, r.text)
        assert r.json()["detail"]["problems"] == [{"code": "DESIGN_UNSUPPORTED", "message": registry.MULTI_UNSUPPORTED_MESSAGE}]
    r = _post(env, {"param_set_id": ps["id"], "sampling": {"kind": "halton", "count": 501}})
    assert r.json()["detail"]["problems"] == [{"code": "TOO_MANY_ROWS", "message": "조합 수는 최대 500개입니다"}]
    r = _post(env, {"param_set_id": ps["id"], "sampling": {"kind": "random", "count": 4}, "seed": 3})
    assert r.status_code == 422
