"""v0.2.14 이슈 #14 "FEM 검증 강제 취소": 취소를 눌러도 검증 목록이 '실행 중'으로 남고 취소 버튼이 그대로이던 결함.

원인: HPC 대기(WAITING_HPC) 취소(T12, 폴러)가 종료 부수효과(`_side_effects_on_end`)를 부르지 않아 작업은 CANCELED인데 검증 행은
RUNNING으로 남았다(`cancel_waiting`). 그 밖에 취소 요청 뒤 응답이 계속 '실행 중'·취소 버튼 유지, lease가 끊긴 고아 작업은 취소가 끝나지 않음.
세 상황 — 실행 중(RUNNING)·대기 중(QUEUED)·HPC 대기 중(WAITING_HPC) — 과 이미 어긋난 옛 행 복구, 원격 취소 실패를 다룬다."""

from __future__ import annotations

import pytest

from physicsai_core.hpc.gateway import HpcGatewayError, HpcStatus
from physicsai_test_support import API, H

from .fv_support import P, PW, create, detail, fv_env, predict, run_until_hpc

AW = H("tok-admin", write=True)


@pytest.fixture(autouse=True)
def _fast_collect(monkeypatch, pbs_state):
    from physicsai_worker.steps import _collect

    monkeypatch.setattr(_collect, "COLLECT_STABLE_INTERVAL_S", 0.02)


def _cancel(env, fid, headers=PW):
    r = env.c.post(f"{API}/fem-verifications/{fid}/cancel", headers=headers)
    assert r.status_code == 202, r.text
    return r.json()


def _listed(env, fid):
    r = env.c.get(f"{API}/studies/{env.sid}/fem-verifications", headers=P)
    assert r.status_code == 200, r.text
    return next(x for x in r.json() if x["id"] == fid)


def _running_with_lease(env, jid, *, live: bool) -> None:
    """FEM_VERIFY를 RUNNING으로(워커 lease 있음 = 살아 있음 / 만료 = 고아)."""
    iv = "interval '1 hour'"
    acq, exp = ("now()", f"now() + {iv}") if live else (f"now() - interval '2 hour'", f"now() - {iv}")
    env.sql("update jobs set state='RUNNING', queue_seq=NULL, started_at=now(), lease_owner_id='w-x', lease_token='t-x',"
            f" lease_acquired_at={acq}, lease_expires_at={exp}, version=version+1 where id=:j", j=jid)


def test_waiting_hpc_cancel_marks_cancelling_then_canceled(predict_env, fake_tools, tmp_path):
    """HPC 대기 중 취소 → 즉시 '취소 중'(버튼 비활성) → 폴러가 T12 → 검증 행도 CANCELED(이슈 #14 원인)."""
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    pj = predict(env)
    d = create(env, {"source": {"kind": "predict_job", "job_id": pj}})
    d = run_until_hpc(env, d["id"])
    assert d["job"]["state"] == "WAITING_HPC" and d["can_cancel"] is True and d["cancel_requested"] is False
    r = _cancel(env, d["id"])
    assert r["status"] == "RUNNING" and r["status_text"] == "취소 중" and r["cancel_requested"] is True and r["can_cancel"] is False
    row = _listed(env, d["id"])
    assert row["status"] == "RUNNING" and row["cancel_requested"] is True
    _cancel(env, d["id"])  # 멱등
    env.w.poll_hpc_once()
    assert env.job(d["job"]["id"])["state"] == "CANCELED"
    d = detail(env, d["id"])
    assert d["status"] == "CANCELED" and d["can_cancel"] is False and d["can_rerun"] is True and d["cancel_requested"] is False
    assert _listed(env, d["id"])["status"] == "CANCELED"


def test_queued_cancel_is_immediate(predict_env, fake_tools, tmp_path):
    """대기 중(QUEUED) 취소는 서버가 바로 CANCELED(T3) — 검증 행도 같은 트랜잭션."""
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    pj = predict(env)
    d = create(env, {"source": {"kind": "predict_job", "job_id": pj}})
    assert d["status"] == "RUNNING" and d["job"]["state"] == "QUEUED"
    r = _cancel(env, d["id"])
    assert r["status"] == "CANCELED" and r["cancel_requested"] is False and r["can_cancel"] is False
    assert env.job(d["job"]["id"])["state"] == "CANCELED"
    assert _listed(env, d["id"])["status"] == "CANCELED"


def test_running_cancel_shows_cancelling_until_worker_confirms(predict_env, fake_tools, tmp_path):
    """실행 중(lease 살아 있음): 서버는 CANCELED로 확정하지 않는다(워커가 다음 확인 지점에서 T8). 그동안 '취소 중'."""
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    pj = predict(env)
    d = create(env, {"source": {"kind": "predict_job", "job_id": pj}})
    _running_with_lease(env, d["job"]["id"], live=True)
    r = _cancel(env, d["id"])
    assert env.job(d["job"]["id"])["state"] == "RUNNING"
    assert r["status"] == "RUNNING" and r["status_text"] == "취소 중" and r["cancel_requested"] is True and r["can_cancel"] is False
    assert _listed(env, d["id"])["cancel_requested"] is True


def test_running_orphan_cancel_finalized_by_server(predict_env, fake_tools, tmp_path):
    """실행 중이라고 적혀 있지만 lease가 만료된 고아 작업: 취소 요청이 바로 CANCELED(리퍼가 INTERRUPTED로 만들 작업)."""
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    pj = predict(env)
    d = create(env, {"source": {"kind": "predict_job", "job_id": pj}})
    _running_with_lease(env, d["job"]["id"], live=False)
    r = _cancel(env, d["id"])
    assert env.job(d["job"]["id"])["state"] == "CANCELED"
    assert r["status"] == "CANCELED" and r["can_cancel"] is False and r["can_rerun"] is True


def test_reaper_cancels_expired_job_with_cancel_request(predict_env, fake_tools, tmp_path):
    """취소 요청 뒤 워커가 죽어 lease가 만료되면 리퍼가 INTERRUPTED가 아니라 CANCELED로(사용자는 취소를 요청했다)."""
    from physicsai_core.db.repositories import job_lease_end

    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    pj = predict(env)
    d = create(env, {"source": {"kind": "predict_job", "job_id": pj}})
    _running_with_lease(env, d["job"]["id"], live=True)
    _cancel(env, d["id"])
    env.sql("update jobs set lease_acquired_at=now() - interval '2 hour', lease_expires_at=now() - interval '1 hour' where id=:j",
            j=d["job"]["id"])
    with env.engine.begin() as conn:
        assert job_lease_end.reap_expired(conn) == [d["job"]["id"]]
    assert env.job(d["job"]["id"])["state"] == "CANCELED"
    assert detail(env, d["id"])["status"] == "CANCELED"


def test_stuck_row_from_old_bug_is_repaired(predict_env, fake_tools, tmp_path):
    """v0.2.13까지 어긋난 행(작업 CANCELED·검증 RUNNING): 취소 API가 바로잡고, 하우스키핑도 같은 정리를 한다."""
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    pj = predict(env)
    d = create(env, {"source": {"kind": "predict_job", "job_id": pj}})
    d = run_until_hpc(env, d["id"])
    env.sql("update jobs set state='CANCELED', finished_at=now(), version=version+1 where id=:j", j=d["job"]["id"])
    assert detail(env, d["id"])["status"] == "RUNNING"  # 재현: 작업은 끝났는데 검증은 진행 중
    env.w.housekeeping_once()
    assert detail(env, d["id"])["status"] == "CANCELED"
    # API 경로(하우스키핑 전에 사용자가 취소를 누른 경우)
    d2 = create(env, {"source": {"kind": "values", "param_set_id": ps["id"], "values": {"THK_1": 3.3, "N_RIB": 5}}})
    env.sql("update jobs set state='CANCELED', queue_seq=NULL, finished_at=now(), version=version+1 where id=:j",
            j=d2["predict"]["job_id"])
    r = _cancel(env, d2["id"])
    assert r["status"] == "CANCELED" and r["can_cancel"] is False


def _hpc_row(env, jid):
    return env.sql("select id, external_job_id, state from hpc_jobs where job_id=:j", j=jid)[0]


def test_remote_cancel_failure_but_remote_already_finished(predict_env, fake_tools, tmp_path, monkeypatch):
    """SCX·PBS 취소 명령이 실패해도 원격 잡이 이미 끝났으면(조회로 확인) 취소를 마친다 — '취소 실패'로 영영 남지 않는다."""
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    pj = predict(env)
    d = create(env, {"source": {"kind": "predict_job", "job_id": pj}})
    d = run_until_hpc(env, d["id"])
    _cancel(env, d["id"])

    def boom(_ext):
        raise HpcGatewayError("UNAVAILABLE", "취소 실패")

    monkeypatch.setattr(env.w.hpc, "cancel", boom)
    monkeypatch.setattr(env.w.hpc, "status", lambda _e: HpcStatus("FINISHED", "F", 0, False))
    env.w.poll_hpc_once()
    assert env.job(d["job"]["id"])["state"] == "CANCELED"
    assert detail(env, d["id"])["status"] == "CANCELED"


def test_remote_cancel_failure_still_running_keeps_waiting(predict_env, fake_tools, tmp_path, monkeypatch):
    """원격 잡이 아직 살아 있는데 취소 명령이 실패하면 계약(phase2 C18)대로 WAITING_HPC 유지·주의 표시, 다음 주기에 재시도.
    화면은 '취소 중'(버튼 비활성)이지 '실행 중'이 아니다."""
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    pj = predict(env)
    d = create(env, {"source": {"kind": "predict_job", "job_id": pj}})
    d = run_until_hpc(env, d["id"])
    _cancel(env, d["id"])

    def boom(_ext):
        raise HpcGatewayError("UNAVAILABLE", "취소 실패")

    monkeypatch.setattr(env.w.hpc, "cancel", boom)
    monkeypatch.setattr(env.w.hpc, "status", lambda _e: HpcStatus("RUNNING", "R", None, False))
    env.w.poll_hpc_once()
    j = env.job(d["job"]["id"])
    assert j["state"] == "WAITING_HPC" and j["attention_code"] == "HPC_CANCEL_FAILED"
    d = detail(env, d["id"])
    assert d["status"] == "RUNNING" and d["status_text"] == "취소 중" and d["can_cancel"] is False
    monkeypatch.undo()
    env.w.poll_hpc_once()
    assert env.job(d["job"]["id"])["state"] == "CANCELED"
    assert detail(env, d["id"])["status"] == "CANCELED"
