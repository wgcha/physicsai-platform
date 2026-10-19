"""native 실행 실패 처리(geometry-engine.md §5.4·§7.2, V-GE-1·9): 보고 없음·종료코드 무시·시간 초과·실행 파일 소실·버전 변경."""

from __future__ import annotations

import os

from helpers_native import native_set
from physicsai_test_support import API, H

PW = H("tok-power", write=True)
VALUES = {"values": {"A_THK_1": 10.2, "B_RIB_H_1": 20.0, "C_HOLE_R_1": 4.0}, "value_source": "manual"}


def _run(env):
    j = env.submit("PREDICT", VALUES)
    return j["id"], env.w.run_once_slot()


def test_missing_report_is_exit_nonzero(native_env, monkeypatch):
    env = native_env()
    native_set(env)
    monkeypatch.setenv("FAKE_PAICAD_NOREPORT", "update")
    jid, state = _run(env)
    jd = env.job(jid)
    assert state == "FAILED" and jd["failure_code"] == "EXIT_NONZERO" and jd["current_step_key"] == "GEOM_UPDATE", jd


def test_nonzero_exit_with_good_output_is_success_with_warning(native_env, monkeypatch):
    env = native_env()
    native_set(env)
    monkeypatch.setenv("FAKE_PAICAD_EXIT_AFTER_OK", "update:5")
    jid, state = _run(env)
    assert state == "SUCCEEDED", env.job(jid)
    assert "EXIT_NONZERO_IGNORED" in [w["code"] for w in env.job(jid)["warnings"]]


def test_timeout_kills_and_reports_geom_timeout(native_env, monkeypatch):
    env = native_env(geometry={"timeout_s": {"update": 1}})
    native_set(env)
    monkeypatch.setenv("FAKE_PAICAD_SLEEP_S", "6")
    jid, state = _run(env)
    jd = env.job(jid)
    assert state == "FAILED" and jd["failure_code"] == "GEOM_TIMEOUT" and "시간" in jd["failure_message"], jd


def test_executable_vanishes_after_job_creation(native_env, tmp_path):
    env = native_env()
    native_set(env)
    j = env.submit("PREDICT", VALUES)
    os.rename(env.lc.settings.geometry.paicad_path, env.lc.settings.geometry.paicad_path + ".gone")
    try:
        assert env.w.run_once_slot() == "FAILED"
        jd = env.job(j["id"])
        assert jd["failure_code"] == "EXECUTABLE_MISSING", jd
        assert jd["failure_message"]
    finally:
        os.rename(env.lc.settings.geometry.paicad_path + ".gone", env.lc.settings.geometry.paicad_path)


def test_version_minor_change_fails_with_input_changed(native_env, monkeypatch):
    """준비 이후 paicad MINOR가 바뀌면 작업 실행 때 INPUT_CHANGED(→ 다시 준비). PATCH 차이는 통과."""
    env = native_env()
    native_set(env)
    monkeypatch.setenv("FAKE_PAICAD_VERSION", "0.5.7")
    jid, state = _run(env)
    assert state == "SUCCEEDED", env.job(jid)
    monkeypatch.setenv("FAKE_PAICAD_VERSION", "0.6.0")
    jid, state = _run(env)
    jd = env.job(jid)
    assert state == "FAILED" and jd["failure_code"] == "INPUT_CHANGED" and "0.6.0" in jd["failure_message"], jd
    assert env.c.get(f"{API}/studies/{env.sid}/param-sets", headers=H("tok-power")).json()[0]["native"]["prep_status"] == "READY"
