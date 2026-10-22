"""doe-methods.md DM-C4·C5·V-DM-3/7: ⑥ 다중 baseline 탐색의 새 DOE method — baseline 층별 생성기(lhs·lhs_opt·halton·random)는 되고 sobol은
DESIGN_UNSUPPORTED(MULTI_UNSUPPORTED_MESSAGE). 생성 직후 탐색 배치(source_kind·meta·baseline 배정)만 확인한다. 가짜 paicad."""

from __future__ import annotations

import pytest
from helpers_native import native_set
from physicsai_test_support import API, H

from physicsai_core.sampling import registry

from .test_native_multi import B2_TOPO, _add, _confirm, _map, _put
from .test_on_multi_baseline import RESP, mb_env  # noqa: F401 - 픽스처 재사용

pytest.importorskip("numpy")
pytest.importorskip("scipy")

PW = H("tok-power", write=True)


def _ready(env, monkeypatch) -> dict:
    ps = native_set(env)
    _add(env, ps["id"], "B2", B2_TOPO, monkeypatch)
    pm = _map(env, ps["id"])
    _put(env, ps["id"], [{"row_id": x["row_id"], "decision": {"action": "accept"}} for x in pm["common"]])
    _confirm(env, ps["id"])
    env.set_responses(ps["id"], RESP)
    return ps


def _body(ps, explore):
    return {"param_set_id": ps["id"], "explore": explore, "objective": {"metric": "resp:MaxStress_MAX", "sense": "min"}, "iterations": 1,
            "candidates": 2, "tol_rel": 1e-9, "seed": 1, "multi_execution": 2, "algorithm": "ga", "algo_options": {"generations": 20},
            "levels": {"baseline": ["base", "B2"]}}


@pytest.mark.parametrize("method,source_kind", [("lhs", "LHS"), ("lhs_opt", "LHS_OPT"), ("halton", "HALTON"), ("random", "RANDOM")])
def test_v_dm_3_multi_explore_layer_generators(mb_env, monkeypatch, method, source_kind):  # noqa: F811
    env = mb_env
    ps = _ready(env, monkeypatch)
    body = _body(ps, {"kind": "new", "count": 8, "seed": 2, "method": method})
    pv = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json=body)
    assert pv.status_code == 200 and pv.json()["problems"] == [], pv.text
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json=body)
    assert r.status_code == 201, r.text
    assert registry.METHODS[method][0] == source_kind
    row = env.sql("select b.id, b.source_kind, b.source_meta, b.run_count from predict_batches b join surrogate_opt_iters i on i.batch_id=b.id"
                  " where i.opt_id=:o and i.iter_no=0", o=r.json()["id"])[0]
    assert row[1] == source_kind and row[3] == 8
    meta = row[2]
    assert set(meta["multi_baseline"]["assign"].values()) == {"base", "B2"} and meta["count"] == 8 and meta["seed"] == 2
    assert len(meta["multi_baseline"]["assign"]) == 8
    if method == "lhs_opt":
        assert meta["criterion"] == "maximin"
    d = env.c.get(f"{API}/surrogate-opts/{r.json()['id']}", headers=H("tok-power")).json()
    assert {x["values"]["baseline"] for x in d["runs"] if x["iter_no"] == 0} == {0.0, 1.0}


def test_v_dm_3_multi_explore_sobol_unsupported(mb_env, monkeypatch):  # noqa: F811
    env = mb_env
    ps = _ready(env, monkeypatch)
    body = _body(ps, {"kind": "new", "count": 8, "method": "sobol"})
    pv = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts/preview", headers=PW, json=body)
    assert pv.status_code == 200
    assert [(p["code"], p["field"], p["message"]) for p in pv.json()["problems"]] == [
        ("DESIGN_UNSUPPORTED", "explore.method", registry.MULTI_UNSUPPORTED_MESSAGE)]
    r = env.c.post(f"{API}/studies/{env.sid}/surrogate-opts", headers=PW, json=body)
    assert r.status_code == 422 and r.json()["detail"]["problems"][0]["code"] == "DESIGN_UNSUPPORTED"
