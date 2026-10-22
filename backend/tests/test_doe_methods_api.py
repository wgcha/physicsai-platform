"""doe-methods.md DM-C3·C6·C8·V-DM-4·V-DM-8(서버): ④ 배치 halton·random(미리보기·생성·DB source_kind·⑤ 영향도 formal), ④ 표 범위 밖은 기존대로 허용,
사이트별 허용 method(openapi 판별 유니온·⑥ method enum) = registry.SITE_KINDS."""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers_api import P
from physicsai_core.sampling import registry
from physicsai_test_support import API
from test_api_predict_batch import _batch, _end, _setup
from test_sampling_api import _preview, _three_params

pytest.importorskip("numpy")
pytest.importorskip("scipy")


@pytest.mark.parametrize("src,kind,label,cls", [
    ({"kind": "halton", "count": 7, "seed": 5}, "HALTON", "Halton(스크램블 QMC)", "formal"),
    ({"kind": "random", "count": 5, "seed": 6}, "RANDOM", "균일 랜덤", "formal")])
def test_v_dm_4_batch_halton_random_preview_create_detail(client, loaded_config, worker_factory, engine, src, kind, label, cls):
    from physicsai_core.db.repositories import predict_batches as pb_repo

    ai = Path(loaded_config.settings.storage.ai_root)
    sid, _mid, _ps = _setup(client, worker_factory(), ai)
    r = _preview(client, sid, src)
    assert r.status_code == 200, r.text
    pv = r.json()
    sp = pv["sampling"]
    assert pv["problems"] == [] and pv["count"] == src["count"] == len(pv["rows"])
    assert (sp["kind"], sp["method"], sp["label"], sp["desc_id"], sp["influence_class"]) == (src["kind"], kind, label, src["kind"], cls)
    assert sp["influence_note"] is None and isinstance(sp["recommended_count"], int)
    assert set(sp["meta"]["quality"]) == {"min_dist", "max_abs_corr"} and sp["meta"]["seed"] == src["seed"]
    assert {"THK_1", "N_RIB"} <= set(pv["rows"][0]["values"])
    again = _preview(client, sid, src).json()
    assert again["rows"] == pv["rows"]                                                       # 같은 입력 같은 값
    job = _batch(client, sid, src, me=2)
    assert job.status_code == 201, job.text
    bid = job.json()["params"]["batch_id"]
    assert job.json()["params"]["source"]["kind"] == src["kind"]
    with engine.connect() as conn:
        b = pb_repo.get(conn, bid)
        runs = pb_repo.runs(conn, bid)
    assert (b["source_kind"], b["run_count"]) == (kind, src["count"])
    assert [{k: x[k] for k in ("doe_no", "run_key", "values", "applied_values", "out_of_range")} for x in runs] == pv["rows"]
    d = client.get(f"{API}/predict-batches/{bid}", headers=P).json()
    assert d["source_kind"] == kind and d["sampling"]["influence_class"] == cls and d["sampling"]["kind"] == src["kind"]
    _end(engine, job.json()["id"], "FAILED", failure_code="EXIT_NONZERO")


def test_v_dm_4_batch_halton_random_validation(client, loaded_config, worker_factory, engine):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid, _mid, ps = _setup(client, worker_factory(), ai)
    _three_params(engine, ps["id"])
    for src, code in (({"kind": "halton", "count": 1}, "TOO_FEW_ROWS"), ({"kind": "random", "count": 1}, "TOO_FEW_ROWS"),
                      ({"kind": "halton", "count": 201}, "TOO_MANY_ROWS"), ({"kind": "random", "count": 3, "ranges": {"THK_1": [5, 2]}},
                                                                             "RANGE_INVALID")):
        r = _preview(client, sid, src)
        assert r.status_code == 200 and [p["code"] for p in r.json()["problems"]] == [code], (src, r.text)
        g = _batch(client, sid, src)
        assert g.status_code == 422 and g.json()["detail"]["code"] == "BATCH_SOURCE_INVALID"
    for bad in ({"kind": "halton"}, {"kind": "halton", "count": 8, "seed": -1}, {"kind": "halton", "count": 8, "seed": 4294967296}, {"kind": "random", "count": 8, "seed": -1},
                {"kind": "halton", "count": 8, "criterion": "corr"}, {"kind": "random", "count": 8, "extra": 1}):
        assert _preview(client, sid, bad).status_code == 422, bad
        g = _batch(client, sid, bad)
        assert g.status_code == 422 and g.json()["detail"]["code"] == "INVALID_PARAMS", bad
    # 3개 변수 세트: 모든 열이 설계에 쓰이고(고정 없음) 범위 안
    pv = _preview(client, sid, {"kind": "halton", "count": 6, "ranges": {"T_2": [1.5, 2.5]}}).json()
    assert pv["problems"] == [] and {r["values"]["T_2"] >= 1.5 and r["values"]["T_2"] <= 2.5 for r in pv["rows"]} == {True}
    assert pv["sampling"]["meta"]["ranges"]["T_2"] == [1.5, 2.5] and set(pv["sampling"]["meta"]["active"]) >= {"THK_1", "N_RIB", "T_2"}


def test_v_dm_8_openapi_site_enums_equal_site_kinds():
    import typing

    from physicsai_api.export_openapi import build_openapi
    from physicsai_api.schemas.stage1_train_data import TrainSampling

    comps = build_openapi()["components"]["schemas"]
    assert set(comps["PredictBatchPreviewRequest"]["properties"]["source"]["discriminator"]["mapping"]) == set(registry.SITE_KINDS["batch"])
    assert set(comps["SoExploreNew"]["properties"]["method"]["enum"]) == set(registry.SITE_KINDS["opt_explore"])
    members = typing.get_args(typing.get_args(TrainSampling)[0])
    train = {typing.get_args(m.model_fields["kind"].annotation)[0] for m in members}
    assert train == set(registry.SITE_KINDS["train_platform"]) == set(registry.PLATFORM_KINDS) | {"table", "train_doe"}
    assert registry.SITE_KINDS["train_native_multi"] == registry.SITE_KINDS["batch_multi"] == ("lhs_opt", "halton", "lhs", "random")
    assert registry.SITE_DEFAULT["batch"] == "lhs_opt" and registry.SITE_DEFAULT["train_native"] == "lhs"
    assert registry.SITE_DEFAULT["opt_explore"] == "lhs" and registry.SITE_DEFAULT["train_platform"] == "lhs_opt"
