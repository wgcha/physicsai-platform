"""doe-methods.md DM-C5·C8·V-DM-7: ⑥ 내장 최적화 탐색 새 DOE `explore.method`(lhs 기본·lhs_opt·sobol·halton·random) —
method 생략 요청의 탐색 배치·settings 저장본이 기존과 같고, 각 method의 source_kind·meta·sobol count(2^m)·criterion 오용 422를 확인한다.
(생성 직후 상태만 — 반복 실행 전체 흐름은 test_surrogate_flow)"""

from __future__ import annotations

import random
from typing import Any

import pytest

from physicsai_core.sampling import registry
from physicsai_test_support import API, H

pytest.importorskip("numpy")
pytest.importorskip("scipy")

PW = H("tok-power", write=True)
P = H("tok-power")
TCL_NAME = "H3D_StaticMinMax_to_CSV_FAST.tcl"
RESP = [{"name": "MaxStress", "unit": "MPa",
         "spec": {"source": "H3D", "subcase": 1, "datatype": "Stress", "component": "vonMises", "layer": "", "stat": "MAX"}},
        {"name": "Disp", "unit": "mm", "spec": None}]


@pytest.fixture()
def so_env(predict_env, tmp_path):
    tcl = tmp_path / "res" / TCL_NAME
    tcl.parent.mkdir(parents=True)
    tcl.write_text("# fake\n")
    env = predict_env(commands={"response_extract": ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"]},
                      resources={"extract_minmax_tcl": str(tcl)})
    ps = env.param_set()
    r = env.c.put(f"{API}/param-sets/{ps['id']}/responses", headers=PW, json={"responses": RESP})
    assert r.status_code == 200, r.text
    env.ps = ps  # type: ignore[attr-defined]
    return env


def _body(explore: dict[str, Any], **kw: Any) -> dict[str, Any]:
    b = {"explore": explore, "objective": {"metric": "resp:MaxStress_MAX", "sense": "min"}, "iterations": 2, "candidates": 2, "tol_rel": 1e-6, "seed": 1,
         "multi_execution": 2}
    b.update(kw)
    return b


def _create(env, explore, **kw):
    return env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json=_body(explore, **kw))


def _batch(env, opt_id: str) -> dict[str, Any]:
    r = env.sql("select b.source_kind, b.source_meta, b.run_count, b.id from predict_batches b join surrogate_opt_iters i on i.batch_id = b.id"
                " where i.opt_id=:o and i.iter_no=0", o=opt_id)[0]
    runs = env.sql("select doe_no, values, applied_values, out_of_range from predict_batch_runs where batch_id=:b order by doe_no", b=r[3])
    return {"source_kind": r[0], "meta": r[1], "run_count": r[2], "runs": [(x[0], x[1], x[2], x[3]) for x in runs]}


def _settings(env, opt_id: str) -> dict[str, Any]:
    return env.sql("select settings from surrogate_opts where id=:o", o=opt_id)[0][0]


def _lhs_expected(names, bounds, n, seed):
    rng = random.Random(seed)
    cols = {}
    for name in names:
        lo, hi = bounds[name]
        perm = list(range(n))
        rng.shuffle(perm)
        cols[name] = [lo + (perm[i] + rng.random()) / n * (hi - lo) for i in range(n)]
    return cols


def test_v_dm_7_method_omitted_is_unchanged_lhs(so_env):
    """method 생략 = 기존 LHS: source_kind LHS, meta {count, seed, ranges}, settings.explore에 method 없음, 값 = lhs 알고리즘."""
    env = so_env
    pv = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json=_body({"kind": "new", "count": 6, "seed": 4}))
    assert pv.status_code == 200 and pv.json()["explore_count"] == 6 and pv.json()["problems"] == []
    r = _create(env, {"kind": "new", "count": 6, "seed": 4})
    assert r.status_code == 201, r.text
    oid = r.json()["id"]
    assert _settings(env, oid)["explore"] == {"kind": "new", "count": 6, "seed": 4}
    b = _batch(env, oid)
    assert b["source_kind"] == "LHS" and b["run_count"] == 6
    bounds = _settings(env, oid)["bounds"]
    assert set(b["meta"]) == {"count", "seed", "ranges"} and b["meta"]["count"] == 6 and b["meta"]["seed"] == 4 and b["meta"]["ranges"] == bounds
    names = [x for x in _settings(env, oid)["names"] if x in {p["name"] for p in env.ps["parameters"]}]
    cols = _lhs_expected(names, {n: tuple(v) for n, v in bounds.items()}, 6, 4)
    for i, (no, vals, _ap, _oor) in enumerate(b["runs"]):
        assert no == i + 1 and [vals[n] for n in names] == [cols[n][i] for n in names]
    # 명시 method:"lhs"도 같은 값(같은 seed)
    env.c.post(f"{API}/surrogate-opts/{oid}/cancel", headers=H("tok-admin", write=True))
    r2 = _create(env, {"kind": "new", "count": 6, "seed": 4, "method": "lhs"})
    assert r2.status_code == 201, r2.text
    assert _batch(env, r2.json()["id"])["runs"] == b["runs"] and _settings(env, r2.json()["id"])["explore"] == {"kind": "new", "count": 6, "seed": 4}


@pytest.mark.parametrize("method,count,source_kind", [("lhs_opt", 6, "LHS_OPT"), ("sobol", 8, "SOBOL"), ("halton", 7, "HALTON"),
                                                      ("random", 5, "RANDOM")])
def test_v_dm_7_each_method_source_kind_meta_and_values(so_env, method, count, source_kind):
    env = so_env
    explore = {"kind": "new", "count": count, "seed": 3, "method": method}
    r = _create(env, explore)
    assert r.status_code == 201, r.text
    oid = r.json()["id"]
    st = _settings(env, oid)
    assert st["explore"] == {"kind": "new", "count": count, "seed": 3, "method": method,
                             **({"criterion": "maximin"} if method == "lhs_opt" else {})}
    b = _batch(env, oid)
    assert b["source_kind"] == source_kind == registry.METHODS[method][0] and b["run_count"] == count
    meta = b["meta"]
    assert meta["count"] == count and meta["seed"] == 3 and set(meta["quality"]) == {"min_dist", "max_abs_corr"}
    assert meta["active"] == list(st["names"]) and meta["fixed"] == [] and meta["ranges"] == {n: list(v) for n, v in st["bounds"].items()}
    if method == "lhs_opt":
        assert meta["criterion"] == "maximin"
    if method == "sobol":
        assert meta["m"] == 3 and meta["scramble"] is True and meta["offset"] == 0 and meta["generator"].startswith("scipy ")
    if method == "halton":
        assert meta["scramble"] is True and meta["generator"].startswith("scipy ")
    for no, vals, ap, oor in b["runs"]:
        for n, (lo, hi) in st["bounds"].items():
            assert lo <= vals[n] <= hi
        assert oor == []
    assert env.c.get(f"{API}/surrogate-opts/{oid}", headers=P).json()["progress_text"].startswith("탐색 B-001")
    # 같은 입력 같은 값(결정적)
    env.c.post(f"{API}/surrogate-opts/{oid}/cancel", headers=H("tok-admin", write=True))
    again = _create(env, explore)
    assert again.status_code == 201, again.text
    assert _batch(env, again.json()["id"])["runs"] == b["runs"]


def test_v_dm_7_fixed_variable_excluded_from_design(so_env):
    env = so_env
    names = [p["name"] for p in env.ps["parameters"]]
    bounds = {names[0]: [env.ps["parameters"][0]["min"], env.ps["parameters"][0]["min"]]}     # lo = hi → 고정
    r = _create(env, {"kind": "new", "count": 6, "seed": 1, "method": "halton"}, bounds=bounds)
    assert r.status_code == 201, r.text
    b = _batch(env, r.json()["id"])
    assert b["meta"]["fixed"] == [names[0]] and b["meta"]["active"] == names[1:]
    assert {vals[names[0]] for _no, vals, _a, _o in b["runs"]} == {env.ps["parameters"][0]["min"]}


def test_v_dm_7_sobol_count_default_and_validation(so_env):
    env = so_env
    pv = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json=_body({"kind": "new", "method": "sobol"}))
    assert pv.status_code == 200 and pv.json()["problems"] == []
    assert pv.json()["explore_count"] == 16                                                   # 기본 10(= max(10, 4·2)) 이상 가장 작은 2^m
    pv = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json=_body({"kind": "new", "method": "random"}))
    assert pv.json()["explore_count"] == 10                                                   # lhs 계열 기본 식 그대로
    pv = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json=_body({"kind": "new", "count": 12, "method": "sobol"}))
    assert [x["code"] for x in pv.json()["problems"]] == ["COUNT_NOT_POW2"] and pv.json()["problems"][0]["field"] == "explore.count"
    r = _create(env, {"kind": "new", "count": 12, "method": "sobol"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "SURROGATE_OPT_INVALID"
    assert r.json()["detail"]["problems"][0]["code"] == "COUNT_NOT_POW2"
    r = _create(env, {"kind": "new", "count": 201, "method": "halton"})
    assert r.status_code == 422 and r.json()["detail"]["problems"][0]["code"] == "EXPLORE_TOO_MANY"
    r = _create(env, {"kind": "new", "count": 2, "method": "halton"})
    assert r.status_code == 422 and r.json()["detail"]["problems"][0]["code"] == "EXPLORE_TOO_FEW"
    r = _create(env, {"kind": "new", "method": "sobol"})                                      # count 생략 = 16
    assert r.status_code == 201 and _batch(env, r.json()["id"])["run_count"] == 16


def test_v_dm_7_criterion_misuse_and_unknown_method_422(so_env):
    env = so_env
    for explore in ({"kind": "new", "count": 6, "criterion": "corr"}, {"kind": "new", "count": 6, "method": "sobol", "criterion": "corr"},
                    {"kind": "new", "count": 6, "method": "halton", "criterion": "maximin"},
                    {"kind": "new", "count": 6, "method": "fullfact"}, {"kind": "new", "count": 6, "method": "table"},
                    {"kind": "new", "count": 6, "method": "lhs_opt", "criterion": "zzz"}):
        for url in (f"{API}/studies/{env.sid}/surrogate-opts", f"{API}/studies/{env.sid}/surrogate-opts/preview"):
            r = env.c.post(url, headers=PW, json=_body(explore))
            assert r.status_code == 422, (explore, url, r.text)
    r = _create(env, {"kind": "new", "count": 6, "seed": 2, "method": "lhs_opt", "criterion": "corr"})
    assert r.status_code == 201, r.text
    assert _settings(env, r.json()["id"])["explore"]["criterion"] == "corr" and _batch(env, r.json()["id"])["meta"]["criterion"] == "corr"


def test_v_dm_7_sobol_default_count_helper():
    from physicsai_api.services.surrogate_opt_space import _explore_method, _is_pow2, _sobol_default_count

    assert [_sobol_default_count(n, 200) for n in (4, 5, 10, 16, 17, 100, 129, 200)] == [4, 8, 16, 16, 32, 128, 128, 128]
    assert _sobol_default_count(300, 200) == 128 and _sobol_default_count(300, 64) == 64 and _sobol_default_count(3, 200) == 4
    assert _is_pow2(8, 200) and not _is_pow2(12, 200) and not _is_pow2(2, 200) and not _is_pow2(256, 200)

    class Ex:
        def __init__(self, method, criterion=None):
            self.method, self.criterion = method, criterion

    assert _explore_method(Ex("lhs")) == {} and _explore_method(Ex("lhs", None)) == {}
    assert _explore_method(Ex("halton")) == {"method": "halton"} and _explore_method(Ex("lhs_opt")) == {"method": "lhs_opt", "criterion": "maximin"}
    assert _explore_method(Ex("lhs_opt", "corr")) == {"method": "lhs_opt", "criterion": "corr"}
