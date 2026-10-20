"""equiv-check.md V-EQ-2(레시피 검증 골든)·V-EQ-5(쌍 매칭)·V-EQ-6(지표 수학 골든, 1e-9) — 순수 함수."""

from __future__ import annotations

import math

import pytest

from physicsai_core.config.schema_equiv import default_system_recipe
from physicsai_core.equiv import metrics as mx
from physicsai_core.equiv import pairing as pr
from physicsai_core.equiv import recipes as rc
from physicsai_core.equiv import volume as vol

TOL = 1e-9


def _m(mid="accel_peak", kind="scalar", source=None, tol=None, **kw):
    if source is None and kind != "mesh_volume":
        source = {"type": "perf", "perf": "ACC"}
    if kind == "mesh_volume" and source is None:
        source = {"type": "mesh_volume", "parts": "cushion"}
    if tol is None:
        tol = {"rel_pct": 5.0} if kind in ("scalar", "mesh_volume") else ({"corr_min": 0.95} if kind == "curve_corr" else {"nrmse_max_pct": 5})
    return {"id": mid, "label": "지표", "kind": kind, "source": source, "tol": tol, "required": True, **kw}


def _d(*metrics, **kw):
    return {"schema_version": 1, "metrics": list(metrics), "pair_rule": {"mode": "all"}, "verdict_rule": "required_all", **kw}


def codes(problems):
    return sorted(p["code"] for p in problems)


# ---- V-EQ-2 ------------------------------------------------------------------------------------------------


def test_v_eq_2_system_recipe_valid_and_unbound_required():
    d = default_system_recipe()
    assert rc.validate_definition(d, max_metrics=20) == []
    assert rc.unbound_required(d) == ["accel_peak", "cushion_deform", "ie_max", "ke_max"]  # 참고(응력·접촉력)는 미연결이어도 실행 가능
    assert codes(rc.validate_definition(d, max_metrics=20, allow_unbound=False)) == ["METRIC_UNBOUND"] * 4
    n = rc.normalize_definition(d)
    assert n["metrics"][4]["required"] is False and n["metrics"][6]["tol"] == {"corr_min": 0.95}


@pytest.mark.parametrize("metric,expected", [
    (_m(mid="Bad-ID"), ["METRIC_ID_INVALID"]),
    (_m(mid="a" * 33), ["METRIC_ID_INVALID"]),
    (_m(tol={"rel_pct": -1}), ["TOL_INVALID"]),
    (_m(tol={"rel_pct": float("nan")}), ["TOL_INVALID"]),
    (_m(tol={}), ["TOL_INVALID"]),
    (_m(kind="curve_corr", source={"type": "curve", "series": None}, tol={"corr_min": 1.5}), ["TOL_INVALID"]),
    (_m(kind="curve_nrmse", source={"type": "curve", "series": None}, tol={"nrmse_max_pct": -2}), ["TOL_INVALID"]),
    (_m(kind="mesh_volume", source={"type": "perf", "perf": "x"}), ["KIND_SOURCE_MISMATCH"]),
    (_m(kind="curve_corr", source={"type": "h3d", "datatype": "S"}, tol={"corr_min": 0.9}), ["KIND_SOURCE_MISMATCH"]),
    (_m(source={"type": "bogus"}), ["SOURCE_INVALID"]),
    (_m(source={"type": "h3d", "subcase": 0, "datatype": "Stress"}), ["SOURCE_INVALID"]),
    (_m(source={"type": "perf", "perf": ""}), ["SOURCE_INVALID"]),
    (_m(kind="mesh_volume", source={"type": "mesh_volume", "parts": [], "origin": "mesh"}), ["SOURCE_INVALID"]),
    (_m(kind="mesh_volume", source={"type": "mesh_volume", "parts": "cushion", "origin": "cad"}), ["SOURCE_INVALID"]),
    (_m(label=""), ["LABEL_INVALID"]),
    (_m(kind="nope"), ["KIND_SOURCE_MISMATCH"]),
])
def test_v_eq_2_golden_problem_codes(metric, expected):
    assert codes(rc.validate_definition(_d(metric), max_metrics=20)) == expected


def test_v_eq_2_duplicate_range_and_rules():
    assert codes(rc.validate_definition(_d(_m(), _m()), max_metrics=20)) == ["METRIC_DUPLICATE"]
    assert codes(rc.validate_definition(_d(), max_metrics=20)) == ["METRICS_RANGE"]
    assert codes(rc.validate_definition(_d(*[_m(mid=f"m{i}") for i in range(21)]), max_metrics=20)) == ["METRICS_RANGE"]
    assert codes(rc.validate_definition(_d(_m(), pair_rule={"mode": "min_ratio", "ratio": 0}), max_metrics=20)) == ["RULE_INVALID"]
    assert codes(rc.validate_definition(_d(_m(), pair_rule={"mode": "x"}), max_metrics=20)) == ["RULE_INVALID"]
    assert codes(rc.validate_definition(_d(_m(), verdict_rule="any"), max_metrics=20)) == ["RULE_INVALID"]
    assert codes(rc.validate_definition("nope", max_metrics=20)) == ["RULE_INVALID"]
    assert rc.tol_text(_m(tol={"rel_pct": 5, "abs": 0.1})) == "상대 5% 또는 절대 0.1"
    assert rc.tol_text(_m(kind="curve_corr", source={"type": "curve", "series": None})) == "r ≥ 0.95"


# ---- V-EQ-5 ------------------------------------------------------------------------------------------------


def _runs(*specs):
    return [{"name": n, "no": None, "params": p, "ok": True} for n, p in specs]


def test_v_eq_5_by_name_exact_then_casefold():
    a = _runs(("run__00001", None), ("run__00002", None), ("Extra", None))
    b = _runs(("RUN__00002", None), ("run__00001", None), ("other", None))
    r = pr.match("by_name", a, b, rel_tol=1e-6, max_pairs=200)
    assert r.pairs == [("run__00001", "run__00001"), ("run__00002", "RUN__00002")]
    assert r.unmatched_a == ["Extra"] and r.unmatched_b == ["other"]


def test_v_eq_5_by_params_tolerance_integer_and_smallest_no():
    a = _runs(("run__00001", {"t": 1.0, "n": 2}), ("run__00002", {"t": 2.0, "n": 3}), ("run__00003", {"t": 3.0, "n": 4}))
    b = _runs(("x_9", {"t": 1.0 + 5e-7, "n": 2.0}), ("x_3", {"t": 2.0, "n": 3}), ("x_2", {"t": 2.0, "n": 3}), ("x_5", {"t": 3.0 + 1e-3, "n": 4}))
    r = pr.match("by_params", a, b, rel_tol=1e-6, integer_names=["n"], max_pairs=200)
    assert r.pairs == [("run__00001", "x_9"), ("run__00002", "x_2")]  # 같은 점 2개 → 가장 작은 번호(x_2)
    assert r.unmatched_a == ["run__00003"] and set(r.unmatched_b) == {"x_3", "x_5"}
    # 정수는 정확 일치(2 ≠ 3), rel_tol 0이면 절대 1e-12
    bb = _runs(("y", {"t": 1.0, "n": 3}))
    assert pr.match("by_params", a[:1], bb, rel_tol=1e-6, integer_names=["n"], max_pairs=200).problems[0]["code"] == "NO_PAIRS"
    assert pr.pair_by_params(_runs(("a", {"t": 1.0})), _runs(("b", {"t": 1.0 + 1e-9})), rel_tol=0).pairs == []
    assert pr.pair_by_params(_runs(("a", {"t": 1.0})), _runs(("b", {"t": 1.0 + 1e-13})), rel_tol=0).pairs == [("a", "b")]


def test_v_eq_5_param_set_mismatch_manual_and_limits():
    a = _runs(("r1", {"t": 1.0, "n": 2}))
    b = _runs(("r1", {"t": 1.0, "k": 2}))
    r = pr.match("by_params", a, b, rel_tol=1e-6, max_pairs=200)
    assert r.problems[0]["code"] == "PARAM_SET_MISMATCH" and r.problems[0]["only_a"] == ["n"] and r.problems[0]["only_b"] == ["k"]
    m = pr.match("manual", a, b, rel_tol=0, max_pairs=200, manual=[{"a": "r1", "b": "r1"}])
    assert m.pairs == [("r1", "r1")] and not m.problems
    bad = pr.match("manual", a, b, rel_tol=0, max_pairs=200, manual=[{"a": "r1", "b": "zz"}])
    assert bad.problems[0]["code"] == "PAIR_RUN_NOT_FOUND"
    many_a = _runs(*[(f"run__{i:05d}", None) for i in range(1, 6)])
    assert pr.match("by_name", many_a, many_a, rel_tol=0, max_pairs=3).problems[0]["code"] == "PAIRS_RANGE"
    assert pr.match("nope", a, b, rel_tol=0, max_pairs=3).problems[0]["code"] == "PAIRING_INVALID"


# ---- V-EQ-6 ------------------------------------------------------------------------------------------------


def test_v_eq_6_scalar_rel_abs_or_rule_and_zero_tol():
    j = mx.judge_scalar(100.0, 104.0, {"rel_pct": 5.0, "abs": None}, zero_tol=1e-12)
    assert j.status == "PASS" and abs(j.diff - 4.0) < TOL and abs(j.rel_pct - 4.0) < TOL
    assert mx.judge_scalar(100.0, 106.0, {"rel_pct": 5.0}, zero_tol=1e-12).status == "FAIL"
    assert mx.judge_scalar(100.0, 106.0, {"rel_pct": 5.0, "abs": 10.0}, zero_tol=1e-12).status == "PASS"  # 어느 하나 만족
    assert mx.judge_scalar(100.0, 94.0, {"rel_pct": 5.0, "abs": 1.0}, zero_tol=1e-12).status == "FAIL"
    z = mx.judge_scalar(0.0, 1e-3, {"rel_pct": 5.0}, zero_tol=1e-12)
    assert z.status == "NA" and z.reason == "REF_ZERO" and z.rel_pct is None
    assert mx.judge_scalar(0.0, 1e-3, {"rel_pct": 5.0, "abs": 1e-2}, zero_tol=1e-12).status == "PASS"  # abs가 보호
    n = mx.judge_scalar(None, 1.0, {"rel_pct": 5.0}, zero_tol=1e-12)
    assert n.status == "NA" and n.reason == "NO_VALUE"
    assert mx.judge_scalar(-200.0, -210.0, {"rel_pct": 5.0}, zero_tol=1e-12).rel_pct == pytest.approx(-5.0, abs=TOL)


def test_v_eq_6_resample_pearson_nrmse():
    xa, ya = [0, 1, 2, 3, 4], [0, 1, 2, 3, 4]
    xb, yb = [1, 2, 3, 4, 5], [2, 4, 6, 8, 10]  # 공통 [1, 4], 선형 → r = 1, 보간 정확
    rs = mx.resample_common(xa, ya, xb, yb, 7)
    assert rs is not None and abs(rs.t[0] - 1.0) < TOL and abs(rs.t[-1] - 4.0) < TOL
    assert abs(rs.a[3] - 2.5) < TOL and abs(rs.b[3] - 5.0) < TOL
    assert abs(mx.pearson(rs.a, rs.b) - 1.0) < TOL
    assert abs(rs.overlap_ratio - 0.75) < TOL
    # NRMSE = RMS(B−A)/(max A − min A)×100: B = 2A → 차 = A, A ∈ [1,4] 균일 7점
    a = rs.a
    rms = math.sqrt(sum((2 * x - x) ** 2 for x in a) / len(a))
    assert abs(mx.nrmse_pct(rs.a, rs.b) - rms / 3.0 * 100.0) < TOL
    # 공통 구간 없음·평탄 곡선
    assert mx.resample_common([0, 1], [0, 1], [2, 3], [0, 1], 10) is None
    flat = mx.resample_common([0, 1, 2], [1, 1, 1], [0, 1, 2], [0, 1, 2], 10)
    assert mx.pearson(flat.a, flat.b) is None and mx.judge_curve("curve_corr", flat, {"corr_min": 0.9}) == (None, "NA", "FLAT_CURVE")
    assert mx.judge_curve("curve_corr", None, {"corr_min": 0.9}) == (None, "NA", "NO_OVERLAP")
    v, st, _ = mx.judge_curve("curve_corr", rs, {"corr_min": 0.95})
    assert st == "PASS" and abs(v - 1.0) < TOL
    anti = mx.resample_common([0, 1, 2], [0, 1, 2], [0, 1, 2], [2, 1, 0], 5)
    assert abs(mx.pearson(anti.a, anti.b) + 1.0) < TOL and mx.judge_curve("curve_corr", anti, {"corr_min": 0.95})[1] == "FAIL"
    assert mx.judge_curve("curve_nrmse", rs, {"nrmse_max_pct": 5})[1] == "FAIL" and mx.judge_curve("curve_nrmse", rs, {"nrmse_max_pct": 200})[1] == "PASS"


def test_v_eq_6_volume_unit_tet_and_hexa_split():
    assert abs(vol.tet_volume((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)) - 1 / 6) < TOL
    cube = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    assert abs(vol.hexa_volume(cube) - 1.0) < TOL
    box = [(0, 0, 0), (2, 0, 0), (2, 3, 0), (0, 3, 0), (0, 0, 4), (2, 0, 4), (2, 3, 4), (0, 3, 4)]
    assert abs(vol.hexa_volume(box) - 24.0) < TOL
    text = ("/NODE\n1 0 0 0\n2 1 0 0\n3 0 1 0\n4 0 0 1\n5 1 1 0\n6 1 0 1\n7 0 1 1\n8 1 1 1\n9 2 0 0\n"
            "/TETRA4/10\n1 1 2 3 4\n/BRICK/11\n2 1 2 5 3 4 6 8 7\n/TETRA10/12\n3 1 2 3 4 5 6 7 8 9\n9\n/PENTA6/13\n4 1 2 3 4 5 6\n/SHELL/20\n5 1 2 5 3\n")
    m = vol.parse_include(text.splitlines())
    assert abs(vol.part_volume(m, ["10"]).volume - 1 / 6) < TOL and abs(vol.part_volume(m, ["11"]).volume - 1.0) < TOL
    assert abs(vol.part_volume(m, ["12"]).volume - 1 / 6) < TOL  # TETRA10은 앞 4 꼭짓점(두 줄 연속)
    assert abs(vol.part_volume(m, None).volume - (1 / 6 + 1 + 1 / 6)) < TOL and m.skipped_kinds == {"PENTA6"}
    assert vol.part_volume(m, ["99"]).n_elems == 0 and vol.resolve_parts("cushion", None) is None and vol.resolve_parts([1, "2"], None) == ["1", "2"]


def test_v_eq_6_aggregate_and_verdict():
    rows = [{"a_run": "r1", "b_run": "r1", "a": 1.0, "b": 1.1, "diff": 0.1, "rel_pct": 10.0, "corr": None, "status": "PASS"},
            {"a_run": "r2", "b_run": "r2", "a": 2.0, "b": 2.5, "diff": 0.5, "rel_pct": 25.0, "corr": None, "status": "FAIL"},
            {"a_run": "r3", "b_run": "r3", "a": None, "b": None, "diff": None, "rel_pct": None, "corr": None, "status": "NA"}]
    ag = mx.aggregate(rows, {"mode": "all"})
    assert ag["status"] == "FAIL" and (ag["n_pairs"], ag["n_pass"], ag["n_fail"], ag["n_na"]) == (3, 1, 1, 1) and ag["partial"] is True
    assert abs(ag["a_mean"] - 1.5) < TOL and abs(ag["b_mean"] - 1.8) < TOL and abs(ag["max_abs_rel_pct"] - 25.0) < TOL
    assert abs(ag["max_abs_diff"] - 0.5) < TOL and ag["worst_pair"] == "r2 ↔ r2"
    assert mx.aggregate(rows, {"mode": "min_ratio", "ratio": 0.5})["status"] == "PASS"
    assert mx.aggregate(rows, {"mode": "min_ratio", "ratio": 0.6})["status"] == "FAIL"
    assert mx.aggregate([rows[2]], {"mode": "all"})["status"] == "NA"
    crow = [{"a_run": "r1", "b_run": "r1", "corr": 0.97, "status": "PASS"}, {"a_run": "r2", "b_run": "r2", "corr": 0.91, "status": "FAIL"}]
    cag = mx.aggregate(crow, {"mode": "all"})
    assert abs(cag["min_corr"] - 0.91) < TOL and cag["worst_pair"] == "r2 ↔ r2"
    mets = [{"id": "m1", "required": True}, {"id": "m2", "required": True}, {"id": "ref", "required": False}]
    assert mx.overall_verdict(mets, {"m1": {"status": "PASS"}, "m2": {"status": "PASS"}, "ref": {"status": "FAIL"}})["verdict"] == "PASS"
    v = mx.overall_verdict(mets, {"m1": {"status": "PASS"}, "m2": {"status": "FAIL"}, "ref": {"status": "FAIL"}})
    assert v["verdict"] == "FAIL" and v["reference_fail"] == 1 and v["required_fail"] == 1
    assert mx.overall_verdict(mets, {"m1": {"status": "PASS"}, "m2": {"status": "NA"}, "ref": {"status": "PASS"}})["verdict"] == "INCOMPLETE"
    assert mx.overall_verdict(mets, {"m1": {"status": "NA"}, "m2": {"status": "FAIL"}})["verdict"] == "FAIL"
    assert mx.reason_text("REF_ZERO") == "기준값 0" and mx.reason_text(None) is None
