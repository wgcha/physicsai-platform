"""S16 V2 조립 FEM 검증 API(phase3 §21.3.2·§21.3.8·§21.3.9): V3-S16-5(출처 해석), V3-S16-7(미리보기·생성·409·422·권한·감사),
V3-S16-14(종료 훅), V3-S16-15(재시도·다시 실행·취소), V3-S16-16(목록·상세·404), V3-S16-17(경로 확인·SPDM 탐색)."""

from __future__ import annotations

import json
import os
import shutil
import uuid

import pytest
from sqlalchemy import text

from physicsai_test_support import API, H, make_assem_files, make_model_folder

from .fv_support import P, PW, RESULT_FILES, VALUES, create, detail, finish_hpc, fv_env, predict, preview, ready_doe, run_until_hpc
from .test_predict_prepared import make_case

G = H("tok-general")
GW = H("tok-general", write=True)
PW2 = H("tok-power2", write=True)
AW = H("tok-admin", write=True)


@pytest.fixture(autouse=True)
def _fast_collect(monkeypatch, pbs_state):
    from physicsai_worker.steps import _collect

    monkeypatch.setattr(_collect, "COLLECT_STABLE_INTERVAL_S", 0.02)


def _codes(items) -> list[str]:
    return [x["code"] for x in items]


def _end(engine, job_id: str, state: str, failure_code: str | None = None) -> None:
    """작업 종료 흉내(lease 해제와 같은 부수효과·알림 순서)."""
    from physicsai_core.db.repositories import jobs as jobs_repo
    from physicsai_core.db.repositories import notifications as notif_repo
    from physicsai_core.db.repositories.job_end import _side_effects_on_end

    with engine.begin() as conn:
        j = jobs_repo.get_job(conn, job_id)
        conn.execute(text("update jobs set state=:s, holds_slot=false, queue_seq=null, finished_at=now(), failure_code=:fc,"
                          " failure_message=:fm where id=:i"),
                     {"s": state, "fc": failure_code, "fm": "실패 사유" if failure_code else None, "i": job_id})
        _side_effects_on_end(conn, j, state)
        notif_repo.notify_job(conn, job_id, {"SUCCEEDED": "JOB_SUCCEEDED", "FAILED": "JOB_FAILED", "CANCELED": "JOB_CANCELED"}[state])


def _resume(env, job_id: str):
    return env.sql("select resume_from_step from jobs where id=:i", i=job_id)[0][0]


def _notifs(engine, job_id: str) -> list[str]:
    with engine.connect() as c:
        return [e for (e,) in c.execute(text("select event from notifications where job_id=:j order by seq"), {"j": job_id})]


# ---- V3-S16-5 출처 해석 -------------------------------------------------------------------------------


def test_v3_s16_5_sources(predict_env, fake_tools, tmp_path):
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    did, _assem = ready_doe(env)
    pj = predict(env)
    # predict_job(조립 템플릿) → 기본 predict_input(reuse), 메시 원천 있음
    pv = preview(env, {"source": {"kind": "predict_job", "job_id": pj}})
    assert pv["problems"] == [] and pv["predict"] == {"job_id": pj, "state": "SUCCEEDED", "reuse": True, "will_run": False,
                                                      "companion": False}
    assert pv["input_mode"] == "reuse" and pv["assembly"]["kind"] == "PREDICT_INPUT" and pv["assembly"]["starter"] == "model0_0000.rad"
    assert pv["mesh"]["available"] is True and pv["mesh"]["path"] == str(env.predict_dir(pj) / "geom" / "EPS_mesh_0000.rad")
    assert pv["design"]["values"] == VALUES and pv["design"]["param_set"]["id"] == ps["id"] and pv["hpc_mode"] == "command"
    assert pv["source_label"].startswith("④ 예측 ") and pv["fem_field"] == "CornerStress"
    # train_doe 지정 → rebuild, 요약
    pv = preview(env, {"source": {"kind": "predict_job", "job_id": pj}, "assembly": {"kind": "train_doe", "doe_id": did}})
    a = pv["assembly"]
    assert pv["input_mode"] == "rebuild" and a["label"] == "DOE-001" and a["starter"] == "model0_0000.rad"
    assert (a["renum_csv"], a["include_baseline"], a["include_referenced"], a["file_count"]) == (True, True, True, 4)
    # values: 같은 값 → 재사용, 다른 값·reuse_existing=false → 동반 예측
    base = {"kind": "values", "param_set_id": ps["id"], "values": VALUES}
    assert preview(env, {"source": base})["predict"]["job_id"] == pj
    pv = preview(env, {"source": {**base, "values": {"THK_1": 3.0 + 1e-12, "N_RIB": 4}}})
    assert pv["predict"]["job_id"] == pj                                                  # |Δ| ≤ 1e-9
    for src in ({**base, "values": {"THK_1": 3.5, "N_RIB": 4}}, {**base, "reuse_existing": False}):
        pv = preview(env, {"source": src})
        assert pv["predict"] == {"job_id": None, "state": None, "reuse": False, "will_run": True, "companion": True}, src
        assert pv["input_mode"] == "reuse" and pv["mesh"]["available"] is True
    pv = preview(env, {"source": {**base, "values": {"THK_1": 9.0, "N_RIB": 4}}})
    assert "OUT_OF_RANGE" in _codes(pv["warnings"])
    r = env.c.post(f"{API}/studies/{env.sid}/fem-verifications/preview", headers=PW,
                   json={"source": {**base, "values": {"THK_1": 3.0}}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS"
    # 다른 모델 → 동반
    mf = make_model_folder(env.sroot / "00_inbox", name="M2")
    jb = env.submit("MODEL_REGISTER", {"model_path": str(mf)})
    assert env.w.run_once_light() == "SUCCEEDED"
    m2 = env.job(jb["id"])["result"]["model_id"]
    assert preview(env, {"source": {**base, "model_id": m2}})["predict"]["companion"] is True
    # INPUT이 정리됨 → 동반
    shutil.move(str(env.predict_dir(pj) / "INPUT"), str(env.sroot / "_moved_input"))
    assert preview(env, {"source": base})["predict"]["companion"] is True
    pv = preview(env, {"source": {"kind": "predict_job", "job_id": pj}})                 # INPUT 없음 → 기본 = 최신 DOE
    assert pv["assembly"]["kind"] == "TRAIN_DOE"
    shutil.move(str(env.sroot / "_moved_input"), str(env.predict_dir(pj) / "INPUT"))
    # predict_job 실패 → PREDICT_NOT_SUCCEEDED, 없는 작업 → SOURCE_NOT_FOUND
    env.lc.settings  # noqa: B018
    bad = env.submit("PREDICT", {"values": {"THK_1": 4.0, "N_RIB": 6}, "value_source": "manual"})
    env.sql("update jobs set state='FAILED', queue_seq=null, failure_code='X' where id=:i", i=bad["id"])
    assert "PREDICT_NOT_SUCCEEDED" in _codes(preview(env, {"source": {"kind": "predict_job", "job_id": bad["id"]}})["problems"])
    assert _codes(preview(env, {"source": {"kind": "predict_job", "job_id": str(uuid.uuid4())}})["problems"]) == ["SOURCE_NOT_FOUND"]
    # prepared(비배치, 조립 상태) → predict_input 가능, rebuild는 MESH_MISSING
    jprep = env.submit("PREDICT", {"input_mode": "prepared", "input_path": str(make_case(env.imports))})
    assert env.w.run_once_slot() == "SUCCEEDED"
    pv = preview(env, {"source": {"kind": "predict_job", "job_id": jprep["id"]}})
    assert pv["problems"] == [] and pv["input_mode"] == "reuse"
    pv = preview(env, {"source": {"kind": "predict_job", "job_id": jprep["id"]}, "assembly": {"kind": "train_doe", "doe_id": did}})
    assert "MESH_MISSING" in _codes(pv["problems"])
    # batch_run: run의 predict_job_id(성공) → 해석, 메시 원천 = B/run__N/m_1
    bid, _bj = env.make_batch(ps["id"], "THK_1\tN_RIB\n3.0\t4\n4.0\t6\n")
    env.sql("update predict_batch_runs set predict_job_id=:j where batch_id=:b and doe_no=1", j=pj, b=bid)
    pv = preview(env, {"source": {"kind": "batch_run", "batch_id": bid, "doe_no": 1}})
    assert pv["predict"]["job_id"] == pj and pv["source_label"] == "B-001 DOE #1"
    pv = preview(env, {"source": {"kind": "batch_run", "batch_id": bid, "doe_no": 2}})
    assert _codes(pv["problems"]) == ["PREDICT_NOT_SUCCEEDED"]
    # opt_design: best → 배치 run, final_optimum 없음 → OPT_DESIGN_UNAVAILABLE, surrogate_optimum → values 규칙, run → 반복 배치
    oid = str(uuid.uuid4())
    env.sql("insert into surrogate_opts(id, study_id, opt_no, param_set_id, model_id, input_kind, settings, status, best,"
            " dir_rel, created_by, created_by_name) values (:i,:s,1,:p,:m,'assembly','{}','DONE',cast(:b as jsonb),"
            " '05_surrogate/SO-001','u-power','파워')",
            i=oid, s=env.sid, p=ps["id"], m=env.model_id, b=json.dumps({"batch_id": bid, "doe_no": 1}))
    env.sql("insert into surrogate_opt_iters(opt_id, iter_no, kind, batch_id, candidates) values (:o, 1, 'VERIFY', :b,"
            " cast(:c as jsonb))", o=oid, b=bid, c=json.dumps([{"values": {"THK_1": 3.0, "N_RIB": 4}}]))
    pv = preview(env, {"source": {"kind": "opt_design", "opt_id": oid, "pick": "best"}})
    assert pv["predict"]["job_id"] == pj and pv["source_label"] == "⑥ SO-001 최적 설계"
    assert _codes(preview(env, {"source": {"kind": "opt_design", "opt_id": oid, "pick": "final_optimum"}})["problems"]) == \
        ["OPT_DESIGN_UNAVAILABLE"]
    pv = preview(env, {"source": {"kind": "opt_design", "opt_id": oid, "pick": "surrogate_optimum"}})
    assert pv["predict"]["job_id"] == pj and pv["design"]["values"] == VALUES                # 최신 후보 1위 → 기존 예측 재사용
    pv = preview(env, {"source": {"kind": "opt_design", "opt_id": oid, "pick": "run", "iter_no": 1, "doe_no": 1}})
    assert pv["predict"]["job_id"] == pj
    r = env.c.post(f"{API}/studies/{env.sid}/fem-verifications/preview", headers=PW,
                   json={"source": {"kind": "opt_design", "opt_id": oid, "pick": "run"}})
    assert r.status_code == 422


def test_v3_s16_5_mesh_only_input(predict_env, fake_tools, tmp_path):
    env, ps = fv_env(predict_env, fake_tools, tmp_path, mesh_only=True)
    pj = predict(env)
    pv = preview(env, {"source": {"kind": "predict_job", "job_id": pj}})
    assert _codes(pv["problems"]) == ["ASSEMBLY_REQUIRED"] and pv["input_mode"] is None   # DOE 없음
    pv = preview(env, {"source": {"kind": "predict_job", "job_id": pj}, "assembly": {"kind": "predict_input"}})
    assert _codes(pv["problems"]) == ["INPUT_MESH_ONLY"]
    did, _a = ready_doe(env)
    pv = preview(env, {"source": {"kind": "predict_job", "job_id": pj}})
    assert pv["problems"] == [] and pv["assembly"]["kind"] == "TRAIN_DOE"
    assert "FEM_RESPONSE_WHOLE_MODEL" in _codes(pv["warnings"])
    env.sql("update train_does set status='BUILDING' where id=:i", i=did)
    pv = preview(env, {"source": {"kind": "predict_job", "job_id": pj}, "assembly": {"kind": "train_doe", "doe_id": did}})
    assert _codes(pv["problems"]) == ["DOE_NOT_READY"]
    env.sql("update train_does set status='READY', parameters_snapshot='[{\"name\": \"OTHER\"}]' where id=:i", i=did)
    pv = preview(env, {"source": {"kind": "predict_job", "job_id": pj}})
    assert "DOE_PARAM_MISMATCH" in _codes(pv["warnings"]) and pv["problems"] == []


# ---- V3-S16-7 생성 ----------------------------------------------------------------------------------


def test_v3_s16_7_create_rules(predict_env, fake_tools, tmp_path, engine):
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    pj = predict(env)
    n_jobs = env.sql("select count(*) from jobs")[0][0]
    preview(env, {"source": {"kind": "predict_job", "job_id": pj}})
    assert env.sql("select count(*) from fem_verifications")[0][0] == 0 and env.sql("select count(*) from jobs")[0][0] == n_jobs
    # 동반 → WAITING_PREDICT + PREDICT QUEUED(params.fem_verify_id), 알림 억제
    d1 = create(env, {"source": {"kind": "values", "param_set_id": ps["id"], "values": {"THK_1": 3.5, "N_RIB": 5}}})
    assert (d1["label"], d1["status"], d1["predict"]["companion"], d1["job"]) == ("FV-001", "WAITING_PREDICT", True, None)
    cj = env.job(d1["predict"]["job_id"])
    assert cj["state"] == "QUEUED" and cj["params"]["fem_verify_id"] == d1["id"] and cj["params"]["input_mode"] == "parametric"
    assert d1["status_text"] == "예측 실행 중" and d1["can_cancel"] is True and d1["can_rerun"] is False
    # 재사용 → RUNNING + FEM_VERIFY QUEUED, 연번
    d2 = create(env, {"source": {"kind": "predict_job", "job_id": pj}, "hpc": {"ncpus": 16}})
    assert (d2["label"], d2["status"], d2["job"]["job_type"], d2["job"]["state"]) == ("FV-002", "RUNNING", "FEM_VERIFY", "QUEUED")
    fj = env.job(d2["job"]["id"])
    assert fj["params"] == {"fem_verify_id": d2["id"], "fv_no": 2, "hpc": {"queue": None, "ncpus": 16, "walltime": None}}
    assert fj["stage_label"] == "④"
    # 같은 예측·같은 조립 원본 → 409
    r = env.c.post(f"{API}/studies/{env.sid}/fem-verifications", headers=PW, json={"source": {"kind": "predict_job", "job_id": pj}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FEM_VERIFY_ACTIVE"
    env.lc.settings.fem_verify.max_active = 2
    did, _a = ready_doe(env)
    r = env.c.post(f"{API}/studies/{env.sid}/fem-verifications", headers=PW,
                   json={"source": {"kind": "predict_job", "job_id": pj}, "assembly": {"kind": "train_doe", "doe_id": did}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FEM_VERIFY_LIMIT"
    assert r.json()["detail"]["message"] == "진행 중인 FEM 검증이 2건입니다(상한 2)"
    env.lc.settings.fem_verify.max_active = 4
    # 422: 문제 목록 / POST /jobs FEM_VERIFY·fem_verify_id
    r = env.c.post(f"{API}/studies/{env.sid}/fem-verifications", headers=PW,
                   json={"source": {"kind": "predict_job", "job_id": str(uuid.uuid4())}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "FEM_VERIFY_INVALID"
    assert _codes(r.json()["detail"]["problems"]) == ["SOURCE_NOT_FOUND"]
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW, json={"job_type": "FEM_VERIFY", "params": {}})
    assert r.status_code == 422
    r = env.c.post(f"{API}/studies/{env.sid}/jobs", headers=PW,
                   json={"job_type": "PREDICT", "params": {"values": VALUES, "value_source": "manual", "fem_verify_id": "x"}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS"
    # 권한: 생성·미리보기 power, 조회 member, 취소 등록자·관리자
    r = env.c.post(f"{API}/studies/{env.sid}/fem-verifications/preview", headers=GW, json={"source": {"kind": "predict_job", "job_id": pj}})
    assert r.status_code == 403
    assert env.c.get(f"{API}/fem-verifications/{d2['id']}", headers=G).status_code == 200
    assert env.c.get(f"{API}/studies/{env.sid}/fem-verifications", headers=G).status_code == 200
    assert env.c.get(f"{API}/fem-verifications/{d2['id']}").status_code == 401
    assert env.c.post(f"{API}/fem-verifications/{d2['id']}/cancel", headers=PW2).status_code == 403
    # 감사
    with engine.connect() as c:
        acts = [a for (a,) in c.execute(text("select action from audit_events where target_id in (:a, :b)"),
                                        {"a": d1["id"], "b": d2["id"]})]
    assert sorted(acts) == ["FEM_VERIFY_CREATE", "FEM_VERIFY_CREATE"]


def test_v3_s16_7_conflicts(predict_env, fake_tools, tmp_path):
    env0, ps0 = fv_env(predict_env, fake_tools, tmp_path, folder="nohpc", hpc={"gateway": "none"})
    pj0 = predict(env0)
    r = env0.c.post(f"{API}/studies/{env0.sid}/fem-verifications/preview", headers=PW, json={"source": {"kind": "predict_job", "job_id": pj0}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "HPC_NOT_CONFIGURED"
    env, ps = fv_env(predict_env, fake_tools, tmp_path, folder="cf")
    pj = predict(env)
    env.lc.settings.fem_verify.enabled = False
    r = env.c.post(f"{API}/studies/{env.sid}/fem-verifications", headers=PW, json={"source": {"kind": "predict_job", "job_id": pj}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FEATURE_NOT_AVAILABLE"
    st = env.c.get(f"{API}/status", headers=P).json()["features"]
    assert st["fem_verify"]["enabled"] is False and "fem_verify.enabled" in st["fem_verify"]["missing"]
    env.lc.settings.fem_verify.enabled = True
    st = env.c.get(f"{API}/status", headers=P).json()["features"]
    assert st["fem_verify"]["enabled"] is True and st["fem_verify_rebuild"]["enabled"] is True
    did, _a = ready_doe(env)
    env.lc.settings.commands.mesh = None
    r = env.c.post(f"{API}/studies/{env.sid}/fem-verifications", headers=PW,
                   json={"source": {"kind": "predict_job", "job_id": pj}, "assembly": {"kind": "train_doe", "doe_id": did}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "TEMPLATE_NOT_CONFIGURED"
    env.lc.settings.commands.mesh = ["{hw}", "-b", "{rendered_script}", "{simlab_mesh}"]
    pv = preview(env, {"source": {"kind": "predict_job", "job_id": pj}, "assembly": {"kind": "train_doe", "doe_id": did}})
    assert "MESH_TEMPLATE_PLACEHOLDER" in _codes(pv["problems"])
    env2, ps2 = fv_env(predict_env, fake_tools, tmp_path, folder="nofinal", final_model=False)
    r = env2.c.post(f"{API}/studies/{env2.sid}/fem-verifications", headers=PW,
                    json={"source": {"kind": "values", "param_set_id": ps2["id"], "values": VALUES}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FINAL_MODEL_REQUIRED"
    env.sql("update studies set status='ARCHIVED' where id=:i", i=env.sid)
    r = env.c.post(f"{API}/studies/{env.sid}/fem-verifications", headers=PW, json={"source": {"kind": "predict_job", "job_id": pj}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "STUDY_ARCHIVED"


# ---- V3-S16-14 종료 훅 -------------------------------------------------------------------------------


def test_v3_s16_14_hooks(predict_env, fake_tools, tmp_path, engine):
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    pj4 = predict(env, {"THK_1": 2.5, "N_RIB": 3})                                        # 재사용 대상(먼저 실행)
    src = lambda t: {"source": {"kind": "values", "param_set_id": ps["id"], "values": {"THK_1": t, "N_RIB": 4}}}  # noqa: E731
    d = create(env, src(3.1))
    cj = d["predict"]["job_id"]
    assert env.w.run_once_slot() == "SUCCEEDED"                                           # 실제 예측 → 훅 → FEM_VERIFY
    d = detail(env, d["id"])
    assert d["status"] == "RUNNING" and d["job"]["state"] == "QUEUED" and d["job"]["created_by"] == "u-power"
    assert "JOB_SUCCEEDED" not in _notifs(engine, cj) and "JOB_STARTED" not in _notifs(engine, cj)  # 동반 예측 알림 억제
    # FEM_VERIFY 성공 → DONE·알림 1건(응답 비교 없음 문구), 멱등
    fj = d["job"]["id"]
    env.sql("update fem_verifications set summary=null where id=:i", i=d["id"])
    _end(engine, fj, "SUCCEEDED")
    d = detail(env, d["id"])
    assert d["status"] == "DONE" and d["finished_at"]
    with engine.connect() as c:
        titles = [t for (t,) in c.execute(text("select title from notifications where event='FEM_VERIFY_DONE'"))]
    assert titles == ["FEM 검증 FV-001 완료 — 응답 비교 없음"]
    from physicsai_core.db.repositories.fem_verifications import done_notice, on_job_end

    assert done_notice(3, {"max_abs_diff_pct": 7.2, "worst": "MaxStress"})[0] == "FEM 검증 FV-003 완료 — 최대 오차 7.2% (MaxStress)"
    with engine.begin() as c:
        on_job_end(c, env.job(fj) | {"params": env.job(fj)["params"]}, "FAILED")           # 이미 종료 → 아무것도 안 함
    assert detail(env, d["id"])["status"] == "DONE"
    # 동반 예측 실패 → FAILED PREDICT_FAILED(JOB_FAILED 알림 유지) / 재시도 → WAITING_PREDICT·predict_job_id 갱신
    d2 = create(env, src(3.2))
    c2 = d2["predict"]["job_id"]
    _end(engine, c2, "FAILED", "TOOL_FAILED")
    d2 = detail(env, d2["id"])
    assert (d2["status"], d2["failure"]) == ("FAILED", {"code": "PREDICT_FAILED", "message": "함께 실행한 예측이 실패했습니다"})
    assert _notifs(engine, c2) == ["JOB_FAILED"]
    r = env.c.post(f"{API}/jobs/{c2}/retry", headers=PW)
    assert r.status_code == 201, r.text
    d2 = detail(env, d2["id"])
    assert d2["status"] == "WAITING_PREDICT" and d2["predict"]["job_id"] == r.json()["id"] and d2["failure"] is None
    # 동반 예측 취소 → CANCELED
    d3 = create(env, src(3.3))
    _end(engine, d3["predict"]["job_id"], "CANCELED")
    assert detail(env, d3["id"])["status"] == "CANCELED"
    # FEM_VERIFY 실패 → FAILED(첫 실패 코드), JOB_FAILED 유지
    d4 = create(env, {"source": {"kind": "predict_job", "job_id": pj4}})
    _end(engine, d4["job"]["id"], "FAILED", "HPC_SUBMIT_FAILED")
    d4 = detail(env, d4["id"])
    assert d4["status"] == "FAILED" and d4["failure"]["code"] == "HPC_SUBMIT_FAILED"
    assert _notifs(engine, d4["job"]["id"]) == ["JOB_FAILED"]


# ---- V3-S16-15 재시도·다시 실행·취소 ----------------------------------------------------------------


def test_v3_s16_15_rerun_from_start_and_from_extract(predict_env, fake_tools, tmp_path, monkeypatch):
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    pj = predict(env)
    d = create(env, {"source": {"kind": "predict_job", "job_id": pj}})
    r = env.c.post(f"{API}/fem-verifications/{d['id']}/rerun", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FEM_VERIFY_NOT_RERUNNABLE"
    monkeypatch.setenv("FAKE_TOOL_MODE_PBS", "submit_fail")
    assert env.w.run_once_slot() == "FAILED"
    d = detail(env, d["id"])
    assert d["status"] == "FAILED" and d["failure"]["code"] == "HPC_SUBMIT_FAILED" and d["attempt_no"] == 1
    monkeypatch.delenv("FAKE_TOOL_MODE_PBS")
    r = env.c.post(f"{API}/fem-verifications/{d['id']}/rerun", headers=PW)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "RUNNING" and _resume(env, d["job"]["id"]) is None              # ≤ 6 → 1단계부터(새 시도)
    run_until_hpc(env, d["id"])
    d = detail(env, d["id"])
    assert d["attempt_no"] == 2 and (env.sroot / "04_verify" / "FV-001" / "a2" / "input").is_dir()
    # 후처리(FV_EXTRACT) 실패 → 그 step부터, 같은 시도
    d = finish_hpc(env, d["id"], {"model0_0000.out": b"x"})                               # h3d 없이 회수 → OUTPUT_MISSING
    assert d["status"] == "FAILED" and d["failure"]["code"] == "OUTPUT_MISSING"
    (env.sroot / "04_verify" / "FV-001" / "a2" / "result" / "model0_0000.h3d").write_bytes(b"late h3d")
    r = env.c.post(f"{API}/fem-verifications/{d['id']}/rerun", headers=PW)
    assert r.status_code == 201, r.text
    nj = r.json()["job"]["id"]
    assert _resume(env, nj) == 7
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(nj)
    steps = env.steps(nj)
    assert [steps[k]["state"] for k in ("FV_PREP", "HPC_SUBMIT", "COLLECT", "FV_EXTRACT")] == ["SKIPPED", "SKIPPED", "SKIPPED", "SUCCEEDED"]
    d = detail(env, d["id"])
    assert d["status"] == "DONE" and d["attempt_no"] == 2 and d["paths"]["input_dir"] == str(env.sroot / "04_verify" / "FV-001" / "a2" / "input")


def test_v3_s16_15_cancel_idempotent(predict_env, fake_tools, tmp_path, monkeypatch):
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    pj = predict(env, {"THK_1": 4.0, "N_RIB": 6})
    d = create(env, {"source": {"kind": "values", "param_set_id": ps["id"], "values": VALUES}})
    assert d["status"] == "WAITING_PREDICT"
    r = env.c.post(f"{API}/fem-verifications/{d['id']}/cancel", headers=PW)
    assert r.status_code == 202 and r.json()["status"] == "CANCELED" and r.json()["can_rerun"] is True
    assert env.job(d["predict"]["job_id"])["state"] == "CANCELED"
    assert env.c.post(f"{API}/fem-verifications/{d['id']}/cancel", headers=PW).status_code == 202   # 멱등
    # 다시 실행 → 동반 예측 재시도
    r = env.c.post(f"{API}/fem-verifications/{d['id']}/rerun", headers=PW)
    assert r.status_code == 201 and r.json()["status"] == "WAITING_PREDICT" and r.json()["predict"]["job_id"] != d["predict"]["job_id"]
    # RUNNING(FEM_VERIFY QUEUED) 취소: 관리자도 가능
    d2 = create(env, {"source": {"kind": "predict_job", "job_id": pj}})
    r = env.c.post(f"{API}/fem-verifications/{d2['id']}/cancel", headers=AW)
    assert r.status_code == 202 and r.json()["status"] == "CANCELED" and env.job(d2["job"]["id"])["state"] == "CANCELED"
    with env.engine.connect() as c:
        acts = [a for (a,) in c.execute(text("select action from audit_events where target_type='fem_verification' order by id"))]
    assert acts.count("FEM_VERIFY_CANCEL") == 2 and acts.count("FEM_VERIFY_RERUN") == 1


def test_d3_64_companion_duplicate_and_retry_limits(predict_env, fake_tools, tmp_path, engine):
    """D3-64 후속: 동반 예측 출처도 같은 설계점(적용값)+같은 조립 원본 중복 409, `/jobs/{id}/retry`·다시 실행은
    검증 행을 되살리기 전에 max_active(FEM_VERIFY_LIMIT)·중복(FEM_VERIFY_ACTIVE)을 다시 본다."""
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    pj = predict(env, {"THK_1": 2.5, "N_RIB": 3})
    vals = lambda t, n=4: {"source": {"kind": "values", "param_set_id": ps["id"], "values": {"THK_1": t, "N_RIB": n}}}  # noqa: E731
    url = f"{API}/studies/{env.sid}/fem-verifications"
    c1 = create(env, vals(3.1))
    assert c1["predict"]["companion"] is True
    r = env.c.post(url, headers=PW, json=vals(3.1))                                       # 같은 값 동반 → 409
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FEM_VERIFY_ACTIVE"
    r = env.c.post(url, headers=PW, json={"source": {**vals(3.1)["source"], "reuse_existing": False}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FEM_VERIFY_ACTIVE"
    c2 = create(env, vals(3.2))                                                          # 다른 값 → 201
    # 동반 예측 실패 → 같은 값으로 새 검증(앞 검증은 끝남) → 앞 동반 예측 재시도는 중복 409
    _end(engine, c1["predict"]["job_id"], "FAILED", "TOOL_FAILED")
    assert detail(env, c1["id"])["status"] == "FAILED"
    c3 = create(env, vals(3.1))
    r = env.c.post(f"{API}/jobs/{c1['predict']['job_id']}/retry", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FEM_VERIFY_ACTIVE"
    r = env.c.post(f"{API}/fem-verifications/{c1['id']}/rerun", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FEM_VERIFY_ACTIVE"
    assert detail(env, c1["id"])["status"] == "FAILED"                                   # 되살리지 않음
    # FEM_VERIFY 실패 → 같은 예측 새 검증 진행 중 → 앞 FEM_VERIFY 재시도 409(중복)
    f1 = create(env, {"source": {"kind": "predict_job", "job_id": pj}})
    _end(engine, f1["job"]["id"], "FAILED", "HPC_SUBMIT_FAILED")
    f2 = create(env, {"source": {"kind": "predict_job", "job_id": pj}})
    r = env.c.post(f"{API}/jobs/{f1['job']['id']}/retry", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FEM_VERIFY_ACTIVE"
    env.c.post(f"{API}/fem-verifications/{f2['id']}/cancel", headers=PW)
    # 진행 중 2건(c2·c3) = 상한 → FEM_VERIFY 재시도·다시 실행 409 LIMIT, 상한을 올리면 201
    n_active = env.sql("select count(*) from fem_verifications where status in ('WAITING_PREDICT','RUNNING')")[0][0]
    assert n_active == 2
    env.lc.settings.fem_verify.max_active = 2
    r = env.c.post(f"{API}/jobs/{f1['job']['id']}/retry", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FEM_VERIFY_LIMIT"
    assert r.json()["detail"]["message"] == "진행 중인 FEM 검증이 2건입니다(상한 2)"
    r = env.c.post(f"{API}/fem-verifications/{f1['id']}/rerun", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FEM_VERIFY_LIMIT"
    n_jobs = env.sql("select count(*) from jobs")[0][0]
    env.lc.settings.fem_verify.max_active = 4
    r = env.c.post(f"{API}/jobs/{f1['job']['id']}/retry", headers=PW)
    assert r.status_code == 201, r.text
    assert detail(env, f1["id"])["status"] == "RUNNING" and env.sql("select count(*) from jobs")[0][0] == n_jobs + 1
    del c2, c3


# ---- V3-S16-16 조회 ----------------------------------------------------------------------------------


def test_v3_s16_16_list_detail_404(predict_env, fake_tools, tmp_path):
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    pj = predict(env)
    did, _a = ready_doe(env)
    ids = [create(env, {"source": {"kind": "predict_job", "job_id": pj}})["id"],
           create(env, {"source": {"kind": "predict_job", "job_id": pj}, "assembly": {"kind": "train_doe", "doe_id": did}})["id"],
           create(env, {"source": {"kind": "values", "param_set_id": ps["id"], "values": {"THK_1": 2.2, "N_RIB": 3}}})["id"]]
    g = lambda q="": env.c.get(f"{API}/studies/{env.sid}/fem-verifications{q}", headers=P)  # noqa: E731
    rows = g().json()
    assert [x["id"] for x in rows] == ids[::-1] and rows[-1]["label"] == "FV-001" and rows[0]["status"] == "WAITING_PREDICT"
    assert set(rows[0]) == {"id", "label", "status", "source_label", "source_kind", "links", "values", "max_abs_diff_pct", "worst",
                            "created_at", "created_by_name", "finished_at"}
    assert [x["id"] for x in g(f"?predict_job_id={pj}").json()] == ids[1::-1]
    assert [x["id"] for x in g("?status=WAITING_PREDICT").json()] == [ids[2]]
    assert g("?status=BOGUS").status_code == 422
    seen, cur = [], None
    while True:
        r = g("?limit=1" + (f"&cursor={cur}" if cur else ""))
        seen += [x["id"] for x in r.json()]
        cur = r.headers.get("X-Next-Cursor")
        if not cur:
            break
    assert seen == ids[::-1]
    d = detail(env, ids[1])
    assert set(d) >= {"id", "label", "status", "status_text", "source", "links", "design", "predict", "assembly", "input_mode",
                      "attempt_no", "dir", "paths", "job", "compare", "warnings", "failure", "can_cancel", "can_rerun",
                      "created_at", "created_by_name", "finished_at"}
    assert d["assembly"]["kind"] == "TRAIN_DOE" and d["assembly"]["label"] == "DOE-001" and d["links"]["predict_job_id"] == pj
    for u in ("", "/media", "/curves", "/table.csv"):
        r = env.c.get(f"{API}/fem-verifications/{uuid.uuid4()}{u}", headers=P)
        assert r.status_code == 404 and r.json()["detail"]["code"] == "FEM_VERIFY_NOT_FOUND", u
    m = env.c.get(f"{API}/fem-verifications/{ids[0]}/media", headers=P).json()
    assert m == {"status": "NONE", "display": None, "legend": None, "items": []}


# ---- V3-S16-17 경로 확인·SPDM 탐색 ------------------------------------------------------------------


def test_v3_s16_17_paths_and_spdm_browse(predict_env, fake_tools, tmp_path):
    env, ps = fv_env(predict_env, fake_tools, tmp_path)
    spdm = os.path.normpath(env.lc.settings.storage.spdm_roots[0])
    os.makedirs(spdm, exist_ok=True)
    a = os.path.join(spdm, "proj", "assem")
    make_assem_files(__import__("pathlib").Path(a))
    before = sorted(os.listdir(a))
    r = env.c.post(f"{API}/studies/{env.sid}/paths/inspect", headers=PW, json={"purpose": "FEM_ASSEMBLY", "path": a})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["ok"] is True and b["normalized_path"] == a and b["summary"]["starter"] == "model0_0000.rad"
    assert b["summary"]["renum_csv"] is True and b["summary"]["warnings"] == []
    r = env.c.post(f"{API}/studies/{env.sid}/paths/inspect", headers=PW, json={"purpose": "FEM_ASSEMBLY", "path": str(tmp_path)})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_OUTSIDE_ROOT"
    roots = env.c.get(f"{API}/fs/roots", headers=P).json()["roots"]
    assert not [x for x in roots if x["key"].startswith("spdm")]
    roots = env.c.get(f"{API}/fs/roots?include_spdm=true", headers=P).json()["roots"]
    assert {"key": "spdm_1", "label": "SPDM 1(읽기 전용)", "path": spdm} in roots
    lst = env.c.get(f"{API}/fs/list", headers=P, params={"path": os.path.join(spdm, "proj")}).json()
    assert [e["name"] for e in lst["entries"]] == ["assem"] and lst["parent"] == spdm
    assert env.c.get(f"{API}/fs/list", headers=P, params={"path": spdm}).json()["parent"] is None
    assert sorted(os.listdir(a)) == before                                                  # 쓰기 0
    env.lc.settings.storage.spdm_roots = []
    assert not [x for x in env.c.get(f"{API}/fs/roots?include_spdm=true", headers=P).json()["roots"] if x["key"].startswith("spdm")]
