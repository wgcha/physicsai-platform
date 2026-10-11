"""phase3 §5 S3 API: V3-S3-3(낡음·사전조건·권한), V3-S3-5(R3-2·R3-4), V3-S3-6(R3-5·R3-6·오류 묶음), V3-S3-8(보고서 모양)."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text

from helpers_manage import P, PW, mk_job, mk_study, put
from physicsai_core.study_storage.stale import stale_reason
from physicsai_test_support import API, H

CAT = "STUDY_CLEANUP"
NOW = datetime.now(timezone.utc)


def _scan_result(partial=False, n_pkg=1):
    items = [{"rel": f"03_package/d{i}", "bytes": 10, "files": 1, "ref_id": f"d{i}", "note": None} for i in range(n_pkg)]
    cats = [{"key": k, "label": k, "total_bytes": 10 * len(items) if k == "PACKAGE_PSDATA" else 0,
             "item_count": len(items) if k == "PACKAGE_PSDATA" else 0, "truncated": False,
             "items": items if k == "PACKAGE_PSDATA" else []}
            for k in ("PACKAGE_PSDATA", "SCORE_PREDICTIONS", "CURATED_H3D", "PREDICT_INPUT", "PREVIEW_OUTPUT", "JOB_LOGS")]
    return {"partial": partial, "total_bytes": 123, "total_files": 3, "skipped_links": 0, "errors": 0, "backup_bytes": 7,
            "backup_files": 1, "folders": [{"key": "03_package", "bytes": 116, "files": 2}, {"key": "_backup", "bytes": 7, "files": 1}],
            "top_files": [{"rel": "03_package/d0/a.psdata", "bytes": 10, "in_backup": False, "modified_at": NOW.isoformat()}],
            "categories": cats}


def _cleanup(c, sid, scan_id, cats=("PACKAGE_PSDATA",), headers=PW):
    return c.post(f"{API}/studies/{sid}/jobs", headers=headers,
                  json={"job_type": CAT, "params": {"scan_job_id": scan_id, "categories": list(cats)}})


def _code(r):
    return r.status_code, r.json()["detail"]["code"]


def test_stale_rules_unit():
    """§5.4 네 규칙(+스캔 없음)."""
    scan = {"started_at": NOW - timedelta(hours=1), "finished_at": NOW - timedelta(minutes=50)}
    kw = {"now": NOW, "stale_after_hours": 24}
    assert stale_reason(None, finished_after=0, has_active=False, **kw) == "아직 계산하지 않았습니다"
    assert stale_reason(scan, finished_after=0, has_active=False, **kw) is None
    assert stale_reason(scan, finished_after=2, has_active=False, **kw) == "스캔 뒤 작업 2개가 끝났습니다"
    assert stale_reason(scan, finished_after=0, has_active=True, **kw) == "실행 중인 작업이 있습니다"
    old = {"started_at": NOW - timedelta(hours=26), "finished_at": NOW - timedelta(hours=25)}
    assert stale_reason(old, finished_after=0, has_active=False, **kw) == "계산한 지 24시간이 지났습니다"


def test_cleanup_preconditions_and_permissions(client, engine):
    sid = mk_study(client, "ST1")
    old_scan = mk_job(engine, sid, "STUDY_STORAGE_SCAN", days_ago=0.02, result=_scan_result())
    scan = mk_job(engine, sid, "STUDY_STORAGE_SCAN", days_ago=0.01, result=_scan_result())
    # 권한: 일반 사용자 403, 조회는 가능
    r = _cleanup(client, sid, scan, headers=H("tok-general", write=True))
    assert _code(r) == (403, "PERMISSION_DENIED")
    assert client.get(f"{API}/studies/{sid}/storage", headers=H("tok-general")).status_code == 200
    r = client.post(f"{API}/studies/{sid}/jobs", headers=H("tok-general", write=True),
                    json={"job_type": "STUDY_STORAGE_SCAN", "params": {}})
    assert _code(r) == (403, "PERMISSION_DENIED")
    # params 검증(알 수 없는 키·중복·빈 목록·없는 범주)
    for bad in ({"scan_job_id": scan, "categories": ["PACKAGE_PSDATA"], "x": 1},
                {"scan_job_id": scan, "categories": ["PACKAGE_PSDATA", "PACKAGE_PSDATA"]},
                {"scan_job_id": scan, "categories": []}, {"scan_job_id": scan, "categories": ["NOPE"]}):
        r = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": CAT, "params": bad})
        assert r.status_code == 422, bad
    assert _code(client.post(f"{API}/studies/{sid}/jobs", headers=PW,
                             json={"job_type": "STUDY_STORAGE_SCAN", "params": {"x": 1}}))[0] == 422
    # 최신 아님·없는 스캔
    assert _code(_cleanup(client, sid, old_scan)) == (409, "STORAGE_SCAN_STALE")
    assert _code(_cleanup(client, sid, str(uuid.uuid4()))) == (409, "STORAGE_SCAN_STALE")
    # 옮길 항목 없음
    r = _cleanup(client, sid, scan, ("JOB_LOGS",))
    assert _code(r) == (422, "INPUT_INVALID") and r.json()["detail"]["errors"][0]["loc"] == ["params", "categories"]
    # 활성 작업 → STUDY_HAS_ACTIVE_JOB, 그 작업이 끝나면 → STORAGE_SCAN_STALE(스캔 뒤 작업 종료)
    q = mk_job(engine, sid, "MODEL_REGISTER", state="QUEUED")
    assert _code(_cleanup(client, sid, scan)) == (409, "STUDY_HAS_ACTIVE_JOB")
    with engine.begin() as c:
        c.execute(text("update jobs set state='SUCCEEDED', queue_seq=null, finished_at=now() where id=:j"), {"j": q})
    r = _cleanup(client, sid, scan)
    assert _code(r) == (409, "STORAGE_SCAN_STALE") and r.json()["detail"]["stale_reason"] == "스캔 뒤 작업 1개가 끝났습니다"
    rep = client.get(f"{API}/studies/{sid}/storage", headers=P).json()
    assert rep["stale"] is True and rep["stale_reason"] == "스캔 뒤 작업 1개가 끝났습니다"


def test_cleanup_stale_age_partial_and_success(client, engine):
    sid = mk_study(client, "ST2")
    aged = mk_job(engine, sid, "STUDY_STORAGE_SCAN", days_ago=1.1, result=_scan_result())
    r = _cleanup(client, sid, aged)
    assert _code(r) == (409, "STORAGE_SCAN_STALE") and "24시간" in r.json()["detail"]["stale_reason"]
    part = mk_job(engine, sid, "STUDY_STORAGE_SCAN", result=_scan_result(partial=True))
    r = _cleanup(client, sid, part)
    assert _code(r) == (409, "STORAGE_SCAN_PARTIAL") and "(부분 스캔)" in r.json()["detail"]["message"]
    scan = mk_job(engine, sid, "STUDY_STORAGE_SCAN", result=_scan_result())
    r = _cleanup(client, sid, scan, ("PACKAGE_PSDATA", "JOB_LOGS"))
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["params"] == {"scan_job_id": scan, "categories": ["PACKAGE_PSDATA", "JOB_LOGS"]} and j["stage"] == 0


def test_cleanup_running_blocks_other_jobs_and_retry(client, engine, loaded_config):
    """V3-S3-5 R3-4(D3-24 조정): 정리 대기·실행 중 모든 작업 생성(스캔 포함)·재시도·Final 지정 409 STUDY_CLEANUP_RUNNING.
    관리 작업 재시도 불가."""
    sid = mk_study(client, "ST3")
    failed = mk_job(engine, sid, "MODEL_REGISTER", state="FAILED")
    mk_job(engine, sid, CAT, state="QUEUED", params={"scan_job_id": "x", "categories": ["JOB_LOGS"]})
    ai = Path(loaded_config.settings.storage.ai_root)
    r = client.post(f"{API}/studies/{sid}/jobs", headers=PW,
                    json={"job_type": "MODEL_REGISTER", "params": {"model_path": str(ai / "ST3" / "00_inbox")}})
    assert _code(r) == (409, "STUDY_CLEANUP_RUNNING")
    assert _code(client.post(f"{API}/jobs/{failed}/retry", headers=PW, json={})) == (409, "STUDY_CLEANUP_RUNNING")
    assert _code(_cleanup(client, sid, str(uuid.uuid4()))) == (409, "STUDY_CLEANUP_RUNNING")
    r = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "STUDY_STORAGE_SCAN", "params": {}})
    assert _code(r) == (409, "STUDY_CLEANUP_RUNNING")
    assert _code(client.put(f"{API}/studies/{sid}/final-model", headers=PW, json={"model_id": None})) == (409, "STUDY_CLEANUP_RUNNING")
    fs = mk_job(engine, sid, "STUDY_STORAGE_SCAN", state="FAILED")
    r = client.post(f"{API}/jobs/{fs}/retry", headers=PW, json={})
    assert _code(r) == (409, "JOB_NOT_RETRYABLE") and "새로 실행" in r.json()["detail"]["message"]
    assert client.get(f"{API}/jobs/{fs}", headers=P).json()["can_retry"] is False


def test_scan_and_final_allowed_after_cleanup_ends(client, engine):
    """D3-24: 정리가 끝나면(종료 상태) 스캔·Final 지정이 다시 가능."""
    sid = mk_study(client, "ST3B")
    mk_job(engine, sid, CAT, state="FAILED", params={"scan_job_id": "x", "categories": ["JOB_LOGS"]})
    r = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "STUDY_STORAGE_SCAN", "params": {}})
    assert r.status_code == 201, r.text
    assert client.put(f"{API}/studies/{sid}/final-model", headers=PW, json={"model_id": None}).status_code == 200


def test_job_create_and_retry_lock_study_row(client, engine, monkeypatch):
    """D3-25: 작업 생성·재시도의 Study 게이트는 Study 행을 FOR UPDATE로 잠근 뒤 검사한다(동시 생성 경합 차단)."""
    from physicsai_core.db.repositories import studies as studies_repo

    sid = mk_study(client, "ST3C")
    failed = mk_job(engine, sid, "MODEL_REGISTER", state="FAILED")
    seen: list[bool] = []
    real = studies_repo.require

    def spy(conn, study_id, *, for_update=False):
        seen.append(for_update)
        return real(conn, study_id, for_update=for_update)

    monkeypatch.setattr(studies_repo, "require", spy)
    assert client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "STUDY_STORAGE_SCAN", "params": {}}).status_code == 201
    assert seen == [True]
    seen.clear()
    client.post(f"{API}/jobs/{failed}/retry", headers=PW, json={})
    assert seen and all(seen)


def test_archived_study_allows_manage_jobs(client, engine, loaded_config):
    """V3-S3-5 R3-2."""
    sid = mk_study(client, "ST4")
    scan = mk_job(engine, sid, "STUDY_STORAGE_SCAN", result=_scan_result())
    assert client.post(f"{API}/studies/{sid}/archive", headers=PW).json()["status"] == "ARCHIVED"
    ai = Path(loaded_config.settings.storage.ai_root)
    r = client.post(f"{API}/studies/{sid}/jobs", headers=PW,
                    json={"job_type": "MODEL_REGISTER", "params": {"model_path": str(ai / "ST4")}})
    assert _code(r) == (409, "STUDY_ARCHIVED")
    c = _cleanup(client, sid, scan)
    assert c.status_code == 201
    scan_req = {"job_type": "STUDY_STORAGE_SCAN", "params": {}}
    assert _code(client.post(f"{API}/studies/{sid}/jobs", headers=PW, json=scan_req)) == (409, "STUDY_CLEANUP_RUNNING")  # D3-24
    with engine.begin() as cn:
        cn.execute(text("update jobs set state='CANCELED', queue_seq=null, finished_at=now() where id=:j"), {"j": c.json()["id"]})
    r = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json=scan_req)
    assert r.status_code == 201, r.text


def test_storage_report_shape(client, engine, loaded_config):
    """V3-S3-8: §5.6 모양, 절대경로는 *_display_path만, rel에 '..' 없음."""
    assert _code(client.get(f"{API}/studies/no-such/storage", headers=P)) == (404, "NOT_FOUND")
    sid = mk_study(client, "ST5")
    rep = client.get(f"{API}/studies/{sid}/storage", headers=P).json()
    assert rep["scan"] is None and rep["stale"] is True and rep["last_cleanup"] is None
    scan = mk_job(engine, sid, "STUDY_STORAGE_SCAN", result=_scan_result())
    mk_job(engine, sid, CAT, params={"scan_job_id": scan, "categories": ["PACKAGE_PSDATA"]}, result={
        "moved": [{"rel": "03_package/d0", "bytes": 10, "category": "PACKAGE_PSDATA"}], "moved_count": 1, "moved_bytes": 10,
        "skipped": [{"rel": "03_package/d1", "reason": "파일이 사용 중"}], "skipped_count": 1,
        "backup_rel": "_backup/20261011T000000Z_x"})
    rep = client.get(f"{API}/studies/{sid}/storage", headers=P).json()
    assert set(rep) == {"study_id", "scan", "stale", "stale_reason", "active_scan_job_id", "active_cleanup_job_id",
                        "last_cleanup", "study_display_path", "backup_display_path"}
    s = rep["scan"]
    assert set(s) == {"job_id", "started_at", "finished_at", "partial", "total_bytes", "total_files", "skipped_links", "errors",
                      "backup_bytes", "backup_files", "folders", "top_files", "categories"}
    assert [c["key"] for c in s["categories"]] == ["PACKAGE_PSDATA", "SCORE_PREDICTIONS", "CURATED_H3D", "PREDICT_INPUT",
                                                    "PREVIEW_OUTPUT", "JOB_LOGS"]
    assert all(c["impact"] for c in s["categories"])
    lc = rep["last_cleanup"]
    assert lc["moved_count"] == 1 and lc["skipped"] == [{"rel": "03_package/d1", "reason": "파일이 사용 중"}]
    assert lc["categories"] == ["PACKAGE_PSDATA"] and lc["backup_display_path"].endswith("20261011T000000Z_x")
    ai = loaded_config.settings.storage.ai_root
    assert rep["study_display_path"].startswith(ai) and rep["backup_display_path"].endswith("_backup")
    rels = [f["rel"] for f in s["top_files"]] + [i["rel"] for c in s["categories"] for i in c["items"]]
    assert rels and all(not r.startswith("/") and ".." not in r.split("/") for r in rels)


def _predict_with_rad(engine, sid):
    jid = mk_job(engine, sid, "PREDICT", state="FAILED")
    with engine.begin() as c:
        c.execute(text("insert into job_steps(id, job_id, step_no, step_key, kind, needs_slot, state)"
                       " values (:i,:j,5,'RAD_ASSEMBLE','INTERNAL',true,'SUCCEEDED')"), {"i": str(uuid.uuid4()), "j": jid})
    return jid


def test_moved_output_messages(client, engine, loaded_config):
    """V3-S3-6: R3-5 로그 문구, R3-6 input 폴더 문구·input_display_path, 오류 묶음 manifest."""
    sid = mk_study(client, "ST6")
    ai = Path(loaded_config.settings.storage.ai_root)
    done = mk_job(engine, sid, "MODEL_REGISTER", state="FAILED")
    r = client.get(f"{API}/jobs/{done}/log", headers=P)
    assert _code(r) == (404, "LOG_NOT_FOUND") and "_backup" in r.json()["detail"]["message"]
    q = mk_job(engine, sid, "EVALUATE", state="QUEUED", params={"model_id": "m"})
    assert client.get(f"{API}/jobs/{q}/log", headers=P).json()["detail"]["message"] == "로그가 아직 없습니다"
    pj = _predict_with_rad(engine, sid)
    assert client.get(f"{API}/jobs/{pj}", headers=P).json()["input_display_path"] is None
    r = client.get(f"{API}/jobs/{pj}/artifacts/input.zip", headers=P)
    assert _code(r) == (409, "INPUT_NOT_READY") and "_backup" in r.json()["detail"]["message"]
    put(ai / "ST6", f"04_predict/{pj}/INPUT/a.rad", 5)
    assert client.get(f"{API}/jobs/{pj}", headers=P).json()["input_display_path"].endswith("INPUT")
    r = client.get(f"{API}/jobs/{done}/error-bundle.zip", headers=P)
    assert r.status_code == 200, r.text
    man = json.loads(zipfile.ZipFile(io.BytesIO(r.content)).read("manifest.json"))
    assert man["logs_present"] is False and "_backup" in man["logs_note"]
