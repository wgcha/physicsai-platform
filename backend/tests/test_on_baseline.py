"""opt-native V-ON-11(단위): 범주 baseline 인코딩 = 학습 입력 인코딩(같은 함수 출력 비교), N/A 마스크·정리, 범위 분할 NO_COVER 판정 =
`assign_baseline`, 다중 baseline 표 조합(baseline 열·배정 메타), GA·EGO 수준별 탐색(범주 유전자·수준별 DE)."""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from physicsai_core.geometry import baselines as bl  # noqa: E402
from physicsai_core.stage4_predict.batch_multi import build_multi_table, restrict  # noqa: E402
from physicsai_core.stage5_optimize.surrogate import encoding, evo_infill, infill, mo_infill  # noqa: E402
from physicsai_core.stage5_optimize.surrogate.dataset import (  # noqa: E402
    Point, Problem, canonical_values, covered, cover_spec, merge, run_values,
)

PM_TOPO = {"usage": "topology", "status": "confirmed",
           "baselines": [{"id": "base", "rel": "."}, {"id": "B2", "rel": "baselines/B2"}, {"id": "B3", "rel": "baselines/B3"}]}
ROWS = [
    {"name": "A", "nominal": 5.0, "min": 0.0, "max": 10.0, "unit": "mm",
     "baselines": {"base": {"param": "A_1", "nominal": 5, "min": 0, "max": 10}, "B2": {"param": "A_2", "nominal": 5, "min": 0, "max": 10},
                   "B3": {"param": "A_3", "nominal": 5, "min": 0, "max": 10}}},
    {"name": "D", "nominal": 2.0, "min": 1.0, "max": 3.0, "unit": "mm",
     "baselines": {"base": None, "B2": {"param": "D_2", "nominal": 2, "min": 1, "max": 3}, "B3": None}},
]


def _settings(levels=("base", "B2", "B3")):
    act = {"D": [lv == "B2" for lv in levels]}
    return {"names": ["A", "D", "baseline"], "integer": ["baseline"], "bounds": {"A": [0, 10], "D": [1, 3], "baseline": [0, len(levels) - 1]},
            "objective": {"metric": "f", "series": None, "sense": "min"}, "constraints": [], "levels": {"baseline": list(levels)},
            "multi_baseline": {"usage": "topology", "baselines": ["base", "B2", "B3"], "active": act, "na": ["D"]}}


def test_v_on_11_encoding_equals_training_input_rule():
    st = _settings()
    spec = encoding.make_spec(st)
    assert spec == Problem.from_settings(st).cat_spec
    free = ["A", "D", "baseline"]
    assert encoding.columns(spec, free) == bl.training_columns(PM_TOPO, ROWS) == ["A", "D", "D__na", "baseline__base", "baseline__B2",
                                                                                  "baseline__B3"]
    rows = [{"A": 3.0, "D": 2.5, "baseline": 0.0}, {"A": 7.0, "D": 1.5, "baseline": 1.0}, {"A": 1.0, "D": 2.0, "baseline": 2.0}]
    for r in rows:
        bid = spec["levels"][int(r["baseline"])]
        assert encoding.training_view(r, spec, ["A", "D"]) == bl.training_values(PM_TOPO, ROWS, bid, {"A": r["A"], "D": r["D"]})
    X = np.array([[r["A"], r["D"], r["baseline"]] for r in rows])
    lo, hi = np.array([0.0, 1.0, 0.0]), np.array([10.0, 3.0, 2.0])
    E = encoding.transform(X, free, lo, hi, spec)
    for r, e in zip(rows, E):  # 학습 값과 같은 열: 공통 변수는 범위 정규화(N/A = 0), 지시·원-핫은 그대로
        tv = bl.training_values(PM_TOPO, ROWS, spec["levels"][int(r["baseline"])], {"A": r["A"], "D": r["D"]})
        assert e[0] == pytest.approx(tv["A"] / 10.0)
        assert e[1] == pytest.approx(0.0 if tv["D__na"] else (tv["D"] - 1.0) / 2.0)
        assert list(e[2:]) == [tv["D__na"], tv["baseline__base"], tv["baseline__B2"], tv["baseline__B3"]]
    eff = encoding.effective(X, free, spec)
    assert np.isnan(eff[0, 1]) and eff[1, 1] == 1.5 and np.isnan(eff[2, 1])
    assert canonical_values({"A": 3.0, "D": 2.5, "baseline": 0.0}, spec) == {"A": 3.0, "D": 0.0, "baseline": 0.0}


def test_v_on_11_levels_subset_and_run_values():
    st = _settings(levels=("base", "B2"))
    spec = Problem.from_settings(st).cat_spec
    assert spec["levels"] == ["base", "B2"] and spec["active"] == {"D": [False, True]}
    meta = {"multi_baseline": {"assign": {"1": "B2", "2": "B3", "3": None}}}
    assert run_values({"A": 2.0, "D": 1.2}, meta, 1, spec) == {"A": 2.0, "D": 1.2, "baseline": 1.0}
    assert "baseline" not in run_values({"A": 2.0, "D": 0.0}, meta, 2, spec)  # 선택 수준 밖 → 실패 설계
    assert "baseline" not in run_values({"A": 2.0, "D": 0.0}, meta, 3, spec)
    assert run_values({"A": 2.0}, None, 1, None) == {"A": 2.0}


def test_v_on_11_range_cover_equals_assign_baseline():
    pm = {"usage": "range", "baselines": [{"id": "base", "rel": "."}, {"id": "B2", "rel": "b"}],
          "range_split": {"param": "A", "intervals": [{"baseline": "base", "nominal": 3}, {"baseline": "B2", "nominal": 8}]}}
    rows = [{"name": "A", "min": 0, "max": 10, "baselines": {"base": {"nominal": 3, "min": 0, "max": 5, "feasible": {"min": 0, "max": 4.5}},
                                                            "B2": {"nominal": 8, "min": 6, "max": 10, "feasible": {"min": 6.5, "max": 10}}}},
            {"name": "R", "min": 1, "max": 2, "baselines": {"base": {"nominal": 1.5, "min": 1, "max": 2},
                                                           "B2": {"nominal": 1.5, "min": 1.4, "max": 1.6}}}]
    st = {"multi_baseline": {"usage": "range", "baselines": ["base", "B2"],
                             "cover": {"A": {"base": [0, 4.5], "B2": [6.5, 10]}, "R": {"base": [1, 2], "B2": [1.4, 1.6]}}}}
    spec = cover_spec(st)
    rng = np.random.default_rng(2)
    for _ in range(200):
        v = {"A": float(rng.uniform(0, 10)), "R": float(rng.uniform(1, 2))}
        assert covered(v, spec) == (bl.assign_baseline(pm, rows, v) is not None), v
    mx = build_multi_table([{"A": 3.0, "R": 1.5}, {"A": 5.5, "R": 1.5}, {"A": 8.0, "R": 1.5}], {"parameters": rows}, pm)
    assert mx.source_meta["multi_baseline"]["assign"] == {"1": "base", "2": None, "3": "B2"}
    assert [n["code"] for n in mx.notes] == ["BASELINE_NO_COVER"] and mx.source_kind == "TABLE"


def test_v_on_11_multi_table_topology_baseline_column_and_restrict():
    mx = build_multi_table([{"A": 3.0, "D": 2.5, "baseline": "base"}, {"A": 4.0, "D": 2.0, "baseline": "B2"}], {"parameters": ROWS}, PM_TOPO)
    assert mx.source_meta["multi_baseline"] == {"usage": "topology", "baselines": ["base", "B2", "B3"],
                                                "stratum": {"1": "base", "2": "B2"}, "assign": {"1": "base", "2": "B2"}}
    assert mx.rows[0].values == {"A": 3.0, "D": 0.0} and mx.rows[1].values == {"A": 4.0, "D": 2.0}  # N/A = 0
    bad = build_multi_table([{"A": 1.0, "baseline": "ZZ"}], {"parameters": ROWS}, PM_TOPO)
    assert bad.problems and bad.problems[0]["code"] == "BASELINE_INVALID"
    pm2, rows2 = restrict(PM_TOPO, ROWS, ["base", "B2"], {"A": [2.0, 4.0]})
    assert bl.baseline_ids(pm2) == ["base", "B2"] and rows2[0]["baselines"]["B2"]["min"] == 2.0 and ROWS[0]["baselines"]["B2"]["min"] == 0


def _cat_designs(seed=1, n=18):
    st = _settings()
    problem = Problem.from_settings(st)
    rng = np.random.default_rng(seed)
    pts = []
    for i in range(n):
        lv = i % 3
        v = {"A": float(rng.uniform(0, 10)), "D": float(rng.uniform(1, 3)) if lv == 1 else 0.0, "baseline": float(lv)}
        f = (v["A"] - 4) ** 2 / 10 + [1.0, 0.0, 0.6][lv] + (v["D"] - 2) ** 2 * (lv == 1)
        pts.append(Point(0, "B", i + 1, f"r{i}", v, f, [], "SUCCEEDED"))
    designs, failed = merge(pts, problem)
    return problem, designs, failed


def test_v_on_11_ga_categorical_genes_and_na_mask():
    problem, designs, failed = _cat_designs()
    fit = infill.fit_all(designs, problem, kind="gp", restarts=2, seed=1)
    assert fit.encoding is not None and fit.normalize(np.array([[4.0, 2.0, 1.0]])).shape == (1, 6)
    sp = evo_infill.Space.basic(fit, problem)
    assert [g.kind for g in sp.genes] == ["real", "real", "cat"] and sp.genes[2].levels == 3
    ep = evo_infill.propose_ga(sp, designs, failed, k=3, seed=1, round_no=1,
                               options={"pop_size": 40, "generations": 40, "crossover_prob": 0.9, "mutation_prob": None, "eta_c": 15.0,
                                        "eta_m": 20.0}, stall=30, archive_max=5000)
    best = ep.candidates[0]["values"]
    assert best["baseline"] == 1.0 and abs(best["A"] - 4) < 1.0  # 수준 B2(가산 0)가 최적
    for c in ep.candidates:
        v = c["values"]
        assert v["baseline"] in (0.0, 1.0, 2.0) and (v["baseline"] == 1.0 or v["D"] == 0.0)  # N/A = 0
    # 저장·복원 후에도 같은 인코딩
    fit2 = infill.FitResult.from_json(fit.to_json())
    X = np.array([[3.0, 2.5, 0.0], [5.0, 1.5, 1.0]])
    assert np.array_equal(fit2.normalize(X), fit.normalize(X))


def test_v_on_11_ego_per_level_de():
    problem, designs, failed = _cat_designs(seed=3)
    fit = infill.fit_all(designs, problem, kind="gp", restarts=2, seed=1)
    from physicsai_core.stage5_optimize.surrogate import infill_propose  # propose·_de 위치(S19 R-B 분할)

    seen: list[int] = []
    orig = infill_propose._de

    def spy(func, bounds, integrality, *, seed, **kw):
        seen.append(seed)
        assert len(bounds) == 2  # 범주를 뺀 차원
        return orig(func, bounds, integrality, seed=seed, **kw)

    infill_propose._de = spy
    try:
        cands, opt = infill.propose(fit, problem, designs, failed, k=2, seed=1, round_no=1, de_maxiter=20, de_popsize=8)
    finally:
        infill_propose._de = orig
    assert seen[:3] == [100000 + 1000 + 800, 100000 + 1000 + 801, 100000 + 1000 + 802]  # 수준별 시드(§6.2)
    assert opt is not None and opt.values["baseline"] == 1.0
    assert all(c.values["baseline"] in (0.0, 1.0, 2.0) for c in cands)
    # 다목적 예측 전선도 수준별로 돌려 합친다
    st = _settings()
    st["objectives"] = [{"metric": "f", "series": None, "sense": "min"}, {"metric": "g", "series": None, "sense": "min"}]
    problem2 = Problem.from_settings(st)
    pts = [Point(0, "B", i + 1, f"r{i}", d.values, d.objective, [], "SUCCEEDED", objectives=[d.objective, 10 - d.values["A"]])
           for i, d in enumerate(designs)]
    d2, f2 = merge(pts, problem2)
    fit_m = mo_infill.fit_mo(d2, problem2, kind="gp", restarts=2, seed=1)
    frame = {"ideal": [0.0, 0.0], "nadir": [5.0, 10.0], "ref_offset": 0.1}
    prop = mo_infill.propose_mo(fit_m, problem2, d2, f2, k=2, seed=1, round_no=1,
                                cfg=mo_infill.MoCfg(h2=2, de_maxiter=10, de_popsize=6, gp_restarts=2), hv_frame=frame)
    assert {p["values"]["baseline"] for p in prop.predicted_front} <= {0.0, 1.0, 2.0} and prop.candidates
