"""V3-S13-3(순수 부분): 내장 최적화 자료 — 같은 설계 평균, 실패 설계, 최선(제약 우선), 개선율, 정지 판정, CSV 왕복."""

from __future__ import annotations

from physicsai_core.stage5_optimize.surrogate import dataset as ds

PROB = ds.Problem(["T", "N"], {"N"}, {"T": (1.0, 3.0), "N": (2.0, 6.0)}, "min",
                  [ds.Constraint("resp:Disp_MAX", None, "<=", 10.0)])


def _pt(it, no, t, n, obj, con, state="SUCCEEDED"):
    return ds.Point(it, f"B-00{it + 1}", no, f"run__{no:05d}", {"T": t, "N": n}, obj, [con], state)


def test_merge_duplicates_and_failed():
    pts = [_pt(0, 1, 2.0, 3, 10.0, 5.0), _pt(0, 2, 2.0 + 1e-12, 3.2, 14.0, 7.0),  # 같은 설계(정수 3 = 3.2 반올림)
           _pt(0, 3, 2.5, 4, None, None, "FAILED"), _pt(0, 4, 2.6, 4, None, 1.0)]  # 값 없음 → 실패 설계
    designs, failed = ds.merge(pts, PROB)
    assert len(designs) == 1 and designs[0].objective == 12.0 and designs[0].constraints == [6.0]
    assert len(designs[0].sources) == 2 and [f["T"] for f in failed] == [2.5, 2.6]


def test_best_prefers_feasible_then_min_violation_and_sense():
    pts = [_pt(0, 1, 1, 2, 5.0, 12.0), _pt(0, 2, 2, 3, 8.0, 9.0), _pt(1, 1, 3, 4, 7.0, 10.0)]
    best, feas = ds.best_point(pts, PROB)
    assert feas and best.objective == 7.0
    best, feas = ds.best_point([_pt(0, 1, 1, 2, 5.0, 12.0), _pt(0, 2, 2, 3, 1.0, 15.0)], PROB)
    assert not feas and best.objective == 5.0  # 위반량 최소
    pmax = ds.Problem(["T", "N"], {"N"}, PROB.bounds, "max")
    assert ds.best_point([_pt(0, 1, 1, 2, 5.0, 0), _pt(0, 2, 2, 3, 8.0, 0)], pmax)[0].objective == 8.0


def test_improvement_and_stop_rules():
    assert ds.improvement_rel((100.0, True), (99.5, True), "min") == 0.005
    assert abs(ds.improvement_rel((100.0, True), (110.0, True), "max") - 0.1) < 1e-12  # 최대화: 커질수록 개선
    assert ds.improvement_rel((100.0, False), (150.0, True), "min") == 1.0
    assert ds.stop_reason(round_no=1, iterations=3, improvement=None, tol_rel=0.01) is None
    assert ds.stop_reason(round_no=3, iterations=3, improvement=0.004, tol_rel=0.01) == "CONVERGED"
    assert ds.stop_reason(round_no=3, iterations=3, improvement=0.2, tol_rel=0.01) is None
    assert ds.stop_reason(round_no=4, iterations=3, improvement=0.2, tol_rel=0.01) == "MAX_ITER"
    assert ds.min_points(2) == 5 and ds.min_points(6) == 8
    assert ds.default_explore_count(2, 200) == 10 and ds.default_explore_count(6, 200) == 24 and ds.default_explore_count(60, 200) == 200


def test_free_variables_skip_fixed_and_data_constant():
    p = ds.Problem(["T", "N", "K"], set(), {"T": (1, 3), "N": (2, 6), "K": (4, 4)}, "min")
    d = [ds.Design({"T": 1.0, "N": 3.0, "K": 4.0}, 1.0, [], []), ds.Design({"T": 2.0, "N": 3.0, "K": 4.0}, 2.0, [], [])]
    assert ds.free_variables(p) == ["T", "N"] and ds.free_variables(p, d) == ["T"]


def test_dataset_csv_golden_and_roundtrip():
    pts = [_pt(0, 1, 2.0, 3, 10.5, 5.0), _pt(1, 2, 2.5, 4, None, None, "FAILED")]
    text = ds.dataset_csv(pts, PROB)
    assert text.splitlines() == ["iter,batch,doe_no,run_key,T,N,objective,resp:Disp_MAX,state",
                                 "0,B-001,1,run__00001,2.0,3.0,10.5,5.0,SUCCEEDED", "1,B-002,2,run__00002,2.5,4.0,,,FAILED"]
    back = ds.read_dataset_csv(text, PROB)
    assert [(p.iter_no, p.doe_no, p.values, p.objective, p.constraints, p.state) for p in back] == \
        [(0, 1, {"T": 2.0, "N": 3.0}, 10.5, [5.0], "SUCCEEDED"), (1, 2, {"T": 2.5, "N": 4.0}, None, [None], "FAILED")]
    full = ds.dataset_csv(pts, PROB, predicted={(0, 1): 11.0}, with_feasible=True, bom=True, crlf=True)
    assert full.startswith("﻿iter,") and "\r\n" in full and ",11.0,true,SUCCEEDED" in full


def test_metric_label():
    assert ds.metric_label("resp:CornerStress_MAX") == "CornerStress_MAX"
    assert ds.metric_label("curve:max", "Node 1 / X") == "커브 최대값(Node 1 / X)"


def test_optimize_builtin_feature_off_without_modules(settings_dict, monkeypatch):
    """V3-S13-6: numpy·scipy 없으면(찾기만, 불러오지 않음) features.optimize_builtin=false + 사유, enabled=false도 사유."""
    from physicsai_core import features
    from physicsai_core.config import load_config_dict
    from physicsai_core.stage5_optimize import surrogate

    s = load_config_dict(dict(settings_dict), environ={}).settings
    monkeypatch.setattr(surrogate, "REQUIRED_MODULES", ("numpy", "no_such_module_xyz"))
    st = features.feature_status(s, False)["optimize_builtin"]
    assert st["enabled"] is False and "python.no_such_module_xyz" in st["missing"]
    d = dict(settings_dict)
    d["surrogate_opt"] = {"enabled": False}
    s2 = load_config_dict(d, environ={}).settings
    assert "surrogate_opt.enabled" in features.feature_status(s2, False)["optimize_builtin"]["missing"]


def test_surrogate_config_validation(settings_dict):
    from physicsai_core.config import load_config_dict

    d = dict(settings_dict)
    d["surrogate_opt"] = {"default_iterations": 30, "max_iterations": 10, "default_surrogate": "svm", "dir_name": "../x"}
    keys = {i.key for i in load_config_dict(d, environ={}).issues}
    assert {"surrogate_opt.default_iterations", "surrogate_opt.default_surrogate", "surrogate_opt.dir_name"} <= keys
