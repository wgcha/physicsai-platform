"""일괄 예측 캡처 옵션(D3-53): 배치 params `capture{enabled, views?, video?}`가 하위 PREDICT의 CONTOUR_CAPTURE를 정한다."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text

from physicsai_test_support import API

from .test_contour_capture import PW, P, _capture_records


def _batch_first_child(env, engine, extra: dict) -> tuple[dict, dict]:
    """PREDICT_BATCH 생성 → BP_GEN·BP_ENQUEUE 흉내 → 첫 하위 PREDICT 실행. (배치 작업, 첫 하위 작업)."""
    from physicsai_core.db.repositories import predict_batches as pb_repo

    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "PREDICT_BATCH", "params": {
        "multi_execution": 1, "source": {"kind": "table", "text": "THK_1\tN_RIB\n3.0\t4\n"}, **extra}})
    assert r.status_code == 201, r.text
    job = r.json()
    bid = job["params"]["batch_id"]
    with engine.begin() as conn:
        b = pb_repo.get(conn, bid)
        for row in pb_repo.runs(conn, bid):
            pb_repo.set_run(conn, bid, row["doe_no"], gen_state="DONE")
        kids = pb_repo.enqueue_children(conn, bid, batch_dir=str(env.sroot / b["dir_rel"]))
        conn.execute(text("update jobs set state='SUCCEEDED', holds_slot=false, queue_seq=null, finished_at=now() where id=:i"),
                     {"i": b["job_id"]})
    case = Path(kids[0]["params"]["input_path"])
    case.mkdir(parents=True, exist_ok=True)
    for name, body in (("Face_Drop_0000.rad", "/BEGIN\n"), ("part.inc", "/NODE\n")):
        (case / name).write_text(body)
    with engine.begin() as conn:
        conn.execute(text("update jobs set params = params || cast(:p as jsonb) where id=:i"),
                     {"p": json.dumps({"input_kind": "dir", "starter_name": "Face_Drop_0000.rad"}), "i": kids[0]["id"]})
    assert env.w.run_once_slot() == "SUCCEEDED"
    return job, env.job(kids[0]["id"])


def test_d3_53_batch_capture_options(predict_env, fake_record, engine):
    """일괄 예측 캡처 옵션: views·video가 하위 캡처 settings에 반영, enabled false면 CONTOUR_CAPTURE SKIPPED(캡처 실행 없음)."""
    env = predict_env()
    env.param_set()
    job, kid = _batch_first_child(env, engine, {"capture": {"views": ["iso", "top"], "video": False}})
    assert job["params"]["capture"] == {"enabled": True, "views": ["iso", "top"], "video": False}
    st = _capture_records(fake_record)[-1]["settings"]
    assert (st["VIEWS"], st["SAVE_VIDEO"]) == (["iso", "top"], "0")
    cap = kid["result"]["capture"]
    assert (cap["status"], cap["views"], cap["video"]) == ("OK", ["iso", "top"], False)
    assert [m["view"] for m in kid["result"]["media"]] == ["iso", "top"] and not any(m["video_artifact_id"] for m in kid["result"]["media"])
    n = len(_capture_records(fake_record))
    job2, kid2 = _batch_first_child(env, engine, {"capture": {"enabled": False}})
    assert job2["params"]["capture"] == {"enabled": False}
    assert len(_capture_records(fake_record)) == n                                    # 캡처 프로세스 실행 없음
    assert env.steps(kid2["id"])["CONTOUR_CAPTURE"]["state"] == "SKIPPED"
    assert kid2["result"]["capture"]["status"] == "SKIPPED" and kid2["result"]["media"] == []
    m = env.c.get(f"{API}/jobs/{kid2['id']}/media", headers=P).json()
    assert (m["status"], m["items"]) == ("SKIPPED", []) and "껐습니다" in m["message"]
    # 옵션 모양 오류는 422
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "PREDICT_BATCH", "params": {
        "multi_execution": 1, "source": {"kind": "table", "text": "THK_1\tN_RIB\n3.0\t4\n"}, "capture": {"views": ["iso", "iso"]}}})
    assert r.status_code == 422, r.text
    # 기본(옵션 없음) = 저장 params에 capture 키 없음 → config 기본
    assert "capture" not in _plain_batch_params(env)


def _plain_batch_params(env) -> dict:
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "PREDICT_BATCH", "params": {
        "multi_execution": 1, "source": {"kind": "table", "text": "THK_1\tN_RIB\n3.0\t4\n"}}})
    assert r.status_code == 201, r.text
    return r.json()["params"]
