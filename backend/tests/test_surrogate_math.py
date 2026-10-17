"""V3-S13-2: 내장 최적화 대리모델 수학(phase3 §18.5) — 해석 함수·LOO 닫힌 식·EI·PoF·정수·고정·시드·중복·GP 실패 폴백."""

from __future__ import annotations

import math

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from physicsai_core.stage5_optimize.surrogate import dataset as ds  # noqa: E402
from physicsai_core.stage5_optimize.surrogate import gp, infill, rbf  # noqa: E402


def _branin(a: float, b: float) -> float:
    return (b - 5.1 / (4 * math.pi ** 2) * a * a + 5 / math.pi * a - 6) ** 2 + 10 * (1 - 1 / (8 * math.pi)) * math.cos(a) + 10


def _designs(fn, bounds: dict[str, tuple[float, float]], n: int, seed: int, cons=None) -> list[ds.Design]:
    names = list(bounds)
    U = gp.lhs_unit(np.random.default_rng(seed), n, len(names))
    out = []
    for u in U:
        v = {k: bounds[k][0] + float(x) * (bounds[k][1] - bounds[k][0]) for k, x in zip(names, u)}
        out.append(ds.Design(v, float(fn(**v)), [float(c(**v)) for c in (cons or [])], []))
    return out


def _problem(bounds, *, sense="min", integer=(), constraints=()) -> ds.Problem:
    return ds.Problem(list(bounds), set(integer), {k: (float(a), float(b)) for k, (a, b) in bounds.items()}, sense,
                      list(constraints))


def _q2_holdout(fit: infill.FitResult, fn, bounds, n=200) -> float:
    names = list(bounds)
    U = gp.lhs_unit(np.random.default_rng(99), n, len(names))
    X = np.array([[bounds[k][0] + u[i] * (bounds[k][1] - bounds[k][0]) for i, k in enumerate(names)] for u in U])
    y = np.array([fn(**dict(zip(names, x))) for x in X])
    pred, _ = fit.objective.raw(fit.normalize(X[:, [names.index(f) for f in fit.free]]))
    pred = fit.sign * pred
    return 1 - float(np.sum((y - pred) ** 2) / np.sum((y - y.mean()) ** 2))


def test_gp_quadratic_and_branin_q2_above_0_9():
    b2 = {"a": (0.0, 1.0), "b": (0.0, 1.0)}
    quad = lambda a, b: (a - 0.3) ** 2 + 2 * (b - 0.6) ** 2  # noqa: E731
    fit = infill.fit_all(_designs(quad, b2, 15, 1), _problem(b2), kind="gp", restarts=4, seed=1)
    assert fit.kind == "gp" and fit.quality["q2"] > 0.9 and _q2_holdout(fit, quad, b2) > 0.9
    bb = {"a": (-5.0, 10.0), "b": (0.0, 15.0)}
    fit = infill.fit_all(_designs(_branin, bb, 40, 3), _problem(bb), kind="gp", restarts=8, seed=1)
    assert fit.quality["q2"] > 0.9 and _q2_holdout(fit, _branin, bb) > 0.9
    assert fit.quality["n_train"] == 40 and fit.quality["d_free"] == 2 and fit.quality["loo_rmse"] > 0


@pytest.mark.parametrize("kind", ["gp", "rbf"])
def test_closed_form_loo_equals_refit(kind):
    rng = np.random.default_rng(0)
    X = gp.lhs_unit(rng, 15, 2)
    y = np.sin(3 * X[:, 0]) + X[:, 1] ** 2
    y = (y - y.mean()) / y.std()
    m = gp.fit_gp(X, y, restarts=3, seed=2) if kind == "gp" else rbf.fit_rbf(X, y)
    loo, _ = m.loo()
    for i in range(15):
        keep = np.arange(15) != i
        mi = gp.GPModel(X[keep], y[keep], m.log_ls, m.log_nugget) if kind == "gp" else rbf.RBFModel(X[keep], y[keep])
        assert abs(mi.predict(X[i:i + 1])[0][0] - loo[i]) < 1e-6


def test_ei_golden_and_pof():
    mean, std = np.array([0.0, 1.0, -1.0]), np.array([1.0, 0.5, 1e-15])
    ei = infill._ei(mean, std, 0.0)
    assert ei[0] == pytest.approx(1 / math.sqrt(2 * math.pi), abs=1e-12)  # z=0 → s·φ(0)
    assert ei[1] == pytest.approx(-1.0 * 0.022750131948179195 + 0.5 * 0.05399096651318806, abs=1e-9)
    assert ei[2] == pytest.approx(1.0, abs=1e-9)  # 확실한 개선
    # 제약 PoF: g(x) = a ≤ 0.4 → 후보는 a ≤ 0.4 쪽, 예측 제약도 만족
    bnd = {"a": (0.0, 1.0), "b": (0.0, 1.0)}
    obj = lambda a, b: -(a + b)  # noqa: E731
    con = lambda a, b: a  # noqa: E731
    prob = _problem(bnd, constraints=[ds.Constraint("resp:A_MAX", None, "<=", 0.4)])
    des = _designs(obj, bnd, 20, 5, [con])
    fit = infill.fit_all(des, prob, kind="gp", restarts=4, seed=1)
    cands, _ = infill.propose(fit, prob, des, [], k=3, seed=1, round_no=1, de_maxiter=60, de_popsize=10)
    assert len(cands) == 3
    assert cands[0].values["a"] <= 0.45 and cands[0].constraints_pred[0] <= 0.4 + 1e-3


def test_integer_fixed_sense_max_and_distinct_candidates():
    bnd = {"x": (0.0, 1.0), "n": (2.0, 7.0), "t": (3.0, 3.0)}
    fn = lambda x, n, t: -((x - 0.7) ** 2) - 0.1 * (n - 5) ** 2 + t  # noqa: E731
    prob = _problem(bnd, sense="max", integer=["n"])
    names = ["x", "n"]
    U = gp.lhs_unit(np.random.default_rng(4), 14, 2)
    des = []
    for u in U:
        v = {"x": float(u[0]), "n": float(round(2 + u[1] * 5)), "t": 3.0}
        des.append(ds.Design(v, fn(**v), [], []))
    fit = infill.fit_all(des, prob, kind="gp", restarts=4, seed=1)
    assert fit.free == names and fit.fill == {"t": 3.0} and fit.sign == -1.0
    cands, opt = infill.propose(fit, prob, des, [], k=4, seed=1, round_no=1, de_maxiter=80, de_popsize=10)
    assert len(cands) == 4
    for c in cands:
        assert c.values["n"] == round(c.values["n"]) and 2 <= c.values["n"] <= 7 and c.values["t"] == 3.0
    assert opt is not None and abs(opt.values["x"] - 0.7) < 0.15 and opt.values["n"] in (4.0, 5.0, 6.0)
    assert opt.predicted == pytest.approx(fn(**opt.values), abs=0.2)  # 원 부호(최대화) 보고
    keys = {(round(c.values["x"], 9), c.values["n"]) for c in cands}
    assert len(keys) == 4  # kriging believer 후보 서로 다름


def test_no_reproposal_of_existing_or_failed_and_same_seed_same_candidates():
    bnd = {"n": (1.0, 3.0), "m": (1.0, 2.0)}
    prob = _problem(bnd, integer=["n", "m"])
    des = [ds.Design({"n": float(n), "m": float(m)}, float(n + m), [], []) for n in (1, 2, 3) for m in (1, 2) if (n, m) != (1, 1)]
    failed = [{"n": 1.0, "m": 1.0}]
    fit = infill.fit_all(des, prob, kind="gp", restarts=2, seed=1)
    cands, _ = infill.propose(fit, prob, des, failed, k=3, seed=1, round_no=1, de_maxiter=30, de_popsize=8)
    assert cands == []  # 정수 격자 6점이 모두 기존(성공 5 + 실패 1) → 새 후보 없음
    bnd = {"a": (0.0, 1.0), "b": (0.0, 1.0)}
    quad = lambda a, b: (a - 0.3) ** 2 + (b - 0.6) ** 2  # noqa: E731
    des = _designs(quad, bnd, 10, 7)
    runs = []
    for _ in range(2):
        fit = infill.fit_all(des, _problem(bnd), kind="gp", restarts=3, seed=11)
        c, _ = infill.propose(fit, _problem(bnd), des, [], k=3, seed=11, round_no=2, de_maxiter=40, de_popsize=8)
        runs.append([tuple(sorted(x.values.items())) for x in c])
    assert runs[0] == runs[1]


def test_rbf_candidates_respect_distance_rule():
    bnd = {"a": (0.0, 1.0), "b": (0.0, 1.0)}
    quad = lambda a, b: (a - 0.3) ** 2 + (b - 0.6) ** 2  # noqa: E731
    des = _designs(quad, bnd, 12, 3)
    fit = infill.fit_all(des, _problem(bnd), kind="rbf", restarts=1, seed=1)
    assert fit.kind == "rbf" and fit.quality["q2"] is not None
    cands, _ = infill.propose(fit, _problem(bnd), des, [], k=3, seed=1, round_no=1, de_maxiter=60, de_popsize=10)
    assert len(cands) == 3 and all(c.ei is None for c in cands)
    pts = [np.array([c.values["a"], c.values["b"]]) for c in cands[1:]]
    ref = [np.array([d.values["a"], d.values["b"]]) for d in des] + [np.array([cands[0].values["a"], cands[0].values["b"]])]
    for p in pts:
        assert min(np.linalg.norm(p - r) for r in ref) / math.sqrt(2) >= 0.0125 - 1e-9


def test_gp_failure_falls_back_to_rbf(monkeypatch):
    def boom(*_a, **_k):
        raise gp.GPFitError("Cholesky 실패")

    monkeypatch.setattr(infill, "fit_gp", boom)
    bnd = {"a": (0.0, 1.0), "b": (0.0, 1.0)}
    fit = infill.fit_all(_designs(lambda a, b: a + b, bnd, 8, 1), _problem(bnd), kind="gp", restarts=2, seed=1)
    assert fit.kind == "rbf" and [w["code"] for w in fit.warnings] == ["GP_FALLBACK_RBF"]


def test_fit_json_roundtrip_predicts_same():
    bnd = {"a": (0.0, 1.0), "b": (0.0, 1.0)}
    des = _designs(lambda a, b: a * b + a, bnd, 10, 2)
    fit = infill.fit_all(des, _problem(bnd), kind="gp", restarts=2, seed=1)
    import json

    back = infill.FitResult.from_json(json.loads(json.dumps(fit.to_json())))
    X = gp.lhs_unit(np.random.default_rng(1), 5, 2)
    assert np.allclose(back.objective.raw(X)[0], fit.objective.raw(X)[0], atol=1e-10)


def test_cancel_checkpoint_propagates():
    class Stop(Exception):
        pass

    def cp():
        raise Stop()

    bnd = {"a": (0.0, 1.0), "b": (0.0, 1.0)}
    with pytest.raises(Stop):
        infill.fit_all(_designs(lambda a, b: a + b, bnd, 8, 1), _problem(bnd), kind="gp", restarts=2, seed=1, checkpoint=cp)


def test_constant_objective_is_reported_not_as_gp_failure():
    bnd = {"a": (0.0, 1.0), "b": (0.0, 1.0)}
    fit = infill.fit_all(_designs(lambda a, b: 100.0, bnd, 8, 1), _problem(bnd), kind="gp", restarts=2, seed=1)
    assert fit.kind == "rbf" and [w["code"] for w in fit.warnings] == ["OBJECTIVE_CONSTANT"]
    assert "실패" not in fit.warnings[0]["message"]
