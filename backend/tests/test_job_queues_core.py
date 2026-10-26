"""job-queues.md V-JQ-1·2·11·13(설정 검증): step 자원 분류 정적 시험, 초기 대기열·건너뛰기 판정, migration 0022, 설정 검증."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from physicsai_core.job_types import JOB_TYPES
from physicsai_core.queues import (
    GPU_START_TYPES,
    entry_lane,
    gpu_step_keys,
    initial_lane,
    segments,
    skip_without_slot,
    step_need,
    step_res,
    uses_gpu,
)
from physicsai_test_support import REPO

GPU_STEPS = {"EDSPY_PREDICT", "EDSPY_SCORE", "HST_OPTIMIZE"}


# ---- V-JQ-1 정적 ------------------------------------------------------------------------------------


def test_v_jq_1_every_local_step_has_resource_and_gpu_set_is_fixed():
    for jt, d in JOB_TYPES.items():
        for s in d.steps:
            if s.kind in ("LOCAL", "HPC_SUBMIT"):
                assert s.res in ("cpu", "gpu"), f"{jt}.{s.key}: LOCAL·HPC_SUBMIT는 res를 정해야 합니다"
            else:  # INTERNAL = 중립, HPC_WAIT·COLLECT = 슬롯 없음
                assert s.res == "none", f"{jt}.{s.key}"
    assert {s.key for d in JOB_TYPES.values() for s in d.steps if s.res == "gpu"} == GPU_STEPS
    assert gpu_step_keys() == GPU_STEPS
    # GPU step은 PhysicsAI 추론뿐: LOCAL이고 EDSPY_PREDICT·EDSPY_SCORE·HST_OPTIMIZE
    assert all(s.kind == "LOCAL" for d in JOB_TYPES.values() for s in d.steps if s.res == "gpu")


def test_v_jq_1_migration_gpu_table_equals_core():
    src = (REPO / "migrations" / "versions" / "0022_job_queues.py").read_text(encoding="utf-8")
    for k in GPU_STEPS:
        assert f'"{k}"' in src
    import importlib.util

    spec = importlib.util.spec_from_file_location("m0022", REPO / "migrations" / "versions" / "0022_job_queues.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)  # type: ignore[union-attr]
    assert set(m.GPU_STEPS) == gpu_step_keys() and set(m.GPU_TYPES) == set(GPU_START_TYPES)


# ---- V-JQ-2 분류 ------------------------------------------------------------------------------------


@pytest.mark.parametrize("job_type,expect", [
    ("PREDICT", "CPU"), ("PREDICT_BATCH", "CPU"), ("SURROGATE_OPT", "CPU"), ("FEM_VERIFY", "CPU"), ("TD_SOLVE", "CPU"),
    ("TD_DOE_GEN", "CPU"), ("DATASET_CREATE", "CPU"), ("PREDICT_VERIFY", "CPU"), ("EQ_CHECK", "CPU"),
    ("EVALUATE", "GPU"), ("OPTIMIZE", "GPU"),
    ("MODEL_REGISTER", "LIGHT"), ("GEOM_PREVIEW", "PREVIEW"), ("CONTOUR_3D", "CPU"),  # CONTOUR_3D = CPU 대기열(2026-10-22 사용자 결정)
])
def test_v_jq_2_initial_lane(job_type, expect):
    assert initial_lane(job_type, {}) == expect
    assert initial_lane(job_type, {"input_mode": "prepared"}) == expect  # prepared도 첫 구간은 CPU(복사 검사)


def test_v_jq_2_every_slot_type_starts_cpu_except_gpu_start_types():
    for jt, d in JOB_TYPES.items():
        if d.lane == "SLOT":
            assert initial_lane(jt, {}) == ("GPU" if jt in GPU_START_TYPES else "CPU"), jt


def test_v_jq_2_resume_from_step_uses_remaining_steps():
    keys = [s.key for s in JOB_TYPES["PREDICT"].steps]
    at = keys.index("EDSPY_PREDICT") + 1
    assert initial_lane("PREDICT", {}, at) == "GPU"  # 남은 첫 step 자체가 추론
    assert initial_lane("PREDICT", {}, at - 1) == "CPU"  # 앞에 준비 step(RAD_ASSEMBLE)이 있으면 CPU 슬롯에서
    assert initial_lane("PREDICT", {}, at + 1) == "CPU"
    assert initial_lane("PREDICT", {}, 1) == "CPU"
    ev = [s.key for s in JOB_TYPES["EVALUATE"].steps]
    assert initial_lane("EVALUATE", {}, 1) == "GPU" and initial_lane("EVALUATE", {}, ev.index("EDSPY_SCORE") + 1) == "GPU"
    assert initial_lane("EVALUATE", {}, ev.index("EV_PARSE") + 1) == "CPU"  # 추론 step이 남지 않았다


def test_v_jq_2_skip_without_slot_prepared_predict_only():
    for k in ("GEOM_UPDATE", "MESH"):
        assert skip_without_slot("PREDICT", {"input_mode": "prepared"}, k)
        assert not skip_without_slot("PREDICT", {}, k)
        assert not skip_without_slot("PREDICT", {"input_mode": "parametric"}, k)
    assert not skip_without_slot("PREDICT", {"input_mode": "prepared"}, "CONTOUR_PREVIEW")
    assert not skip_without_slot("PREDICT_BATCH", {"input_mode": "prepared"}, "GEOM_UPDATE")
    geom = JOB_TYPES["PREDICT"].step_of("GEOM_UPDATE")
    assert step_need("PREDICT", geom, {}) == "CPU" and step_need("PREDICT", geom, {"input_mode": "prepared"}) is None


def test_v_jq_2_step_resource_override_and_segments():
    pred = JOB_TYPES["PREDICT"].step_of("CONTOUR_CAPTURE")
    assert step_res(pred) == "cpu" and step_res(pred, {"CONTOUR_CAPTURE": "gpu"}) == "gpu"
    # GPU 동시 1 엄수: 계약 GPU 단계는 cpu로 내리는 덮어쓰기를 무시한다(설정 검증이 막지만 실행 쪽에서도 방어)
    assert step_res(JOB_TYPES["PREDICT"].step_of("EDSPY_PREDICT"), {"EDSPY_PREDICT": "cpu"}) == "gpu"
    assert step_res(JOB_TYPES["PREDICT"].step_of("PR_PREP"), {"PR_PREP": "gpu"}) == "none"  # INTERNAL은 중립 — 덮어쓰기 대상 아님
    hpc = JOB_TYPES["TD_SOLVE"].step_of("HPC_WAIT")
    assert step_res(hpc, {"HPC_WAIT": "gpu"}) == "none"
    assert segments("PREDICT") == ["cpu", "gpu", "cpu"]
    assert segments("PREDICT", {"CONTOUR_CAPTURE": "gpu"}) == ["cpu", "gpu", "cpu", "gpu"]
    assert segments("EVALUATE") == ["gpu"] and segments("OPTIMIZE") == ["gpu"]
    assert segments("DATASET_CREATE") == ["cpu"] and segments("MODEL_REGISTER") == ["light"] and segments("GEOM_PREVIEW") == ["preview"]
    assert uses_gpu("PREDICT") and uses_gpu("EVALUATE") and not uses_gpu("TD_SOLVE") and not uses_gpu("MODEL_REGISTER")
    assert uses_gpu("DATASET_CREATE", {"EDSPY_DATASET_TRAIN": "gpu"})
    demote = {k: "cpu" for k in GPU_STEPS}  # GPU 단계를 cpu로 내려도 구간 흐름·초기 대기열 불변
    assert segments("PREDICT", demote) == ["cpu", "gpu", "cpu"] and segments("EVALUATE", demote) == ["gpu"] and segments("OPTIMIZE", demote) == ["gpu"]
    assert initial_lane("EVALUATE", None, None, demote) == "GPU" and initial_lane("PREDICT", None, 6, demote) == "GPU"
    assert gpu_step_keys(demote) == GPU_STEPS


def test_v_jq_2_entry_lane_after_pbs_collect():
    steps = [{"step_key": s.key, "state": "SUCCEEDED" if i < 4 else "PENDING"} for i, s in enumerate(JOB_TYPES["PREDICT_VERIFY"].steps)]
    # PV_PREP·HPC_SUBMIT·HPC_WAIT·COLLECT 끝, 남은 PV_EXTRACT(LOCAL cpu)·PV_TABLE → CPU
    assert entry_lane("PREDICT_VERIFY", steps, {}) == "CPU"
    only_internal = [{"step_key": "TS_REGISTER", "state": "PENDING"}]
    assert entry_lane("TD_SOLVE", only_internal, {}) == "CPU"  # INTERNAL뿐이면 CPU
    gpu_first = [{"step_key": "EDSPY_PREDICT", "state": "PENDING"}]
    assert entry_lane("PREDICT", gpu_first, {}) == "GPU"


# ---- V-JQ-13 설정 검증 ------------------------------------------------------------------------------


def _cfg(settings_dict, **queues):
    from physicsai_core.config import load_config_dict

    d = dict(settings_dict)
    d["worker"] = {**d["worker"], "queues": queues}
    return load_config_dict(d, environ={})


def test_v_jq_13_defaults_and_valid(settings_dict):
    lc = _cfg(settings_dict)
    q = lc.settings.worker.queues
    assert lc.ok and q.cpu.max_concurrent == 4 and q.cpu.min_free_memory_gb == 8 and q.total_cap is True and q.step_resource == {}
    lc = _cfg(settings_dict, cpu={"max_concurrent": 16, "min_free_memory_gb": 0}, step_resource={"CONTOUR_CAPTURE": "gpu"})
    assert lc.ok, lc.issues
    assert _cfg(settings_dict, cpu={"max_concurrent": 1}).ok


@pytest.mark.parametrize("queues,key", [
    ({"cpu": {"max_concurrent": 0}}, "worker.queues.cpu.max_concurrent"),
    ({"cpu": {"max_concurrent": 17}}, "worker.queues.cpu.max_concurrent"),
    ({"cpu": {"min_free_memory_gb": -1}}, "worker.queues.cpu.min_free_memory_gb"),
    ({"cpu": {"min_free_memory_gb": 64}}, "worker.queues.cpu.min_free_memory_gb"),  # max_memory_gb(시험 설정 8) 이상
    ({"gpu": {"max_concurrent": 2}}, "worker.queues.gpu"),
    ({"gpu": None}, "worker.queues.gpu"),
    ({"step_resource": {"NOPE_STEP": "cpu"}}, "worker.queues.step_resource.NOPE_STEP"),
    ({"step_resource": {"HPC_SUBMIT": "gpu"}}, "worker.queues.step_resource.HPC_SUBMIT"),
    ({"step_resource": {"HPC_WAIT": "cpu"}}, "worker.queues.step_resource.HPC_WAIT"),
    ({"step_resource": {"PR_PREP": "cpu"}}, "worker.queues.step_resource.PR_PREP"),  # INTERNAL
    ({"step_resource": {"CONTOUR_CAPTURE": "tpu"}}, "worker.queues.step_resource.CONTOUR_CAPTURE"),
    ({"step_resource": {"EDSPY_PREDICT": "cpu"}}, "worker.queues.step_resource.EDSPY_PREDICT"),  # GPU 단계를 cpu로 — GPU 동시 1 우회
    ({"step_resource": {"EDSPY_SCORE": "cpu"}}, "worker.queues.step_resource.EDSPY_SCORE"),
    ({"step_resource": {"HST_OPTIMIZE": "cpu", "CONTOUR_CAPTURE": "gpu"}}, "worker.queues.step_resource.HST_OPTIMIZE"),
])
def test_v_jq_13_invalid_settings(settings_dict, queues, key):
    lc = _cfg(settings_dict, **queues)
    assert not lc.ok
    assert key in lc.error_keys(), lc.issues


def test_v_jq_13_gpu_demotion_rejected_but_promotion_allowed(settings_dict):
    from physicsai_core.queues import contract_gpu_step_keys, gpu_demotions

    assert contract_gpu_step_keys() == GPU_STEPS  # 계약 GPU 집합 = StepDef.res(코드에 키 목록을 따로 두지 않는다)
    assert gpu_demotions({"EDSPY_PREDICT": "cpu", "EDSPY_SCORE": "gpu", "CONTOUR_CAPTURE": "gpu", "HST_OPTIMIZE": "cpu"}) == ["EDSPY_PREDICT", "HST_OPTIMIZE"]
    lc = _cfg(settings_dict, step_resource={"EDSPY_PREDICT": "cpu"})
    msg = [i.message for i in lc.issues if i.key == "worker.queues.step_resource.EDSPY_PREDICT"][0]
    assert "GPU 단계" in msg and "동시에 1개" in msg
    # 같은 값(gpu 유지)·CPU 단계를 gpu로 올리는 현장 보정(HyperView 캡처 등)은 허용
    assert _cfg(settings_dict, step_resource={"EDSPY_PREDICT": "gpu", "EDSPY_SCORE": "gpu", "HST_OPTIMIZE": "gpu"}).ok
    assert _cfg(settings_dict, step_resource={"CONTOUR_CAPTURE": "gpu", "FV_CAPTURE": "gpu"}).ok


def test_v_jq_13_gpu_key_message(settings_dict):
    lc = _cfg(settings_dict, gpu={"max_concurrent": 2})
    msg = [i.message for i in lc.issues if i.key == "worker.queues.gpu"][0]
    assert "GPU 작업은 동시에 1개만 실행합니다" in msg


def test_v_jq_13_small_max_memory_keeps_default_valid(settings_dict):
    from physicsai_core.config import load_config_dict

    d = dict(settings_dict)
    d["worker"] = {**d["worker"], "max_memory_gb": 4}  # 시연 설정처럼 작아도 기본 min_free(8)는 오류가 아니다(명시한 값만 검사)
    assert load_config_dict(d, environ={}).ok


# ---- V-JQ-11 migration 0022 --------------------------------------------------------------------------


def _alembic(url: str, rev: str, down: bool = False) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "migrations"))
    cfg.attributes["url"] = url
    (command.downgrade if down else command.upgrade)(cfg, rev)


@pytest.fixture()
def fresh_db(pg_server):
    name = f"physicsai_jq_{uuid.uuid4().hex[:8]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    base, _, _ = pg_server["admin_url"].rpartition("/")
    url = f"{base}/{name}"
    eng = create_engine(url)
    try:
        yield url, eng
    finally:
        eng.dispose()
        with pg_server["admin"].connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def _steps(c, jid, job_type, states: dict[str, str]):
    for no, sd in enumerate(JOB_TYPES[job_type].steps, start=1):
        c.execute(text("insert into job_steps(id, job_id, step_no, step_key, kind, needs_slot, state, log_rel)"
                       " values (:u,:j,:n,:k,:kind,true,:st,'x')"),
                  {"u": str(uuid.uuid4()), "j": jid, "n": no, "k": sd.key, "kind": sd.kind, "st": states.get(sd.key, "SUCCEEDED")})


def _old_job(c, sid, job_type, state, seq=None, *, lease=False, steps: dict[str, str] | None = None, lane: str = "SLOT") -> str:
    jid = str(uuid.uuid4())
    running = state == "RUNNING"
    c.execute(text("insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, queue_seq, params,"
                   " failure_code, created_by, created_by_name, lease_owner_id, lease_token, lease_acquired_at, lease_expires_at)"
                   " values (:i,:s,'p-1',:t,:st,:lane,:state,:h,:q,'{}',:fc,'u','u',:lo,:lt,:la,:le)"),
              {"i": jid, "lane": lane, "s": sid, "t": job_type, "st": JOB_TYPES[job_type].stage, "state": state, "h": running, "q": seq,
               "fc": "X" if state in ("FAILED", "INTERRUPTED") else None,
               "lo": "w" if lease else None, "lt": "tok" if lease else None,
               "la": "2026-01-01" if lease else None, "le": "2026-01-02" if lease else None})
    _steps(c, jid, job_type, steps or {})
    return jid


def test_v_jq_11_migration_0022_up_data_conversion_and_down(fresh_db):
    from physicsai_core.db import MIGRATION_HEAD

    url, eng = fresh_db
    assert MIGRATION_HEAD == "0025_doe_preview"  # 0022는 0023의 직전 리비전
    _alembic(url, "0021_uploads")
    sids = {}
    with eng.begin() as c:
        for n in range(12):
            sid = str(uuid.uuid4())
            sids[n] = sid
            c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                           " values (:i,'p-1',:f,'t','/x','u','u')"), {"i": sid, "f": f"J{n}"})
        pred_at_edspy = _old_job(c, sids[0], "PREDICT", "QUEUED", 11, steps={
            k.key: ("PENDING" if i >= 5 else "SUCCEEDED") for i, k in enumerate(JOB_TYPES["PREDICT"].steps)})
        pred_fresh = _old_job(c, sids[1], "PREDICT", "QUEUED", 12, steps={k.key: "PENDING" for k in JOB_TYPES["PREDICT"].steps})
        doe = _old_job(c, sids[2], "TD_DOE_GEN", "QUEUED", 13, steps={k.key: "PENDING" for k in JOB_TYPES["TD_DOE_GEN"].steps})
        ev = _old_job(c, sids[3], "EVALUATE", "QUEUED", 14, steps={k.key: "PENDING" for k in JOB_TYPES["EVALUATE"].steps})
        opt = _old_job(c, sids[4], "OPTIMIZE", "QUEUED", 15, steps={k.key: "PENDING" for k in JOB_TYPES["OPTIMIZE"].steps})
        solve = _old_job(c, sids[5], "TD_SOLVE", "WAITING_HPC", steps={
            "TS_PREP": "SUCCEEDED", "HPC_SUBMIT": "SUCCEEDED", "HPC_WAIT": "RUNNING", "COLLECT": "PENDING", "TS_REGISTER": "PENDING"})
        done_ev = _old_job(c, sids[6], "EVALUATE", "SUCCEEDED")
        done_pr = _old_job(c, sids[7], "PREDICT", "FAILED")
        c3 = _old_job(c, sids[9], "CONTOUR_3D", "QUEUED", 16, lane="LIGHT", steps={k.key: "PENDING" for k in JOB_TYPES["CONTOUR_3D"].steps})
        light = _old_job(c, sids[10], "MODEL_REGISTER", "QUEUED", 17, lane="LIGHT", steps={k.key: "PENDING" for k in JOB_TYPES["MODEL_REGISTER"].steps})
        run = _old_job(c, sids[8], "PREDICT", "RUNNING", lease=True, steps={"EDSPY_PREDICT": "RUNNING", "CONTOUR_PREVIEW": "PENDING"})
        c.execute(text("update worker_slot set holder_job_id=:j, lease_owner_id='w', lease_token='tok', lease_acquired_at='2026-01-01',"
                       " lease_expires_at='2026-01-02' where id=1"), {"j": run})
    _alembic(url, "head")
    with eng.begin() as c:
        assert c.execute(text("select version_num from alembic_version")).scalar() == MIGRATION_HEAD
        lane = {r[0]: r for r in c.execute(text("select id, lane, holds_slot, queue_seq, queue_origin_seq from jobs"))}
        assert lane[pred_at_edspy][1] == "GPU" and lane[pred_fresh][1] == "CPU" and lane[doe][1] == "CPU"
        assert lane[ev][1] == "GPU" and lane[opt][1] == "GPU"  # INTERNAL 선행 step을 건너뛴 첫 LOCAL이 추론
        assert lane[solve][1] == "CPU"
        assert lane[c3][1] == "CPU" and lane[c3][4] == 16 and lane[light][1] == "LIGHT"  # CONTOUR_3D 대기 행은 CPU로, 다른 LIGHT는 그대로
        assert lane[done_ev][1] == "GPU" and lane[done_pr][1] == "CPU"  # 종결 = 이력 표시용
        assert lane[run][1] == "GPU" and lane[run][2] is True  # RUNNING 추론은 슬롯 유지
        assert [lane[j][4] for j in (pred_at_edspy, pred_fresh, doe, ev, opt)] == [11, 12, 13, 14, 15]  # origin = queue_seq
        assert lane[solve][4] is None and lane[done_ev][4] is None
        assert c.execute(text("select holder_job_id from worker_slot")).scalar() == run
        assert c.execute(text("select count(*) from jobs where lane='SLOT'")).scalar() == 0
        # 옛 claim_slot 질의는 0건(옛 워커는 아무것도 받지 않는다 — 안전 실패)
        assert c.execute(text("select count(*) from jobs where state='QUEUED' and lane='SLOT'")).scalar() == 0
        # 새 제약: holds_slot = RUNNING AND GPU, lane 값 집합
        defs = {r[0]: r[1] for r in c.execute(text("select conname, pg_get_constraintdef(oid) from pg_constraint"
                                                   " where conname in ('ck_jobs_lane','ck_jobs_holds_slot')"))}
        assert "SLOT" not in defs["ck_jobs_lane"] and "'GPU'" in defs["ck_jobs_holds_slot"]
        with pytest.raises(IntegrityError), c.begin_nested():
            c.execute(text("update jobs set lane='SLOT' where id=:i"), {"i": doe})
    # RUNNING 1건만 있으면 되돌릴 수 있다(전역 슬롯 1개와 같은 상태) — 먼저 RUNNING을 끝낸다
    with eng.begin() as c:
        c.execute(text("update jobs set state='SUCCEEDED', holds_slot=false, lease_owner_id=null, lease_token=null,"
                       " lease_acquired_at=null, lease_expires_at=null, finished_at=now() where id=:i"), {"i": run})
        c.execute(text("update worker_slot set holder_job_id=null, lease_owner_id=null, lease_token=null, lease_acquired_at=null,"
                       " lease_expires_at=null where id=1"))
    _alembic(url, "0021_uploads", down=True)
    with eng.begin() as c:
        assert c.execute(text("select version_num from alembic_version")).scalar() == "0021_uploads"
        assert {r[0] for r in c.execute(text("select distinct lane from jobs"))} == {"SLOT", "LIGHT"}
        assert c.execute(text("select lane from jobs where id=:i"), {"i": c3}).scalar() == "LIGHT"  # CONTOUR_3D는 옛 구조에서 LIGHT
        cols = {r[0] for r in c.execute(text("select column_name from information_schema.columns where table_name='jobs'"))}
        assert "queue_origin_seq" not in cols
    _alembic(url, "head")  # 다시 올릴 수 있다
    with eng.begin() as c:
        assert c.execute(text("select count(*) from jobs where lane='GPU'")).scalar() >= 3


def test_v_jq_11_migration_0022_downgrade_refuses_when_several_running(fresh_db):
    url, eng = fresh_db
    _alembic(url, "head")
    with eng.begin() as c:
        for n, (lane, holds) in enumerate((("CPU", False), ("CPU", False))):
            sid = str(uuid.uuid4())
            c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                           " values (:i,'p-1',:f,'t','/x','u','u')"), {"i": sid, "f": f"D{n}"})
            c.execute(text("insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, params, created_by,"
                           " created_by_name, lease_owner_id, lease_token, lease_acquired_at, lease_expires_at)"
                           " values (:i,:s,'p-1','TD_DOE_GEN',1,:l,'RUNNING',:h,'{}','u','u','w','t','2026-01-01','2026-01-02')"),
                      {"i": str(uuid.uuid4()), "s": sid, "l": lane, "h": holds})
    with pytest.raises(RuntimeError, match="이전 구조로 되돌릴 수 없습니다"):
        _alembic(url, "0021_uploads", down=True)


def test_v_jq_11_metadata_matches_migration():
    from physicsai_core.db.tables import jobs

    cons = {c.name: str(c.sqltext) for c in jobs.constraints if getattr(c, "name", "")}
    assert "'CPU'" in cons["ck_jobs_lane"] and "'GPU'" in cons["ck_jobs_lane"] and "SLOT" not in cons["ck_jobs_lane"]
    assert "GPU" in cons["ck_jobs_holds_slot"]
    assert "queue_origin_seq" in jobs.c
