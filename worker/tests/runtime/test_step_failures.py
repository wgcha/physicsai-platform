"""step 실패·재시도(V-SM-5·6, V-CMD-5, V-CMD-7, V-DS-2): 출력 부족 → 재시도 시 작업 폴더 재사용·백업, 로그 오류 감지,
종료코드·실행 파일 없음, hang 작업은 자동 종료하지 않음."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from helpers_queue import AW, PW, P, _dataset_job, _state
from physicsai_test_support import API, H, wait_for


def test_output_too_small_then_retry_reuses_and_backs_up(client, engine, loaded_config, worker_factory, monkeypatch):
    ai = Path(loaded_config.settings.storage.ai_root)
    monkeypatch.setenv("FAKE_TOOL_MODE_EDSPY", "small")
    sid, j = _dataset_job(client, ai, "RT1")
    w = worker_factory()
    assert w.run_once_slot() == "FAILED"
    jd = client.get(f"{API}/jobs/{j['id']}", headers=P).json()
    assert jd["failure_code"] == "OUTPUT_TOO_SMALL"
    steps = {s["step_key"]: s["state"] for s in jd["steps"]}
    assert steps == {"DS_SCAN": "SUCCEEDED", "DS_YAML": "SUCCEEDED", "EDSPY_DATASET_TRAIN": "FAILED",
                     "EDSPY_DATASET_EVAL": "SKIPPED", "DS_REGISTER": "SKIPPED"}
    assert jd["can_retry"] is True
    # 남의 작업 재시도는 전역 관리자만
    assert client.post(f"{API}/jobs/{j['id']}/retry", headers=H("tok-power2", write=True), json={}).status_code == 403
    monkeypatch.delenv("FAKE_TOOL_MODE_EDSPY")
    r = client.post(f"{API}/jobs/{j['id']}/retry", headers=PW, json={})
    assert r.status_code == 201, r.text
    nj = r.json()
    assert nj["retry_of_job_id"] == j["id"]
    assert [s["state"] for s in nj["steps"]][:3] == ["SKIPPED", "SKIPPED", "PENDING"]
    assert w.run_once_slot() == "SUCCEEDED"
    ds_id = jd["result"]["dataset_id"]
    assert client.get(f"{API}/datasets/{ds_id}", headers=P).json()["status"] == "READY"
    backups = list((ai / "RT1" / "_backup").rglob("dataset.psdata"))
    assert len(backups) == 1 and backups[0].stat().st_size == 1024
    assert client.post(f"{API}/jobs/{nj['id']}/retry", headers=PW, json={}).json()["detail"]["code"] == "JOB_NOT_RETRYABLE"


def test_log_error_detected(client, engine, loaded_config, worker_factory, monkeypatch):
    monkeypatch.setenv("FAKE_TOOL_MODE_EDSPY", "error_log")
    _sid, j = _dataset_job(client, loaded_config.settings.storage.ai_root, "LE1")
    assert worker_factory().run_once_slot() == "FAILED"
    assert _state(engine, j["id"])["failure_code"] == "LOG_ERROR_DETECTED"


def test_exit_nonzero_and_executable_missing(client, engine, loaded_config, worker_factory, monkeypatch):
    monkeypatch.setenv("FAKE_TOOL_MODE_EDSPY", "fail")
    _sid, j = _dataset_job(client, loaded_config.settings.storage.ai_root, "EX1")
    assert worker_factory().run_once_slot() == "FAILED"
    assert _state(engine, j["id"])["failure_code"] == "EXIT_NONZERO"


def test_hang_not_auto_terminated(client, engine, loaded_config, worker_factory, monkeypatch, tmp_path):
    """V-SM-6: 실행 시간 한도 없음 — hang 작업은 취소 전까지 계속 RUNNING."""
    pidfile = tmp_path / "pids"
    monkeypatch.setenv("FAKE_TOOL_MODE_EDSPY", "hang")
    monkeypatch.setenv("FAKE_TOOL_PIDFILE", str(pidfile))
    _sid, j = _dataset_job(client, loaded_config.settings.storage.ai_root, "HG1")
    w = worker_factory()
    t = threading.Thread(target=w.run_once_slot)
    t.start()
    wait_for(lambda: pidfile.exists() and pidfile.read_text().strip())
    time.sleep(float(os.environ.get("PHYSICSAI_HANG_TEST_S", "5")))
    assert _state(engine, j["id"])["state"] == "RUNNING"
    client.post(f"{API}/jobs/{j['id']}/cancel", headers=AW)
    t.join(timeout=20)
    assert _state(engine, j["id"])["state"] == "CANCELED"
