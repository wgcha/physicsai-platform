"""V3-S17-7: 다목적 루프(`mo_infill.run_offline` — 해석 함수를 평가기로, 실제 작업 없음, 설정 기본값 §22.11).

ZDT1·ZDT2(d=3, 탐색 12 + 4×4), DTLZ2(m=3, d=4, 탐색 16 + 4×4). 기준: 검증 HV/참 HV ≥ ZDT1 0.80 · ZDT2 0.70 · DTLZ2 0.70(시드 1),
같은 예산 LHS만 쓴 HV보다 큼(시드 1~5 중 4개 이상). HV 기준점 1.1(원 목적 공간, 참 HV = 1.21 − ∫전선).

기본 test-all은 ZDT1 시드 1만, 나머지는 `slow` 마커(scripts/test-all --slow — nightly 같은 별도 명령).

측정(2026-10-19, numpy 2.4.6·scipy 1.17.1, 시드 1~5 · 괄호 = 같은 예산 LHS):
ZDT1 0.865·0.837·0.878·0.911·0.879 (0.281·0.176·0.338·0.049·0.137) — 충족, 5/5.
ZDT2 0.727·0.707·0.728·0.809·0.751 (모두 0.0) — 충족, 5/5.
DTLZ2 계약 원안(HVI 1개 + ParEGO): 0.666·0.540·0.437·0.583·0.543 (0.416·0.542·0.477·0.547·0.492) — 미달, 3/5.
DTLZ2 3목적 조정(메인 지시 — mo_hvi_share_m3 0.5: HVI 활용 ⌈k/2⌉개, mo_front_prox_m3 6: ParEGO 획득값 × exp(−6·예측 전선까지 거리)):
0.734·0.680·0.565·0.556·0.573 — 시드 1 충족, 5/5. 2목적은 두 키를 쓰지 않는다(위 ZDT 값 그대로).
"""

from __future__ import annotations

import math

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from physicsai_core.config.schema_stages import SurrogateOptCfg  # noqa: E402
from physicsai_core.stage5_optimize.surrogate import mo_infill, pareto  # noqa: E402

CFG = mo_infill.MoCfg.from_settings(SurrogateOptCfg())


def zdt1(x):
    g = 1 + 9 * float(np.mean(x[1:]))
    return [float(x[0]), g * (1 - math.sqrt(float(x[0]) / g))]


def zdt2(x):
    g = 1 + 9 * float(np.mean(x[1:]))
    return [float(x[0]), g * (1 - (float(x[0]) / g) ** 2)]


def dtlz2(x):
    g = float(np.sum((x[2:] - 0.5) ** 2))
    a, b = float(x[0]) * math.pi / 2, float(x[1]) * math.pi / 2
    return [(1 + g) * math.cos(a) * math.cos(b), (1 + g) * math.cos(a) * math.sin(b), (1 + g) * math.sin(a)]


CASES = {  # 함수, d, m, 탐색 수, 참 HV(R=1.1), 기준 비율
    "zdt1": (zdt1, 3, 2, 12, 1.21 - 1 / 3, 0.80),
    "zdt2": (zdt2, 3, 2, 12, 1.21 - 2 / 3, 0.70),
    "dtlz2": (dtlz2, 4, 3, 16, 1.331 - math.pi / 6, 0.70),
}
_CACHE: dict[tuple[str, int, bool], float] = {}


def _hv_ratio(name: str, seed: int, lhs_only: bool = False) -> float:
    key = (name, seed, lhs_only)
    if key not in _CACHE:
        f, d, m, n0, true, _ = CASES[name]
        out = mo_infill.run_offline(f, d, m, n0=n0, iterations=4, k=4, seed=seed, cfg=CFG, restarts=8, lhs_only=lhs_only)
        assert len(out["F"]) == n0 + 16
        _CACHE[key] = pareto.hypervolume(out["F"].tolist(), [1.1] * m) / true
    return _CACHE[key]


def test_v3_s17_7_zdt1_seed1():
    """기본 test-all 몫(빠름)."""
    assert _hv_ratio("zdt1", 1) >= CASES["zdt1"][5]


@pytest.mark.slow
@pytest.mark.timeout(900)
@pytest.mark.parametrize("name", ["zdt2", "dtlz2"])
def test_v3_s17_7_hv_ratio_seed1(name):
    assert _hv_ratio(name, 1) >= CASES[name][5]


@pytest.mark.slow
@pytest.mark.timeout(900)
@pytest.mark.parametrize("name", ["zdt1", "zdt2", "dtlz2"])
def test_v3_s17_7_beats_lhs_same_budget(name):
    wins = sum(_hv_ratio(name, s) > _hv_ratio(name, s, lhs_only=True) for s in range(1, 6))
    assert wins >= 4
