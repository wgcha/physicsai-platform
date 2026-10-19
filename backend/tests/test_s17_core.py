"""S17 성능 정의·HV(phase3 §22.3·§22.5.5·§22.6): V3-S17-2(정의 검증)·3(perf_value·METRIC_RE·LRU)·5(pareto 골든)·6(해석 전선 HV)·
10(가중 추천 골든 — `data/s17_recommend.json`, 프런트 `pareto.ts`와 같은 표). 표준 라이브러리만(API 프로세스 규칙)."""

from __future__ import annotations

import itertools
import json
import math
import os
import random
from pathlib import Path

import pytest

from physicsai_core.stage4_predict import run_metrics as rm
from physicsai_core.stage4_predict.performance import PerfDef, perf_defs, perf_label, perf_value
from physicsai_core.stage4_predict.response_defs import validate_response_defs
from physicsai_core.stage4_predict.responses import (
    REQUESTS_FILE,
    RESPONSES_FILE,
    SILENT_REASONS,
    build_requests,
    h3d_request,
    parse_requests_text,
    requests_text,
)
from physicsai_core.stage4_predict.run_metrics import METRIC_RE, RunFiles, RunMetrics, metric_value
from physicsai_core.stage5_optimize.surrogate import pareto

DATA = Path(__file__).resolve().parent / "data"
H3D = {"source": "H3D", "subcase": 1, "datatype": "CornerStress", "component": "", "layer": "", "stat": "MAX"}


@pytest.fixture(autouse=True)
def _fresh_cache():
    rm.cache_clear()
    yield
    rm.cache_clear()


# ---- V3-S17-2 정의 검증 --------------------------------------------------------------------------------------------


def _v(rows):
    return validate_response_defs(rows)


def test_v3_s17_2_curve_spec_valid_and_normalized():
    rows = [{"name": "AccelPeak", "unit": "g", "spec": {"source": "CURVE", "series": "Node 100 / X", "stat": "ABSMAX"}},
            {"name": "First", "unit": "", "spec": {"source": "CURVE", "series": None, "stat": "MIN"}},
            {"name": "Kor", "unit": "", "spec": {"source": "CURVE", "series": "가속도: 노드 1", "stat": "MAX"}},
            {"name": "Long", "unit": "", "spec": {"source": "CURVE", "series": "a" * 200, "stat": "MAX"}},
            {"name": "NoSeries", "unit": "", "spec": {"source": "CURVE", "stat": "MAX"}},
            {"name": "CornerStress", "unit": "MPa", "spec": H3D}]
    out, problems = _v(rows)
    assert problems == []
    assert out[0]["spec"] == {"source": "CURVE", "series": "Node 100 / X", "stat": "ABSMAX"}
    assert out[1]["spec"]["series"] is None and out[4]["spec"] == {"source": "CURVE", "series": None, "stat": "MAX"}
    assert out[5]["spec"] == H3D  # H3D 회귀


@pytest.mark.parametrize("spec", [
    {"source": "CURVE", "series": "a|b", "stat": "MAX"},
    {"source": "CURVE", "series": "a\x01b", "stat": "MAX"},
    {"source": "CURVE", "series": "a\nb", "stat": "MAX"},
    {"source": "CURVE", "series": "a" * 201, "stat": "MAX"},
    {"source": "CURVE", "series": "", "stat": "MAX"},
    {"source": "CURVE", "series": 3, "stat": "MAX"},
    {"source": "CURVE", "series": None, "stat": "AVG"},
    {"source": "CURVE", "series": None},
    {"source": "CURVE", "series": None, "stat": "MAX", "subcase": 1},
    {"source": "XYDATA", "series": None, "stat": "MAX"},
])
def test_v3_s17_2_curve_spec_invalid(spec):
    _out, problems = _v([{"name": "A", "unit": "", "spec": spec}])
    assert problems and all(p["code"] == "RESPONSE_INVALID" for p in problems)


def test_v3_s17_2_curve_is_silent_for_h3d_paths():
    rows = [{"name": "A", "spec": {"source": "CURVE", "series": None, "stat": "MAX"}}, {"name": "B", "spec": H3D}]
    assert h3d_request(rows[0]) == (None, "CURVE") and "CURVE" in SILENT_REASONS
    reqs, skipped = build_requests(rows)
    assert [r.name for r in reqs] == ["B"] and skipped == {"A": "CURVE"}


# ---- V3-S17-3 perf_value·METRIC_RE·LRU -----------------------------------------------------------------------------


def _h3d(stat="MAX", **kw):
    return PerfDef("CornerStress", "MPa", "H3D", {**H3D, "stat": stat, **kw})


def _curve(stat="MAX", series=None):
    return PerfDef("AccelPeak", "g", "CURVE", {"source": "CURVE", "series": series, "stat": stat})


REQ_OK = {"CornerStress": ("1", "CornerStress", "", "")}
RESP = {"CornerStress_MIN": -200.0, "CornerStress_MAX": 150.0}
CURVE = {"Node 100 / X": {"max": 41.0, "min": -55.0, "absmax": 55.0}, "Node 200 / Z": {"max": 3.0, "min": 1.0, "absmax": 3.0}}


def test_v3_s17_3_perf_value_h3d_golden():
    m = RunMetrics(curve=None, resp=RESP, requests=REQ_OK)
    assert perf_value(_h3d("MAX"), m) == (150.0, None)
    assert perf_value(_h3d("MIN"), m) == (-200.0, None)
    assert perf_value(_h3d("ABSMAX"), m) == (200.0, None)
    # 요청 줄이 정의와 다르면 SPEC_CHANGED(stat만 바뀐 것은 요청 줄과 무관)
    assert perf_value(_h3d("MAX", subcase=2), m) == (None, "SPEC_CHANGED")
    assert perf_value(_h3d("MAX", component="vonMises"), m) == (None, "SPEC_CHANGED")
    # 요청 파일 없음(옛 run) → 비교 생략
    assert perf_value(_h3d("MAX", subcase=2), RunMetrics(curve=None, resp=RESP, requests=None)) == (150.0, None)
    # 요청 파일에 이름이 없으면 비교 없이 값(없으면 NO_VALUE)
    assert perf_value(_h3d("MAX"), RunMetrics(curve=None, resp=RESP, requests={})) == (150.0, None)
    assert perf_value(_h3d("MAX"), RunMetrics(curve=None, resp=None, requests=None)) == (None, "NOT_EXTRACTED")
    assert perf_value(_h3d("MAX"), RunMetrics(curve=None, resp={"Other_MAX": 1.0}, requests=None)) == (None, "NO_VALUE")
    assert perf_value(_h3d("ABSMAX"), RunMetrics(curve=None, resp={"CornerStress_MAX": 1.0}, requests=None)) == (None, "NO_VALUE")
    assert perf_label(_h3d("MAX")) == "CornerStress (MAX)"


def test_v3_s17_3_perf_value_curve_golden():
    m = RunMetrics(curve=CURVE, resp=None)
    assert perf_value(_curve("MAX", "Node 100 / X"), m) == (41.0, None)
    assert perf_value(_curve("MIN", "Node 100 / X"), m) == (-55.0, None)
    assert perf_value(_curve("ABSMAX", "Node 100 / X"), m) == (55.0, None)
    assert perf_value(_curve("MAX", None), m) == (41.0, None)          # null = 첫 계열
    assert perf_value(_curve("MAX", "Node 300"), m) == (None, "SERIES_MISSING")
    assert perf_value(_curve("MAX"), RunMetrics(curve=None, resp=None)) == (None, "NO_CURVE")
    assert perf_value(_curve("MAX"), RunMetrics(curve={}, resp=None)) == (None, "SERIES_MISSING")
    assert perf_label(_curve("ABSMAX", "Node 100 / X")) == "AccelPeak (커브 |최대|, Node 100 / X)"
    assert perf_label(_curve("MIN")) == "AccelPeak (커브 최소)"


def test_v3_s17_3_perf_defs_and_metric_value():
    rows = [{"name": "CornerStress", "unit": "MPa", "spec": H3D}, {"name": "Disp", "unit": "mm", "spec": None},
            {"name": "AccelPeak", "unit": "g", "spec": {"source": "CURVE", "series": None, "stat": "ABSMAX"}}]
    defs = perf_defs(rows)
    assert list(defs) == ["CornerStress", "AccelPeak"] and defs["AccelPeak"].source == "CURVE"
    m = RunMetrics(curve=CURVE, resp=RESP, requests=REQ_OK)
    assert metric_value(m, "perf:CornerStress", series=None, table=None, perfs=defs) == 150.0
    assert metric_value(m, "perf:AccelPeak", series=None, table=None, perfs=defs) == 55.0
    assert metric_value(m, "perf:CornerStress", series=None, table=None) is None      # perfs 없음
    assert metric_value(m, "perf:Disp", series=None, table=None, perfs=defs) is None  # spec null
    assert metric_value(m, "perf:cornerstress", series=None, table=None, perfs=defs) is None  # 대소문자 정확히


@pytest.mark.parametrize("mid,ok", [("perf:CornerStress", True), ("perf:A", True), ("perf:A_1", True),
                                    ("perf:" + "A" * 64, True), ("perf:" + "A" * 65, False), ("perf:1A", False),
                                    ("perf:_A", False), ("perf:응력", False), ("perf:", False), ("perf:A ", False),
                                    ("perf:A-B", False), ("perf:Ａ", False), ("xperf:A", False), ("perf:A\n", False)])
def test_v3_s17_3_metric_re_perf(mid, ok):
    assert bool(METRIC_RE.fullmatch(mid)) is ok


def _write_requests(folder: Path, lines: list[str]) -> None:
    (folder / REQUESTS_FILE).write_text("# h\n# NAME|SUBCASE|DATATYPE|COMPONENT|LAYER\n" + "\n".join(lines) + "\n",
                                        encoding="utf-8")


def test_v3_s17_3_requests_in_lru_and_reread_on_mtime(tmp_path):
    rd = tmp_path / "RESULT"
    rd.mkdir()
    (rd / RESPONSES_FILE).write_text("# r\nRESP:CornerStress_MIN=-1.0\nRESP:CornerStress_MAX=2.0\n", encoding="utf-8")
    _write_requests(rd, ["CornerStress|1|CornerStress||"])
    files = RunFiles(curve_json=None, result_dir=str(rd))
    m = rm.load_run_metrics(files, max_bytes=10**6)
    assert m.requests == {"CornerStress": ("1", "CornerStress", "", "")}
    assert perf_value(_h3d(), m) == (2.0, None)
    before = rm.cache_info()["misses"]
    rm.load_run_metrics(files, max_bytes=10**6)
    assert rm.cache_info()["misses"] == before  # 다시 읽지 않음
    _write_requests(rd, ["CornerStress|2|CornerStress||"])
    st = os.stat(rd / REQUESTS_FILE)
    os.utime(rd / REQUESTS_FILE, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    m2 = rm.load_run_metrics(files, max_bytes=10**6)
    assert m2.requests == {"CornerStress": ("2", "CornerStress", "", "")}
    assert perf_value(_h3d(), m2) == (None, "SPEC_CHANGED")
    os.remove(rd / REQUESTS_FILE)
    assert rm.load_run_metrics(files, max_bytes=10**6).requests is None


def test_v3_s17_3_parse_requests_roundtrip():
    reqs, _ = build_requests([{"name": "A", "spec": H3D}, {"name": "B", "spec": {**H3D, "component": "Mag", "subcase": 3}}])
    parsed = parse_requests_text(requests_text(reqs))
    assert parsed == {"A": ("1", "CornerStress", "", ""), "B": ("3", "CornerStress", "Mag", "")}
    assert parse_requests_text("﻿# x\n\nA|1|S||\nA|2|S||\nbad|line\n") == {"A": ("1", "S", "", "")}


# ---- V3-S17-5 pareto 골든 ------------------------------------------------------------------------------------------


def test_v3_s17_5_nondominated_order_and_duplicates():
    pts = [(1, 5), (2, 2), (1, 5), (3, 1), (2, 3), (0.5, 9), (2, 2)]
    assert pareto.nondominated(pts) == [0, 1, 3, 5]
    assert pareto.dominates((1, 1), (1, 2)) and not pareto.dominates((1, 1), (1, 1)) and not pareto.dominates((0, 2), (1, 1))
    assert pareto.nondominated([]) == []


def test_v3_s17_5_hv_golden():
    assert abs(pareto.hypervolume([(0.2, 0.8), (0.5, 0.5), (0.8, 0.2)], (1, 1)) - 0.37) <= 1e-12
    assert abs(pareto.hypervolume([(0.2, 0.6, 0.6), (0.6, 0.2, 0.6), (0.6, 0.6, 0.2)], (1, 1, 1)) - 0.256) <= 1e-12
    # 기준점 밖·지배된 점 무시
    base = [(0.2, 0.8), (0.5, 0.5), (0.8, 0.2)]
    assert abs(pareto.hypervolume([*base, (0.6, 0.6), (1.0, 0.1), (1.2, 0.0), (0.5, 0.5)], (1, 1)) - 0.37) <= 1e-12
    assert pareto.hypervolume([(1.0, 0.0)], (1, 1)) == 0.0 and pareto.hypervolume([], (1, 1)) == 0.0
    with pytest.raises(ValueError):
        pareto.hypervolume([(0, 0, 0, 0)], (1, 1, 1, 1))


def _hv_incl_excl(pts, ref):
    """포함–배제 직접 계산: Σ_{S≠∅} (−1)^{|S|+1} Π_i (R_i − max_{p∈S} p_i)."""
    total = 0.0
    for k in range(1, len(pts) + 1):
        for sub in itertools.combinations(pts, k):
            vol = 1.0
            for i in range(len(ref)):
                vol *= max(0.0, ref[i] - max(p[i] for p in sub))
            total += (-1) ** (k + 1) * vol
    return total


def test_v3_s17_5_random_3d_matches_inclusion_exclusion_and_hvi():
    rng = random.Random(7)
    for _ in range(20):
        pts = [tuple(rng.random() for _ in range(3)) for _ in range(5)]
        ref = (1.1, 1.0, 1.2)
        assert abs(pareto.hypervolume(pts, ref) - _hv_incl_excl(pts, ref)) <= 1e-12
        p = tuple(rng.random() for _ in range(3))
        hvi = pareto.hv_improvement(pts, p, ref)
        assert abs(hvi - (_hv_incl_excl([*pts, p], ref) - _hv_incl_excl(pts, ref))) <= 1e-12 and hvi >= -1e-15
    assert pareto.hv_improvement([(0.2, 0.2)], (0.5, 0.5), (1, 1)) == 0.0


def test_v3_s17_5_normalize_frame():
    assert pareto.normalize([3.0, 10.0], [1.0, 10.0], [5.0, 10.0]) == [0.5, 0.0]  # 평평 Δ = max(1e-12, |z*|, 1) = 10
    assert pareto.frame_delta([0.0], [0.0]) == [1.0]
    assert pareto.make_frame([(1, 5), (3, 2)]) == ([1.0, 2.0], [3.0, 5.0])


# ---- V3-S17-6 해석 전선 HV --------------------------------------------------------------------------------------------


def test_v3_s17_6_zdt1_true_front_hv():
    pts = [(i / 100, 1 - math.sqrt(i / 100)) for i in range(101)]
    assert abs(pareto.hypervolume(pts, (1.1, 1.1)) - (1.21 - 1 / 3)) <= 0.01


def _sphere(h: int) -> list[tuple[float, ...]]:
    pts = []
    for i in range(h + 1):
        for j in range(h + 1 - i):
            w = (i / h, j / h, (h - i - j) / h)
            n = math.sqrt(sum(x * x for x in w))
            pts.append(tuple(x / n for x in w))
    return pts


def test_v3_s17_6_dtlz2_sphere_front_hv():
    """231점(격자 H=20을 구면에 투영)의 정확 HV는 0.76909(몬테카를로 40만 점 0.76932로 교차 확인) — 이산 전선의 계단 손실로
    해석값 0.80740과 0.0383 차이(계약 ± 0.02는 231점으로 달성 불가 — 변경 메모 요청). 점을 늘리면 해석값으로 수렴한다."""
    exact = 1.331 - math.pi / 6
    pts = _sphere(20)
    assert len(pts) == 231
    hv = pareto.hypervolume(pts, (1.1, 1.1, 1.1))
    assert abs(hv - 0.7690864406541024) <= 1e-9 and abs(hv - exact) <= 0.04
    hvs = [pareto.hypervolume(_sphere(h), (1.1, 1.1, 1.1)) for h in (20, 40, 100)]
    assert hvs[0] < hvs[1] < hvs[2] < exact and abs(hvs[2] - exact) <= 0.01


# ---- V3-S17-10 가중 추천 골든(프런트 pareto.ts와 같은 표) ----------------------------------------------------------------


def _golden():
    return json.loads((DATA / "s17_recommend.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _golden()["cases"], ids=lambda c: c["id"])
def test_v3_s17_10_recommend_golden(case):
    g = _golden()
    front = [p["f"] for p in g["front"]]
    signs = [1.0 if s == "min" else -1.0 for s in case["senses"]]
    idx, scores = pareto.recommend(front, signs, case["weights"])
    assert g["front"][idx]["key"] == case["recommended"]
    for s, want in zip(scores, case["scores"]):
        assert abs(s - want) <= 5e-5


def test_v3_s17_10_ties_and_predicted_scores():
    # 동점: S 같으면 g₁ 작은 쪽 → 앞 인덱스
    idx, s = pareto.recommend([[0, 1], [1, 0]], [1, 1], [1, 1])
    assert s == [0.5, 0.5] and idx == 0
    idx, _ = pareto.recommend([[1, 0], [0, 1]], [1, 1], [1, 1])
    assert idx == 1  # g₁ 작은 쪽
    idx, _ = pareto.recommend([[2, 2], [2, 2]], [1, 1], [1, 1])
    assert idx == 0  # 평평 → g=0, 앞 인덱스
    # 예측 점: 같은 lo·hi, 0~1 밖 허용(추천 대상 아님)
    front = [p["f"] for p in _golden()["front"]]
    lo, hi = pareto.front_scale(front)
    sc, gs = pareto.weighted_scores([[0.0, 12.0]], lo, hi, [1, 1], [50, 50])
    assert gs[0][0] < 0 and gs[0][1] > 1 and abs(sc[0] - 0.5 * (-1 / 9 + 11 / 8)) <= 1e-12
    with pytest.raises(ValueError):
        pareto.recommend([], [1, 1], [1, 1])
