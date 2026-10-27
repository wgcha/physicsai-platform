"""phase3 §16.12: ④ PREDICT_VERIFY scx 모드(가짜 relay) — 업로드 → 제출 → 폴링 → V/result 회수, 결과 모름 → 제출 안 됨(T13),
상태 매핑(Failed·Aborted·SCX_JOB_NOT_FOUND→LOST·연결 실패→hpc_unreachable_since), housekeeping, STAGE_IN 일시정지·시간 초과."""

from __future__ import annotations

import copy
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from physicsai_test_support import API, H, make_model_folder, make_param_set_folder, scx_hpc_cfg

PW, P, AW = H("tok-power", write=True), H("tok-power"), H("tok-admin", write=True)


@pytest.fixture()
def scx_env(settings_dict, fake_tools, engine, fake_dashboard, fake_relay, tmp_path):
    from physicsai_api.context import build_context
    from physicsai_api.main import create_app
    from physicsai_core.config import load_config_dict
    from physicsai_worker.runtime import Worker

    d = copy.deepcopy(settings_dict)
    d["hpc"] = scx_hpc_cfg(fake_relay, tmp_path)
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    ctx = build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler))
    with TestClient(create_app(ctx), base_url="http://127.0.0.1") as c:
        w = Worker(lc, engine)
        w.hpc._sleep = lambda _s: None
        yield c, w, Path(d["storage"]["ai_root"]), fake_relay


def _setup_predict(c, w, ai: Path, name: str) -> tuple[str, str]:
    sid = c.post(f"{API}/studies", headers=PW, json={"project_id": "p-1", "folder_name": name, "title": name}).json()["id"]
    sroot = ai / name
    mf = make_model_folder(sroot / "00_inbox")
    jid = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "MODEL_REGISTER", "params": {"model_path": str(mf)}}).json()["id"]
    assert w.run_once_light() == "SUCCEEDED"
    mid = c.get(f"{API}/jobs/{jid}", headers=P).json()["result"]["model_id"]
    c.put(f"{API}/studies/{sid}/final-model", headers=PW, json={"model_id": mid})
    psf = make_param_set_folder(sroot / "00_inbox")
    assert c.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(psf)}).status_code == 201
    pj = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "PREDICT", "params": {"values": {"THK_1": 3, "N_RIB": 4}, "value_source": "nominal"}}).json()["id"]
    assert w.run_once_slot() == "SUCCEEDED"
    return sid, pj


def _verify(c, sid, pj):
    r = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "PREDICT_VERIFY", "params": {"predict_job_id": pj}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _hpc(c, vid):
    return c.get(f"{API}/jobs/{vid}/hpc-jobs", headers=P).json()


def _job(c, vid):
    return c.get(f"{API}/jobs/{vid}", headers=P).json()


def test_scx_verify_full_cycle(scx_env, engine):
    c, w, ai, fake = scx_env
    fake.outputs = {"model0_0000.h3d": b"H3D", "model0_0000.out": b"x", "model0_0000.rad.bak": b"no"}
    sid, pj = _setup_predict(c, w, ai, "SV1")
    vid = _verify(c, sid, pj)
    assert w.run_once_slot() == "WAITING_HPC", _job(c, vid)
    dirs = [p.name for p in (fake.drive / "SV1").iterdir()]
    assert len(dirs) == 1 and re.fullmatch(r"04_V-001_\d{8}T\d{6}", dirs[0]), dirs
    body = fake.adapter_calls[0]
    starter = _job(c, vid)["result"]["starter"]
    assert body["input_path"] == f"SV1/{dirs[0]}/{starter}"
    h = _hpc(c, vid)[0]
    assert h["state"] == "QUEUED" and h["run_key"] == "verify" and h["remote_dir"] == f"/Users/vd.dashboard/SV1/{dirs[0]}"
    for _ in range(3):
        w.poll_hpc_once()
    assert _job(c, vid)["state"] == "COLLECTING"
    assert w.run_once_collect() == "QUEUED"
    assert w.run_once_slot() == "SUCCEEDED", _job(c, vid)
    j = _job(c, vid)
    assert j["result"]["collected"] == ["model0_0000.h3d", "model0_0000.out"]
    V = ai / "SV1" / "04_predict" / pj / "verify" / "1" / "result"
    assert (V / "model0_0000.h3d").read_bytes() == b"H3D" and not list(V.glob("*.part"))
    with engine.connect() as conn:
        ev = [e for (e,) in conn.execute(text("select event from notifications where job_id=:j order by seq"), {"j": vid})]
    assert ev == ["JOB_STARTED", "HPC_COLLECTED", "JOB_SUCCEEDED"]
    # 두 번째 검증: V-002
    vid2 = _verify(c, sid, pj)
    assert w.run_once_slot() == "WAITING_HPC"
    assert any(n.startswith("04_V-002_") for n in (p.name for p in (fake.drive / "SV1").iterdir()))
    del vid2


def test_scx_verify_unknown_mark_not_submitted(scx_env, engine):
    """④ 결과 모름 → attention·알림 → 제출 안 됨 → 행 FAILED → T13(작업 실패, 검증을 새로 실행)."""
    c, w, ai, fake = scx_env
    sid, pj = _setup_predict(c, w, ai, "SV2")
    fake.submit_mode = "unknown"
    vid = _verify(c, sid, pj)
    assert w.run_once_slot() == "WAITING_HPC"
    j = _job(c, vid)
    assert j["attention_code"] == "HPC_SUBMISSION_UNKNOWN" and j["result"]["not_submitted"] == []
    h = _hpc(c, vid)[0]
    assert h["state"] == "UNKNOWN" and h["submission_unknown"]
    with engine.connect() as conn:
        title = conn.execute(text("select title from notifications where job_id=:j and event='HPC_SUBMISSION_UNKNOWN'"),
                             {"j": vid}).scalar()
    assert title.startswith("SCX 제출 확인 필요: ")
    r = c.post(f"{API}/jobs/{vid}/hpc-jobs/{h['id']}/resolve", headers=PW, json={"action": "mark_not_submitted", "version": h["version"]})
    assert r.status_code == 202
    w.poll_hpc_once()
    j = _job(c, vid)
    assert j["state"] == "FAILED" and j["failure_code"] == "HPC_RUN_FAILED"
    assert fake.resolves[-1]["action"] == "abandon"
    h = _hpc(c, vid)[0]
    assert h["state"] == "FAILED" and h["error_message"] == "제출되지 않음(사용자 확인)"
    # 조치 후 다시 요청 → 409 HPC_NOT_UNKNOWN
    r = c.post(f"{API}/jobs/{vid}/hpc-jobs/{h['id']}/resolve", headers=PW, json={"action": "recheck", "version": h["version"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "HPC_NOT_UNKNOWN"


@pytest.mark.parametrize("seq, final, code", [
    (["Running", "Failed"], "FAILED", "HPC_RUN_FAILED"),
    (["Running", "Aborted"], "CANCELED", "HPC_RUN_FAILED"),
    (["Running", "Cancelled"], "CANCELED", "HPC_RUN_FAILED"),
    (["Weird", "__SCX_NOT_FOUND__"], "LOST", "HPC_RUN_FAILED"),
])
def test_scx_verify_state_mapping(scx_env, seq, final, code):
    """§16.6 표: Failed(오류 문구 마스킹)·Aborted("SCX에서 취소됨")·그 밖 문자열/SCX_JOB_NOT_FOUND → UNKNOWN 계수 → LOST."""
    c, w, ai, fake = scx_env
    sid, pj = _setup_predict(c, w, ai, "SV3")
    fake.status_seq = list(seq)
    vid = _verify(c, sid, pj)
    assert w.run_once_slot() == "WAITING_HPC"
    for _ in range(len(seq)):
        w.poll_hpc_once()
    h = _hpc(c, vid)[0]
    assert h["state"] == final, h
    j = _job(c, vid)
    assert j["state"] == "FAILED" and j["failure_code"] == code
    if seq[-1] == "Failed":
        assert "abc.def.ghi" not in h["error_message"] and "Bearer ***" in h["error_message"]
    if seq[-1] in ("Aborted", "Cancelled"):
        assert h["error_message"] == f"SCX에서 취소됨({seq[-1]})"
        assert "SCX에서 취소됨" in j["failure_message"]  # 사용자 취소 없이도 작업이 계속 대기하지 않고 끝남


def test_scx_verify_cancelling_stays_running_and_unknown_warns_once(scx_env):
    """Cancelling은 RUNNING 유지(끝나지 않음). 알 수 없는 원문은 UNKNOWN 계수 + 작업 경고 1회(같은 원문 반복 없음)."""
    c, w, ai, fake = scx_env
    sid, pj = _setup_predict(c, w, ai, "SV3b")
    fake.status_seq = ["Cancelling", "Weird", "Running", "Weird"]
    vid = _verify(c, sid, pj)
    assert w.run_once_slot() == "WAITING_HPC"
    w.poll_hpc_once()
    assert _hpc(c, vid)[0]["state"] == "RUNNING"
    for _ in range(3):  # Weird → Running(계수 초기화) → Weird: 같은 원문이라 경고는 1회
        w.poll_hpc_once()
    h = _hpc(c, vid)[0]
    assert h["state"] == "RUNNING" and h["external_state_raw"] == "Weird"
    j = _job(c, vid)
    assert j["state"] == "WAITING_HPC"
    assert [x["code"] for x in j["warnings"]].count("SCX_UNKNOWN_STATUS") == 1
    assert "Weird" in next(x["message"] for x in j["warnings"] if x["code"] == "SCX_UNKNOWN_STATUS")


def test_scx_verify_unreachable_keeps_state(scx_env):
    """연결 실패·DRIVE_BUSY → 상태 유지 + hpc_unreachable_since, 회복되면 지움."""
    c, w, ai, fake = scx_env
    sid, pj = _setup_predict(c, w, ai, "SV4")
    vid = _verify(c, sid, pj)
    assert w.run_once_slot() == "WAITING_HPC"
    fake.busy_status = 1
    w.poll_hpc_once()
    j = _job(c, vid)
    assert j["state"] == "WAITING_HPC" and j["result"].get("hpc_unreachable_since")
    assert _hpc(c, vid)[0]["state"] == "QUEUED"
    fake.drop_all = True
    w.poll_hpc_once()
    fake.drop_all = False
    w.poll_hpc_once()
    j = _job(c, vid)
    assert "hpc_unreachable_since" not in j["result"]


def test_scx_verify_cancel_terminates(scx_env):
    c, w, ai, fake = scx_env
    sid, pj = _setup_predict(c, w, ai, "SV5")
    vid = _verify(c, sid, pj)
    assert w.run_once_slot() == "WAITING_HPC"
    assert c.post(f"{API}/jobs/{vid}/cancel", headers=AW).status_code == 202
    w.poll_hpc_once()
    assert _job(c, vid)["state"] == "CANCELED"
    assert fake.terminated == [_hpc(c, vid)[0]["external_job_id"]]


def test_scx_housekeeping_orphan_submitting(scx_env, engine):
    """워커 중단 후 남은 SUBMITTING: 제출 단계였으면 UNKNOWN + submission_unknown, 업로드 단계였으면 FAILED."""
    import uuid

    from physicsai_worker import housekeeping

    c, w, ai, fake = scx_env
    sid, pj = _setup_predict(c, w, ai, "SV6")
    with engine.begin() as conn:
        step = conn.execute(text("select id from job_steps where job_id=:j order by step_no limit 1"), {"j": pj}).scalar()
        ids = []
        for i, phase in enumerate(("submit", "stage_in")):
            hid = str(uuid.uuid4())
            ids.append(hid)
            conn.execute(text("insert into hpc_jobs(id, job_id, step_id, run_key, attempt_no, gateway_mode, state, request_id, staged)"
                              " values (:i,:j,:s,:r,1,'scx','SUBMITTING',:q,cast(:st as jsonb))"),
                         {"i": hid, "j": pj, "s": step, "r": f"r{i}", "q": "pai-" + hid, "st": f'{{"phase": "{phase}"}}'})
    out = housekeeping.scx_submitting_orphans(engine)
    assert out == {"unknown": [ids[0]], "failed": [ids[1]]}
    with engine.connect() as conn:
        rows = dict(conn.execute(text("select id, state || ':' || submission_unknown::text from hpc_jobs where id = any(:ids)"),
                                 {"ids": ids}).all())
    assert rows == {ids[0]: "UNKNOWN:true", ids[1]: "FAILED:false"}
    assert housekeeping.scx_submitting_orphans(engine) == {"unknown": [], "failed": []}


def test_scx_stage_in_paused_then_timeout(scx_env, monkeypatch):
    """묶음 PAUSED(재로그인 필요)는 계속 기다리고, stage_timeout_s를 넘으면 SCX_STAGE_IN_FAILED(제출 0건)."""
    from physicsai_worker.steps import _scx

    c, w, ai, fake = scx_env
    sid, pj = _setup_predict(c, w, ai, "SV7")
    clock = {"t": 0.0}

    class FakeTime:
        @staticmethod
        def monotonic():
            clock["t"] += 30.0
            return clock["t"]

        @staticmethod
        def sleep(_s):
            pass

    monkeypatch.setattr(_scx, "time", FakeTime)
    fake.batch_steps = ["PAUSED"] * 100
    vid = _verify(c, sid, pj)
    assert w.run_once_slot() == "FAILED"
    j = _job(c, vid)
    assert j["failure_code"] == "SCX_STAGE_IN_FAILED" and "초 안에" in j["failure_message"]
    assert fake.adapter_calls == [] and _hpc(c, vid)[0]["state"] == "FAILED"
    # PAUSED 뒤 DONE → 정상 진행
    import time as real_time

    monkeypatch.setattr(_scx, "time", real_time)  # 실제 시계(stage_poll_s 1초 × 2)
    fake.batch_steps = ["PAUSED", "PAUSED", "DONE"]
    vid2 = _verify(c, sid, pj)
    assert w.run_once_slot() == "WAITING_HPC", _job(c, vid2)["failure_message"]


def test_scx_resolve_on_finished_job_only_mark_not_submitted(scx_env, engine):
    """minor b: 작업이 WAITING_HPC가 아니면(중단 등) recheck·attach는 409 HPC_RESOLVE_NOT_ALLOWED, mark_not_submitted만 처리."""
    c, w, ai, fake = scx_env
    sid, pj = _setup_predict(c, w, ai, "SV8")
    fake.submit_mode = "unknown"
    vid = _verify(c, sid, pj)
    assert w.run_once_slot() == "WAITING_HPC"
    with engine.begin() as conn:
        conn.execute(text("update jobs set state='FAILED', finished_at=now(), failure_code='WORKER_LOST' where id=:j"), {"j": vid})
    h = _hpc(c, vid)[0]
    url = f"{API}/jobs/{vid}/hpc-jobs/{h['id']}/resolve"
    for body in ({"action": "recheck"}, {"action": "attach", "external_job_id": "scx-1"}):
        r = c.post(url, headers=PW, json={**body, "version": h["version"]})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "HPC_RESOLVE_NOT_ALLOWED", r.text
    r = c.post(url, headers=PW, json={"action": "mark_not_submitted", "version": h["version"]})
    assert r.status_code == 202
    w.poll_hpc_once()
    h = _hpc(c, vid)[0]
    assert h["state"] == "FAILED" and h["resolve_pending"] is False and _job(c, vid)["state"] == "FAILED"


def test_scx_external_state_raw_masked_and_capped_128(scx_env):
    """external_state_raw는 비밀(Bearer 토큰)을 마스킹하고 128자로 자른다."""
    c, w, ai, fake = scx_env
    sid, pj = _setup_predict(c, w, ai, "SV3c")
    fake.status_seq = ["Running", "Bearer abc.def.ghi " + "x" * 300]
    vid = _verify(c, sid, pj)
    assert w.run_once_slot() == "WAITING_HPC"
    w.poll_hpc_once()
    w.poll_hpc_once()
    raw = _hpc(c, vid)[0]["external_state_raw"]
    assert raw and len(raw) <= 128 and "abc.def.ghi" not in raw and raw.startswith("Bearer ***")
