"""④ 설계공간 지도 `perf:` 서버 계산(phase3 §24.5 S19, D3-67 Q11·Q12): V3-S19-12.

H3D·CURVE 값 = `performance.perf_value`, SPEC_CHANGED → null + `perf_reason` + `metrics[].spec_changed` + `counts.spec_changed`
+ `reason_text`, NOT_EXTRACTED + 결과 표 값 → 표 값(H3D만, CURVE는 대체 없음), 성공 아닌 run null, 지표 순서(curve → resp →
perf 템플릿 순)·값 없는 성능 제외, 파일 추가 읽기 0(LRU `cache_info`), 기존 지표 키 불변(perf 아닌 지표에 spec_changed 없음).
"""

from __future__ import annotations

from pathlib import Path

from helpers_api import PW
from physicsai_core.stage4_predict import performance as perf
from physicsai_core.stage4_predict import run_metrics as rm
from physicsai_core.stage4_predict.responses import REASON_TEXT, h3d_request, requests_text
from physicsai_test_support import API
from test_api_predict_batch import P, _batch, _client, _end, _gen_done, _setup
from test_design_map_api import TABLE5, _finish

H3D = {"source": "H3D", "subcase": 1, "datatype": "CornerStress", "component": "", "layer": "", "stat": "MAX"}
CURVE = {"source": "CURVE", "series": "Node 100 / X", "stat": "ABSMAX"}
NEVER = {**H3D, "datatype": "Nope"}
ROWS = [{"name": "MaxStress", "unit": "MPa", "spec": None}, {"name": "Disp", "unit": "mm", "spec": None},
        {"name": "Accel", "unit": "g", "spec": CURVE}, {"name": "Never", "unit": "", "spec": NEVER},
        {"name": "Corner", "unit": "MPa", "spec": H3D}]
RESP = "RESP:Corner_MIN=-2.0e+01\nRESP:Corner_MAX=1.0e+01\n"


def _requests(run_dir: Path, spec: dict) -> None:
    req, why = h3d_request({"name": "Corner", "spec": spec})
    assert req is not None, why
    (run_dir / "P" / "RESULT" / "H3D_REQUESTS.txt").write_text(requests_text([req]), encoding="utf-8")


def test_v3_s19_12_design_map_perf(settings_dict, engine, fake_dashboard, worker_factory):
    rm.cache_clear()
    with _client(settings_dict, engine, fake_dashboard) as (c, lc):
        ai = Path(lc.settings.storage.ai_root)
        sid, _mid, ps = _setup(c, worker_factory(), ai, "DP")
        r = c.put(f"{API}/param-sets/{ps['id']}/responses", headers=PW, json={"responses": ROWS})
        assert r.status_code == 200, r.text
        bid = _batch(c, sid, {"kind": "table", "text": TABLE5}).json()["params"]["batch_id"]
        k1, k3, k4, k5 = _gen_done(engine, ai, "DP", bid, failed=(2,))
        run1 = _finish(engine, ai, "DP", sid, k1, series=[{"name": "Node 100 / X", "x": [0, 1, 2], "y": [0.0, 152.3, -3.1]}],
                       resp_text=RESP, table=[{"name": "Corner", "predicted": 99.0}])
        _requests(run1, H3D)                                                    # 정의와 같은 요청 → 값
        run3 = _finish(engine, ai, "DP", sid, k3, series=[{"name": "Node 300", "x": [0, 1], "y": [1.0, 2.0]}], resp_text=RESP)
        _requests(run3, {**H3D, "datatype": "Stress"})                          # 추출 뒤 정의 변경 → SPEC_CHANGED
        _end(engine, k4["id"], "FAILED", failure_code="EXIT_NONZERO")
        _finish(engine, ai, "DP", sid, k5, table=[{"name": "Corner", "predicted": 7.5}, {"name": "Accel", "predicted": 9.9}])

        d = c.get(f"{API}/predict-batches/{bid}/design-map", headers=P).json()
        # 지표: curve → resp → perf(템플릿 순, 값 없는 Never 제외), perf 아닌 지표에는 spec_changed 키 없음
        assert [m["id"] for m in d["metrics"]] == ["curve:max", "curve:min", "curve:absmax", "resp:Corner_MAX",
                                                   "resp:Corner_MIN", "perf:Accel", "perf:Corner"]
        assert all("spec_changed" not in m for m in d["metrics"][:5])
        assert d["metrics"][5:] == [
            {"id": "perf:Accel", "label": "Accel (커브 |최대|, Node 100 / X)", "unit": "g", "needs_series": False,
             "spec_changed": 0},
            {"id": "perf:Corner", "label": "Corner (MAX)", "unit": "MPa", "needs_series": False, "spec_changed": 1},
        ]
        assert d["counts"] == {"total": 5, "succeeded": 3, "no_curve": 1, "no_resp": 1, "spec_changed": 1}
        runs = {x["doe_no"]: x for x in d["runs"]}
        # run 1: CURVE absmax·H3D MAX(결과 표 99.0이 있어도 RESPONSES.txt 값), 값 없는 성능은 사유
        assert runs[1]["perf"] == {"Accel": 152.3, "Never": None, "Corner": 10.0}
        assert runs[1]["perf_reason"] == {"Never": "NO_VALUE"}
        # run 3: 계열 없음·정의 변경
        assert runs[3]["perf"] == {"Accel": None, "Never": None, "Corner": None}
        assert runs[3]["perf_reason"] == {"Accel": "SERIES_MISSING", "Never": "NO_VALUE", "Corner": "SPEC_CHANGED"}
        # run 5: 옛 추출 run — H3D만 결과 표 값으로 대체, CURVE는 대체 없음, 표 값 없는 H3D는 NOT_EXTRACTED
        assert runs[5]["perf"] == {"Accel": None, "Never": None, "Corner": 7.5}
        assert runs[5]["perf_reason"] == {"Accel": "NO_CURVE", "Never": "NOT_EXTRACTED"}
        for n in (2, 4):                                                        # 성공 아닌 run
            assert runs[n]["state"] != "SUCCEEDED" and (runs[n]["perf"], runs[n]["perf_reason"]) == (None, None)
        assert d["reason_text"] == {k: REASON_TEXT[k] for k in
                                    ("NOT_EXTRACTED", "NO_CURVE", "NO_VALUE", "SERIES_MISSING", "SPEC_CHANGED")}
        # 기존 키·값 불변(S12)
        assert runs[1]["resp"] == {"Corner_MIN": -20.0, "Corner_MAX": 10.0} and runs[5]["tbl"]["Corner"] == 7.5

        # 파일 추가 읽기 0: 첫 호출 읽기 = 있는 파일 수(run1·run3의 curve·RESPONSES·H3D_REQUESTS), 두 번째는 전부 캐시
        info = rm.cache_info()
        assert info["misses"] == 6
        assert c.get(f"{API}/predict-batches/{bid}/design-map", headers=P).json() == d
        info2 = rm.cache_info()
        assert (info2["misses"], info2["hits"] - info["hits"]) == (6, 6)

        # 값 = performance.perf_value(같은 RunMetrics)
        files = rm.RunFiles(curve_json=str(run1 / "P" / "curve.json"), result_dir=str(run1 / "P" / "RESULT"))
        m = rm.load_run_metrics(files, max_bytes=lc.settings.ui.max_artifact_bytes)
        defs = perf.perf_defs(ROWS)
        assert {k: perf.perf_value(v, m)[0] for k, v in defs.items()} == runs[1]["perf"]


def test_v3_s19_12_design_map_no_perf_keeps_shape(settings_dict, engine, fake_dashboard, worker_factory):
    """성능 정의 없음 → perf 지표 없음, counts에 spec_changed 없음(기본 0), 성공 run perf = {}, reason_text = {}."""
    rm.cache_clear()
    with _client(settings_dict, engine, fake_dashboard) as (c, lc):
        ai = Path(lc.settings.storage.ai_root)
        sid, _mid, ps = _setup(c, worker_factory(), ai, "DN")
        assert c.put(f"{API}/param-sets/{ps['id']}/responses", headers=PW, json={"responses": ROWS[:2]}).status_code == 200
        bid = _batch(c, sid, {"kind": "table", "text": "THK_1,N_RIB\n3,4\n"}).json()["params"]["batch_id"]
        (k1,) = _gen_done(engine, ai, "DN", bid)
        _finish(engine, ai, "DN", sid, k1, table=[{"name": "MaxStress", "predicted": 120.0}])
        d = c.get(f"{API}/predict-batches/{bid}/design-map", headers=P).json()
        assert d["metrics"] == [{"id": "tbl:MaxStress", "label": "MaxStress(결과 표)", "unit": "MPa", "needs_series": False}]
        assert d["counts"] == {"total": 1, "succeeded": 1, "no_curve": 1, "no_resp": 1}
        assert (d["runs"][0]["perf"], d["runs"][0]["perf_reason"], d["reason_text"]) == ({}, {}, {})
