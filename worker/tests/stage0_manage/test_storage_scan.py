"""phase3 §5.3·§5.5 V3-S3-1(스캔 집계)·V3-S3-2(범주 분류)·V3-S3-7(스캔 알림) — 워커."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from helpers_manage import P, PW, mk_job, mk_study, put
from physicsai_core.study_storage import scan as scan_mod
from physicsai_core.study_storage.categories import is_protected
from physicsai_core.study_storage.classify import Rules, StudyRefs, classify
from physicsai_test_support import API

NOW = datetime.now(timezone.utc)


def _tree(root: Path) -> None:
    put(root, "00_inbox/a.h3d", 100)
    put(root, "01_train/doe/run_1/x.txt", 50)
    put(root, "_backup/20260101T000000Z_j/old.bin", 300)
    put(root, "study.json", 10)
    put(root, "notes.txt", 5)
    put(root, "logs/j1/job.log", 20)
    put(root, "logs/j2/job.log", 7)
    put(root, "03_package/d1/dataset_train.psdata", 400)


def test_walk_totals_top_backup_links_errors(tmp_path):
    root = tmp_path / "S"
    _tree(root)
    t = scan_mod.walk(str(root), max_entries=10_000, top_n=3)
    s = t.summary()
    assert s["total_bytes"] == 100 + 50 + 300 + 10 + 5 + 20 + 7 + 400 and s["total_files"] == 8
    assert s["skipped_links"] == 0 and s["errors"] == 0 and s["partial"] is False
    folders = {f["key"]: (f["bytes"], f["files"]) for f in s["folders"]}
    assert folders == {"00_inbox": (100, 1), "01_train": (50, 1), "_backup": (300, 1), "(기타)": (15, 2), "logs": (27, 2),
                       "03_package": (400, 1)}
    assert [f["key"] for f in s["folders"]] == ["00_inbox", "01_train", "03_package", "logs", "_backup", "(기타)"]
    assert (s["backup_bytes"], s["backup_files"]) == (300, 1)
    assert [(f["rel"], f["bytes"], f["in_backup"]) for f in s["top_files"]] == [
        ("03_package/d1/dataset_train.psdata", 400, False), ("_backup/20260101T000000Z_j/old.bin", 300, True),
        ("00_inbox/a.h3d", 100, False)]
    items = t.items_json()
    assert items["logs/j1"] == [20, 1, 0] and items["logs/j2"] == [7, 1, 0] and items["03_package/d1"] == [400, 1, 0]
    assert not any(k.startswith(("00_inbox", "_backup", "01_train")) for k in items)


def test_walk_does_not_follow_links(tmp_path):
    """링크는 따라가지 않고 개수만, 범주 항목 안 링크는 항목에 표시(→ 분류에서 제외)."""
    root = tmp_path / "S"
    _tree(root)
    outside = tmp_path / "outside"
    put(outside, "big.bin", 9999)
    try:
        os.symlink(outside, root / "01_train" / "lnk", target_is_directory=True)
        os.symlink(outside / "big.bin", root / "logs" / "j2" / "lnk.bin")
    except OSError as exc:  # Windows에서 심볼릭 링크 권한이 없으면 만들 수 없다
        pytest.skip(f"심볼릭 링크를 만들 수 없음: {exc}")
    t = scan_mod.walk(str(root), max_entries=10_000, top_n=3)
    assert t.skipped_links == 2 and t.total_bytes == 892 and t.items["logs/j2"].links == 1


def test_walk_permission_error_and_partial(tmp_path, monkeypatch):
    root = tmp_path / "S"
    _tree(root)
    real_scandir = os.scandir

    def fake(p):
        if str(p).endswith(os.path.join("logs", "j1")):
            raise PermissionError(p)
        return real_scandir(p)

    monkeypatch.setattr(scan_mod.os, "scandir", fake)
    t = scan_mod.walk(str(root), max_entries=10_000, top_n=20)
    assert t.errors == 1 and t.total_files == 7 and "logs/j1" not in t.items
    monkeypatch.setattr(scan_mod.os, "scandir", real_scandir)
    seen: list[int] = []
    monkeypatch.setattr(scan_mod, "PROGRESS_EVERY", 2)
    t = scan_mod.walk(str(root), max_entries=5, top_n=20, on_progress=seen.append)
    assert t.partial is True and t.entries == 5 and seen == [2, 4]


def _job(jid, jt, state="SUCCEEDED", days=40.0, retry_of=None, **params):
    ts = NOW - timedelta(days=days)
    return {"id": jid, "job_type": jt, "state": state, "created_at": ts, "finished_at": ts if state != "RUNNING" else None,
            "retry_of_job_id": retry_of, "params": params}


def test_classify_rules_per_category():
    """§5.5 표 각 행의 후보·제외 조건, 항상 보호, 항목 상한·truncated."""
    jobs = [
        _job("ev1", "EVALUATE", model_id="mA"), _job("ev2", "EVALUATE", model_id="mF", days=30),
        _job("ev2r", "EVALUATE", retry_of="ev2", model_id="mF", days=29), _job("ev3", "EVALUATE", model_id="mF", days=50),
        _job("pr1", "PREDICT"), _job("pr2", "PREDICT", state="FAILED"), _job("pr2r", "PREDICT", retry_of="pr2"),
        _job("pv1", "PREDICT_VERIFY", predict_job_id="pr2r"),
        _job("hp1", "CU_H3D_PREVIEW", days=60), _job("hp2", "CU_H3D_PREVIEW", days=50),
        _job("hp3", "CU_H3D_PREVIEW", state="FAILED", days=1), _job("tp1", "CU_T01_PREVIEW", days=40),
        _job("old1", "PACKAGE_EXPORT", days=100), _job("old2", "PACKAGE_EXPORT", days=90),
        _job("young", "MODEL_REGISTER", days=5), _job("mr_old", "MODEL_REGISTER", days=200),
        _job("f1", "OPTIMIZE", state="FAILED", days=300), _job("f2", "OPTIMIZE", state="INTERRUPTED", days=310),
        _job("f3", "OPTIMIZE", state="FAILED", days=320), _job("op_ok", "OPTIMIZE", days=10),
    ]
    refs = StudyRefs(
        jobs=jobs,
        datasets=[{"id": "d1", "package_rel": "03_package/d1/"}, {"id": "d2", "package_rel": None}],
        curations=[{"id": "c1", "kind": "H3D", "status": "READY", "output_rel": "02_curated/c1/CURATED_DATA/"},
                   {"id": "c2", "kind": "H3D", "status": "FAILED", "output_rel": "02_curated/c2/CURATED_DATA/"}],
        curation_dataset_counts={"c1": 2},
        models=[{"id": "mA", "name": "A", "version": 1, "eval_job_id": "ev1"},
                {"id": "mF", "name": "F", "version": 2, "eval_job_id": "ev2r"}],
        final_model_id="mF",
    )
    rels = [
        "03_package/d1", "03_package/d2", "03_model/score/mA/ev1/predictions.psdata",
        "03_model/score/mF/ev2/predictions.psdata", "03_model/score/mF/ev3/predictions.psdata",
        "02_curated/c1/CURATED_DATA", "02_curated/c2/CURATED_DATA", "04_predict/pr1/INPUT", "04_predict/pr2/INPUT",
        "04_predict/pr2/verify/1/input", "02_preview/hp1", "02_preview/hp2", "02_preview/hp3", "02_preview/tp1",
        *[f"logs/{j['id']}" for j in jobs],
    ]
    items = {r: [100 + i, 1, 0] for i, r in enumerate(rels)}
    cats, link_ex = classify(items, refs, Rules(log_min_age_days=30, keep_failed_logs=3), NOW, 500)
    got = {c["key"]: sorted(x["rel"] for x in c["items"]) for c in cats}
    assert got["PACKAGE_PSDATA"] == ["03_package/d1"]
    # Final 모델(mF)의 최신 평가(ev2r → 폴더 root ev2)는 제외, Final의 옛 평가(ev3)·다른 모델 평가는 후보
    assert got["SCORE_PREDICTIONS"] == ["03_model/score/mA/ev1/predictions.psdata", "03_model/score/mF/ev3/predictions.psdata"]
    assert got["CURATED_H3D"] == ["02_curated/c1/CURATED_DATA"]
    cur = next(c for c in cats if c["key"] == "CURATED_H3D")["items"][0]
    assert cur["ref_id"] == "c1" and "데이터셋 2개" in cur["note"]
    assert got["PREDICT_INPUT"] == ["04_predict/pr1/INPUT", "04_predict/pr2/INPUT", "04_predict/pr2/verify/1/input"]
    # 유형별 최신 성공(hp2, tp1)은 제외, 실패한 hp3는 후보
    assert got["PREVIEW_OUTPUT"] == ["02_preview/hp1", "02_preview/hp3"]
    logs = set(got["JOB_LOGS"])
    assert "logs/young" not in logs and "logs/op_ok" not in logs  # 30일 안 됨
    assert "logs/old2" not in logs and "logs/old1" in logs  # 유형별 최신 보호
    assert "logs/mr_old" in logs and not {"logs/hp3", "logs/pr2", "logs/f1"} & logs  # 실패·중단 최근 3개 보호
    assert {"logs/f2", "logs/f3"} <= logs
    assert link_ex == 0
    # 진행 중인 검증 작업이 있으면 그 예측 입력은 후보 아님
    refs.jobs = [*jobs, _job("pv2", "PREDICT_VERIFY", state="RUNNING", predict_job_id="pr2r")]
    cats, _ = classify(items, refs, Rules(30, 1), NOW, 500)
    assert {x["rel"] for c in cats if c["key"] == "PREDICT_INPUT" for x in c["items"]} == {"04_predict/pr1/INPUT"}
    # 상한·truncated(큰 것부터), 링크 든 항목 제외
    items["03_model/score/mA/ev1/predictions.psdata"][2] = 1
    cats, link_ex = classify(items, refs, Rules(30, 1), NOW, 1)
    pv = next(c for c in cats if c["key"] == "PREVIEW_OUTPUT")
    assert pv["truncated"] is True and pv["item_count"] == 1 and pv["items"][0]["rel"] == "02_preview/hp3"
    assert pv["total_bytes"] == items["02_preview/hp3"][0] and link_ex == 1


@pytest.mark.parametrize("rel", ["03_model/models/m1", "03_dataset/d1", "04_params/p", "00_inbox/x", "study.json",
                                 "_backup/x", "_platform/x", "../x", "/abs", "a//b"])
def test_always_protected(rel):
    assert is_protected(rel)


def test_scan_job_end_to_end(client, worker_factory, loaded_config, engine):
    """API로 스캔 생성 → 워커 실행 → 보고서·성공 알림 없음(R3-3)."""
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = mk_study(client, "SC1")
    root = ai / "SC1"
    put(root, "03_package/d1/dataset_train.psdata", 400)
    put(root, "_backup/x/old.bin", 30)
    old = mk_job(engine, sid, "PACKAGE_EXPORT", days_ago=100)
    mk_job(engine, sid, "PACKAGE_EXPORT", days_ago=1)
    put(root, f"logs/{old}/job.log", 5)
    r = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "STUDY_STORAGE_SCAN", "params": {}})
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["stage"] == 0 and j["stage_label"] == "관리" and j["lane"] == "LIGHT" and j["can_retry"] is False
    rep = client.get(f"{API}/studies/{sid}/storage", headers=P).json()
    assert rep["active_scan_job_id"] == j["id"] and rep["scan"] is None and rep["stale_reason"] == "아직 계산하지 않았습니다"
    assert worker_factory().run_once_light() == "SUCCEEDED"
    rep = client.get(f"{API}/studies/{sid}/storage", headers=P).json()
    s = rep["scan"]
    assert s["job_id"] == j["id"] and s["backup_bytes"] == 30 and rep["stale"] is False and rep["active_scan_job_id"] is None
    logs = next(c for c in s["categories"] if c["key"] == "JOB_LOGS")
    assert [x["rel"] for x in logs["items"]] == [f"logs/{old}"] and logs["impact"]
    with engine.connect() as c:
        assert c.execute(text("select count(*) from notifications where job_id=:j"), {"j": j["id"]}).scalar() == 0


def test_scan_failure_notifies_failed_only(client, worker_factory, engine, monkeypatch):
    """V3-S3-7: 스캔 실패 → JOB_FAILED 1건(시작 알림 없음)."""
    from physicsai_worker.steps.stage0_manage import storage_scan

    def boom(*_a, **_k):
        raise OSError("disk gone")

    monkeypatch.setattr(storage_scan, "walk", boom)
    sid = mk_study(client, "SC2")
    jid = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "STUDY_STORAGE_SCAN", "params": {}}).json()["id"]
    assert worker_factory().run_once_light() == "FAILED"
    with engine.connect() as c:
        ev = [r.event for r in c.execute(text("select event from notifications where job_id=:j"), {"j": jid})]
    assert ev == ["JOB_FAILED"]
