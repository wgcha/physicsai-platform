"""V3-S16-19 e2e(가짜 도구, phase3 §21.3): mesh_only 템플릿 값 → FEM 검증(values, ① DOE 조립) → 동반 예측 → FEM_VERIFY(가짜 PBS
command in_place, 가짜 hw minmax·캡처) → DONE·비교 표·두 쪽 컨투어. assembly 예측 → predict_input FEM 검증.
scx 가짜 relay 1회(잡 폴더 `04_FV-001_<ts>`, 회수) + SUBMISSION_UNKNOWN(자동 재제출 없음·attention·알림 → 제출 안 됨 → 검증 FAILED)."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text

from physicsai_test_support import API, scx_hpc_cfg

from ..stage4_predict.conftest import pbs_state, predict_env  # noqa: F401 - fixture 재사용
from ..stage4_predict.fv_support import (P, PW, RESULT_FILES, VALUES, attempt_dir, create, detail, finish_hpc, fv_env, predict,
                                         ready_doe, run_until_hpc)


@pytest.fixture(autouse=True)
def _fast_collect(monkeypatch, pbs_state):  # noqa: F811
    from physicsai_worker.steps import _collect

    monkeypatch.setattr(_collect, "COLLECT_STABLE_INTERVAL_S", 0.02)


def test_v3_s16_19_mesh_only_values_companion_to_done(predict_env, fake_tools, fake_record, tmp_path, engine):  # noqa: F811
    env, ps = fv_env(predict_env, fake_tools, tmp_path, mesh_only=True)
    did, _assem = ready_doe(env)
    body = {"source": {"kind": "values", "param_set_id": ps["id"], "values": {"THK_1": 3.7, "N_RIB": 5}},
            "assembly": {"kind": "train_doe", "doe_id": did}, "display": {"views": ["iso", "front"]}}
    pv = env.c.post(f"{API}/studies/{env.sid}/fem-verifications/preview", headers=PW, json=body).json()
    assert pv["problems"] == [] and pv["predict"]["will_run"] is True and pv["input_mode"] == "rebuild"
    d = create(env, body)
    assert d["status"] == "WAITING_PREDICT"
    d = run_until_hpc(env, d["id"])                                                     # 동반 예측 → 훅 → FEM_VERIFY → 제출
    pj = d["predict"]["job_id"]
    assert env.job(pj)["state"] == "SUCCEEDED" and env.job(pj)["params"]["fem_verify_id"] == d["id"]
    d = finish_hpc(env, d["id"], RESULT_FILES)
    assert d["status"] == "DONE" and d["status_text"] == "완료" and d["can_rerun"] is False
    rows = d["compare"]["responses"]
    assert [r["name"] for r in rows] == ["MaxStress", "MinDisp"] and all(r["pred_value"] is not None for r in rows)
    assert all(r["fem_value"] is not None and r["diff_pct"] is not None for r in rows)
    m = env.c.get(f"{API}/fem-verifications/{d['id']}/media", headers=P).json()
    assert [i["view"] for i in m["items"]] == ["iso", "front"] and all(i["pred"]["image"] and i["fem"]["image"] for i in m["items"])
    assert m["legend"]["mode"] == "fixed" and m["display"]["views"] == ["iso", "front"]
    lst = env.c.get(f"{API}/studies/{env.sid}/fem-verifications", headers=P).json()
    assert lst[0]["status"] == "DONE" and lst[0]["max_abs_diff_pct"] == d["compare"]["max_abs_diff_pct"]
    run = env.c.get(f"{API}/studies/{env.sid}/predict-runs", headers=P).json()             # V1 목록: 동반 예측 origin
    assert [x["origin"] for x in run if x["job_id"] == pj] == ["fem_verify"]
    # assembly 템플릿 예측 → predict_input
    ps2 = env.param_set()
    env.set_responses(ps2["id"], [])
    pj2 = predict(env, VALUES)
    d2 = create(env, {"source": {"kind": "predict_job", "job_id": pj2}})
    assert d2["input_mode"] == "reuse" and d2["assembly"]["kind"] == "PREDICT_INPUT"
    run_until_hpc(env, d2["id"])
    d2 = finish_hpc(env, d2["id"], RESULT_FILES)
    assert d2["status"] == "DONE" and d2["compare"]["responses"] == []
    with engine.connect() as c:
        n = c.execute(text("select count(*) from notifications where event='FEM_VERIFY_DONE'")).scalar()
    assert n == 2


@pytest.fixture()
def scx_fv(predict_env, fake_tools, fake_relay, tmp_path):  # noqa: F811
    env, ps = fv_env(predict_env, fake_tools, tmp_path, hpc=scx_hpc_cfg(fake_relay, tmp_path), folder="SFV")
    env.w.hpc._sleep = lambda _s: None
    return env, ps, fake_relay


def test_v3_s16_19_scx_once_and_unknown(scx_fv, engine):
    env, ps, fake = scx_fv
    pj = predict(env)
    fake.outputs = {"model0_0000.h3d": b"H3D", "model0_0000.out": b"x"}
    d = create(env, {"source": {"kind": "predict_job", "job_id": pj}})
    assert env.w.run_once_slot() == "WAITING_HPC", env.job(detail(env, d["id"])["job"]["id"])
    dirs = [p.name for p in (fake.drive / "SFV").iterdir()]
    assert len(dirs) == 1 and re.fullmatch(r"04_FV-001_\d{8}T\d{6}", dirs[0]), dirs
    d = detail(env, d["id"])
    assert d["status_text"] == "해석 대기(SCX)" and d["paths"]["remote_dir"] == f"/Users/vd.dashboard/SFV/{dirs[0]}"
    for _ in range(3):
        env.w.poll_hpc_once()
    assert env.w.run_once_collect() == "QUEUED"
    assert env.w.run_once_slot() == "SUCCEEDED"
    d = detail(env, d["id"])
    assert d["status"] == "DONE" and d["paths"]["collected"] == ["model0_0000.h3d", "model0_0000.out"]
    assert (attempt_dir(env, d) / "result" / "model0_0000.h3d").read_bytes() == b"H3D"
    # 결과 모름 → attention·알림, 자동 재제출 없음 → 제출 안 됨 → 작업 실패 → 검증 FAILED → 다시 실행(새 시도·새 폴더)
    fake.submit_mode = "unknown"
    pj2 = predict(env, {"THK_1": 4.0, "N_RIB": 6})
    d2 = create(env, {"source": {"kind": "predict_job", "job_id": pj2}})
    assert env.w.run_once_slot() == "WAITING_HPC"
    jid = detail(env, d2["id"])["job"]["id"]
    j = env.job(jid)
    assert j["attention_code"] == "HPC_SUBMISSION_UNKNOWN"
    n_submit = len(fake.adapter_calls)
    env.w.poll_hpc_once()
    assert len(fake.adapter_calls) == n_submit                                             # 자동 재제출 없음
    with engine.connect() as c:
        assert c.execute(text("select count(*) from notifications where job_id=:j and event='HPC_SUBMISSION_UNKNOWN'"),
                         {"j": jid}).scalar() == 1
    h = env.c.get(f"{API}/jobs/{jid}/hpc-jobs", headers=P).json()[0]
    r = env.c.post(f"{API}/jobs/{jid}/hpc-jobs/{h['id']}/resolve", headers=PW, json={"action": "mark_not_submitted", "version": h["version"]})
    assert r.status_code == 202
    env.w.poll_hpc_once()
    d2 = detail(env, d2["id"])
    assert d2["status"] == "FAILED" and env.job(jid)["state"] == "FAILED"
    fake.submit_mode = "ok"
    r = env.c.post(f"{API}/fem-verifications/{d2['id']}/rerun", headers=PW)
    assert r.status_code == 201, r.text
    assert env.w.run_once_slot() == "WAITING_HPC"
    assert detail(env, d2["id"])["attempt_no"] == 2
    assert len([p for p in (fake.drive / "SFV").iterdir() if p.name.startswith("04_FV-002_")]) == 2
