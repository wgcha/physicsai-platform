"""V3-S9-1: 0007_predict_batch — param_sets.input_kind(기존 행 assembly)·mesh_only NULL 허용·CHECK, 새 테이블,
PREDICT_BATCH_DONE 알림, 하위 PREDICT 활성 중복 허용, MIGRATION_HEAD, downgrade 거부. + 저장소(predict_batches) 기본 동작."""

from __future__ import annotations

import importlib.util
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from physicsai_test_support import REPO

PS_COLS = ("insert into param_sets(id, study_id, source_path, stored_rel, parameters, responses, sample_count,"
           " sample_has_measured, cad_file_name, tpl_rel, assem_rel, starter_name, tpl_params, registered_by,"
           " registered_by_name{extra}) values (:i,:s,'/x','r/',:p,'[]',0,false,'c','t',:a,:st,:tp,'u','u'{extra_v})")


def _alembic(url: str, rev: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "migrations"))
    cfg.attributes["url"] = url
    command.upgrade(cfg, rev)


def _study(c) -> str:
    sid = str(uuid.uuid4())
    c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                   " values (:i,'p-1',:f,'t','/x','u','u')"), {"i": sid, "f": "B" + sid[:8]})
    return sid


def _param_set(c, sid, *, assem="a/", starter="s_0000.rad", kind=None) -> str:
    ps = str(uuid.uuid4())
    extra, extra_v = (", input_kind", ", :k") if kind else ("", "")
    c.execute(text(PS_COLS.format(extra=extra, extra_v=extra_v)),
              {"i": ps, "s": sid, "a": assem, "st": starter, "k": kind,
               "p": '[{"name":"THK","nominal":3,"min":2,"max":5,"unit":""},{"name":"RIB_N","nominal":6,"min":5,"max":8,"unit":""}]',
               "tp": '[{"name":"THK","format":"%5.2f"},{"name":"RIB_N","format":"%3i"}]'})
    return ps


def _model(c, sid) -> str:
    mid = str(uuid.uuid4())
    c.execute(text("insert into models(id, study_id, name, version, source_path, stored_rel, psmdl_rel, psmdl_sha256, psmdl_size,"
                   " log_status, registered_by, registered_by_name) values (:i,:s,'m',1,'/x','r','r/a.psmdl',:h,1,'MISSING','u','u')"),
              {"i": mid, "s": sid, "h": "0" * 64})
    return mid


def _job(c, sid, job_type="PREDICT", params="{}", seq=1) -> str:
    jid = str(uuid.uuid4())
    c.execute(text("insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, queue_seq, params,"
                   " created_by, created_by_name) values (:i,:s,'p-1',:t,4,'SLOT','QUEUED',false,:q,cast(:p as jsonb),'u','u')"),
              {"i": jid, "s": sid, "t": job_type, "p": params, "q": seq})
    return jid


def test_upgrade_keeps_rows_assembly_and_allows_mesh_only(pg_server):
    from physicsai_core.db import MIGRATION_HEAD

    assert MIGRATION_HEAD == "0019_extract_filter"
    name = f"physicsai_m7_{uuid.uuid4().hex[:8]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    base, _, _ = pg_server["admin_url"].rpartition("/")
    url = f"{base}/{name}"
    eng = create_engine(url)
    try:
        _alembic(url, "0006_param_set_label")
        with eng.begin() as c:
            sid = _study(c)
            ps = _param_set(c, sid)
            c.execute(text("update param_sets set label='쿠션 v1' where id=:i"), {"i": ps})
            # 0006에서는 같은 Study에 활성 PREDICT 2개 불가
            _job(c, sid, params='{"batch_run":{"batch_id":"x","doe_no":1}}')
        with pytest.raises(IntegrityError), eng.begin() as c:
            _job(c, sid, params='{"batch_run":{"batch_id":"x","doe_no":2}}', seq=2)
        _alembic(url, "head")
        with eng.begin() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == MIGRATION_HEAD
            row = c.execute(text("select input_kind, assem_rel, starter_name, label from param_sets where id=:i"), {"i": ps}).one()
            assert tuple(row) == ("assembly", "a/", "s_0000.rad", "쿠션 v1")
            ps2 = _param_set(c, sid, assem=None, starter=None, kind="mesh_only")
            assert c.execute(text("select input_kind from param_sets where id=:i"), {"i": ps2}).scalar() == "mesh_only"
            # 하위 PREDICT(batch_run)는 같은 Study에 여러 개 활성 가능
            _job(c, sid, params='{"batch_run":{"batch_id":"x","doe_no":2}}', seq=2)
            _job(c, sid, params="{}", seq=3)  # 일반 PREDICT 1개도 함께
        with pytest.raises(IntegrityError), eng.begin() as c:
            _job(c, sid, params="{}", seq=4)  # 일반 PREDICT 두 번째는 여전히 거부
        for kw in ({"assem": None}, {"starter": None}, {"assem": None, "starter": None, "kind": "assembly"}, {"kind": "other"}):
            with pytest.raises(IntegrityError), eng.begin() as c:
                _param_set(c, sid, **kw)
    finally:
        eng.dispose()
        with pg_server["admin"].connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def test_new_tables_and_checks(engine):
    with engine.begin() as c:
        sid = _study(c)
        ps, mid, jid = _param_set(c, sid), _model(c, sid), _job(c, sid, "PREDICT_BATCH")
        c.execute(text("insert into notifications(user_id, event, title) values ('u','PREDICT_BATCH_DONE','t')"))
        c.execute(text("insert into predict_batches(id, study_id, batch_no, job_id, param_set_id, model_id, input_kind, source_kind,"
                       " run_count, dir_rel, created_by, created_by_name) values ('b1',:s,1,:j,:p,:m,'assembly','LHS',2,"
                       "'04_batch/B-001','u','u')"), {"s": sid, "j": jid, "p": ps, "m": mid})
        c.execute(text("""insert into predict_batch_runs(batch_id, doe_no, run_key, "values", applied_values, input_rel)"""
                       """ values ('b1',1,'run__00001',cast(:v as jsonb),cast(:v as jsonb),'run__00001/m_3')"""),
                  {"v": '{"THK": 2.5}'})
        r = c.execute(text("select gen_state, out_of_range, responses, status from predict_batch_runs, predict_batches"
                           " where id='b1'")).one()
        assert tuple(r) == ("PENDING", [], None, "GENERATING")
    bad = [
        "insert into notifications(user_id, event, title) values ('u','NOPE','t')",
        "insert into predict_batches(id, study_id, batch_no, job_id, param_set_id, model_id, input_kind, source_kind, run_count,"
        " dir_rel, created_by, created_by_name) values ('b2',:s,1,:j,:p,:m,'assembly','LHS',1,'d','u','u')",  # batch_no 중복
        "insert into predict_batches(id, study_id, batch_no, job_id, param_set_id, model_id, input_kind, source_kind, run_count,"
        " dir_rel, created_by, created_by_name) values ('b3',:s,2,:j,:p,:m,'assembly','CSV',1,'d','u','u')",
        "update predict_batches set status='NOPE' where id='b1'",
        """insert into predict_batch_runs(batch_id, doe_no, run_key, "values", applied_values, input_rel)"""
        """ values ('b1',2,'run__00001','{}','{}','x')""",  # run_key 중복
        "update predict_batch_runs set gen_state='NOPE'",
    ]
    for sql in bad:
        with pytest.raises(IntegrityError), engine.begin() as c:
            c.execute(text(sql), {"s": sid, "j": jid, "p": ps, "m": mid})


def test_downgrade_refused():
    spec = importlib.util.spec_from_file_location("m0007", REPO / "migrations" / "versions" / "0007_predict_batch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    assert mod.down_revision == "0006_param_set_label"
    with pytest.raises(RuntimeError):
        mod.downgrade()


# ---- 저장소(predict_batches) -----------------------------------------------------------------------


def _make_batch(c, sid, ps, mid, *, n=3, kind="assembly"):
    from physicsai_core.db.repositories import jobs as jobs_repo
    from physicsai_core.db.repositories import predict_batches as pb
    from physicsai_core.db.repositories import studies as studies_repo
    from physicsai_core.stage4_predict.batch_matrix import batch_dir_rel, build_matrix

    st = studies_repo.require(c, sid)
    psr = {"parameters": [{"name": "THK", "min": 2, "max": 5}, {"name": "RIB_N", "min": 5, "max": 8}],
           "tpl_params": [{"name": "RIB_N", "format": "%3i"}]}
    m = build_matrix({"kind": "lhs", "count": n, "seed": 1}, parameters=psr["parameters"], tpl_params=psr["tpl_params"],
                     max_runs=200, table_max_bytes=1024)
    no = pb.next_batch_no(c, sid)
    bid = pb.new_batch_id()
    parent = jobs_repo.insert_job(c, study=st, job_type="PREDICT_BATCH", params={"batch_id": bid, "batch_no": no},
                                  user_id="u-1", user_name="사용자")
    b = pb.create_batch(c, batch_id=bid, batch_no=no, study_id=sid, job_id=parent["id"], param_set_id=ps, model_id=mid,
                        input_kind=kind, matrix=m, multi_execution=2, dir_rel=batch_dir_rel("04_batch", no),
                        simlab_mesh_name="EPS_mesh_0000.rad", user_id="u-1", user_name="사용자")
    return b, parent


def test_repo_create_enqueue_and_complete(engine):
    from physicsai_core.db.repositories import jobs as jobs_repo
    from physicsai_core.db.repositories import predict_batches as pb
    from physicsai_core.db.repositories import studies as studies_repo
    from physicsai_core.db.tables import jobs

    with engine.begin() as c:
        sid = _study(c)
        ps, mid = _param_set(c, sid), _model(c, sid)
        b, parent = _make_batch(c, sid, ps, mid)
        assert (b["batch_no"], b["dir_rel"], b["status"], b["run_count"], b["source_kind"]) == (1, "04_batch/B-001", "GENERATING", 3, "LHS")
        assert b["source_meta"] == {"count": 3, "seed": 1, "ranges": {"THK": [2.0, 5.0], "RIB_N": [5.0, 8.0]}}
        rs = pb.runs(c, b["id"])
        assert [r["run_key"] for r in rs] == ["run__00001", "run__00002", "run__00003"]
        assert rs[0]["input_rel"] == "run__00001/m_3" and isinstance(rs[0]["applied_values"]["RIB_N"], int)
        assert pb.get_by_job(c, parent["id"])["id"] == b["id"]
        # 생성 결과: 1·3 성공, 2 실패
        pb.set_run(c, b["id"], 1, gen_state="DONE")
        pb.set_run(c, b["id"], 2, gen_state="FAILED", gen_code="EXIT_NONZERO", gen_message="x" * 900)
        pb.set_run(c, b["id"], 3, gen_state="DONE")
        assert len(pb.runs(c, b["id"], gen_states=["FAILED"])[0]["gen_message"]) == 500
        kids = pb.enqueue_children(c, b["id"], batch_dir="/ai/S/04_batch/B-001")
        assert [k["params"]["batch_run"]["doe_no"] for k in kids] == [1, 3]
        seqs = [k["queue_seq"] for k in kids]
        assert seqs == sorted(seqs) and seqs[1] == seqs[0] + 1
        k1 = kids[0]
        assert k1["params"]["input_mode"] == "prepared" and k1["params"]["model_id"] == mid and k1["created_by"] == "u-1"
        assert k1["params"]["input_path"].replace("\\", "/").endswith("04_batch/B-001/run__00001/m_3")
        assert pb.enqueue_children(c, b["id"], batch_dir="/ai/S/04_batch/B-001") == []  # 멱등
        assert pb.get(c, b["id"])["status"] == "PREDICTING"
        assert pb.counts(c, b["id"]) == {"gen": {"total": 3, "done": 2, "failed": 1, "running": 0, "waiting": 0},
                                         "predict": {"running": 0, "queued": 2, "succeeded": 0, "failed": 0, "canceled": 0}}
        assert pb.active_child_job_ids(c, b["id"]) == [k["id"] for k in kids]
        assert [pb.row_state(r, r["job_state"]) for r in pb.runs_with_jobs(c, b["id"])] == ["QUEUED", "GEN_FAILED", "QUEUED"]
        # 하위 1 성공(응답 복사), 아직 완료 아님
        c.execute(jobs.update().where(jobs.c.id == k1["id"]).values(state="SUCCEEDED", queue_seq=None,
                                                                     result={"response_table": [{"name": "MaxStress", "predicted": 152.3},
                                                                                                {"name": "Bad", "predicted": None}]}))
        assert pb.on_child_end(c, jobs_repo.get_job(c, k1["id"]), "SUCCEEDED") is None
        assert pb.runs(c, b["id"])[0]["responses"] == {"MaxStress": 152.3, "Bad": None}
        # 하위 3 실패 → 재시도(새 작업) → PREDICTING 유지·응답 비움
        k3 = kids[1]
        c.execute(jobs.update().where(jobs.c.id == k3["id"]).values(state="FAILED", queue_seq=None, failure_code="EXIT_NONZERO"))
        done = pb.on_child_end(c, jobs_repo.get_job(c, k3["id"]), "FAILED")
        assert done is not None and done[1] == {"succeeded": 1, "failed": 2} and done[0]["status"] == "DONE"
        assert pb.mark_done_if_complete(c, b["id"]) is None  # 멱등
        assert pb.done_notice(done[0]["batch_no"], 1, 2)[0] == "일괄 예측 B-001 완료 — 완료 1 · 실패 2"
        st = studies_repo.require(c, sid)
        k3b = jobs_repo.insert_job(c, study=st, job_type="PREDICT", params=k3["params"], user_id="u-1", user_name="사용자",
                                   retry_of_job_id=k3["id"])
        run = pb.replace_child_job(c, k3["id"], k3b["id"])
        assert run is not None and run["doe_no"] == 3
        assert pb.get(c, b["id"])["status"] == "PREDICTING" and pb.runs(c, b["id"])[2]["predict_job_id"] == k3b["id"]
        assert pb.batch_run_ref(k3b) == (b["id"], 3) and pb.batch_run_ref(parent) is None
        # 부모 재시도 → GENERATING, 다음 배치 번호 2
        pb.set_parent_job(c, b["id"], parent["id"])
        assert pb.get(c, b["id"])["status"] == "GENERATING" and pb.next_batch_no(c, sid) == 2
        assert [x["id"] for x in pb.list_for_study(c, sid)] == [b["id"]]
