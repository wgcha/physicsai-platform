"""④ 일괄 예측 설계공간 지도 API(phase3 §17.4 S12, D3-59): V3-S12-2.

GET /predict-batches/{bid}/design-map — 모양, 실패·미완료 run null, metrics 목록 규칙(계열 없음 → curve 없음, resp 사전순·단위,
tbl 조건), counts, 권한(401·member 200), 404, 큰 curve.json 무시, 캐시(두 번째 호출은 파일을 다시 읽지 않음·바뀌면 다시),
경로 안전(Study 밖·링크 curve 무시).
"""

from __future__ import annotations

import json
from pathlib import Path

from physicsai_core.stage4_predict import run_metrics as rm
from physicsai_test_support import API, H
from test_api_predict_batch import P, _batch, _client, _end, _gen_done, _setup

TABLE5 = "THK_1,N_RIB\n3.0,4\n2.5,5\n4.0,7\n3.5,6\n2.2,3\n"
RESP1 = "# RESPONSES.txt\nRESP:MaxStress_MIN=1.0e+00\nRESP:MaxStress_MAX=1.523e+02\nRESP:Disp=NO_VALUE\n"
RESP3 = "RESP:Disp_MAX=4.5\nRESP:MaxStress=OPEN_ERROR\nRESP:응력_MAX=3\n"


def _artifact(engine, sid: str, job_id: str, rel: str, size: int = 1) -> str:
    from physicsai_core.db.repositories import artifacts as artifacts_repo

    with engine.begin() as conn:
        return artifacts_repo.insert(conn, study_id=sid, job_id=job_id, kind="CURVE_JSON", rel_path=rel, size=size,
                                     sha256=None, content_type="application/json")


def _finish(engine, ai: Path, folder: str, sid: str, kid: dict, *, series: list[dict] | None = None,
            resp_text: str | None = None, table: list[dict] | None = None, curve_rel: str | None = None) -> Path:
    """하위 PREDICT 성공 흉내: run 폴더 P/curve.json(+artifact), P/RESULT/RESPONSES.txt, result.pred_h3d_rel."""
    run_dir = Path(kid["params"]["input_path"]).parent  # …/run__0000N/m_3 → run 폴더
    rel_run = run_dir.relative_to(ai / folder).as_posix()
    res = run_dir / "P" / "RESULT"
    res.mkdir(parents=True, exist_ok=True)
    result: dict = {"pred_h3d_rel": f"{rel_run}/P/RESULT/x_pred.h3d"}
    if series is not None:
        cp = run_dir / "P" / "curve.json"
        cp.write_text(json.dumps({"file": "a.xy", "series": series, "note": ""}), encoding="utf-8")
        result["curve_artifact_id"] = _artifact(engine, sid, kid["id"], curve_rel or f"{rel_run}/P/curve.json")
    elif curve_rel is not None:
        result["curve_artifact_id"] = _artifact(engine, sid, kid["id"], curve_rel)
    if resp_text is not None:
        (res / "RESPONSES.txt").write_text(resp_text, encoding="utf-8")
    if table is not None:
        result["response_table"] = table
    _end(engine, kid["id"], "SUCCEEDED", result)
    return run_dir


def test_v3_s12_2_design_map_shape_rules_cache(settings_dict, engine, fake_dashboard, worker_factory):
    rm.cache_clear()
    with _client(settings_dict, engine, fake_dashboard) as (c, lc):
        ai = Path(lc.settings.storage.ai_root)
        sid, _mid, _ps = _setup(c, worker_factory(), ai, "DM")
        job = _batch(c, sid, {"kind": "table", "text": TABLE5})
        assert job.status_code == 201, job.text
        bid = job.json()["params"]["batch_id"]
        kids = _gen_done(engine, ai, "DM", bid, failed=(2,))          # doe 2 생성 실패 → 하위 1,3,4,5
        k1, k3, k4, k5 = kids
        run1 = _finish(engine, ai, "DM", sid, k1, series=[
            {"name": "Node 100 / X", "x": [0, 0.012, 0.02], "y": [0.0, 152.3, -3.1]},
            {"name": "Node 200 / Z", "x": [0, 1], "y": [1.0, 2.0]}],
            resp_text=RESP1, table=[{"name": "MaxStress", "unit": "MPa", "predicted": 151.9}, {"name": "Disp", "predicted": None}])
        _finish(engine, ai, "DM", sid, k3, series=[{"name": "Node 300", "x": [0, 1], "y": [-8.0, 2.0]},
                                                  {"name": "Node 100 / X", "x": [0, 1], "y": [5.0, 6.0]}], resp_text=RESP3)
        _end(engine, k4["id"], "FAILED", failure_code="EXIT_NONZERO")
        _finish(engine, ai, "DM", sid, k5)                                # 커브·RESPONSES 없음

        assert c.get(f"{API}/predict-batches/{bid}/design-map").status_code == 401
        r = c.get(f"{API}/predict-batches/{bid}/design-map", headers=H("tok-general"))  # member 조회
        assert r.status_code == 200, r.text
        assert r.headers["cache-control"] == "no-store"
        d = r.json()
        assert (d["batch_id"], d["label"], d["status"]) == (bid, "B-001", "DONE")
        assert d["parameters"] == [{"name": "THK_1", "integer": False, "min": 2.0, "max": 5.0},
                                   {"name": "N_RIB", "integer": True, "min": 2.0, "max": 8.0}]
        assert d["series"] == ["Node 100 / X", "Node 200 / Z", "Node 300"]  # 첫 등장 순(doe_no 순 순회)
        assert d["metrics"] == [
            {"id": "curve:max", "label": "커브 최대값", "unit": None, "needs_series": True},
            {"id": "curve:min", "label": "커브 최소값", "unit": None, "needs_series": True},
            {"id": "curve:absmax", "label": "커브 |최대|", "unit": None, "needs_series": True},
            {"id": "resp:Disp_MAX", "label": "Disp 최대(RESP)", "unit": "mm", "needs_series": False},
            {"id": "resp:MaxStress_MAX", "label": "MaxStress 최대(RESP)", "unit": "MPa", "needs_series": False},
            {"id": "resp:MaxStress_MIN", "label": "MaxStress 최소(RESP)", "unit": "MPa", "needs_series": False},
        ]  # resp 사전순, RESPONSES.txt가 있으므로 tbl 없음, 비ASCII 키 제외
        assert d["counts"] == {"total": 5, "succeeded": 3, "no_curve": 1, "no_resp": 1}
        runs = {x["doe_no"]: x for x in d["runs"]}
        assert [x["doe_no"] for x in d["runs"]] == [1, 2, 3, 4, 5]
        assert runs[1]["state"] == "SUCCEEDED" and runs[1]["run_key"] == "run__00001"
        assert runs[1]["values"] == {"THK_1": 3.0, "N_RIB": 4.0}
        assert runs[1]["curve"]["Node 100 / X"] == {"max": 152.3, "min": -3.1, "absmax": 152.3, "x_at_max": 0.012,
                                                    "x_at_min": 0.02, "n": 3}
        assert runs[1]["resp"] == {"MaxStress_MIN": 1.0, "MaxStress_MAX": 152.3}
        assert runs[1]["tbl"] == {"MaxStress": 151.9, "Disp": None}
        assert runs[3]["resp"] == {"Disp_MAX": 4.5}
        for n, st in ((2, "GEN_FAILED"), (4, "FAILED")):
            assert runs[n]["state"] == st and (runs[n]["curve"], runs[n]["resp"], runs[n]["tbl"]) == (None, None, None)
        assert runs[2]["values"] == {"THK_1": 2.5, "N_RIB": 5.0}
        assert runs[5]["state"] == "SUCCEEDED" and runs[5]["curve"] is None and runs[5]["resp"] is None

        # 캐시: 두 번째 호출은 파일을 읽지 않는다, 파일이 바뀌면 다시 읽는다
        misses = rm.cache_info()["misses"]
        assert c.get(f"{API}/predict-batches/{bid}/design-map", headers=P).json() == d
        assert rm.cache_info()["misses"] == misses
        cp = run1 / "P" / "curve.json"
        cp.write_text(json.dumps({"file": "a.xy", "series": [{"name": "Node 100 / X", "x": [0, 1], "y": [0.0, 999.5]}],
                                  "note": ""}), encoding="utf-8")
        d2 = c.get(f"{API}/predict-batches/{bid}/design-map", headers=P).json()
        assert d2["runs"][0]["curve"] == {"Node 100 / X": {"max": 999.5, "min": 0.0, "absmax": 999.5, "x_at_max": 1.0,
                                                           "x_at_min": 0.0, "n": 2}}
        assert rm.cache_info()["misses"] == misses + 1

        r = c.get(f"{API}/predict-batches/00000000-0000-0000-0000-000000000000/design-map", headers=P)
        assert r.status_code == 404 and r.json()["detail"]["code"] == "BATCH_NOT_FOUND"


def test_v3_s12_2_design_map_tbl_only_no_series_big_and_unsafe(settings_dict, engine, fake_dashboard, worker_factory):
    rm.cache_clear()
    with _client(settings_dict, engine, fake_dashboard, ui={"max_artifact_bytes": 400}) as (c, lc):
        ai = Path(lc.settings.storage.ai_root)
        sid, _mid, _ps = _setup(c, worker_factory(), ai, "DT")
        bid = _batch(c, sid, {"kind": "table", "text": "THK_1,N_RIB\n3,4\n4,5\n2,6\n"}).json()["params"]["batch_id"]
        k1, k2, k3 = _gen_done(engine, ai, "DT", bid)
        table = [{"name": "MaxStress", "unit": "MPa", "predicted": 120.0}, {"name": "Disp", "predicted": None}]
        # 큰 curve.json(> ui.max_artifact_bytes) → 커브 없음
        big = [{"name": "Big", "x": list(range(200)), "y": list(range(200))}]
        _finish(engine, ai, "DT", sid, k1, series=big, table=table)
        # Study 밖 경로 artifact → 무시
        outside = ai / "secret.json"
        outside.write_text(json.dumps({"series": [{"name": "Out", "x": [0], "y": [1]}]}), encoding="utf-8")
        _finish(engine, ai, "DT", sid, k2, curve_rel="../secret.json", table=table)
        # 링크 curve.json → 무시
        link_rel = "04_batch/B-001/run__00003/P/link.json"
        (ai / "DT" / "04_batch" / "B-001" / "run__00003" / "P").mkdir(parents=True, exist_ok=True)
        (ai / "DT" / link_rel).symlink_to(outside)
        _finish(engine, ai, "DT", sid, k3, curve_rel=link_rel, table=[{"name": "MaxStress", "predicted": 130.0}])
        d = c.get(f"{API}/predict-batches/{bid}/design-map", headers=P).json()
        assert d["series"] == [] and [x["curve"] for x in d["runs"]] == [None, None, None]
        # 계열 없음 → curve 지표 없음, RESPONSES.txt 없음 → tbl(값 있는 응답만, 템플릿 순서·단위)
        assert d["metrics"] == [{"id": "tbl:MaxStress", "label": "MaxStress(결과 표)", "unit": "MPa", "needs_series": False}]
        assert d["counts"] == {"total": 3, "succeeded": 3, "no_curve": 3, "no_resp": 3}
        assert [x["tbl"]["MaxStress"] for x in d["runs"]] == [120.0, 120.0, 130.0]
        # 진행 중(하위가 대기) 배치: 성공 run 없음 → 지표 없음, 행은 전부
        bid2 = _batch(c, sid, {"kind": "table", "text": "THK_1,N_RIB\n3,4\n"}).json()
        assert bid2.get("params"), bid2  # 같은 Study 두 번째 배치(첫 배치 DONE)
        d = c.get(f"{API}/predict-batches/{bid2['params']['batch_id']}/design-map", headers=P).json()
        assert d["metrics"] == [] and d["series"] == [] and d["counts"]["succeeded"] == 0
        assert [(x["state"], x["curve"]) for x in d["runs"]] == [("GEN_PENDING", None)]
