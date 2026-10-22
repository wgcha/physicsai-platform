"""job-queues.md V-JQ-14: GET /queue gpu·cpu 분리·자기 대기열 순번·deprecated 필드, /resources.jobs, MCP system_status·plan·lane_info,
JobSummary.resumed·대기 중 current_step_label(다음 step)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from helpers_queue import P, PW
from mcp_helpers import T, enable, issue
from physicsai_test_support import API
from queue_support import add_job, job_row


@pytest.fixture()
def settings_dict(settings_dict):
    return enable(settings_dict)


def test_queue_splits_gpu_and_cpu_with_own_positions_and_deprecated_fields(client, engine):
    from physicsai_core.db.repositories import job_lease as lease_repo

    c1 = add_job(engine, "TD_DOE_GEN")["id"]
    g1 = add_job(engine, "EVALUATE")["id"]
    c2 = add_job(engine, "TD_EXTRACT_PARAMS")["id"]
    g2 = add_job(engine, "EVALUATE")["id"]
    light = add_job(engine, "PACKAGE_EXPORT")["id"]
    q = client.get(f"{API}/queue", headers=P).json()
    assert [x["id"] for x in q["gpu"]["queued"]] == [g1, g2] and [x["queue_position"] for x in q["gpu"]["queued"]] == [1, 2]
    assert [x["id"] for x in q["cpu"]["queued"]] == [c1, c2] and [x["queue_position"] for x in q["cpu"]["queued"]] == [1, 2]
    assert q["gpu"]["limit"] == 1 and q["cpu"]["limit"] == 4 and q["cpu"]["min_free_memory_gb"] == 8 and q["cpu"]["memory_gate"] is None
    assert [x["id"] for x in q["light"]["queued"]] == [light]
    assert {x["lane"] for x in q["gpu"]["queued"]} == {"GPU"} and {x["lane"] for x in q["cpu"]["queued"]} == {"CPU"}
    # deprecated: queued = GPU·CPU를 queue_seq 순으로 합침(순번은 각 대기열 안), running = gpu ?? cpu ?? null, slot = GPU 슬롯
    assert [x["id"] for x in q["queued"]] == [c1, g1, c2, g2] and q["running"] is None and q["slot"]["holder_job_id"] is None
    with engine.begin() as c:
        run_c = lease_repo.claim_cpu(c, "w", 30, 4)
        run_g = lease_repo.claim_gpu(c, "w", 30)
    assert run_c["id"] == c1 and run_g["id"] == g1
    q = client.get(f"{API}/queue", headers=P).json()
    assert [x["id"] for x in q["gpu"]["running"]] == [g1] and [x["id"] for x in q["cpu"]["running"]] == [c1]
    assert q["running"]["id"] == g1 and q["slot"]["holder_job_id"] == g1 and q["gpu"]["since"] is not None
    assert [x["queue_position"] for x in q["cpu"]["queued"]] == [1] and [x["queue_position"] for x in q["gpu"]["queued"]] == [1]
    assert all(x["queue_position"] is None for x in q["gpu"]["running"] + q["cpu"]["running"])


def test_job_summary_resumed_and_next_step_label_while_waiting(client, engine):
    from physicsai_core.db.repositories import job_lease as lease_repo

    a = add_job(engine, "PREDICT")["id"]
    q = client.get(f"{API}/queue", headers=P).json()
    assert q["cpu"]["queued"][0]["resumed"] is False and q["cpu"]["queued"][0]["current_step_key"] is None
    with engine.begin() as c:
        job = lease_repo.claim_cpu(c, "w", 30, 4)
        for k in ("PR_PREP", "TPL_RENDER", "GEOM_UPDATE", "MESH", "RAD_ASSEMBLE"):
            c.execute(text("update job_steps set state='SUCCEEDED' where job_id=:i and step_key=:k"), {"i": a, "k": k})
        c.execute(text("update jobs set progress_pct=40 where id=:i"), {"i": a})
        lease_repo.release(c, a, job["lease_token"], "QUEUED", next_lane="GPU")  # T17
    row = job_row(engine, a)
    assert row["current_step_no"] == 6 and row["lane"] == "GPU" and row["queue_seq"] == row["queue_origin_seq"]
    q = client.get(f"{API}/queue", headers=P).json()
    it = q["gpu"]["queued"][0]
    assert it["id"] == a and it["resumed"] is True and it["progress_pct"] == 40
    assert it["current_step_key"] == "EDSPY_PREDICT" and it["current_step_label"] == "예측 실행"  # 다음에 실행할 step
    assert client.get(f"{API}/jobs/{a}", headers=P).json()["resumed"] is True


def test_queue_view_hides_preview_lane(client, engine):
    from physicsai_core.db.repositories import jobs as jobs_repo
    from physicsai_core.db.repositories import studies as studies_repo
    from queue_support import new_study

    sid = new_study(engine)
    with engine.begin() as c:
        jid = jobs_repo.insert_job(c, study=studies_repo.require(c, sid), job_type="GEOM_PREVIEW", params={}, user_id="u", user_name="u")["id"]
    assert job_row(engine, jid)["lane"] == "PREVIEW"
    q = client.get(f"{API}/queue", headers=P).json()
    seen = [x["id"] for k in ("gpu", "cpu") for x in q[k]["queued"] + q[k]["running"]] + [x["id"] for x in q["light"]["queued"]]
    assert jid not in seen and q["queued"] == []


def test_resources_has_jobs_and_new_limits(client, engine, worker_factory):
    from physicsai_core.db.repositories import workers as workers_repo

    base = {"sampled_at": "2026-10-19T00:00:00+00:00", "cpu_pct": 1.0, "ram_used_gb": 1.0, "ram_total_gb": 2.0, "gpu": [], "job": None}
    with engine.begin() as c:  # 옛 표본: jobs·새 한도 키 없음 → 빈 목록·null
        workers_repo.upsert(c, worker_id="w-old", host="h", pid=1, app_version="x", limiter="null",
                            effective_limits={"cores": 4}, resources=base)
    r = client.get(f"{API}/resources", headers=P).json()
    assert r["jobs"] == [] and r["limits"]["cpu_max_concurrent"] is None and r["limits"]["total_cap"] is None
    jobs = [{"job_id": "j-g", "lane": "GPU", "cpu_time_s": 1.5, "peak_memory_gb": 2.0},
            {"job_id": "j-c", "lane": "CPU", "cpu_time_s": 0.5, "peak_memory_gb": None}]
    with engine.begin() as c:
        workers_repo.upsert(c, worker_id="w-new", host="h", pid=2, app_version="x", limiter="posix",
                            effective_limits={"cores": 4, "cpu_max_concurrent": 3, "total_cap": "nested", "memory_gate": "ok"},
                            resources={**base, "job": jobs[0], "jobs": jobs})
    r = client.get(f"{API}/resources", headers=P).json()
    assert [j["job_id"] for j in r["jobs"]] == ["j-g", "j-c"] and r["job"]["job_id"] == "j-g" and r["job"]["lane"] == "GPU"
    assert r["limits"]["cpu_max_concurrent"] == 3 and r["limits"]["total_cap"] == "nested"
    assert client.get(f"{API}/queue", headers=P).json()["cpu"]["memory_gate"] == "ok"


def test_worker_heartbeat_reports_queue_limits(client, worker_factory):
    w = worker_factory()
    w.heartbeat_once()
    r = client.get(f"{API}/resources", headers=P).json()
    assert r["limits"]["cpu_max_concurrent"] == 4 and r["limits"]["total_cap"] == w.cap_mode and r["jobs"] == []


def test_mcp_system_status_plan_and_lane_info(client, engine):
    from physicsai_api.mcp import job_kinds as jk
    from physicsai_core.db.repositories import job_lease as lease_repo

    g1 = add_job(engine, "EVALUATE")["id"]
    c1 = add_job(engine, "TD_DOE_GEN")["id"]
    with engine.begin() as c:
        lease_repo.claim_gpu(c, "w", 30)
        lease_repo.claim_cpu(c, "w", 30, 4)
    read, _ = issue(client, scope="read")
    st = client.get(f"{API}/mcp/system", headers=T(read)).json()
    assert st["gpu_holder_job_id"] == g1 == st["slot_holder_job_id"] and st["cpu_running"] == 1 and st["cpu_limit"] == 4
    assert {x["id"] for x in st["queue_head"]} == {g1, c1} and len(st["queue_head"]) <= 5
    # lane_info: 정적 lane 불변(SLOT·LIGHT·PREVIEW) + uses_global_slot = GPU step 있음 + segments
    assert jk.lane_info("PREDICT") == {"lane": "SLOT", "uses_global_slot": True, "segments": ["cpu", "gpu", "cpu"]}
    assert jk.lane_info("TD_DOE_GEN") == {"lane": "SLOT", "uses_global_slot": False, "segments": ["cpu"]}
    assert jk.lane_info("EVALUATE")["segments"] == ["gpu"]
    assert jk.lane_info("MODEL_REGISTER") == {"lane": "LIGHT", "uses_global_slot": False, "segments": ["light"]}
    assert jk.lane_info("GEOM_PREVIEW")["lane"] == "PREVIEW"


def test_mcp_plan_queue_ahead_counts_initial_queue(client, engine, monkeypatch, tmp_path):
    from mcp_helpers import install_test_kinds

    root = tmp_path / "hpc_results"
    root.mkdir(exist_ok=True)
    calls = install_test_kinds(monkeypatch, root)
    for _ in range(3):
        add_job(engine, "EVALUATE")  # GPU 대기 3건 — CPU 대기열 계획의 queue_ahead에 섞이지 않는다
    add_job(engine, "TD_DOE_GEN")
    r = client.post(f"{API}/studies", headers=PW, json={"project_id": "p-1", "folder_name": "QA", "title": "QA"})
    sid = r.json()["id"]
    p = client.post(f"{API}/mcp/jobs/plan", headers=PW, json={"kind": "test_heavy", "study_id": sid, "params": {}}).json()
    assert p["valid"] and calls["plan"]
    # test_heavy는 MODEL_REGISTER(LIGHT)라 LIGHT 대기열(0건) 기준
    assert p["lane"] == "LIGHT" and p["queue_ahead"] == 0 and p["segments"] == ["light"] and p["uses_global_slot"] is False


def test_contour3d_runs_in_cpu_queue_not_light(client, engine):
    """2026-10-22 사용자 결정(job-queues.md JQ-8): CONTOUR_3D는 LIGHT가 아니라 CPU 대기열 — CPU 상한에 세고 claim_light는 받지 않는다."""
    from physicsai_core.db.repositories import job_lease as lease_repo

    c3 = add_job(engine, "CONTOUR_3D")["id"]
    assert job_row(engine, c3)["lane"] == "CPU"
    q = client.get(f"{API}/queue", headers=P).json()
    assert [x["id"] for x in q["cpu"]["queued"]] == [c3] and q["light"]["queued"] == []
    with engine.begin() as c:
        assert lease_repo.claim_light(c, "w", 30) is None
    other = add_job(engine, "TD_DOE_GEN")["id"]
    with engine.begin() as c:
        assert lease_repo.claim_cpu(c, "w", 30, 1)["id"] == c3  # 상한 1: 먼저 등록된 CONTOUR_3D가 CPU 슬롯을 쥔다
        assert lease_repo.claim_cpu(c, "w", 30, 1) is None  # 다른 CPU 작업은 상한 때문에 대기
    assert job_row(engine, other)["state"] == "QUEUED"
    assert job_row(engine, c3)["state"] == "RUNNING"
