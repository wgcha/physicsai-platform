"""doe-methods.md(DM-C*) 순수 함수 시험: SITE_KINDS(V-DM-8 백엔드), halton·random(V-DM-4), ① table(V-DM-5), 다중 baseline 층 안 생성기(V-DM-3),
⑤ 영향도 등급(V-DM-10), 기존 방식 결과 불변(V-DM-6 일부), 성능 기록(V-DM-13)."""

from __future__ import annotations

import random
import time
import warnings
from types import SimpleNamespace

import numpy as np
import pytest

from physicsai_core.geometry import baselines as bl
from physicsai_core.sampling import designs, qmc, registry
from physicsai_core.sampling.layer_gen import layer_generator
from physicsai_core.sampling.matrix_basic import lhs_values
from physicsai_core.stage1_train_data import doe_platform
from physicsai_core.stage4_predict.batch_matrix import BatchShapeError, build_matrix, run_key_for
from physicsai_core.stage4_predict.batch_multi import build_multi_matrix

SETTINGS = SimpleNamespace(train_data=SimpleNamespace(platform_max_runs=500), predict_batch=SimpleNamespace(table_max_bytes=1 << 20, max_runs=200),
                           predict=SimpleNamespace(integer_rounding="half_up"))


def _setup(k: int, *, fmt: str = "%8.3f") -> dict:
    params = [{"name": f"P{i}", "nominal": 5.0, "min": 0.0, "max": 10.0, "use": True, "format": fmt, "unit": ""} for i in range(1, k + 1)]
    return {"parameters": params, "tpl_params": None}


def _build(source: dict, k: int = 3, *, max_runs: int = 200) -> object:
    params = [{"name": f"X{i}", "nominal": 5.0, "min": 0.0, "max": 10.0} for i in range(k)]
    tpl = [{"var": f"var_{i + 1}", "name": f"X{i}", "format": "%8.3f"} for i in range(k)]
    return build_matrix(source, parameters=params, tpl_params=tpl, max_runs=max_runs, table_max_bytes=1 << 20)


def _codes(items) -> list[str]:
    return [x["code"] for x in items]


# ---- V-DM-8(백엔드): SITE_KINDS = 요청 스키마 --------------------------------------------------------------------


def test_v_dm_8_site_kinds_table_and_defaults():
    full = ("lhs_opt", "sobol", "halton", "lhs", "random", "fullfact", "fracfact", "pb", "bbd", "ccd", "table", "train_doe")
    multi = ("lhs_opt", "halton", "lhs", "random")
    assert registry.SITE_KINDS == {"train_platform": full, "train_native": full, "train_native_multi": multi, "batch": full,
                                   "batch_multi": multi, "opt_explore": ("lhs", "lhs_opt", "sobol", "halton", "random")}
    assert tuple(registry.METHODS) == full                                         # §20.4 순서 = 드롭다운 순서
    for kinds in registry.SITE_KINDS.values():
        assert set(kinds) <= set(registry.METHODS)
    assert registry.SITE_DEFAULT == {"train_platform": "lhs_opt", "train_native": "lhs", "train_native_multi": "lhs", "batch": "lhs_opt",
                                     "batch_multi": "lhs", "opt_explore": "lhs"}
    for site, kind in registry.SITE_DEFAULT.items():
        assert kind in registry.SITE_KINDS[site]
    assert registry.PLATFORM_KINDS == tuple(k for k in full if k not in ("table", "train_doe"))
    assert {"HALTON", "RANDOM", "TABLE"} <= set(registry.PLATFORM_DOE_TYPES) and "TRAIN_DOE" not in registry.PLATFORM_DOE_TYPES
    assert doe_platform.KINDS == registry.SITE_KINDS["train_platform"] == registry.SITE_KINDS["train_native"]
    assert registry.method_info("halton") == ("HALTON", "Halton(스크램블 QMC)", "halton")
    assert registry.method_info("random") == ("RANDOM", "균일 랜덤", "random")
    assert registry.kind_of_source("HALTON") == "halton" and registry.kind_of_source("RANDOM") == "random"
    for k in ("halton", "random"):
        assert registry.recommended_count(k, 4, 200) == registry.recommended_count("lhs", 4, 200) == 40
        assert registry.recommended_count(k, 40, 200) == 200 and registry.recommended_count(k, 1, 200) == 10


# ---- V-DM-4 halton ------------------------------------------------------------------------------------------------


def test_v_dm_4_halton_range_determinism_and_scipy_match():
    m = _build({"kind": "halton", "count": 16, "seed": 3}, k=4)
    assert m.ok and m.source_kind == "HALTON" and len(m.rows) == 16
    assert all(0.0 <= r.values[f"X{j}"] <= 10.0 for r in m.rows for j in range(4))
    assert [r.run_key for r in m.rows] == [f"run__{i:05d}" for i in range(1, 17)]
    again = _build({"kind": "halton", "count": 16, "seed": 3}, k=4)
    assert [r.values for r in m.rows] == [r.values for r in again.rows]
    assert [r.values for r in m.rows] != [r.values for r in _build({"kind": "halton", "count": 16, "seed": 4}, k=4).rows]
    from scipy.stats import qmc as sq

    kw = qmc.rng_keyword(sq.Halton)
    direct = sq.Halton(d=4, scramble=True, **{kw: np.random.default_rng(3)}).random(16)
    for i, r in enumerate(m.rows):
        assert [r.values[f"X{j}"] for j in range(4)] == pytest.approx([10.0 * float(direct[i][j]) for j in range(4)], abs=1e-12)
    meta = m.source_meta
    assert {"count", "seed", "ranges", "scramble", "generator", "active", "fixed", "quality"} <= set(meta)
    assert meta["count"] == 16 and meta["seed"] == 3 and meta["scramble"] is True and meta["generator"] == qmc.generator_label()
    assert meta["active"] == ["X0", "X1", "X2", "X3"] and meta["fixed"] == [] and set(meta["quality"]) == {"min_dist", "max_abs_corr"}
    assert meta["ranges"]["X0"] == [0.0, 10.0]


def test_v_dm_4_halton_fixed_variable_excluded_and_inputs():
    params = [{"name": "A", "min": 0.0, "max": 10.0}, {"name": "B", "min": 3.0, "max": 3.0}]
    m = build_matrix({"kind": "halton", "count": 4}, parameters=params, tpl_params=[], max_runs=50, table_max_bytes=1000)
    assert m.ok and m.source_meta["fixed"] == ["B"] and {r.values["B"] for r in m.rows} == {3.0} and m.source_meta["seed"] == 1
    assert "FIXED_EXCLUDED" in _codes(m.notes)
    for bad, code in (({"kind": "halton", "count": 1}, "TOO_FEW_ROWS"), ({"kind": "halton", "count": 201}, "TOO_MANY_ROWS")):
        assert _codes(_build(bad).problems) == [code]
    for bad in ({"kind": "halton"}, {"kind": "halton", "count": 4, "seed": -1}, {"kind": "halton", "count": 4, "seed": 4294967296},
                {"kind": "halton", "count": 4, "seed": True}, {"kind": "halton", "count": "4"}):
        with pytest.raises(BatchShapeError):
            _build(bad)
    assert _build({"kind": "halton", "count": 4, "seed": 4294967295}).ok
    fixed_all = build_matrix({"kind": "halton", "count": 4}, parameters=[{"name": "A", "min": 1.0, "max": 1.0}], tpl_params=[], max_runs=50,
                             table_max_bytes=1000)
    assert _codes(fixed_all.problems) == ["DESIGN_UNSUPPORTED"]                    # k = 0


class _FakeHalton:
    calls: list[dict] = []

    def __init__(self, d, *, scramble=True, rng=None):
        type(self).calls.append({"d": d, "scramble": scramble, "rng": rng})
        self.d = d

    def random(self, n):
        warnings.warn("fake warning", UserWarning)
        return np.array([[((i + 1) * (j + 1) * 0.01) % 1.0 for j in range(self.d)] for i in range(n)])


class _FakeHaltonSeed(_FakeHalton):
    def __init__(self, d, *, scramble=True, seed=None):
        type(self).calls.append({"d": d, "scramble": scramble, "seed": seed})
        self.d = d


@pytest.mark.parametrize(("cls", "key"), [(_FakeHalton, "rng"), (_FakeHaltonSeed, "seed")])
def test_v_dm_4_halton_shares_kw_detection_and_suppresses_warning(monkeypatch, cls, key):
    cls.calls.clear()
    monkeypatch.setattr(qmc, "_load_halton", lambda: (cls, np, "9.9.9"))
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        pts, gen = qmc.halton_unit(3, 5, 11)
    assert [w for w in rec if issubclass(w.category, UserWarning)] == []
    assert gen == "scipy 9.9.9" and len(pts) == 5 and len(pts[0]) == 3
    assert set(cls.calls[0]) == {"d", "scramble", key} and cls.calls[0]["scramble"] is True and cls.calls[0]["d"] == 3
    assert isinstance(cls.calls[0][key], np.random.Generator)


def test_v_dm_4_halton_generator_unavailable(monkeypatch):
    def boom():
        raise qmc.GeneratorUnavailable(qmc.GENERATOR_UNAVAILABLE_MESSAGE)

    monkeypatch.setattr(qmc, "_load_halton", boom)
    m = _build({"kind": "halton", "count": 8})
    assert _codes(m.problems) == ["GENERATOR_UNAVAILABLE"] and m.rows == [] and "scipy" in m.problems[0]["message"]
    p = doe_platform.check({"kind": "halton", "count": 8}, _setup(3), SETTINGS)
    assert _codes(p.problems) == ["GENERATOR_UNAVAILABLE"]
    assert _build({"kind": "random", "count": 4}).ok and _build({"kind": "sobol", "count": 8}).ok   # 다른 방식은 영향 없음


def test_v_dm_4_halton_import_failure_is_wrapped(monkeypatch):
    import builtins

    real = builtins.__import__

    def fake(name, *a, **kw):
        if name.startswith("scipy"):
            raise ImportError("no scipy")
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(qmc.GeneratorUnavailable):
        qmc.halton_unit(2, 4, 1)


# ---- V-DM-4 random --------------------------------------------------------------------------------------------------


def test_v_dm_4_random_golden_row_major_consumption():
    rng = random.Random(5)
    expect = [[rng.random() for _ in range(3)] for _ in range(2)]                 # 행 우선: i마다 활성 변수 순서
    assert designs.random_unit(2, 3, 5) == expect
    assert [round(v, 12) for v in expect[0]] == [0.62290169489, 0.741786989261, 0.795193565566]
    m = _build({"kind": "random", "count": 6, "seed": 5}, k=3)
    assert m.ok and m.source_kind == "RANDOM" and len(m.rows) == 6
    rng = random.Random(5)
    for r in m.rows:
        for j in range(3):
            assert r.values[f"X{j}"] == 0.0 + rng.random() * 10.0
    assert [r.values for r in m.rows] == [r.values for r in _build({"kind": "random", "count": 6, "seed": 5}, k=3).rows]
    assert {"count", "seed", "ranges", "active", "fixed", "quality"} <= set(m.source_meta) and "generator" not in m.source_meta
    assert _build({"kind": "random", "count": 4}).source_meta["seed"] == 1
    # 고정 변수는 소비에서 빠진다(활성 변수 순서)
    params = [{"name": "A", "min": 0.0, "max": 1.0}, {"name": "F", "min": 2.0, "max": 2.0}, {"name": "B", "min": 0.0, "max": 1.0}]
    mf = build_matrix({"kind": "random", "count": 2, "seed": 9}, parameters=params, tpl_params=[], max_runs=10, table_max_bytes=100)
    rng = random.Random(9)
    assert [(r.values["A"], r.values["B"]) for r in mf.rows] == [(rng.random(), rng.random()) for _ in range(2)]
    for bad in ({"kind": "random", "count": 4, "seed": -1}, {"kind": "random"}, {"kind": "random", "count": 4, "seed": False}):
        with pytest.raises(BatchShapeError):
            _build(bad)
    assert _build({"kind": "random", "count": 4, "seed": 2 ** 40}).ok               # 상한 없음(0 이상)
    assert _codes(_build({"kind": "random", "count": 1}).problems) == ["TOO_FEW_ROWS"]


def test_halton_random_integer_rounding_and_duplicates():
    params = [{"name": "I", "min": 1.0, "max": 3.0}, {"name": "J", "min": 0.0, "max": 10.0}]
    tpl = [{"var": "var_1", "name": "I", "format": "%3i"}, {"var": "var_2", "name": "J", "format": "%8.3f"}]
    for kind in ("halton", "random"):
        m = build_matrix({"kind": kind, "count": 12, "seed": 2}, parameters=params, tpl_params=tpl, max_runs=50, table_max_bytes=100)
        assert m.ok and all(r.applied_values["I"] in (1.0, 2.0, 3.0) for r in m.rows)
        assert all(r.applied_values["J"] == r.values["J"] for r in m.rows)
        dup = len(m.rows) - len({tuple(r.applied_values.values()) for r in m.rows})
        assert ("DUPLICATE_ROWS" in _codes(m.notes)) == bool(dup)


# ---- doe_platform: 새 kind 입력 정규화·check = build ----------------------------------------------------------------


def test_doe_platform_new_kinds_normalize_and_check_equals_build():
    assert doe_platform.normalize({"kind": "halton", "count": 8}) == ("halton", {"count": 8, "seed": 1})
    assert doe_platform.normalize({"kind": "random", "count": 8, "seed": 3}) == ("random", {"count": 8, "seed": 3})
    assert doe_platform.normalize({"kind": "table", "text": "P1,P2\n1,2\n"}) == ("table", {"text": "P1,P2\n1,2\n"})
    for bad in ({"kind": "halton"}, {"kind": "random", "count": 4, "levels": {}}, {"kind": "halton", "count": 4, "criterion": "corr"},
                {"kind": "table"}, {"kind": "table", "text": 3}, {"kind": "table", "text": "a", "count": 3}, {"kind": "foo"}):
        with pytest.raises(BatchShapeError):
            doe_platform.normalize(bad)
    for kind, inp in (("halton", {"count": 12, "seed": 5}), ("random", {"count": 9, "seed": 6})):
        for k in range(2, 12):
            chk = doe_platform.check({"kind": kind, **inp}, _setup(k), SETTINGS)
            bld = doe_platform.build({"kind": kind, **inp}, _setup(k), SETTINGS)
            assert chk.run_count == bld.run_count == inp["count"] and chk.problems == bld.problems == []
            assert chk.doe_type == bld.doe_type == registry.METHODS[kind][0] and chk.desc_id == f"td_{kind}"
            assert chk.rows[0].values == bld.rows[0].values and bld.sampling_record(with_meta=True)["meta"] == bld.meta
    big = doe_platform.check({"kind": "halton", "count": 501}, _setup(3), SETTINGS)
    assert big.problems == [{"code": "TOO_MANY_ROWS", "message": "조합 수는 최대 500개입니다"}]


# ---- V-DM-5 ①의 table -----------------------------------------------------------------------------------------------


def _tbl(text: str, k: int = 3, settings=SETTINGS):
    return doe_platform.check({"kind": "table", "text": text}, _setup(k), settings)


def test_v_dm_5_table_ok_header_any_order_and_stored_input():
    p = _tbl("P3,P1,P2\n1,2,3\n4,5,6\n7,8,9\n")
    assert p.ok and p.run_count == 3 and p.doe_type == "TABLE" and p.label == "표 붙여넣기 / CSV" and p.desc_id == "td_table"
    assert p.rows[0].values == {"P1": 2.0, "P2": 3.0, "P3": 1.0} and [r.run_key for r in p.rows] == ["run__00001", "run__00002", "run__00003"]
    assert p.stored_input() == {"row_count": 3} and "text" in p.input                    # DB에는 본문 대신 행 수
    assert p.sampling_record(with_meta=False) == {"kind": "table", "input": {"row_count": 3}, "meta": None}
    assert doe_platform.stored_input("table", p.input, 3) == {"row_count": 3}
    assert doe_platform.stored_input("halton", {"count": 4, "seed": 1}, 4) == {"count": 4, "seed": 1}
    tab = _tbl("P1\tP2\tP3\n0\t0\t0\n10\t10\t10\n")                                       # 탭·경계값(= min·max)은 범위 안
    assert tab.ok
    bom = _tbl("﻿P1,P2,P3\n1,2,3\n4,5,6\n")
    assert bom.ok
    assert doe_platform.build({"kind": "table", "text": "P1,P2,P3\n1,2,3\n4,5,6\n"}, _setup(3), SETTINGS).rows[1].applied_values["P1"] == 4.0


def test_v_dm_5_table_problems():
    assert _codes(_tbl("P1,P2\n1,2\n3,4\n").problems) == ["TABLE_HEADER"]                # 열 없음(P3)
    assert _codes(_tbl("P1,P2,P3,ZZ\n1,2,3,4\n1,2,3,4\n").problems) == ["TABLE_HEADER"]  # 모르는 열
    assert _codes(_tbl("P1,P1,P2,P3\n1,2,3,4\n1,2,3,4\n").problems)[0] == "TABLE_HEADER"
    bad = _tbl("P1,P2,P3\n1,x,3\n4,5,6\n")
    assert _codes(bad.problems) == ["TABLE_VALUE"] and bad.problems[0]["row"] == 1
    assert _codes(_tbl("P1,P2,P3\n1,nan,3\n4,5,inf\n").problems) == ["TABLE_VALUE", "TABLE_VALUE"]
    assert _codes(_tbl("P1,P2,P3\n1,2\n4,5,6\n").problems) == ["TABLE_VALUE"]
    assert _codes(_tbl("P1,P2,P3\n1,2,3\n").problems) == ["TOO_FEW_ROWS"]               # ①은 행 2개 이상(④는 1개)
    assert _codes(_tbl("P1,P2,P3\n").problems) == ["TOO_FEW_ROWS"]
    assert _codes(_tbl("").problems) == ["TABLE_HEADER"]
    small = SimpleNamespace(train_data=SimpleNamespace(platform_max_runs=3), predict_batch=SimpleNamespace(table_max_bytes=1 << 20),
                            predict=SimpleNamespace(integer_rounding="half_up"))
    many = _tbl("P1,P2,P3\n" + "1,2,3\n" * 4, settings=small)
    assert many.problems == [{"code": "TOO_MANY_ROWS", "message": "행은 최대 3개입니다(현재 4개)"}]
    assert _tbl("P1,P2,P3\n" + "1,2,3\n" * 3, settings=small).ok
    tiny = SimpleNamespace(train_data=SimpleNamespace(platform_max_runs=500), predict_batch=SimpleNamespace(table_max_bytes=10),
                           predict=SimpleNamespace(integer_rounding="half_up"))
    assert _codes(_tbl("P1,P2,P3\n1,2,3\n4,5,6\n", settings=tiny).problems) == ["TEXT_TOO_LARGE"]


def test_v_dm_5_table_out_of_range_blocked_but_batch_table_allows():
    p = _tbl("P1,P2,P3\n1,2,3\n4,5,60\n-1,5,6\n")
    assert _codes(p.problems) == ["TABLE_OUT_OF_RANGE", "TABLE_OUT_OF_RANGE"]
    assert p.problems[0] == {"code": "TABLE_OUT_OF_RANGE", "message": "'P3' 값 60가 학습 범위 0~10 밖입니다", "row": 2}
    assert p.problems[1]["message"] == "'P1' 값 -1가 학습 범위 0~10 밖입니다" and p.problems[1]["row"] == 3 and not p.ok
    assert _codes(doe_platform.build({"kind": "table", "text": "P1,P2,P3\n1,2,3\n4,5,60\n"}, _setup(3), SETTINGS).problems) == ["TABLE_OUT_OF_RANGE"]
    # 같은 표를 ④(build_matrix table)가 받으면 기존대로 허용 + out_of_range 표시
    params = [{"name": f"P{i}", "min": 0.0, "max": 10.0} for i in (1, 2, 3)]
    m = build_matrix({"kind": "table", "text": "P1,P2,P3\n1,2,3\n"}, parameters=params, tpl_params=[], max_runs=10, table_max_bytes=1000)
    assert m.ok and len(m.rows) == 1                                                   # ④는 1행도 허용(기존)
    m = build_matrix({"kind": "table", "text": "P1,P2,P3\n1,2,3\n4,5,60\n"}, parameters=params, tpl_params=[], max_runs=10, table_max_bytes=1000)
    assert m.ok and m.rows[1].out_of_range == ["P3"] and m.problems == []
    # inputs 인자(Native 세트 기준) — 범위는 inputs 기준
    inputs = doe_platform.design_inputs_from_params([{"name": "A", "min": 0.0, "max": 1.0, "nominal": 0.5}, {"name": "B", "min": 2.0, "max": 3.0}])
    ok = doe_platform.check({"kind": "table", "text": "A,B\n0.5,2.5\n1,3\n"}, {}, SETTINGS, inputs=inputs)
    assert ok.ok and ok.run_count == 2
    bad = doe_platform.check({"kind": "table", "text": "A,B\n0.5,2.5\n1,3.5\n"}, {}, SETTINGS, inputs=inputs)
    assert bad.problems[0]["message"] == "'B' 값 3.5가 학습 범위 2~3 밖입니다"


def test_table_problem_code_registered():
    from physicsai_core.sampling.matrix_rows import PROBLEM_CODES

    assert "TABLE_OUT_OF_RANGE" in PROBLEM_CODES


# ---- V-DM-3 다중 baseline 층 안 생성기 --------------------------------------------------------------------------------


def _pm():
    return {"schema_version": 1, "status": "confirmed", "confirmed_by": "u", "confirmed_at": "t", "usage": "topology",
            "baselines": [{"id": "base", "rel": "."}, {"id": "B2", "rel": "baselines/B2"}, {"id": "B3", "rel": "baselines/B3"}],
            "discrete": {"name": "baseline", "values": ["base", "B2", "B3"]}, "range_split": None,
            "common": [
                {"row_id": "r1", "type": "thickness", "unit": "mm", "signature": "s1", "needs_review": False,
                 "proposed": {"name": "T", "grade": "recommend", "map": {"base": "T1", "B2": "T2", "B3": "T3"},
                              "nominal": {"base": 10.0, "B2": 15.0, "B3": 12.0}},
                 "decision": {"action": "accept", "name": "T", "map": {"base": "T1", "B2": "T2", "B3": "T3"}}},
                {"row_id": "r2", "type": "radius", "unit": "mm", "signature": "s2", "needs_review": False,
                 "proposed": {"name": "R", "grade": "recommend", "map": {"base": "R1", "B2": None, "B3": "R3"},
                              "nominal": {"base": 4.0, "B2": None, "B3": 5.0}},
                 "decision": {"action": "accept", "name": "R", "map": {"base": "R1", "B2": None, "B3": "R3"}}}]}


def _multi_set():
    feats = {"base": {"T1": {"nominal": 10.0, "range": {"min": 9.5, "max": 10.5}}, "R1": {"nominal": 4.0, "range": {"min": 3.8, "max": 4.2}}},
             "B2": {"T2": {"nominal": 15.0, "range": {"min": 14.25, "max": 15.75}}},
             "B3": {"T3": {"nominal": 12.0, "range": {"min": 11.4, "max": 12.6}}, "R3": {"nominal": 5.0, "range": {"min": 4.5, "max": 5.5}}}}
    pm = _pm()
    rows = bl.parameter_rows(pm, feats, {"base": {}, "B2": {}, "B3": {}})
    return pm, {"id": "ps", "parameters": rows}


def _multi(source: dict):
    pm, ps = _multi_set()
    return build_multi_matrix(source, ps, pm, SETTINGS)


def test_v_dm_3_lhs_stratified_golden_unchanged():
    """DM-C8: lhs 층화 행 = 기존 `stratified_lhs(…, lhs_values, …)` 결과 그대로(층 seed = seed + 층 번호)."""
    pm, ps = _multi_set()
    old = bl.stratified_lhs(pm, ps["parameters"], 7, 4, lhs_values, run_key_for, {})
    m = build_multi_matrix({"kind": "lhs", "count": 7, "seed": 4}, ps, pm, SETTINGS)
    assert m.ok and m.source_kind == "LHS" and m.source_meta["count"] == 7 and m.source_meta["seed"] == 4
    assert set(m.source_meta) == {"count", "seed", "multi_baseline"}                    # lhs meta 모양 불변
    assert [r.values for r in m.rows] == [{k: (0.0 if v is None else v) for k, v in o[3].items()} for o in old]
    assert m.source_meta["multi_baseline"]["stratum"] == {str(o[0]): o[2] for o in old}
    assert layer_generator("lhs") is lhs_values


@pytest.mark.parametrize("kind", ["lhs_opt", "halton", "lhs", "random"])
def test_v_dm_3_layer_kinds_stratify_and_are_deterministic(kind):
    src = {"kind": kind, "count": 8, "seed": 5}
    a, b = _multi(src), _multi(src)
    assert a.ok and a.source_kind == registry.METHODS[kind][0] and len(a.rows) == 8
    assert [r.values for r in a.rows] == [r.values for r in b.rows]
    strata = list(a.source_meta["multi_baseline"]["stratum"].values())
    per = [strata.count(x) for x in ("base", "B2", "B3")]
    assert sum(per) == 8 and max(per) - min(per) <= 1 and per == [3, 3, 2]             # 앞쪽 baseline부터 나머지 1씩
    assert strata == ["base"] * 3 + ["B2"] * 3 + ["B3"] * 2
    for r, s in zip(a.rows, strata):
        lo, hi = {"base": (9.5, 10.5), "B2": (14.25, 15.75), "B3": (11.4, 12.6)}[s]
        assert lo <= r.values["T"] <= hi
        if s == "B2":
            assert r.values["R"] == 0.0                                                # N/A 변수 = 0
        else:
            assert ({"base": 3.8, "B3": 4.5}[s]) <= r.values["R"] <= ({"base": 4.2, "B3": 5.5}[s])
    assert [r.values for r in a.rows] != [r.values for r in _multi({**src, "seed": 6}).rows]
    if kind == "lhs_opt":
        assert a.source_meta["criterion"] == "maximin"
        assert _multi({**src, "criterion": "corr"}).source_meta["criterion"] == "corr"
    if kind == "halton":
        assert a.source_meta["scramble"] is True and a.source_meta["generator"] == qmc.generator_label()
    others = _multi({"kind": "lhs" if kind != "lhs" else "random", "count": 8, "seed": 5})
    assert [r.values for r in a.rows] != [r.values for r in others.rows]


def test_v_dm_3_layer_seed_is_seed_plus_layer_index():
    pm, ps = _multi_set()
    raw = bl.stratified_lhs(pm, ps["parameters"], 6, 10, layer_generator("random"), run_key_for, {})
    layer1 = [r for r in raw if r[2] == "B2"]
    rng = random.Random(11)                                                            # 층 k = 1 → seed 11, B2 활성 변수 = T만
    assert [r[3]["T"] for r in layer1] == [14.25 + rng.random() * 1.5 for _ in layer1]
    gen = layer_generator("halton")
    assert gen(["A"], {"A": (0.0, 1.0)}, 4, 3) == gen(["A"], {"A": (0.0, 1.0)}, 4, 3)
    # 고정 변수(lo = hi)는 설계에서 빠지고 고정값, 점 1개 층의 lhs_opt는 lhs와 같다
    out = layer_generator("lhs_opt")(["A", "F"], {"A": (0.0, 1.0), "F": (2.0, 2.0)}, 5, 1)
    assert {r["F"] for r in out} == {2.0} and len({r["A"] for r in out}) == 5
    assert layer_generator("lhs_opt")(["A"], {"A": (0.0, 1.0)}, 1, 3) == lhs_values(["A"], {"A": (0.0, 1.0)}, 1, 3)
    assert layer_generator("random")(["F"], {"F": (2.0, 2.0)}, 3, 1) == [{"F": 2.0}] * 3
    with pytest.raises(ValueError):
        layer_generator("sobol")


def test_v_dm_3_multi_unsupported_kinds_and_shape_errors():
    for src in ({"kind": "sobol", "count": 8}, {"kind": "fullfact"}, {"kind": "fracfact"}, {"kind": "pb"}, {"kind": "bbd"}, {"kind": "ccd"},
                {"kind": "table", "text": "T,R\n1,2\n"}, {"kind": "train_doe", "doe_id": "x"}):
        m = _multi(src)
        assert _codes(m.problems) == ["MULTI_BASELINE_SOURCE"] and m.rows == []
        assert m.problems[0]["message"] == "다중 baseline 세트는 baseline별 층화라 LHS·최적화 LHS·Halton·균일 랜덤만 됩니다"
        assert m.problems[0]["message"] == registry.MULTI_UNSUPPORTED_MESSAGE
    for src in ({"kind": "halton", "count": 1}, {"kind": "random", "count": 201}, {"kind": "lhs_opt", "count": 1}):
        assert _codes(_multi(src).problems) == ["TOO_FEW_ROWS" if src["count"] < 2 else "TOO_MANY_ROWS"]
    assert _codes(_multi({"kind": "halton", "count": 6, "ranges": {"T": [1, 2]}}).problems) == ["RANGE_INVALID"]
    with pytest.raises(BatchShapeError):
        _multi({"kind": "random", "count": "x"})
    with pytest.raises(BatchShapeError):
        _multi({"kind": "random", "count": 4, "criterion": "corr"})
    with pytest.raises(BatchShapeError):
        _multi({"kind": "lhs_opt", "count": 4, "criterion": "zzz"})


def test_v_dm_3_multi_halton_unavailable(monkeypatch):
    def boom():
        raise qmc.GeneratorUnavailable(qmc.GENERATOR_UNAVAILABLE_MESSAGE)

    monkeypatch.setattr(qmc, "_load_halton", boom)
    m = _multi({"kind": "halton", "count": 6})
    assert _codes(m.problems) == ["GENERATOR_UNAVAILABLE"] and m.rows == []
    assert _multi({"kind": "random", "count": 6}).ok


# ---- V-DM-10 ⑤ 영향도 등급 ---------------------------------------------------------------------------------------------


def test_v_dm_10_influence_classes():
    inf, bi = registry.doe_influence, registry.batch_influence
    assert bi("HALTON", {}) == bi("RANDOM", {}) == (registry.FORMAL, None)
    assert inf("HALTON", {}) == inf("RANDOM", {}) == (registry.FORMAL, None)
    assert inf("TABLE", {}) == (registry.REFERENCE, registry.NOTE_TABLE) == bi("TABLE", {})
    assert inf("NATIVE_LHS", {"seed": 1}) == (registry.FORMAL, None)                  # 부수 발견 수정
    # 기존 등급 표(S15 §20.7) 무변경
    for src in ("LHS", "LHS_OPT", "SOBOL", "FULLFACT"):
        assert bi(src, {}) == (registry.FORMAL, None) == inf(src, {})
    assert bi("FRACFACT", {"resolution": 5}) == (registry.REFERENCE, registry.NOTE_FRAC_V)
    assert bi("PB", {}) == (registry.REFERENCE, registry.NOTE_PB)
    assert bi("BBD", {}) == bi("CCD", {}) == (registry.REFERENCE, registry.NOTE_RSM)
    assert inf("TYPE_SOBOL", {}) == (registry.FORMAL, None) and inf("TYPE_FRACFACT", {"RESOLUTION": "3"})[1] == registry.NOTE_FRAC_III
    assert inf("WHATEVER", {}) == (registry.REFERENCE, registry.NOTE_UNKNOWN_DOE)
    assert bi("HALTON", {}, "VERIFY") == (registry.REFERENCE, registry.NOTE_VERIFY)


# ---- V-DM-6 일부: 기존 방식 결과 불변(골든) -----------------------------------------------------------------------------


def test_v_dm_6_existing_kind_goldens_unchanged():
    assert lhs_values(["A", "B"], {"A": (9.5, 10.5), "B": (0.0, 1.0)}, 4, 7) == [
        {"A": 10.412733618259963, "B": 0.2593739146104962}, {"A": 9.768109071666885, "B": 0.8584114209155964},
        {"A": 9.633970501076671, "B": 0.5174638558936547}, {"A": 10.091422229228147, "B": 0.022678253335966264}]
    sob = _build({"kind": "sobol", "count": 8, "seed": 7}, k=2)
    assert sob.ok and sob.source_kind == "SOBOL" and sob.source_meta["offset"] == 0
    lo = _build({"kind": "lhs_opt", "count": 6, "seed": 2}, k=3)
    assert lo.ok and lo.source_meta["criterion"] == "maximin" and lo.source_meta["candidates"] == designs.LHS_OPT_CANDIDATES


# ---- V-DM-13 성능 기록 --------------------------------------------------------------------------------------------------


def test_v_dm_13_performance_records(capsys):
    """lhs_opt n=500·k=30(워커 build), halton n=500·k=50 생성 시간을 기록한다. lhs_opt가 60초를 넘으면 R2 조치를 Plan에 보고해야 한다."""
    big = SimpleNamespace(train_data=SimpleNamespace(platform_max_runs=500), predict_batch=SimpleNamespace(table_max_bytes=1 << 20),
                          predict=SimpleNamespace(integer_rounding="half_up"))
    t0 = time.perf_counter()
    lo = doe_platform.build({"kind": "lhs_opt", "count": 500, "seed": 1}, _setup(30), big)
    t_lo = time.perf_counter() - t0
    t0 = time.perf_counter()
    ha = doe_platform.build({"kind": "halton", "count": 500, "seed": 1}, _setup(50), big)
    t_ha = time.perf_counter() - t0
    with capsys.disabled():
        print(f"\n[V-DM-13] lhs_opt n=500 k=30: {t_lo:.1f}s · halton n=500 k=50: {t_ha:.1f}s")
    assert lo.ok and lo.run_count == 500 and ha.ok and ha.run_count == 500
    assert t_lo < 60.0 and t_ha < 60.0


# ---- design_inputs_native · V-DM-12(의존성·마이그레이션) ------------------------------------------------------------


def test_design_inputs_native_no_integer_rounding_vs_design_inputs():
    setup = _setup(2, fmt="%3i")
    nat_params, nat_tpl = doe_platform.design_inputs_native(setup)
    params, tpl = doe_platform.design_inputs(setup)
    assert nat_params == params and nat_tpl == [] and tpl and all(t["format"] == "%3i" for t in tpl)   # tpl이 없어 정수 반올림 대상이 없다
    plan_nat = doe_platform.build({"kind": "halton", "count": 6, "seed": 2}, setup, SETTINGS, inputs=(nat_params, nat_tpl))
    plan_alt = doe_platform.build({"kind": "halton", "count": 6, "seed": 2}, setup, SETTINGS)
    assert [r.values for r in plan_nat.rows] == [r.values for r in plan_alt.rows]
    assert all(r.applied_values == r.values for r in plan_nat.rows)                                    # Native: 반영값 = 설계 값
    assert any(r.applied_values != r.values for r in plan_alt.rows)                                    # Altair: %3i 정수 반올림


def test_v_dm_12_single_migration_and_head():
    import re
    from pathlib import Path

    from physicsai_core.db import MIGRATION_HEAD

    root = Path(__file__).resolve().parents[2]
    mig = sorted(p.name for p in (root / "migrations" / "versions").glob("*_doe_methods.py"))
    assert mig == ["0023_doe_methods.py"] and MIGRATION_HEAD == "0025_doe_preview"
    text = (root / "migrations" / "versions" / mig[0]).read_text(encoding="utf-8")
    assert re.search(r'^revision\s*=\s*"0023_doe_methods"', text, re.M)
