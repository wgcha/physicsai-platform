"""④ 단일 예측 실행 목록·상세 API(phase3 §21.2 S16 V1): V3-S16-1·2.

작업 행은 저장소 함수(insert_job)로 만들고 상태·결과·시각을 SQL로 맞춘다(워커 실행 없이 목록 규칙만 시험)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text

from helpers_api import P, PW, _model, _sid
from physicsai_test_support import API, H, make_param_set_folder

T0 = datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc)


def _setup(c, w, ai: Path):
    sid = _sid(c)
    mid = _model(c, w, sid, ai / "S1" / "00_inbox")
    folder = make_param_set_folder(ai / "S1" / "00_inbox")
    r = c.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(folder)})
    assert r.status_code == 201, r.text
    return sid, mid, r.json()


def _insert(engine, sid: str, job_type: str, params: dict, *, state="SUCCEEDED", result=None, minutes=0, retry_of=None,
            warnings=None, failure=None) -> str:
    from physicsai_core.db.repositories import jobs as jobs_repo
    from physicsai_core.db.repositories import studies as studies_repo

    with engine.begin() as conn:
        st = studies_repo.require(conn, sid)
        j = jobs_repo.insert_job(conn, study=st, job_type=job_type, params=params, user_id="u-power", user_name="파워",
                                 retry_of_job_id=retry_of)
        at = T0 + timedelta(minutes=minutes)
        conn.execute(text(
            "update jobs set state=cast(:s as varchar), result=cast(:r as jsonb), created_at=:a, started_at=:a, finished_at=:f,"
            " queue_seq=case when cast(:s as varchar) = 'QUEUED' then queue_seq else null end,"
            " warnings=cast(:w as jsonb), failure_code=:fc, failure_message=:fm where id=:i"),
            {"s": state, "r": json.dumps(result) if result is not None else None, "a": at,
             "f": at + timedelta(seconds=512) if state in ("SUCCEEDED", "FAILED", "CANCELED") else None,
             "w": json.dumps(warnings or []), "fc": (failure or {}).get("code") or ("TOOL_FAILED" if state == "FAILED" else None), "fm": (failure or {}).get("message"),
             "i": j["id"]})
    return j["id"]


def _tpl_params(ps_id, mid, **kw):
    return {"param_set_id": ps_id, "model_id": mid, "values": {"THK_1": 4.0, "N_RIB": 6}, "value_source": "manual", **kw}


def _tpl_result(ps_id, mid, n_resp=7):
    return {"param_set_id": ps_id, "model_id": mid, "values": {"THK_1": 4.0, "N_RIB": 6},
            "applied_values": {"THK_1": 4.0, "N_RIB": 6}, "out_of_range": [], "starter": "Face_Drop_0000.rad",
            "nearest": {"run_key": "run__00014", "distance": 0.12}, "curve_artifact_id": "a-1",
            "response_table": [{"name": f"R{i}", "unit": "MPa", "predicted": 100.0 + i, "nearest_measured": 99.0,
                                "diff_pct": 1.0} for i in range(n_resp)],
            "capture": {"status": "OK", "display": {"field": "CornerStress", "component": "vonMises", "avgmode": "",
                                                    "comps": [], "legend": {"mode": "auto", "min": None, "max": None},
                                                    "views": ["iso"]}},
            "media": [{"view": "iso", "image_artifact_id": "img-1", "video_artifact_id": None}],
            "pred_h3d_rel": "04_predict/ROOT/RESULT/EPS_mesh_0000_pred.h3d"}


def _db_counts(engine) -> tuple:
    with engine.connect() as c:
        return (tuple(c.execute(text("select count(*), max(updated_at), sum(version) from jobs")).one()),
                c.execute(text("select count(*) from audit_events")).scalar())


def test_v3_s16_1_predict_runs_list(client, worker_factory, loaded_config, engine):
    ai_root = Path(loaded_config.settings.storage.ai_root)
    sid, mid, ps = _setup(client, worker_factory(), ai_root)
    psid = ps["id"]
    old = _insert(engine, sid, "PREDICT", {"values": {"THK_1": 3}, "param_set_id": psid, "model_id": mid},  # input_mode 없는 옛 작업
                  result={"values": {"THK_1": 3.0}, "applied_values": {"THK_1": 3.0}}, minutes=1)
    a1 = _insert(engine, sid, "PREDICT", _tpl_params(psid, mid, input_mode="parametric"), state="FAILED", minutes=2,
                 failure={"code": "TOOL_FAILED", "message": "SimLab 실패"})
    a2 = _insert(engine, sid, "PREDICT", _tpl_params(psid, mid, input_mode="parametric"), result=_tpl_result(psid, mid),
                 minutes=3, retry_of=a1, warnings=[{"code": "W", "message": "m"}])
    prep = _insert(engine, sid, "PREDICT", {"input_mode": "prepared", "input_path": "E:\\cases\\A", "model_id": mid},
                   result={"starter": "Face_Drop_0000.rad", "model_id": mid}, minutes=4, state="CANCELED")
    fv = _insert(engine, sid, "PREDICT", _tpl_params(psid, mid, fem_verify_id="fv-1"), minutes=5, state="CANCELED")
    _insert(engine, sid, "PREDICT", {"input_mode": "prepared", "input_path": "/x", "batch_run": {"batch_id": "b", "doe_no": 1}},
            minutes=6)                                                                       # 일괄 하위 → 제외
    _insert(engine, sid, "MODEL_REGISTER", {"model_path": "/m"}, minutes=7)                   # 다른 유형 → 제외
    pv = _insert(engine, sid, "PREDICT_VERIFY", {"predict_job_id": a2}, minutes=8)
    before = _db_counts(engine)

    r = client.get(f"{API}/studies/{sid}/predict-runs", headers=H("tok-general"))            # 로그인 = 조회 가능
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [x["job_id"] for x in rows] == [fv, prep, a2, old] and "X-Next-Cursor" not in r.headers
    by = {x["job_id"]: x for x in rows}
    x = by[a2]
    assert (x["root_job_id"], x["attempts"], x["state"], x["origin"], x["input_mode"]) == (a1, 2, "SUCCEEDED", "manual", "template")
    assert x["template"] == {"id": psid, "label": ps.get("label"), "input_kind": "assembly"}
    assert x["model"]["id"] == mid and x["model"]["name"] == "cushion_TNS" and x["duration_s"] == 512
    assert x["values"] == {"THK_1": 4.0, "N_RIB": 6} and x["applied_values"] == {"THK_1": 4.0, "N_RIB": 6}
    assert len(x["responses"]) == 5 and x["responses"][0] == {"name": "R0", "unit": "MPa", "predicted": 100.0}
    assert x["capture"] == {"status": "OK", "views": ["iso"]} and x["has_curve"] is True and x["warnings_count"] == 1
    assert x["verify"] == {"job_id": pv, "state": "SUCCEEDED"} and x["failure"] is None and x["starter"] == "Face_Drop_0000.rad"
    assert by[old]["input_mode"] == "template" and by[old]["attempts"] == 1 and by[old]["capture"] is None
    p = by[prep]
    assert (p["input_mode"], p["input_path"], p["starter"], p["template"], p["verify"]) == (
        "prepared", "E:\\cases\\A", "Face_Drop_0000.rad", None, None)
    assert by[fv]["origin"] == "fem_verify"

    # 필터
    g = lambda q: client.get(f"{API}/studies/{sid}/predict-runs{q}", headers=P)  # noqa: E731
    assert [x["job_id"] for x in g("?mode=template").json()] == [fv, a2, old]
    assert [x["job_id"] for x in g("?mode=prepared").json()] == [prep]
    assert [x["job_id"] for x in g("?state=QUEUED,CANCELED").json()] == [fv, prep]
    for q in ("?mode=batch", "?state=DONE", "?cursor=@@@"):
        r = g(q)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS", q
    # 실패한 이전 시도만 남은 묶음: 최신 시도가 실패면 failure
    a3 = _insert(engine, sid, "PREDICT", _tpl_params(psid, mid), state="FAILED", minutes=9,
                 failure={"code": "TOOL_FAILED", "message": "x"})
    assert g("?state=FAILED").json()[0]["failure"] == {"code": "TOOL_FAILED", "message": "x"}

    # 커서: 중복·누락 없음
    seen, cur = [], None
    while True:
        r = g("?limit=2" + (f"&cursor={cur}" if cur else ""))
        assert r.status_code == 200
        seen += [x["job_id"] for x in r.json()]
        cur = r.headers.get("X-Next-Cursor")
        if not cur:
            break
    assert seen == [a3, fv, prep, a2, old]
    assert client.get(f"{API}/studies/{sid}/predict-runs").status_code == 401
    assert client.get(f"{API}/studies/{uuid.uuid4()}/predict-runs", headers=P).status_code == 404
    after = _db_counts(engine)
    assert after[1] == before[1] and after[0][0] == before[0][0] + 1                      # 조회는 DB 쓰기 0(a3 삽입만)
    assert after[0][2] == before[0][2] + 1


def test_v3_s16_2_predict_run_detail(client, worker_factory, loaded_config, engine):
    ai_root = Path(loaded_config.settings.storage.ai_root)
    sid, mid, ps = _setup(client, worker_factory(), ai_root)
    a1 = _insert(engine, sid, "PREDICT", _tpl_params(ps["id"], mid), state="FAILED", minutes=1)
    res = _tpl_result(ps["id"], mid)
    res["pred_h3d_rel"] = f"04_predict/{a1}/RESULT/EPS_mesh_0000_pred.h3d"
    a2 = _insert(engine, sid, "PREDICT", _tpl_params(ps["id"], mid), result=res, minutes=2, retry_of=a1)
    sroot = ai_root / "S1"
    pdir = sroot / "04_predict" / a1
    for d in ("INPUT", "RESULT/media"):
        (pdir / d).mkdir(parents=True)
    (pdir / "RESULT" / "EPS_mesh_0000_pred.h3d").write_bytes(b"h3d")
    r = client.get(f"{API}/predict-runs/{a2}", headers=H("tok-general"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["job_id"] == a2 and d["root_job_id"] == a1 and d["attempts"] == 2
    assert d["nearest"] == {"run_key": "run__00014", "distance": 0.12} and len(d["response_table"]) == 7
    assert d["response_table"][0] == {"name": "R0", "unit": "MPa", "predicted": 100.0, "nearest_measured": 99.0, "diff_pct": 1.0}
    assert d["display"]["field"] == "CornerStress"
    base = str(sroot / "04_predict" / a1)
    assert d["paths"] == {"dir": base, "input_dir": base + "/INPUT", "result_dir": base + "/RESULT",
                          "pred_h3d": base + "/RESULT/EPS_mesh_0000_pred.h3d", "media_dir": base + "/RESULT/media",
                          "geom_dir": None}
    # 정리로 옮겨진 폴더 → null
    (sroot / "_backup").mkdir(exist_ok=True)
    pdir.rename(sroot / "_backup" / a1)
    assert set(client.get(f"{API}/predict-runs/{a2}", headers=P).json()["paths"].values()) == {None}
    # 404
    child = _insert(engine, sid, "PREDICT", {"input_mode": "prepared", "input_path": "/x",
                                             "batch_run": {"batch_id": "b", "doe_no": 1}}, minutes=3)
    other = _insert(engine, sid, "MODEL_REGISTER", {"model_path": "/m"}, minutes=4)
    for jid, code in ((child, "NOT_PREDICT_RUN"), (other, "NOT_PREDICT_RUN"), (str(uuid.uuid4()), "JOB_NOT_FOUND")):
        r = client.get(f"{API}/predict-runs/{jid}", headers=P)
        assert r.status_code == 404 and r.json()["detail"]["code"] == code, (jid, r.text)
    assert client.get(f"{API}/predict-runs/{a2}").status_code == 401


def test_v3_s16_2_openapi_routes():
    from physicsai_api.export_openapi import build_openapi

    paths = build_openapi()["paths"]
    lst = paths["/physicsai/api/studies/{study_id}/predict-runs"]["get"]
    det = paths["/physicsai/api/predict-runs/{job_id}"]["get"]
    assert lst["operationId"] == "list_predict_runs_physicsai_api_studies__study_id__predict_runs_get"
    assert det["operationId"] == "get_predict_run_physicsai_api_predict_runs__job_id__get"
    assert {p["name"] for p in lst["parameters"]} == {"study_id", "mode", "state", "limit", "cursor"}
