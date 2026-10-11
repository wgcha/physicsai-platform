"""phase3 §5.7 V3-S3-4(정리 이동·매니페스트·재검사·잠금·취소)·V3-S3-7(정리 알림) — 워커."""

from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import text

from helpers_manage import P, PW, mk_dataset, mk_job, mk_study, put
from physicsai_test_support import API
from physicsai_worker.steps.stage0_manage import cleanup as cleanup_mod


def _run(c, w, sid, jt, params):
    r = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": jt, "params": params})
    assert r.status_code == 201, r.text
    state = w.run_once_light()
    return r.json()["id"], state


def _setup(client, engine, ai: Path, name: str):
    sid = mk_study(client, name)
    root = ai / name
    put(root, "03_package/d1/dataset_train.psdata", 400)
    put(root, "03_package/d2/dataset_train.psdata", 200)
    d1 = mk_dataset(engine, sid, "03_package/d1/")
    d2 = mk_dataset(engine, sid, "03_package/d2/")
    hp1 = mk_job(engine, sid, "CU_H3D_PREVIEW", days_ago=3)
    mk_job(engine, sid, "CU_H3D_PREVIEW", days_ago=2)
    put(root, f"02_preview/{hp1}/PREVIEW_H3D.json", 50)
    put(root, "03_model/models/m1/model.psmdl", 999)  # 항상 보호
    return sid, root, d1, d2, hp1


def _job(c, jid):
    return c.get(f"{API}/jobs/{jid}", headers=P).json()


def test_cleanup_moves_records_and_rechecks(client, worker_factory, loaded_config, engine, monkeypatch):
    ai = Path(loaded_config.settings.storage.ai_root)
    w = worker_factory()
    sid, root, d1, d2, hp1 = _setup(client, engine, ai, "CL1")
    scan_id, st = _run(client, w, sid, "STUDY_STORAGE_SCAN", {})
    assert st == "SUCCEEDED"
    # 스캔 뒤 DB 조건 변경(작업 종료 아님 → 낡지 않음): d2는 더 이상 패키지 아님 → 실행 시점 재검사로 건너뜀
    with engine.begin() as cn:
        cn.execute(text("update datasets set package_rel=null where id=:d"), {"d": d2})
    real_replace = os.replace
    calls: list[str] = []

    def spy(a, b):
        calls.append(str(a))
        if f"02_preview{os.sep}{hp1}" in str(a) and "_backup" not in str(a):
            raise PermissionError("locked")
        return real_replace(a, b)

    monkeypatch.setattr(os, "replace", spy)
    cid, st = _run(client, w, sid, "STUDY_CLEANUP",
                   {"scan_job_id": scan_id, "categories": ["PACKAGE_PSDATA", "PREVIEW_OUTPUT"]})
    j = _job(client, cid)
    assert st == "SUCCEEDED", j
    r = j["result"]
    assert [m["rel"] for m in r["moved"]] == ["03_package/d1"] and r["moved_bytes"] == 400 and r["moved_count"] == 1
    assert {(s["rel"], s["reason"]) for s in r["skipped"]} == {
        ("03_package/d2", cleanup_mod.SKIP_CHANGED), (f"02_preview/{hp1}", cleanup_mod.SKIP_LOCKED)}
    assert [x["code"] for x in j["warnings"]] == ["PARTIAL_OUTPUT"]
    stamp_dir = root / r["backup_rel"]
    assert r["backup_rel"].startswith("_backup/") and r["backup_rel"].endswith(f"_{cid}")
    assert (stamp_dir / "03_package" / "d1" / "dataset_train.psdata").stat().st_size == 400
    assert not (root / "03_package" / "d1").exists() and (root / "03_package" / "d2").exists()
    assert (root / "02_preview" / hp1).exists() and (root / "03_model" / "models" / "m1" / "model.psmdl").exists()
    man = json.loads((stamp_dir / "CLEANUP_MANIFEST.json").read_text(encoding="utf-8"))
    assert man["job_id"] == cid and man["categories"] == ["PACKAGE_PSDATA", "PREVIEW_OUTPUT"] and man["restore"]
    assert man["items"] == [{"rel": "03_package/d1", "bytes": 400, "category": "PACKAGE_PSDATA"}]
    ds = client.get(f"{API}/datasets/{d1}", headers=P).json()
    assert ds["package_ready"] is False and ds["package_rel"] is None
    with engine.connect() as cn:
        notes = cn.execute(text("select event, body from notifications where job_id=:j"), {"j": cid}).all()
        audit = cn.execute(text("select detail from audit_events where action='STUDY_CLEANUP'")).scalar_one()
    assert [(n.event, n.body) for n in notes if n.event != "JOB_STARTED"] == [("JOB_SUCCEEDED", "1개 항목, 400 B 이동")]
    assert audit["moved_count"] == 1 and audit["job_id"] == cid
    rep = client.get(f"{API}/studies/{sid}/storage", headers=P).json()
    lc = rep["last_cleanup"]
    assert lc["job_id"] == cid and lc["moved_count"] == 1 and lc["skipped_count"] == 2 and lc["backup_display_path"]
    assert rep["stale"] is True  # 정리 뒤 다시 계산 필요


def test_cleanup_all_locked_fails(client, worker_factory, loaded_config, engine, monkeypatch):
    ai = Path(loaded_config.settings.storage.ai_root)
    w = worker_factory()
    sid, root, *_ = _setup(client, engine, ai, "CL2")
    scan_id, _ = _run(client, w, sid, "STUDY_STORAGE_SCAN", {})
    real_replace = os.replace

    def locked(a, b):
        if f"{os.sep}03_package{os.sep}" in str(a) and "_backup" not in str(a):
            raise PermissionError("locked")
        return real_replace(a, b)

    monkeypatch.setattr(os, "replace", locked)
    cid, st = _run(client, w, sid, "STUDY_CLEANUP", {"scan_job_id": scan_id, "categories": ["PACKAGE_PSDATA"]})
    j = _job(client, cid)
    assert st == "FAILED" and j["failure_code"] == "OUTPUT_LOCKED"
    assert (root / "03_package" / "d1").exists() and not [x for x in (root / "_backup").rglob("*") if x.is_file()]
    with engine.connect() as cn:
        assert cn.execute(text("select event from notifications where job_id=:j and event='JOB_FAILED'"), {"j": cid}).all()


def test_cleanup_cancel_keeps_remaining(client, worker_factory, loaded_config, engine, monkeypatch):
    ai = Path(loaded_config.settings.storage.ai_root)
    w = worker_factory()
    sid, root, *_ = _setup(client, engine, ai, "CL3")
    scan_id, _ = _run(client, w, sid, "STUDY_STORAGE_SCAN", {})
    real = cleanup_mod.backup_existing
    holder: dict[str, str] = {}

    def move_then_cancel(study_root, paths, job_id, stamp):
        out = real(study_root, paths, job_id, stamp)
        with engine.begin() as cn:
            cn.execute(text("update jobs set cancel_requested_at=now() where id=:j"), {"j": job_id})
        holder["job"] = job_id
        return out

    monkeypatch.setattr(cleanup_mod, "backup_existing", move_then_cancel)
    cid, st = _run(client, w, sid, "STUDY_CLEANUP", {"scan_job_id": scan_id, "categories": ["PACKAGE_PSDATA"]})
    assert st == "CANCELED" and holder["job"] == cid
    r = _job(client, cid)["result"]
    assert r["moved_count"] == 1 and [m["rel"] for m in r["moved"]] == ["03_package/d1"]  # 큰 것부터
    assert not (root / "03_package" / "d1").exists() and (root / "03_package" / "d2").exists()
    assert (root / r["backup_rel"] / "CLEANUP_MANIFEST.json").is_file()


def test_cleanup_validate_skips_link_item_and_continues(client, worker_factory, loaded_config, engine, tmp_path):
    """D3-22: 스캔 뒤 항목이 Study 밖을 가리키는 링크로 바뀌면 그 항목만 LINK_OR_OUTSIDE로 빼고 나머지는 옮긴다(작업 실패 아님)."""
    import pytest

    ai = Path(loaded_config.settings.storage.ai_root)
    w = worker_factory()
    sid, root, *_ = _setup(client, engine, ai, "CL4")
    scan_id, _ = _run(client, w, sid, "STUDY_STORAGE_SCAN", {})
    outside = tmp_path / "outside_d2"
    (root / "03_package" / "d2").rename(outside)  # 시험 준비: 치우고 같은 이름 링크로 바꾼다(삭제 아님)
    try:
        os.symlink(outside, root / "03_package" / "d2", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"심볼릭 링크를 만들 수 없음: {exc}")
    cid, st = _run(client, w, sid, "STUDY_CLEANUP", {"scan_job_id": scan_id, "categories": ["PACKAGE_PSDATA"]})
    j = _job(client, cid)
    assert st == "SUCCEEDED", j
    r = j["result"]
    assert [m["rel"] for m in r["moved"]] == ["03_package/d1"]
    assert [(s["rel"], s["code"], s["reason"]) for s in r["skipped"]] == [
        ("03_package/d2", cleanup_mod.CODE_LINK_OR_OUTSIDE, cleanup_mod.SKIP_LINK)]
    assert (outside / "dataset_train.psdata").stat().st_size == 200 and (root / "03_package" / "d2").is_symlink()


def test_cleanup_move_distinguishes_outside_and_locked(client, worker_factory, loaded_config, engine, monkeypatch):
    """D3-23: SC_MOVE에서 경로 탈출(Study 밖·보호 경로) 거부와 파일 잠김은 다른 사유 코드."""
    from physicsai_core.errors import StepFailure

    ai = Path(loaded_config.settings.storage.ai_root)
    w = worker_factory()
    sid, root, *_ = _setup(client, engine, ai, "CL5")
    scan_id, _ = _run(client, w, sid, "STUDY_STORAGE_SCAN", {})

    def fake_backup(study_root, paths, job_id, stamp):
        if paths[0].endswith("d1"):
            raise StepFailure("INTERNAL_ERROR", "Study 밖 산출물은 백업할 수 없습니다")
        raise StepFailure("OUTPUT_LOCKED", "기존 산출물을 백업 폴더로 옮기지 못했습니다")

    monkeypatch.setattr(cleanup_mod, "backup_existing", fake_backup)
    cid, st = _run(client, w, sid, "STUDY_CLEANUP", {"scan_job_id": scan_id, "categories": ["PACKAGE_PSDATA"]})
    r = _job(client, cid)["result"]
    assert st == "FAILED"
    assert {(s["rel"], s["code"], s["reason"]) for s in r["skipped"]} == {
        ("03_package/d1", cleanup_mod.CODE_PATH_OUTSIDE, cleanup_mod.SKIP_OUTSIDE),
        ("03_package/d2", cleanup_mod.CODE_LOCKED, cleanup_mod.SKIP_LOCKED)}
    rep = client.get(f"{API}/studies/{sid}/storage", headers=P).json()
    assert {s["reason"] for s in rep["last_cleanup"]["skipped"]} == {cleanup_mod.SKIP_OUTSIDE, cleanup_mod.SKIP_LOCKED}
