"""V3-S17-9(표준 라이브러리 부분): 다목적 자료 모델 — Problem(objectives·observe·weights, 0014 이전 settings 호환), Point 유효성
(관찰 값 없음은 영향 없음, 목적·제약 모두 필요), range 위반량, HV 틀(만족 ≥ 2면 만족 설계)·HV·개선율(HV_{t−1}=0 → None),
가중 추천 설계, dataset.csv 열(단일 = 기존 그대로, 다목적 objective_1..m·obs:·reason)과 왕복."""

from __future__ import annotations

from physicsai_core.stage5_optimize.surrogate import dataset as ds

BASE = {"names": ["A", "B"], "integer": [], "bounds": {"A": [0, 1], "B": [0, 1]}, "surrogate": "gp", "iterations": 2,
        "candidates": 2, "tol_rel": 0.01, "seed": 1}


def _multi(**kw):
    s = {**BASE, "objective": {"metric": "perf:F1", "series": None, "sense": "min"},
         "objectives": [{"metric": "perf:F1", "series": None, "sense": "min"},
                        {"metric": "perf:F2", "series": None, "sense": "max"}],
         "constraints": [{"metric": "perf:G", "series": None, "op": "range", "value": None, "lo": 0.0, "hi": 10.0}],
         "observe": [{"metric": "perf:O", "series": None}], "weights": [0.25, 0.75]}
    s.update(kw)
    return ds.Problem.from_settings(s)


def _pt(no, vals, objs, cons, obs=None, it=0, state="SUCCEEDED"):
    return ds.Point(it, "B-001", no, f"run__{no:05d}", vals, objs[0], cons, state, objectives=objs,
                    observed=obs or {}, reasons={"perf:O": "NO_VALUE"} if obs is None else {})


def test_v3_s17_9_problem_from_settings_and_legacy():
    p = _multi()
    assert p.multi and p.m == 2 and p.signs() == [1.0, -1.0] and p.sense == "min" and p.weights == [0.25, 0.75]
    assert p.constraints[0].op == "range" and p.constraints[0].lo == 0.0 and p.observe[0].key == "perf:O"
    legacy = ds.Problem.from_settings({**BASE, "objective": {"metric": "curve:max", "series": "S", "sense": "max"},
                                       "constraints": [{"metric": "curve:min", "series": None, "op": ">=", "value": 1.0}]})
    assert not legacy.multi and legacy.objectives[0].key == "curve:max@S" and legacy.weights == [1.0]
    assert legacy.constraints[0].value == 1.0 and legacy.constraints[0].violation(0.5) == 0.5


def test_v3_s17_9_point_validity_and_merge():
    p = _multi()
    a = _pt(1, {"A": 0.1, "B": 0.2}, [1.0, 5.0], [3.0])            # 관찰 값 없음 → 그래도 유효
    b = _pt(2, {"A": 0.1, "B": 0.2}, [3.0, 7.0], [5.0], {"perf:O": 2.0})
    c = _pt(3, {"A": 0.9, "B": 0.2}, [2.0, None], [1.0])          # 목적 하나 없음 → 무효
    d = _pt(4, {"A": 0.5, "B": 0.5}, [2.0, 1.0], [None])          # 제약 없음 → 무효
    assert a.valid and b.valid and not c.valid and not d.valid and a.key == "0:1"
    designs, failed = ds.merge([a, b, c, d], p)
    assert len(designs) == 1 and designs[0].objectives == [2.0, 6.0] and designs[0].objective == 2.0
    assert designs[0].constraints == [4.0] and len(failed) == 2


def test_v3_s17_9_hv_frame_hv_and_improvement():
    p = _multi()
    pts = [_pt(1, {"A": 0.0, "B": 0.0}, [1.0, 9.0], [5.0]), _pt(2, {"A": 0.5, "B": 0.0}, [3.0, 4.0], [5.0]),
           _pt(3, {"A": 1.0, "B": 0.0}, [6.0, 2.0], [50.0])]         # 3은 위반 → 틀은 만족 2개로
    designs, _ = ds.merge(pts, p)
    frame = ds.make_hv_frame(designs, p, 0.1)
    assert frame == {"ideal": [1.0, -9.0], "nadir": [3.0, -4.0], "ref_offset": 0.1, "signs": [1.0, -1.0]}
    hv, size = ds.hv_value(designs, p, frame)
    # 만족 2점 정규화: (0, 0)·(1, 1) → (1,1)은 (0,0)에 지배 → HV = 1.1²
    assert size == 1 and abs(hv - 1.21) < 1e-12
    assert ds.hv_improvement_rel(0.0, 0.5) is None and ds.hv_improvement_rel(None, 0.5) is None
    assert abs(ds.hv_improvement_rel(0.5, 0.6) - 0.2) < 1e-12
    # 틀 밖(기준점 이상) 점뿐이면 HV 0
    far = ds.merge([_pt(1, {"A": 0, "B": 0}, [100.0, -100.0], [5.0])], p)[0]
    assert ds.hv_value(far, p, frame) == (0.0, 1)
    # 만족 설계 1개면 기준 집합 = 유효 설계 전부
    one = ds.merge(pts[:1] + pts[2:], p)[0]
    assert ds.make_hv_frame(one, p, 0.1)["nadir"] == [6.0, -2.0]


def test_v3_s17_9_recommend_design_uses_signs():
    p = _multi(weights=[0.5, 0.5])
    pts = [_pt(1, {"A": 0.0, "B": 0}, [1.0, 9.0], [1.0]), _pt(2, {"A": 0.2, "B": 0}, [3.0, 4.0], [1.0]),
           _pt(3, {"A": 0.4, "B": 0}, [6.0, 2.0], [1.0]), _pt(4, {"A": 0.6, "B": 0}, [10.0, 1.0], [1.0])]
    designs, _ = ds.merge(pts, p)
    front = ds.front_designs(designs, p)
    assert len(front) == 1 and front[0].sources[0].doe_no == 1      # f2 max → A가 둘 다 최선
    idx, scores = ds.recommend_design(designs, p, [50, 50])
    assert idx == 0 and abs(scores[1] - 0.4236) < 5e-5               # §22.6 표 5행


def test_v3_s17_9_dataset_csv_columns_and_roundtrip():
    single = ds.Problem.from_settings({**BASE, "objective": {"metric": "curve:max", "series": None, "sense": "min"},
                                       "constraints": []})
    pts = [ds.Point(0, "B-001", 1, "run__00001", {"A": 0.5, "B": 0.25}, 1.5, [], "SUCCEEDED")]
    assert ds.dataset_csv(pts, single).splitlines()[0] == "iter,batch,doe_no,run_key,A,B,objective,state"
    p = _multi()
    mpts = [_pt(1, {"A": 0.5, "B": 0.25}, [1.0, 2.0], [3.0], {"perf:O": 4.0}), _pt(2, {"A": 0.1, "B": 0.2}, [None, 2.0], [3.0])]
    text = ds.dataset_csv(mpts, p, with_feasible=True)
    lines = text.splitlines()
    assert lines[0] == "iter,batch,doe_no,run_key,A,B,objective_1,objective_2,perf:G,obs:O,reason,predicted,feasible,state"
    assert lines[1] == "0,B-001,1,run__00001,0.5,0.25,1.0,2.0,3.0,4.0,,,true,SUCCEEDED"
    assert lines[2].endswith(",,2.0,3.0,,NO_VALUE,,,SUCCEEDED")
    back = ds.read_dataset_csv(ds.dataset_csv(mpts, p), p)
    assert back[0].objectives == [1.0, 2.0] and back[0].observed == {"perf:O": 4.0} and back[0].valid
    assert back[1].objectives == [None, 2.0] and not back[1].valid
    assert ds.metric_label("perf:CornerStress") == "CornerStress"
