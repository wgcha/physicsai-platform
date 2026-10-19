"""S17 다목적 수학(phase3 §22.5, numpy·scipy): V3-S17-8 세부(격자·Chebyshev·c₁ HVI/거리·ParEGO 가중치 배정·range PoF·정수·고정·
sense max 혼합·중복/실패 재제안 없음·RBF·시드 결정성·GP 실패 폴백). V3-S17-7 루프는 test_s17_mo_loop.py."""

from __future__ import annotations

import math

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from physicsai_core.stage5_optimize.surrogate import dataset as ds  # noqa: E402
from physicsai_core.stage5_optimize.surrogate import gp as gp_mod  # noqa: E402
from physicsai_core.stage5_optimize.surrogate import mo_infill as mo  # noqa: E402
from physicsai_core.stage5_optimize.surrogate.infill import cons_pof, cons_violation  # noqa: E402

FAST = mo.MoCfg(h2=10, h3=6, de_maxiter=15, de_popsize=8, rho=0.05, ref_offset=0.1, gp_restarts=2)


def _problem(names=("a", "b"), *, integer=(), bounds=None, senses=("min", "min"), constraints=()):
    b = bounds or {n: [0.0, 1.0] for n in names}
    return ds.Problem.from_settings({
        "names": list(names), "integer": list(integer), "bounds": b,
        "objectives": [{"metric": f"f{i}", "series": None, "sense": s} for i, s in enumerate(senses)],
        "objective": {"metric": "f0", "series": None, "sense": senses[0]}, "constraints": list(constraints)})


def _designs(problem, X, func, cons=None):
    pts = []
    for i, x in enumerate(X, 1):
        vals = {n: float(v) for n, v in zip(problem.names, x)}
        f = func(np.asarray(x, dtype=float))
        c = cons(np.asarray(x, dtype=float)) if cons else []
        pts.append(ds.Point(0, "B-001", i, f"run_{i}", vals, f[0], c, "SUCCEEDED", objectives=list(f)))
    return ds.merge(pts, problem)


def zdt1(x):
    g = 1 + 9 * float(np.mean(x[1:]))
    return [float(x[0]), g * (1 - math.sqrt(float(x[0]) / g))]


def _lhs(n, d, seed=3):
    return gp_mod.lhs_unit(np.random.default_rng(seed), n, d)


def _frame(problem, designs):
    return ds.make_hv_frame(designs, problem, 0.1)


# ---- 격자·스칼라화 ----------------------------------------------------------------------------------


def test_v3_s17_8_lattice_sizes_and_order():
    w2 = mo.lattice(2, 10)
    assert len(w2) == 11 and w2[0] == (0.0, 1.0) and w2[-1] == (1.0, 0.0)
    assert all(abs(a - j / 10) < 1e-12 and abs(b - (1 - j / 10)) < 1e-12 for j, (a, b) in enumerate(w2))
    w3 = mo.lattice(3, 6)
    assert len(w3) == 28 and w3 == sorted(w3) and all(abs(sum(w) - 1) < 1e-12 for w in w3)
    assert w3[0] == (0.0, 0.0, 1.0) and w3[-1] == (1.0, 0.0, 0.0)


def test_v3_s17_8_chebyshev_golden():
    F = np.array([[0.2, 0.6], [0.5, 0.5], [1.0, 0.0]])
    got = mo.chebyshev(F, (0.5, 0.5), 0.05)
    assert np.allclose(got, [0.3 + 0.05 * 0.4, 0.25 + 0.05 * 0.5, 0.5 + 0.05 * 0.5], atol=1e-12)
    assert np.allclose(mo.chebyshev(np.array([[0.2, 0.6, 0.1]]), (0.2, 0.3, 0.5), 0.0), [0.18], atol=1e-12)


def test_v3_s17_8_c1_hvi_then_distance_rule():
    front = [[0.2, 0.8], [0.8, 0.2]]
    pred = [[0.9, 0.9], [0.5, 0.5], [0.1, 0.95]]          # (0.5,0.5) HVI 최대, (0.9,0.9)는 지배됨 → 0
    order = mo.c1_order(pred, front, [1.1, 1.1])
    assert order[0][0] == 1 and order[0][1] > 0 and dict(order)[0] == 0.0
    # 모든 HVI 0 → F까지 최소 거리 큰 순
    dominated = [[0.3, 0.9], [0.95, 0.95], [0.85, 0.3]]
    order = mo.c1_order(dominated, front, [1.1, 1.1])
    assert all(h <= 1e-12 for _i, h in order)
    d = [min(math.dist(p, q) for q in front) for p in dominated]
    assert [i for i, _h in order] == sorted(range(3), key=lambda i: -d[i])


def test_v3_s17_8_parego_weight_assignment():
    used: list[int] = []
    seen: list[list[int]] = []
    for r in range(1, 4):
        chosen, used = mo.assign_weights(11, 3, seed=1, round_no=r, used=used)
        assert len(chosen) == 3 and len(set(chosen)) == 3
        seen.append(chosen)
    flat = [j for c in seen for j in c]
    assert len(set(flat)) == 9                            # 반복 간 겹치지 않음
    perm = list(np.random.default_rng(1 * 1000 + 1).permutation(11))
    assert seen[0] == [int(x) for x in perm[:3]]
    chosen, used2 = mo.assign_weights(11, 3, seed=1, round_no=4, used=used)  # 남은 2개 → 소진 후 재시작
    assert set(chosen[:2]) == set(range(11)) - set(flat) and len(set(chosen)) == 3
    assert len(used2) == 1 and used2[0] == chosen[2]


def test_v3_s17_8_range_pof_and_violation():
    c = ds.Constraint("m", None, "range", lo=30.0, hi=60.0)
    assert c.violation(20.0) == 10.0 and c.violation(45.0) == 0.0 and c.violation(70.0) == 10.0
    assert ds.is_feasible([45.0], [c]) and not ds.is_feasible([29.0], [c])
    m, s = np.array([45.0, 30.0, 80.0]), np.array([5.0, 1e-9, 5.0])
    p = cons_pof(c, m, s)
    from scipy.stats import norm
    assert abs(p[0] - (norm.cdf(3) - norm.cdf(-3))) < 1e-12 and abs(p[1] - 0.5) < 1e-9 and p[2] < 1e-4
    assert np.allclose(cons_violation(c, np.array([20.0, 45.0, 70.0])), [10.0, 0.0, 10.0])
    le = ds.Constraint("m", None, "<=", 12.0)
    assert abs(float(cons_pof(le, np.array([12.0]), np.array([2.0]))[0]) - 0.5) < 1e-12


# ---- 적합·후보 --------------------------------------------------------------------------------------


def _run(problem, designs, failed=(), *, k=4, seed=1, r=1, kind="gp", used=()):
    fit = mo.fit_mo(designs, problem, kind=kind, restarts=2, seed=seed * 1000 + r)
    return fit, mo.propose_mo(fit, problem, designs, list(failed), k=k, seed=seed, round_no=r, cfg=FAST,
                              hv_frame=_frame(problem, designs), used_weights=used)


def test_v3_s17_8_candidates_roles_dedup_and_determinism():
    pr = _problem(("a", "b", "c"))
    designs, _ = _designs(pr, _lhs(12, 3), zdt1)
    failed = [{"a": 0.5, "b": 0.5, "c": 0.5}]
    fit, p1 = _run(pr, designs, failed)
    roles = [c.role for c in p1.candidates]
    assert roles[0] == "hvi" and set(roles[1:]) <= {"parego"} and len(roles) == 4
    assert all(c.weight is not None for c in p1.candidates[1:]) and p1.candidates[0].weight is None
    assert len(p1.used_weights) == 3
    for c in p1.candidates:                                   # 기존·실패·서로 같은 설계 없음
        assert not any(ds.same_design(c.values, d.values, pr) for d in designs)
        assert not ds.same_design(c.values, failed[0], pr)
        assert len(c.mean) == 2 and len(c.std) == 2
    vals = [tuple(round(c.values[n], 12) for n in pr.names) for c in p1.candidates]
    assert len(set(vals)) == 4
    assert 1 <= len(p1.predicted_front) <= 11 and all(f["pof"] == 1.0 for f in p1.predicted_front)
    assert fit.quality["per_objective"][1]["metric"] == "f1" and fit.quality["kind"] == "gp"
    _f2, p2 = _run(pr, designs, failed)                       # 같은 시드 → 같은 후보
    assert [c.values for c in p2.candidates] == [c.values for c in p1.candidates]
    _f3, p3 = _run(pr, designs, failed, seed=2)               # 다른 시드 → 다른 후보
    assert [c.values for c in p3.candidates] != [c.values for c in p1.candidates]
    d = p1.candidates[1].as_dict(2)
    assert d["doe_no"] == 2 and d["predicted"] == d["predicted_objectives"][0] and d["role"] == "parego"


def test_v3_s17_8_integer_fixed_and_sense_max():
    pr = _problem(("a", "n", "z"), integer=("n",), bounds={"a": [0.0, 1.0], "n": [1.0, 6.0], "z": [0.3, 0.3]},
                  senses=("min", "max"))

    def f(x):
        return [float((x[0] - 0.3) ** 2 + 0.1 * x[1]), float(-((x[0] - 0.8) ** 2) + 0.05 * x[1])]

    X = _lhs(10, 2)
    X = np.column_stack([X[:, 0], 1 + np.floor(X[:, 1] * 6), np.full(10, 0.3)])
    designs, _ = _designs(pr, X, f)
    fit, p = _run(pr, designs, k=3)
    assert fit.signs == [1.0, -1.0] and "z" not in fit.free
    for c in p.candidates:
        assert c.values["n"] == round(c.values["n"]) and 1 <= c.values["n"] <= 6 and c.values["z"] == 0.3
    # 원 부호 보고: max 목적의 예측은 실제 함수 값과 같은 부호 규모
    c = p.candidates[0]
    x = np.array([c.values["a"], c.values["n"], 0.3])
    assert abs(c.mean[1] - f(x)[1]) < 1.0


def test_v3_s17_8_range_constraint_candidates_feasible():
    pr = _problem(("a", "b"), constraints=[{"metric": "g", "series": None, "op": "range", "lo": 0.3, "hi": 0.6}])
    designs, _ = _designs(pr, _lhs(14, 2), lambda x: [float(x[0]), float(1 - x[0] + (x[1] - 0.5) ** 2)],
                          cons=lambda x: [float(x[1])])
    _fit, p = _run(pr, designs, k=3)
    assert p.candidates and all(0.2 <= c.values["b"] <= 0.7 for c in p.candidates)
    assert all(0.3 - 0.05 <= f["values"]["b"] <= 0.6 + 0.05 for f in p.predicted_front)


def test_v3_s17_8_rbf_path():
    pr = _problem(("a", "b", "c"))
    designs, _ = _designs(pr, _lhs(12, 3), zdt1)
    fit, p = _run(pr, designs, kind="rbf", k=3)
    assert fit.kind == "rbf" and fit.quality["per_objective"][0]["kind"] == "rbf"
    assert [c.role for c in p.candidates][0] == "hvi" and {c.role for c in p.candidates[1:]} <= {"rbf"}
    assert len(p.candidates) == 3


def test_v3_s17_8_gp_failure_falls_back_for_that_objective(monkeypatch):
    pr = _problem(("a", "b", "c"))
    designs, _ = _designs(pr, _lhs(12, 3), zdt1)
    orig = mo.fit_gp
    calls = {"n": 0}

    def flaky(X, y, **kw):
        calls["n"] += 1
        if calls["n"] == 2:                                   # 목적 2만 실패
            raise gp_mod.GPFitError("시험")
        return orig(X, y, **kw)

    monkeypatch.setattr(mo, "fit_gp", flaky)
    fit = mo.fit_mo(designs, pr, kind="gp", restarts=2, seed=5)
    assert [o.model.kind for o in fit.objectives] == ["gp", "rbf"]
    assert [w["code"] for w in fit.warnings] == ["GP_FALLBACK_RBF"] and "목적 2(f1)" in fit.warnings[0]["message"]
    assert fit.quality["kind"] == "mixed"
    rt = mo.FitResult.from_json(fit.to_json())
    assert len(rt.objectives) == 2 and rt.signs == [1.0, 1.0]


def test_v3_s17_8_three_objectives_hvi_share_and_prox():
    """3목적 조정 키(mo_hvi_share_m3·mo_front_prox_m3): k=4 → HVI 2개(서로 다른 점) + ParEGO 2개, 0이면 계약 원안(HVI 1개)."""
    import dataclasses

    def f3(x):
        return [float(x[0]), float(x[1]), float(2 - x[0] - x[1] + (x[2] - 0.5) ** 2)]

    pr = _problem(("a", "b", "c"), senses=("min", "min", "min"))
    designs, _ = _designs(pr, _lhs(14, 3), f3)
    for share, prox, roles in ((0.5, 6.0, ["hvi", "hvi", "parego", "parego"]), (0.0, 0.0, ["hvi", "parego", "parego", "parego"])):
        cfg = dataclasses.replace(FAST, hvi_share_m3=share, front_prox_m3=prox)
        fit = mo.fit_mo(designs, pr, kind="gp", restarts=2, seed=1001)
        p = mo.propose_mo(fit, pr, designs, [], k=4, seed=1, round_no=1, cfg=cfg, hv_frame=_frame(pr, designs))
        assert [c.role for c in p.candidates] == roles
        assert len({tuple(round(c.values[n], 9) for n in pr.names) for c in p.candidates}) == 4
