"""V3-S15-1~6: 표본 방식 설계 계산(phase3 §20.5, D3-63) — 최적화 LHS·Sobol·전체 요인·부분 요인·PB·BBD·CCD.

순수 계산이라 DB·API 없음. 설계 성질은 구현과 별개로 이 파일에서 다시 계산해 확인한다(해상도·직교·XᵀX = N·I).
"""

from __future__ import annotations

import itertools
import json
import math
import time
import warnings
from typing import Any

import numpy as np
import pytest

from physicsai_core.sampling import designs, fractional, qmc, registry
from physicsai_core.stage4_predict import batch_matrix as bm
from physicsai_test_support import REPO

GOLDEN = REPO / "backend" / "tests" / "data" / "lhs_opt_golden.json"


def _params(k: int, *, ints: tuple[int, ...] = (), fixed: tuple[int, ...] = ()) -> tuple[list[dict], list[dict]]:
    """k개 파라미터(X0.. 범위 0~10, ints 인덱스는 정수 형식, fixed 인덱스는 min = max)."""
    ps = [{"name": f"X{i}", "min": 5.0 if i in fixed else 0.0, "max": 5.0 if i in fixed else 10.0} for i in range(k)]
    tp = [{"name": f"X{i}", "format": "%3i" if i in ints else "%5.2f"} for i in range(k)]
    return ps, tp


def _build(source: dict, k: int = 3, *, ints: tuple[int, ...] = (), fixed: tuple[int, ...] = (), max_runs: int = 200, **kw: Any):
    ps, tp = _params(k, ints=ints, fixed=fixed)
    return bm.build_matrix(source, parameters=ps, tpl_params=tp, max_runs=max_runs, table_max_bytes=1024, **kw)


def _codes(m, k: int) -> list[list[float]]:
    """값 → 코드값(−1~+1, 범위 0~10) — 활성 변수만."""
    return [[(r.values[f"X{i}"] - 5.0) / 5.0 for i in range(k)] for r in m.rows]


def _codes_of(m) -> list[list[float]]:
    act = m.source_meta["active"]
    return [[(r.values[n] - 5.0) / 5.0 for n in act] for r in m.rows]


def _pcodes(m) -> list[str]:
    return [p["code"] for p in m.problems]


def _ncodes(m) -> list[str]:
    return [n["code"] for n in m.notes]


# ---- V3-S15-1 lhs_opt ----------------------------------------------------------------------------------


def test_v3_s15_1_lhs_opt_golden():
    g = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for crit in ("maximin", "corr"):
        u, info = designs.lhs_opt_unit(g[crit]["n"], g[crit]["k"], g[crit]["seed"], crit)
        assert np.allclose(np.array(u), np.array(g[crit]["u"]), rtol=0, atol=1e-12), crit
        assert info["final_score"] == pytest.approx(g[crit]["final_score"], rel=1e-12)
        assert designs.quality(u) == g[crit]["quality"]


@pytest.mark.parametrize("criterion", ["maximin", "corr"])
def test_v3_s15_1_lhs_opt_properties(criterion):
    n, k = 20, 4
    a, ia = designs.lhs_opt_unit(n, k, 5, criterion)
    b, _ib = designs.lhs_opt_unit(n, k, 5, criterion)
    c, _ic = designs.lhs_opt_unit(n, k, 6, criterion)
    assert a == b and a != c                                              # 같은 seed 같음, 다른 seed 다름
    for j in range(k):                                                    # 열마다 칸당 1점
        assert sorted(int(a[i][j] * n) for i in range(n)) == list(range(n))
    assert ia["final_score"] <= ia["candidate_score"]                     # 최종 점수 ≤ 후보 최선
    assert ia["final_score"] == pytest.approx(designs.lhs_opt_score(a, criterion), rel=1e-9)
    base, _ = designs.lhs_opt_unit(n, k, 5, criterion)                    # 후보만(교환 0회)보다 나쁘지 않음
    assert designs.lhs_opt_score(base, criterion) <= ia["candidate_score"]


def test_v3_s15_1_lhs_opt_improves_on_lhs():
    """최적화 LHS는 같은 후보 중 최선보다 낫고(점수), 최소 거리가 일반 LHS 평균 이상이다."""
    n, k = 30, 3
    opt, info = designs.lhs_opt_unit(n, k, 3, "maximin")
    assert info["final_score"] < info["candidate_score"]
    plain = [designs.min_dist(designs._candidate(__import__("random").Random(s), n, k)) for s in range(10)]
    assert designs.min_dist(opt) > sum(plain) / len(plain)
    cor, cinfo = designs.lhs_opt_unit(n, k, 3, "corr")
    assert cinfo["final_score"] < cinfo["candidate_score"]


def test_v3_s15_1_quality_values():
    pts = [[0.0, 0.0], [1.0, 1.0], [0.5, 0.2]]
    q = designs.quality(pts)
    exp_min = min(math.dist(a, b) for a, b in itertools.combinations(pts, 2)) / math.sqrt(2)
    assert q["min_dist"] == round(exp_min, 4)
    x, y = [p[0] for p in pts], [p[1] for p in pts]
    assert q["max_abs_corr"] == round(abs(float(np.corrcoef(x, y)[0, 1])), 4)
    assert designs.quality([[0.1], [0.5], [0.9]])["max_abs_corr"] == 0.0   # k < 2


def test_v3_s15_1_lhs_opt_matrix_meta_and_time():
    m = _build({"kind": "lhs_opt", "count": 12, "seed": 3, "criterion": "corr"}, k=3)
    assert m.ok and m.source_kind == "LHS_OPT" and len(m.rows) == 12
    assert set(m.source_meta) == {"count", "seed", "criterion", "candidates", "iterations", "ranges", "active", "fixed", "quality"}
    assert (m.source_meta["candidates"], m.source_meta["iterations"], m.source_meta["criterion"]) == (5, 2000, "corr")
    assert set(m.source_meta["quality"]) == {"min_dist", "max_abs_corr"}
    assert _build({"kind": "lhs_opt", "count": 12, "seed": 3, "criterion": "corr"}, k=3).rows == m.rows
    assert all(0.0 <= v <= 10.0 for r in m.rows for v in r.values.values())
    assert _pcodes(_build({"kind": "lhs_opt", "count": 1}, k=3)) == ["TOO_FEW_ROWS"]
    assert _pcodes(_build({"kind": "lhs_opt", "count": 201}, k=3)) == ["TOO_MANY_ROWS"]
    t = time.perf_counter()
    big = _build({"kind": "lhs_opt", "count": 200, "seed": 1}, k=20)
    assert big.ok and len(big.rows) == 200 and time.perf_counter() - t < 10.0   # 성능은 10초 상한만


def test_v3_s15_1_fixed_variables_excluded():
    m = _build({"kind": "lhs_opt", "count": 8, "seed": 1}, k=3, fixed=(1,))
    assert m.source_meta["active"] == ["X0", "X2"] and m.source_meta["fixed"] == ["X1"]
    assert all(r.values["X1"] == 5.0 for r in m.rows)
    assert _ncodes(m)[0] == "FIXED_EXCLUDED" and "X1" in m.notes[0]["message"]
    k0 = _build({"kind": "lhs_opt", "count": 8}, k=2, fixed=(0, 1))
    assert _pcodes(k0) == ["DESIGN_UNSUPPORTED"] and "범위가 있는 변수가 없습니다" in k0.problems[0]["message"]
    bad = _build({"kind": "lhs_opt", "count": 8, "ranges": {"X0": [5, 5]}}, k=2)
    assert _pcodes(bad) == ["RANGE_INVALID"]


# ---- V3-S15-2 sobol ------------------------------------------------------------------------------------


def _sobol(count: int, k: int = 3, **src: Any):
    return _build({"kind": "sobol", "count": count, **src}, k=k)


def _prev_of(m, *, label: str = "B-001", pid: str = "ps1") -> dict:
    return {"id": "b-prev", "label": label, "source_kind": "SOBOL", "param_set_id": pid, "source_meta": dict(m.source_meta),
            "runs": [{"doe_no": r.doe_no, "values": dict(r.values)} for r in m.rows]}


def test_v3_s15_2_sobol_basic_and_balance():
    a, b = _sobol(16, seed=4), _sobol(16, seed=4)
    assert a.ok and a.rows == b.rows and a.source_kind == "SOBOL"
    assert _sobol(16, seed=5).rows != a.rows
    n = 16
    for j in range(3):                                                     # n = 2^m: 열마다 1/n 칸당 1점
        assert sorted(int(r.values[f"X{j}"] / 10.0 * n) for r in a.rows) == list(range(n))
    meta = a.source_meta
    assert (meta["count"], meta["m"], meta["seed"], meta["offset"], meta["continue_from"], meta["scramble"]) == (16, 4, 4, 0, None, True)
    assert meta["generator"].startswith("scipy ") and set(meta["quality"]) == {"min_dist", "max_abs_corr"}
    import scipy

    assert meta["generator"] == f"scipy {scipy.__version__}"
    assert _sobol(4).source_meta["seed"] == 1                              # seed 생략 = 1
    with pytest.raises(bm.BatchShapeError):
        _sobol(8, seed=-1)
    with pytest.raises(bm.BatchShapeError):
        _sobol(8, seed=4294967296)


@pytest.mark.parametrize("count", [0, 1, 2, 3, 6, 12, 100, 256])
def test_v3_s15_2_count_not_pow2(count):
    m = _sobol(count)
    assert "COUNT_NOT_POW2" in _pcodes(m) and m.rows == []
    assert "4·8·16·32·64·128" in next(p["message"] for p in m.problems if p["code"] == "COUNT_NOT_POW2")


def test_v3_s15_2_sobol_continue_equals_tail_of_double():
    first = _sobol(8, seed=7)
    cont = _build({"kind": "sobol", "count": 8, "continue_from": "b-prev"}, k=3, continue_batch=_prev_of(first),
                  param_set_id="ps1")
    assert cont.ok, cont.problems
    both = _sobol(16, seed=7)
    assert [r.values for r in cont.rows] == [r.values for r in both.rows[8:]]    # 이어서 추가 = 처음 2n개의 뒤 n개
    assert [r.doe_no for r in cont.rows] == list(range(1, 9))                    # 배치 안 번호는 1부터
    mt = cont.source_meta
    assert (mt["offset"], mt["seed"], mt["count"]) == (8, 7, 8)
    assert mt["continue_from"] == {"batch_id": "b-prev", "label": "B-001"} and mt["ranges"] == first.source_meta["ranges"]
    assert {"code": "SEQUENCE_CONTINUED", "message": "B-001과 합치면 16개(균형 유지)"} in cont.notes
    # 다시 이어서 추가(이어서 추가한 배치를 또 이어감) + 균형 아님 안내
    prev2 = _prev_of(cont, label="B-002")
    c3 = _build({"kind": "sobol", "count": 8, "continue_from": "b-prev"}, k=3, continue_batch=prev2, param_set_id="ps1")
    assert c3.ok and c3.source_meta["offset"] == 16
    assert [r.values for r in c3.rows] == [r.values for r in _sobol(32, seed=7).rows[16:24]]
    c4 = _build({"kind": "sobol", "count": 4, "continue_from": "b-prev"}, k=3, continue_batch=_prev_of(first), param_set_id="ps1")
    assert c4.ok and any("합계는 균형 아님" in n["message"] and "12개" in n["message"] for n in c4.notes)


def test_v3_s15_2_continue_invalid_reasons():
    first = _sobol(8, seed=7)
    src = {"kind": "sobol", "count": 8, "continue_from": "b-prev"}

    def go(prev, **over):
        return _build({**src, **over}, k=3, continue_batch=prev, param_set_id="ps1")

    def one(m):
        assert _pcodes(m) == ["CONTINUE_INVALID"] and m.rows == []
        return m.problems[0]["message"]

    assert one(go({**_prev_of(first), "source_kind": "LHS"})) == "Sobol 배치가 아닙니다"
    assert one(go({**_prev_of(first), "param_set_id": "other"})) == "다른 템플릿의 배치입니다"
    changed = {**_prev_of(first), "source_meta": {**first.source_meta, "active": ["X0", "X1"]}}
    assert one(go(changed)) == "변수 구성이 다릅니다"
    assert one(go(_prev_of(first), seed=3)) == "이어서 추가는 이전 배치의 시드·범위를 그대로 씁니다"
    assert one(go(_prev_of(first), ranges={"X0": [0, 5]})) == "이어서 추가는 이전 배치의 시드·범위를 그대로 씁니다"
    assert "찾을 수 없습니다" in one(go({"missing": True}))
    msg = one(go(_prev_of(first), count=16))                                  # offset 8 % 16 ≠ 0
    assert msg == "이어서 추가할 run 수는 8을 나누어떨어지게 하는 2의 거듭제곱이어야 합니다(권장 8)"
    prev12 = _prev_of(_build({"kind": "sobol", "count": 4, "continue_from": "b-prev"}, k=3,
                             continue_batch=_prev_of(first), param_set_id="ps1"))
    assert "12을" in one(go(prev12, count=8)) and "권장 4" in one(go(prev12, count=8))


def test_v3_s15_2_sequence_mismatch_on_tampered_values():
    first = _sobol(8, seed=7)
    prev = _prev_of(first)
    prev["runs"][3]["values"]["X1"] += 0.001                                   # 저장 값 변조
    m = _build({"kind": "sobol", "count": 8, "continue_from": "b-prev"}, k=3, continue_batch=prev, param_set_id="ps1")
    assert _pcodes(m) == ["SEQUENCE_MISMATCH"] and "새 Sobol 배치로 시작하세요" in m.problems[0]["message"]
    short = _prev_of(first)
    short["runs"].pop()
    assert _pcodes(_build({"kind": "sobol", "count": 8, "continue_from": "b-prev"}, k=3, continue_batch=short,
                          param_set_id="ps1")) == ["SEQUENCE_MISMATCH"]


def test_v3_s15_2_generator_unavailable(monkeypatch):
    def boom():
        raise qmc.GeneratorUnavailable(qmc.GENERATOR_UNAVAILABLE_MESSAGE)

    monkeypatch.setattr(qmc, "_load", boom)
    m = _sobol(8)
    assert _pcodes(m) == ["GENERATOR_UNAVAILABLE"] and m.rows == []
    assert "scipy" in m.problems[0]["message"] and "관리자에게 문의하세요" in m.problems[0]["message"]


def test_v3_s15_2_import_failure_is_wrapped(monkeypatch):
    import builtins

    real = builtins.__import__

    def fake(name, *a, **kw):
        if name.startswith("scipy"):
            raise ImportError("no scipy")
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(qmc.GeneratorUnavailable):
        qmc.sobol_unit(2, 4, 1, 0)


class _FakeBase:
    calls: list[dict] = []

    def __init__(self, d, scramble, kw):
        self.d, self.scramble, self.kw, self.pos = d, scramble, kw, 0
        type(self).calls.append({"d": d, "scramble": scramble, **kw})

    def fast_forward(self, n):
        self.pos += n

    def random(self, n):
        warnings.warn("balance properties asymptotically", UserWarning)
        return np.array([[((self.pos + i + 1) * (j + 1) * 0.01) % 1.0 for j in range(self.d)] for i in range(n)])


class _FakeRng(_FakeBase):
    calls: list[dict] = []

    def __init__(self, d, *, scramble=True, rng=None):
        super().__init__(d, scramble, {"rng": rng})


class _FakeSeed(_FakeBase):
    calls: list[dict] = []

    def __init__(self, d, *, scramble=True, seed=None):
        super().__init__(d, scramble, {"seed": seed})


@pytest.mark.parametrize(("cls", "key"), [(_FakeRng, "rng"), (_FakeSeed, "seed")])
def test_v3_s15_2_rng_or_seed_keyword_branches(monkeypatch, cls, key):
    cls.calls.clear()
    monkeypatch.setattr(qmc, "_load", lambda: (cls, np, "9.9.9"))
    assert qmc.rng_keyword(cls) == key
    with warnings.catch_warnings(record=True) as rec:                          # 경고가 밖으로 새지 않음
        warnings.simplefilter("always")
        pts, gen = qmc.sobol_unit(2, 4, 11, 8)
    assert [w for w in rec if issubclass(w.category, UserWarning)] == []
    assert gen == "scipy 9.9.9" and len(pts) == 4 and len(pts[0]) == 2
    assert cls.calls[0]["d"] == 2 and cls.calls[0]["scramble"] is True and set(cls.calls[0]) == {"d", "scramble", key}
    assert isinstance(cls.calls[0][key], np.random.Generator)
    assert pts[0] == pytest.approx([(8 + 1) * 0.01, (8 + 1) * 2 * 0.01])      # fast_forward(offset)


def test_v3_s15_2_real_scipy_warning_contained():
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        qmc.sobol_unit(3, 6, 1, 0)                                              # 2의 거듭제곱이 아니면 scipy가 경고
    assert [w for w in rec if issubclass(w.category, UserWarning)] == []


# ---- V3-S15-3 fullfact ---------------------------------------------------------------------------------


def test_v3_s15_3_fullfact_order_runs_and_ends():
    m = _build({"kind": "fullfact", "levels": {"X0": 3, "X1": 2, "X2": 2}}, k=3)
    assert m.ok and m.source_kind == "FULLFACT" and len(m.rows) == 12
    got = [(r.values["X0"], r.values["X1"], r.values["X2"]) for r in m.rows]
    exp = [(a, b, c) for a in (0.0, 5.0, 10.0) for b in (0.0, 10.0) for c in (0.0, 10.0)]   # 마지막 변수가 가장 빨리
    assert got == exp
    assert m.source_meta["levels"] == {"X0": 3, "X1": 2, "X2": 2}
    assert m.rows[0].values["X0"] == 0.0 and m.rows[-1].values["X0"] == 10.0              # 끝값 정확
    default = _build({"kind": "fullfact"}, k=3)
    assert len(default.rows) == 8 and default.source_meta["levels"] == {"X0": 2, "X1": 2, "X2": 2}
    m7 = _build({"kind": "fullfact", "levels": {"X0": 7}, "ranges": {"X0": [0.1, 0.7]}}, k=1)
    assert m7.rows[0].values["X0"] == 0.1 and m7.rows[-1].values["X0"] == 0.7


def test_v3_s15_3_fullfact_integer_levels():
    ps, tp = _params(2, ints=(0,))
    ps[0].update(min=2.0, max=5.0)
    ok = bm.build_matrix({"kind": "fullfact", "levels": {"X0": 4, "X1": 2}}, parameters=ps, tpl_params=tp, max_runs=200,
                         table_max_bytes=1)
    assert ok.ok and sorted({r.values["X0"] for r in ok.rows}) == [2.0, 3.0, 4.0, 5.0]
    assert all(float(r.values["X0"]).is_integer() for r in ok.rows)
    over = bm.build_matrix({"kind": "fullfact", "levels": {"X0": 5}}, parameters=ps, tpl_params=tp, max_runs=200, table_max_bytes=1)
    assert _pcodes(over) == ["LEVELS_INVALID"] and over.problems[0]["message"] == "'X0'은 정수 변수라 2~5에서 최대 4수준입니다"
    unknown = _build({"kind": "fullfact", "levels": {"ZZ": 3}}, k=2)
    assert _pcodes(unknown) == ["LEVELS_INVALID"] and "범위가 있는 변수가 아닙니다" in unknown.problems[0]["message"]
    one = _build({"kind": "fullfact", "levels": {"X0": 1}}, k=2)
    assert _pcodes(one) == ["LEVELS_INVALID"] and "수준은 2~10" in one.problems[0]["message"]
    assert _pcodes(_build({"kind": "fullfact", "levels": {"X0": 11}}, k=2)) == ["LEVELS_INVALID"]
    with pytest.raises(bm.BatchShapeError):
        _build({"kind": "fullfact", "levels": {"X0": "3"}}, k=2)


def test_v3_s15_3_fullfact_too_many_and_fixed():
    m = _build({"kind": "fullfact", "levels": {"X0": 10, "X1": 10, "X2": 3}}, k=3)
    assert _pcodes(m) == ["TOO_MANY_ROWS"] and m.problems[0]["message"] == \
        "전체 요인 run 수 300개가 상한 200개를 넘습니다 — 수준 수를 줄이세요"
    fx = _build({"kind": "fullfact", "levels": {"X0": 3, "X1": 9}}, k=3, fixed=(1,))      # 고정 변수 입력 무시
    assert fx.ok and len(fx.rows) == 6 and all(r.values["X1"] == 5.0 for r in fx.rows)
    assert fx.source_meta["levels"] == {"X0": 3, "X2": 2} and fx.source_meta["fixed"] == ["X1"]
    assert _ncodes(fx)[0] == "FIXED_EXCLUDED"


# ---- V3-S15-4 fracfact ---------------------------------------------------------------------------------

# §20.5.9 run 수 표: k → (IV, V)
RUNS_FRAC = {2: (4, 4), 3: (8, 8), 4: (8, 16), 5: (16, 16), 6: (16, 32), 7: (16, 64), 8: (16, 64), 9: (32, 128), 10: (32, 128),
             11: (32, 128)}


def _mat(k: int, res: int) -> np.ndarray:
    r, gens, _full = fractional.fracfact_plan(k, res)
    return np.array(fractional.two_level_matrix(k, r, gens), dtype=int)


def _resolution_numeric(x: np.ndarray) -> int:
    """설계 행렬에서 직접 계산한 해상도 하한: 주효과–2인자 직교면 ≥ IV, 2인자끼리 직교면 ≥ V (그렇지 않으면 III 이하)."""
    n, k = x.shape
    pairs = list(itertools.combinations(range(k), 2))
    if any(x[:, i] @ x[:, j] != 0 for i, j in pairs):
        return 2
    mains_vs_2fi = all(x[:, i] @ (x[:, j] * x[:, m]) == 0 for i in range(k) for j, m in pairs if i not in (j, m))
    if not mains_vs_2fi:
        return 3
    fi2 = [x[:, j] * x[:, m] for j, m in pairs]
    ok5 = all(fi2[a] @ fi2[b] == 0 for a in range(len(fi2)) for b in range(a + 1, len(fi2)))
    return 5 if ok5 else 4


_CELLS = [(res, k) for res in (4, 5) for k in range(2, 12) if fractional.fracfact_plan(k, res)[1]]


def test_v3_s15_4_table_has_15_generator_cells():
    assert len(_CELLS) == 15


@pytest.mark.parametrize(("res", "k"), _CELLS)
def test_v3_s15_4_generator_resolution(res, k):
    r, gens, full = fractional.fracfact_plan(k, res)
    assert not full
    assert fractional.resolution_of(k, gens) >= res                            # 정의 관계로 계산
    x = _mat(k, res)
    assert x.shape == (RUNS_FRAC[k][res - 4], k)
    assert _resolution_numeric(x) >= res                                       # 설계 행렬로 다시 계산(독립)


@pytest.mark.parametrize(("res", "k"), [(res, k) for res in (4, 5) for k in range(2, 12)])
def test_v3_s15_4_balance_orthogonality_runs(res, k):
    x = _mat(k, res)
    assert x.shape[0] == RUNS_FRAC[k][res - 4]                                 # §20.5.9
    assert (x.sum(axis=0) == 0).all()                                          # 열 균형
    gram = x.T @ x
    assert (gram == x.shape[0] * np.eye(k, dtype=int)).all()                   # 쌍 직교
    assert _resolution_numeric(x) >= res


def test_v3_s15_4_yates_order_and_matrix():
    m = _build({"kind": "fracfact", "resolution": 4}, k=4)
    codes = _codes_of(m)
    assert [c[0] for c in codes] == [-1, 1] * 4 and [c[1] for c in codes[:4]] == [-1, -1, 1, 1]   # 첫 요인이 가장 빨리
    assert all(c[3] == c[0] * c[1] * c[2] for c in codes)                                       # D = ABC
    assert m.source_meta["generators"] == ["D=ABC"] and m.source_meta["runs"] == 8 and m.source_meta["full"] is False
    assert m.source_meta["letters"] == {"A": "X0", "B": "X1", "C": "X2", "D": "X3"} and m.source_meta["resolution"] == 4
    assert m.rows[0].values["X0"] == 0.0 and m.rows[1].values["X0"] == 10.0                    # −1 → lo, +1 → hi
    assert "FULL_FACTORIAL_USED" not in _ncodes(m)


def test_v3_s15_4_full_factorial_note_and_letters():
    m = _build({"kind": "fracfact", "resolution": 5}, k=4)
    assert m.source_meta["full"] is True and len(m.rows) == 16 and m.source_meta["generators"] == []
    assert any(n == {"code": "FULL_FACTORIAL_USED", "message": "변수 4개에서는 부분 요인 대신 전체 2수준 요인(2^4)을 씁니다"}
               for n in m.notes)
    m11 = _build({"kind": "fracfact", "resolution": 4}, k=11)
    assert list(m11.source_meta["letters"]) == list("ABCDEFGHJKL") and len(m11.rows) == 32
    assert m11.source_meta["generators"][0] == "F=ABC"
    dflt = _build({"kind": "fracfact"}, k=6)
    assert dflt.source_meta["resolution"] == 5 and len(dflt.rows) == 32


def test_v3_s15_4_unsupported_counts_and_shape():
    for k in (1, 12):
        m = _build({"kind": "fracfact"}, k=k)
        assert _pcodes(m) == ["DESIGN_UNSUPPORTED"] and m.rows == []
        assert m.problems[0]["message"] == "부분 요인은 범위가 있는 변수 2~11개에서만 만들 수 있습니다"
    for bad in (3, 6, "5"):
        with pytest.raises(bm.BatchShapeError):
            _build({"kind": "fracfact", "resolution": bad}, k=4)
    capped = _build({"kind": "fracfact", "resolution": 5}, k=8, max_runs=32)
    assert _pcodes(capped) == ["TOO_MANY_ROWS"]


# ---- V3-S15-5 pb ---------------------------------------------------------------------------------------


def _expected_pb_size(k: int) -> int:
    sizes = sorted({q + 1 for q in range(7, 400) if all(q % d for d in range(2, int(q ** 0.5) + 1)) and q % 4 == 3}
                   | {2 ** m for m in range(3, 9)})
    return next(s for s in sizes if s >= k + 1)


def test_v3_s15_5_pb_sizes_and_construction():
    for k in range(2, 48):
        n = fractional.pb_size(k)
        assert n == _expected_pb_size(k), k
        x, construction = fractional.pb_matrix(n, k)
        assert len(x) == n and construction in ("paley", "sylvester")
        assert construction == ("paley" if fractional._paley_prime(n) else "sylvester")
    assert [fractional.pb_size(k) for k in (2, 7, 8, 11, 12)] == [8, 8, 12, 12, 16]


def test_v3_s15_5_pb_orthogonal_all_sizes():
    sizes = [n for n in range(8, 201) if fractional._paley_prime(n) or fractional._is_pow2(n)]
    assert sizes == [8, 12, 16, 20, 24, 32, 44, 48, 60, 64, 68, 72, 80, 84, 104, 108, 128, 132, 140, 152, 164, 168, 180,
                     192, 200]
    for n in sizes:
        x = np.array(fractional.pb_matrix(n, n - 1)[0])
        assert x.shape == (n, n - 1)
        assert (x.T @ x == n * np.eye(n - 1, dtype=int)).all(), n                 # XᵀX = N·I
        assert set(np.unique(x)) == {-1, 1}


def test_v3_s15_5_pb_n12_first_row_and_matrix():
    row, construction = fractional.pb_matrix(12, 11)
    assert "".join("+" if v > 0 else "-" for v in row[0]) == "++-+++---+-" and construction == "paley"
    assert fractional.pb_matrix(16, 15)[1] == "sylvester" and fractional.pb_matrix(32, 31)[1] == "paley"
    m = _build({"kind": "pb"}, k=9)
    assert m.ok and len(m.rows) == 12 and m.source_meta["runs"] == 12 and m.source_meta["construction"] == "paley"
    assert {r.values["X0"] for r in m.rows} == {0.0, 10.0}
    assert "quality" not in m.source_meta
    one = _build({"kind": "pb"}, k=1)
    assert _pcodes(one) == ["DESIGN_UNSUPPORTED"]
    assert _pcodes(_build({"kind": "pb"}, k=20, max_runs=16)) == ["TOO_MANY_ROWS"]


# ---- V3-S15-6 bbd / ccd --------------------------------------------------------------------------------

RUNS_BBD = {3: 13, 4: 25, 5: 41, 6: 61, 7: 85, 8: 113, 9: 145, 10: 181}
RUNS_CCD = {2: 9, 3: 15, 4: 25, 5: 27, 6: 45, 7: 79, 8: 81, 9: 147, 10: 149, 11: 151}


@pytest.mark.parametrize("k", list(RUNS_BBD))
def test_v3_s15_6_bbd(k):
    m = _build({"kind": "bbd"}, k=k)
    assert m.ok and len(m.rows) == RUNS_BBD[k] == 2 * k * (k - 1) + 1
    codes = _codes_of(m)
    assert {round(v, 9) for c in codes for v in c} == {-1.0, 0.0, 1.0}              # 3수준
    assert codes[-1] == [0.0] * k                                                    # 중심 행 마지막, 1개
    assert sum(1 for c in codes if not any(c)) == 1
    assert all(sum(1 for v in c if v) == 2 for c in codes[:-1])                       # 쌍 방식: 두 변수만 극값
    assert all(0.0 <= v <= 10.0 for r in m.rows for v in r.values.values())
    assert m.source_meta["center"] == 1 and m.source_meta["pairwise"] is (k >= 6)
    assert ("BBD_PAIRWISE" in _ncodes(m)) is (k >= 6)


def test_v3_s15_6_bbd_limits():
    for k in (1, 2):
        m = _build({"kind": "bbd"}, k=k)
        assert _pcodes(m) == ["DESIGN_UNSUPPORTED"] and "3개 이상" in m.problems[0]["message"]
    m = _build({"kind": "bbd"}, k=11)
    assert _pcodes(m) == ["TOO_MANY_ROWS"] and "221" in m.problems[0]["message"]
    assert _codes_of(_build({"kind": "bbd"}, k=3))[:4] == [[-1, -1, 0], [1, -1, 0], [-1, 1, 0], [1, 1, 0]]


@pytest.mark.parametrize("k", list(RUNS_CCD))
@pytest.mark.parametrize("alpha", ["face", "inscribed"])
def test_v3_s15_6_ccd(k, alpha):
    m = _build({"kind": "ccd", "alpha": alpha}, k=k)
    assert m.ok and len(m.rows) == RUNS_CCD[k], m.problems
    codes = np.array(_codes_of(m))
    f = len(m.rows) - 2 * k - 1
    assert (codes[-1] == 0).all()                                                    # 중심 1행 마지막
    axial = codes[f:f + 2 * k]
    assert [list(r) for r in axial[:2]] == [[-1.0] + [0.0] * (k - 1), [1.0] + [0.0] * (k - 1)]
    levels = {round(float(v), 6) for v in codes.ravel()}
    if alpha == "face":
        assert levels == {-1.0, 0.0, 1.0} and m.source_meta["alpha"] == 1.0
    else:
        a = f ** 0.25
        assert levels == {-1.0, -round(1 / a, 6), 0.0, round(1 / a, 6), 1.0} and m.source_meta["alpha"] == pytest.approx(a)
        assert len(levels) == 5
    assert np.all(np.abs(codes) <= 1.0 + 1e-12)
    assert all(0.0 <= v <= 10.0 for r in m.rows for v in r.values.values())          # 범위 밖 없음
    assert m.source_meta["factorial"] == ("full" if k <= 4 else "fracV") and m.source_meta["alpha_kind"] == alpha
    if k >= 5:
        assert m.source_meta["generators"] == list(fractional.generator_table(5)[k][1])


def test_v3_s15_6_ccd_limits_and_shape():
    for k in (1, 12):
        assert _pcodes(_build({"kind": "ccd"}, k=k)) == ["DESIGN_UNSUPPORTED"]
    with pytest.raises(bm.BatchShapeError):
        _build({"kind": "ccd", "alpha": "rotatable"}, k=3)
    assert _pcodes(_build({"kind": "ccd"}, k=6, max_runs=40)) == ["TOO_MANY_ROWS"]


def test_v3_s15_6_integer_variable_duplicates():
    ps, tp = _params(3, ints=(0, 1, 2))
    for p in ps:
        p.update(min=2.0, max=3.0)
    m = bm.build_matrix({"kind": "bbd"}, parameters=ps, tpl_params=tp, max_runs=200, table_max_bytes=1)
    assert m.ok and len(m.rows) == 13                                                     # 행은 지우지 않는다
    dup = next(n for n in m.notes if n["code"] == "DUPLICATE_ROWS")                       # 중심(2.5→3)과 (+,+,0)이 같은 조합
    assert dup["message"].startswith("정수 반올림 뒤 같은 조합이 ") and "같은 예측이 반복됩니다" in dup["message"]
    assert m.rows[-1].applied_values == m.rows[3].applied_values


def test_v3_s15_6_code_to_value_formula():
    assert designs.code_to_value(-1, 2.0, 5.0) == 2.0 and designs.code_to_value(1, 2.0, 5.0) == 5.0
    assert designs.code_to_value(0, 2.0, 5.0) == (2.0 + 5.0) / 2
    assert designs.code_to_value(0.5, 2.0, 6.0) == (2.0 + 6.0) / 2 + 0.5 * (6.0 - 2.0) / 2
    assert designs.unit_to_value(0.25, 2.0, 6.0) == 2.0 + 0.25 * 4.0


def test_registry_recommended_counts_match_table():
    """§20.5.9 sobol·lhs 권장 열 (k = 2~11, R = 200)."""
    sobol = {2: 32, 3: 32, 4: 64, 5: 64, 6: 64, 7: 128, 8: 128, 9: 128, 10: 128, 11: 128}
    for k, v in sobol.items():
        assert registry.recommended_count("sobol", k, 200) == v
        assert registry.recommended_count("lhs", k, 200) == registry.recommended_count("lhs_opt", k, 200) == max(10, 10 * k)
    assert registry.recommended_count("sobol", 30, 200) == 128 and registry.recommended_count("lhs", 30, 200) == 200
    assert registry.recommended_count("bbd", 4, 200) is None
