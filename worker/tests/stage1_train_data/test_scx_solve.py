"""phase3 §16.12: ①-4 TD_SOLVE scx 모드(가짜 relay) — 업로드 → 제출 → 폴링 → 회수, 결과 모름(SUBMISSION_UNKNOWN)·조치,
확정 실패 형제 취소, STAGE_IN 실패, 취소, 경로 안전."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text

from helpers_stage1 import _ready_doe, job, submit
from physicsai_test_support import API, H

PW, P, AW = H("tok-power", write=True), H("tok-power"), H("tok-admin", write=True)
OUTPUTS = {"drop_A001.h3d": b"H3D-result", "drop_T01": b"T01", "drop_0000.out": b"out", "sub/drop_A002.h3d": b"H3D-2",
           "ignore.tmp": b"x"}


def _runs(c, doe_id):
    return {r["run_key"]: r for r in c.get(f"{API}/train-does/{doe_id}/runs", headers=P).json()}


def _hpc(c, jid):
    return c.get(f"{API}/jobs/{jid}/hpc-jobs", headers=P).json()


def _no_sleep(w):
    w.hpc._sleep = lambda _s: None


def _enrich_inputs(ai, name, doe_id):
    """run 입력 폴더에 engine·include·제외 대상(.txt·하위 폴더·링크)을 더한다."""
    starters = sorted((ai / name / "01_train" / "doe" / doe_id).rglob("drop_0000.rad"))
    assert starters
    for st in starters:
        d = st.parent
        (d / "drop_0001.rad").write_text("/ENGINE\n")
        (d / "RENUM_INIT.csv").write_text("part,node_start\n")
        (d / "notes.txt").write_text("x")
        (d / "nested").mkdir(exist_ok=True)
        (d / "nested" / "deep.inc").write_text("x")
    return starters


def test_scx_solve_full_cycle(p2_scx, engine):
    """업로드(패턴만·sha·새 폴더) → 제출(engine·additional) → 상태 Queued/Running/Completed → relay 다운로드 회수 → 등록."""
    c, mk, ai, lc, d, fake = p2_scx
    fake.outputs = dict(OUTPUTS)
    w = mk()
    sid, doe_id = _ready_doe(c, w, ai, "sx1")
    _enrich_inputs(ai, "sx1", doe_id)
    j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id, "hpc": {"ncpus": 4, "queue": "ignored"}})
    assert w.run_once_slot() == "WAITING_HPC", job(c, j["id"])
    # 드라이브: sx1/01_D-001_run__0000N_<ts>/ (항상 새 폴더), 패턴 일치 파일만
    proj = fake.drive / "sx1"
    dirs = sorted(p.name for p in proj.iterdir())
    assert len(dirs) == 3 and all(re.fullmatch(r"01_D-001_run__0000[123]_\d{8}T\d{6}", n) for n in dirs), dirs
    assert len({n.rsplit("_", 1)[1] for n in dirs}) == 1  # 한 작업의 run들은 같은 시각
    up = sorted(p.name for p in (proj / dirs[0]).iterdir())
    assert up == ["RENUM_INIT.csv", "drop_0000.rad", "drop_0001.rad", "eps_mesh_1.inc"], up  # .txt·하위 폴더 제외
    assert any(x["code"] == "SCX_SUBDIR_SKIPPED" for x in job(c, j["id"])["warnings"])
    # 제출 요청: starter·engine(_0001)·나머지 additional(이름순)·자원(params ncpus 덮어씀)·같은 폴더
    body = fake.adapter_calls[0]
    jd0 = f"sx1/{dirs[0]}"
    assert body["input_path"] == f"{jd0}/drop_0000.rad" and body["engine_paths"] == [f"{jd0}/drop_0001.rad"]
    assert body["additional_paths"] == [f"{jd0}/RENUM_INIT.csv", f"{jd0}/eps_mesh_1.inc"]
    assert body["resources"] == {"appliance": "radioss-app", "ncpu": 4, "memory_gb": None, "queue_type": "implicit"}
    assert body["request_id"].startswith("pai-") and body["client_ref"]["run_key"] == "run__00001"
    hj = _hpc(c, j["id"])
    assert [h["state"] for h in hj] == ["QUEUED"] * 3 and all(h["gateway_mode"] == "scx" for h in hj)
    assert all(h["remote_dir"].startswith("/Users/vd.dashboard/sx1/01_D-001_") for h in hj)
    assert {h["request_id"] for h in hj} == {"pai-" + h["id"] for h in hj}
    assert all(h["submission_unknown"] is False and h["resolve_pending"] is False for h in hj)
    assert set(r["state"] for r in _runs(c, doe_id).values()) == {"SUBMITTED"}
    # 폴링: Queued → Running → Completed(outcome SUCCEEDED) → T10
    for _ in range(3):
        w.poll_hpc_once()
    jd = job(c, j["id"])
    assert jd["state"] == "COLLECTING", jd
    assert w.run_once_collect() == "QUEUED"
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    R = ai / "sx1" / "01_train" / "results" / doe_id / "run__00001"
    assert (R / "drop_A001.h3d").read_bytes() == b"H3D-result" and (R / "sub" / "drop_A002.h3d").read_bytes() == b"H3D-2"
    assert not (R / "ignore.tmp").exists() and not list(R.rglob("*.part"))
    runs = _runs(c, doe_id)
    assert {r["state"] for r in runs.values()} == {"COLLECTED"}
    assert job(c, j["id"])["result"]["collected"] == 3
    assert all(h["collect_state"] == "COLLECTED" for h in _hpc(c, j["id"]))
    with engine.connect() as conn:
        ev = [e for (e,) in conn.execute(text("select event from notifications where job_id=:j order by seq"), {"j": j["id"]})]
    assert "HPC_SUBMISSION_UNKNOWN" not in ev and "HPC_COLLECTED" in ev


def test_scx_unknown_then_attach(p2_scx, engine):
    """SUBMISSION_UNKNOWN: 형제 취소 없음·남은 run 미제출·attention·알림·WAITING_HPC, 폴러 조회 건너뜀(LOST 안 됨) → attach."""
    c, mk, ai, lc, d, fake = p2_scx
    fake.outputs = dict(OUTPUTS)
    w = mk()
    _no_sleep(w)
    sid, doe_id = _ready_doe(c, w, ai, "sx2")
    fake.submit_mode_seq = ["ok", "unknown"]
    j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id})
    assert w.run_once_slot() == "WAITING_HPC", job(c, j["id"])
    jd = job(c, j["id"])
    assert jd["attention_code"] == "HPC_SUBMISSION_UNKNOWN"
    assert jd["result"]["not_submitted"] == ["run__00003"] and jd["result"]["submitted"] == 2
    assert any(x["code"] == "SCX_NOT_SUBMITTED" for x in jd["warnings"])
    assert fake.terminated == [] and len(fake.adapter_calls) == 2  # 자동 재제출·형제 취소 없음, 3번째 미제출
    hj = {h["run_key"]: h for h in _hpc(c, j["id"])}
    assert hj["run__00001"]["state"] == "QUEUED"
    u = hj["run__00002"]
    assert u["state"] == "UNKNOWN" and u["submission_unknown"] and u["external_job_id"] is None
    assert "SCX에서 확인 필요" in u["error_message"]
    assert hj["run__00003"]["state"] == "CANCELED"
    runs = _runs(c, doe_id)
    assert runs["run__00001"]["state"] == runs["run__00002"]["state"] == "SUBMITTED"
    assert runs["run__00003"]["state"] == "GENERATED"  # 다시 제출 대상
    with engine.connect() as conn:
        n = conn.execute(text("select count(*) from notifications where job_id=:j and event='HPC_SUBMISSION_UNKNOWN'"),
                         {"j": j["id"]}).scalar()
    assert n == 1
    # 폴링 여러 번: 결과 모름 행은 조회하지 않고 LOST·실패가 되지 않는다
    for _ in range(6):
        w.poll_hpc_once()
    jd = job(c, j["id"])
    assert jd["state"] == "WAITING_HPC"
    hj = {h["run_key"]: h for h in _hpc(c, j["id"])}
    assert hj["run__00001"]["state"] == "SUCCEEDED" and hj["run__00002"]["state"] == "UNKNOWN"
    # resolve API: 권한·검증·409
    url = f"{API}/jobs/{j['id']}/hpc-jobs/{u['id']}/resolve"
    assert c.post(url, json={"action": "recheck", "version": u["version"]}).status_code == 401
    assert c.post(url, headers=H("tok-power2", write=True), json={"action": "recheck", "version": u["version"]}).status_code == 403
    r = c.post(f"{API}/jobs/{j['id']}/hpc-jobs/{hj['run__00001']['id']}/resolve", headers=PW,
               json={"action": "recheck", "version": hj["run__00001"]["version"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "HPC_NOT_UNKNOWN"
    r = c.post(url, headers=PW, json={"action": "attach", "version": u["version"]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS"
    r = c.post(url, headers=PW, json={"action": "attach", "external_job_id": "a\x01b", "version": u["version"]})
    assert r.status_code == 422
    r = c.post(url, headers=PW, json={"action": "recheck", "version": u["version"] + 5})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "VERSION_CONFLICT"
    # recheck: 같은 request_id replay → 여전히 UNKNOWN(어댑터 재호출 없음)
    r = c.post(url, headers=PW, json={"action": "recheck", "version": u["version"]})
    assert r.status_code == 202 and r.json()["resolve_pending"] is True
    r2 = c.post(url, headers=PW, json={"action": "recheck", "version": r.json()["version"]})
    assert r2.status_code == 409 and r2.json()["detail"]["code"] == "HPC_RESOLVE_PENDING"
    w.poll_hpc_once()
    u = {h["run_key"]: h for h in _hpc(c, j["id"])}["run__00002"]
    assert u["state"] == "UNKNOWN" and u["resolve_pending"] is False and "아직 확인 불가" in u["error_message"]
    assert len(fake.adapter_calls) == 2
    # attach: 사용자가 SCX에서 찾은 잡 ID 연결
    jid_remote = fake_relay_add(fake, u["remote_dir"].removeprefix("/Users/vd.dashboard/"))
    r = c.post(url, headers=PW, json={"action": "attach", "external_job_id": jid_remote, "version": u["version"]})
    assert r.status_code == 202, r.text
    w.poll_hpc_once()
    u = {h["run_key"]: h for h in _hpc(c, j["id"])}["run__00002"]
    assert u["state"] in ("QUEUED", "RUNNING", "SUCCEEDED") and u["external_job_id"] == jid_remote
    assert u["submission_unknown"] is False
    jd = job(c, j["id"])
    assert jd["attention_code"] is None or jd["state"] != "WAITING_HPC"
    with engine.connect() as conn:
        acts = [a for (a,) in conn.execute(text("select action from audit_events where target_id=:h"), {"h": u["id"]})]
    assert acts.count("HPC_RESOLVE") == 2
    for _ in range(4):
        w.poll_hpc_once()
    assert job(c, j["id"])["state"] == "COLLECTING"
    assert w.run_once_collect() == "QUEUED"
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    runs = _runs(c, doe_id)
    assert runs["run__00001"]["state"] == runs["run__00002"]["state"] == "COLLECTED"
    assert job(c, j["id"])["result"]["submitted"] == 2  # 미제출(not_submitted) 행 제외
    # D3-57 ①: 미제출 CANCELED 행은 실패로 세지 않음 → T10b(일부 실패)가 아니라 T10
    with engine.connect() as conn:
        ev = [e for (e,) in conn.execute(text("select event from notifications where job_id=:j"), {"j": j["id"]})]
    assert "HPC_PARTIAL_FAILED" not in ev


def fake_relay_add(fake, job_dir: str) -> str:
    from physicsai_test_support import fake_relay_module

    return fake_relay_module().add_remote_job(fake, job_dir)


def test_scx_unknown_mark_not_submitted_and_cancel(p2_scx):
    """mark_not_submitted → 행 FAILED·run SOLVE_FAILED(재제출 대상). 결과 모름 행이 있는 작업 취소 → 원격 호출 없이 CANCELED + 경고."""
    c, mk, ai, lc, d, fake = p2_scx
    w = mk()
    _no_sleep(w)
    sid, doe_id = _ready_doe(c, w, ai, "sx3", num_runs=2)
    fake.submit_mode_seq = ["unknown"]
    j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id})
    assert w.run_once_slot() == "WAITING_HPC"
    hj = {h["run_key"]: h for h in _hpc(c, j["id"])}
    u = hj["run__00001"]
    assert u["state"] == "UNKNOWN" and hj["run__00002"]["state"] == "CANCELED"
    fake.resolve_mode = "DRIVE_BUSY"  # relay 정리 실패여도 PhysicsAI 쪽은 진행 + 경고
    r = c.post(f"{API}/jobs/{j['id']}/hpc-jobs/{u['id']}/resolve", headers=PW,
               json={"action": "mark_not_submitted", "version": u["version"]})
    assert r.status_code == 202
    w.poll_hpc_once()
    u = {h["run_key"]: h for h in _hpc(c, j["id"])}["run__00001"]
    assert u["state"] == "FAILED" and u["error_message"] == "제출되지 않음(사용자 확인)"
    jd = job(c, j["id"])
    assert jd["state"] == "FAILED" and jd["failure_code"] == "HPC_RUN_FAILED"  # 성공 0개 → T13
    assert any(x["code"] == "SCX_RESOLVE_RELAY_FAILED" for x in jd["warnings"])
    runs = _runs(c, doe_id)
    assert runs["run__00001"]["state"] == "SOLVE_FAILED" and runs["run__00002"]["state"] == "GENERATED"
    # 다시 제출: 새 TD_SOLVE·새 잡 폴더(이전 폴더 재사용 없음)
    fake.resolve_mode = "ok"
    fake.submit_mode_seq = ["ok", "unknown"]
    j2 = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id})
    assert w.run_once_slot() == "WAITING_HPC"
    dirs = sorted(p.name for p in (fake.drive / "sx3").iterdir())
    assert len(dirs) == 4, dirs
    # 취소: 제출된 run은 terminate, 결과 모름 행은 원격 호출 없이 CANCELED + 경고
    assert c.post(f"{API}/jobs/{j2['id']}/cancel", headers=AW).status_code == 202
    w.poll_hpc_once()
    jd2 = job(c, j2["id"])
    assert jd2["state"] == "CANCELED"
    assert len(fake.terminated) == 1
    hj2 = {h["run_key"]: h for h in _hpc(c, j2["id"])}
    unk = [h for h in hj2.values() if h["submission_unknown"]]
    assert len(unk) == 1 and unk[0]["state"] == "CANCELED" and "SCX에서 직접 확인" in unk[0]["error_message"]
    assert any(x["code"] == "SCX_UNKNOWN_CANCELED" for x in jd2["warnings"])


def test_scx_definite_failure_cancels_siblings(p2_scx):
    """확정 실패 → 행 FAILED + 이미 제출한 run terminate + HPC_SUBMIT_FAILED(phase2 §6.5 그대로)."""
    c, mk, ai, lc, d, fake = p2_scx
    w = mk()
    sid, doe_id = _ready_doe(c, w, ai, "sx4")
    fake.submit_mode_seq = ["ok", "fail:SCX_JOB_ERROR"]
    j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id})
    assert w.run_once_slot() == "FAILED"
    jd = job(c, j["id"])
    assert jd["failure_code"] == "HPC_SUBMIT_FAILED" and "SCX_JOB_ERROR" in jd["failure_message"]
    assert len(fake.terminated) == 1
    states = {h["run_key"]: h["state"] for h in _hpc(c, j["id"])}
    assert states == {"run__00001": "CANCELED", "run__00002": "FAILED", "run__00003": "CANCELED"}
    runs = _runs(c, doe_id)
    assert runs["run__00001"]["state"] == "SOLVE_FAILED" and runs["run__00003"]["state"] == "GENERATED"


@pytest.mark.parametrize("mode, code", [("conflict", "SCX_STAGE_IN_FAILED"), ("spdm", "SCX_PATH_NOT_ALLOWED"),
                                        ("no_job_api", "HPC_SUBMIT_FAILED"), ("writes_off", "HPC_SUBMIT_FAILED"),
                                        ("too_big", "INPUT_INVALID")])
def test_scx_stage_in_failures_submit_nothing(p2_scx, mode, code):
    """STAGE_IN 실패·경로 금지·health 거부 → 제출 0건, 행 FAILED(또는 없음), 드라이브 삭제 없음."""
    c, mk, ai, lc, d, fake = p2_scx
    w = mk()
    sid, doe_id = _ready_doe(c, w, ai, "sx5", num_runs=2)
    if mode == "conflict":
        fake.batch_steps = ["CONFLICT"]
    elif mode == "spdm":
        fake.forbidden_prefixes = ["SX5/inner"]  # 프로젝트 폴더(sx5)가 SPDM 루트의 상위 → 거부(대소문자 무시)
    elif mode == "writes_off":
        fake.writes_active = False
    elif mode == "too_big":
        fake.max_upload_bytes = 5
    j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id})
    if mode == "no_job_api":  # 작업 생성 뒤 대시보드 어댑터가 바뀜(생성 때는 API availability가 막는다 — 아래 시험)
        fake.job_api = False
    assert w.run_once_slot() == "FAILED"
    jd = job(c, j["id"])
    assert jd["failure_code"] == code, jd
    assert fake.adapter_calls == []
    hj = _hpc(c, j["id"])
    assert all(h["state"] == "FAILED" for h in hj)
    if mode == "conflict":
        assert len(hj) == 2
    else:
        assert hj == []
    assert {r["state"] for r in _runs(c, doe_id).values()} == {"GENERATED"}


def test_scx_replay_on_dropped_response(p2_scx):
    """제출 응답이 끊기면 같은 request_id로 replay — relay 어댑터 호출 1회(중복 제출 아님)."""
    c, mk, ai, lc, d, fake = p2_scx
    w = mk()
    _no_sleep(w)
    sid, doe_id = _ready_doe(c, w, ai, "sx6", num_runs=2)
    fake.drop_submit = 2
    j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id, "run_keys": ["run__00001"]})
    assert w.run_once_slot() == "WAITING_HPC"
    assert len(fake.adapter_calls) == 1 and len(fake.calls("/jobs/radioss")) == 3
    assert [h["state"] for h in _hpc(c, j["id"])] == ["QUEUED"]


def test_scx_collect_failures(p2_scx, engine):
    """회수: output_rel 없음 → SCX_OUTPUT_MISSING, 해시 불일치 1회는 다시 받음(.part 미잔존), 상한 초과 → 그 run 실패(T10b 기록)."""
    c, mk, ai, lc, d, fake = p2_scx
    fake.outputs = {"drop_A001.h3d": b"H3D", "drop_T01": b"T"}
    w = mk()
    sid, doe_id = _ready_doe(c, w, ai, "sx7", num_runs=2)
    fake.hash_mismatch = 1
    j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id})
    assert w.run_once_slot() == "WAITING_HPC"
    # run__00002는 결과 위치를 모름(relay output_rel null — E4-11-6)
    rj = [x for x in fake.jobs.values() if x["body"]["client_ref"]["run_key"] == "run__00002"][0]
    rj["output_rel"] = None
    with engine.begin() as conn:
        conn.execute(text("update hpc_jobs set output_rel=null, output_path=null where job_id=:j and run_key='run__00002'"),
                     {"j": j["id"]})
    for _ in range(3):
        w.poll_hpc_once()
    assert job(c, j["id"])["state"] == "COLLECTING"
    assert w.run_once_collect() == "QUEUED"
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    jd = job(c, j["id"])
    assert jd["result"]["collected_runs"] == ["run__00001"] and jd["result"]["collect_failed"] == ["run__00002"]
    assert any(x["code"] == "COLLECT_PARTIAL" for x in jd["warnings"])
    R = ai / "sx7" / "01_train" / "results" / doe_id
    assert (R / "run__00001" / "drop_A001.h3d").read_bytes() == b"H3D" and not list(R.rglob("*.part"))
    assert _runs(c, doe_id)["run__00002"]["state"] == "COLLECT_FAILED"
    log = (ai / "sx7" / "logs" / j["id"]).rglob("*.log")
    assert any("SCX 결과 위치 없음" in p.read_text(encoding="utf-8") for p in log)


def test_scx_job_api_missing_blocks_creation(p2_scx):
    """availability: 대시보드 어댑터에 잡 API 없음 → configured=false → 작업 생성 409(HPC_NOT_CONFIGURED)."""
    c, mk, ai, lc, d, fake = p2_scx
    w = mk()
    sid, doe_id = _ready_doe(c, w, ai, "sx8", num_runs=2)
    fake.job_api = False
    r = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "TD_SOLVE", "params": {"doe_id": doe_id}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "HPC_NOT_CONFIGURED"
    st = c.get(f"{API}/status", headers=P).json()["hpc"]
    assert st["mode"] == "scx" and st["configured"] is False and "잡 API" in st["message"]


def test_scx_collect_path_safety(tmp_path, settings_dict):
    """회수 경로 안전: `..`·빈 구간·':'·공백(AI 루트 경로 규칙)·링크·AI 루트 밖 거부, relay 목록의 이상한 이름은 건너뜀."""
    import os
    import types

    from physicsai_core.config import load_config_dict
    from physicsai_worker.steps import _scx

    lc = load_config_dict(settings_dict, environ={})
    ai = lc.settings.storage.ai_root
    ctx = types.SimpleNamespace(settings=lc.settings)
    res = os.path.join(ai, "S1", "01_train", "results", "d", "run__00001")
    os.makedirs(res)
    assert _scx._safe_target(ctx, res, "sub/a.h3d") == os.path.join(res, "sub", "a.h3d")
    for bad in ("../a.h3d", "sub/../../a.h3d", "a//b.h3d", "a:b.h3d", "a b.h3d", "/abs.h3d"):
        with pytest.raises(_scx.CollectFail) as ei:
            _scx._safe_target(ctx, res, bad)
        assert ei.value.code == "PATH_UNSAFE", bad
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(_scx.CollectFail):
        _scx._safe_target(ctx, str(outside), "a.h3d")
    if os.name != "nt":
        os.symlink(outside, os.path.join(res, "lnk"))
        with pytest.raises(_scx.CollectFail):
            _scx._safe_target(ctx, res, "lnk/a.h3d")

    class GW:
        def list(self, rel, _n):
            return {"out": [{"name": "../evil.h3d", "kind": "file", "size": 1}, {"name": "a\\b.h3d", "kind": "file", "size": 1},
                            {"name": "ok.h3d", "kind": "file", "size": 3}, {"name": "d", "kind": "dir"}],
                    "out/d": [{"name": "deep", "kind": "dir"}, {"name": "x.h3d", "kind": "file", "size": 2}],
                    "out/d/deep": [{"name": "y.h3d", "kind": "file", "size": 2}]}[rel]

    assert _scx._walk(GW(), "out", 1) == [("d/x.h3d", 2), ("ok.h3d", 3)]
    assert _scx._walk(GW(), "out", 2) == [("d/deep/y.h3d", 2), ("d/x.h3d", 2), ("ok.h3d", 3)]
    assert _scx._walk(GW(), "out", 0) == [("ok.h3d", 3)]


def _stub_ctx(settings, logs=None):
    import types

    ex = types.SimpleNamespace(db=lambda fn: None)
    return types.SimpleNamespace(settings=settings, checkpoint=lambda: None, log=(logs or []).append, ex=ex, params={})


@pytest.mark.parametrize("rel", ["NUL.h3d", "con/x.h3d", "CON/x", "a?.h3d", "a*.h3d", "a<b.h3d", 'a"b.h3d', "a|b.h3d",
                                 "lpt1.out", "x./a.h3d", "sub /a.h3d"])
def test_scx_collect_rejects_windows_unsafe_names(settings_dict, rel):
    """M1: Windows 예약 이름·금지 문자·끝 마침표/공백 → 그 run PATH_UNSAFE(Linux에서도 같은 판정)."""
    import os

    from physicsai_core.config import load_config_dict
    from physicsai_worker.steps import _scx

    lc = load_config_dict(settings_dict, environ={})
    res = os.path.join(lc.settings.storage.ai_root, "S2", "r")
    os.makedirs(res)
    with pytest.raises(_scx.CollectFail) as ei:
        _scx._safe_target(_stub_ctx(lc.settings), res, rel)
    assert ei.value.code == "PATH_UNSAFE"


def test_scx_collect_collisions_and_local_errors(settings_dict):
    """M1: 대소문자만 다른 경로·파일/폴더 이름 충돌·이미 있는 같은 이름 폴더·로컬 쓰기 오류는 그 run만 실패(CollectFail)."""
    import os
    import types

    from physicsai_core.config import load_config_dict
    from physicsai_worker.steps import _scx

    assert _scx._collisions(["A.h3d", "b.h3d", "a.h3d"]) == "A.h3d · a.h3d"
    assert _scx._collisions(["d", "D/x.h3d"]) == "d · D/x.h3d"
    assert _scx._collisions(["a.h3d", "sub/a.h3d"]) is None
    lc = load_config_dict(settings_dict, environ={})
    ctx = _stub_ctx(lc.settings)
    res = os.path.join(lc.settings.storage.ai_root, "S3", "r")
    os.makedirs(os.path.join(res, "x.h3d"))  # 같은 이름 폴더가 이미 있음
    with pytest.raises(_scx.CollectFail) as ei:
        _scx._safe_target(ctx, res, "x.h3d")
    assert ei.value.code == "PATH_UNSAFE"

    class GW:
        cfg = types.SimpleNamespace(max_download_bytes=1 << 30, collect_max_depth=2)

        def __init__(self, entries, fail=None):
            self.entries, self.fail, self.got = entries, fail, []

        def list(self, rel, _n):
            return self.entries.get(rel, [])

        def download(self, remote, dst, _limit, on_chunk=None):
            if self.fail:
                raise self.fail
            with open(dst, "wb") as fh:
                fh.write(b"x")
            self.got.append(remote)
            return 1, "h"

    row = {"id": "h1", "output_rel": "out", "external_job_id": "j"}
    f = lambda n: {"name": n, "kind": "file", "size": 1}  # noqa: E731
    gw = GW({"out": [f("A.h3d"), f("a.h3d")]})
    with pytest.raises(_scx.CollectFail) as ei:
        _scx.collect_run(ctx, gw, row, res, None)
    assert ei.value.code == "PATH_UNSAFE" and gw.got == []  # 내려받기 전에 실패
    gw = GW({"out": [f("ok.h3d"), f("NUL.h3d")]})
    with pytest.raises(_scx.CollectFail):
        _scx.collect_run(ctx, gw, row, res, None)
    assert gw.got == []  # 모든 대상 검사 후에만 내려받음
    gw = GW({"out": [f("ok.h3d")]}, fail=IsADirectoryError("x"))
    with pytest.raises(_scx.CollectFail) as ei:
        _scx.collect_run(ctx, gw, row, res, None)
    assert ei.value.code == "COLLECT_FAILED" and "IsADirectoryError" in ei.value.message
    gw = GW({"out": [f("ok.h3d"), {"name": "s", "kind": "dir"}], "out/s": [f("ok2.h3d")]})
    assert _scx.collect_run(ctx, gw, row, res, None) == ["ok.h3d", "s/ok2.h3d"]
    assert not [p for p in os.listdir(res) if p.endswith(".part")]


def test_scx_build_request_engine_casefold():
    """minor c: starter `_0000.RAD`(대소문자 무관) → 같은 기준 이름의 `_0001` engine."""
    import types

    from physicsai_worker.steps import _scx

    cfg = types.SimpleNamespace(list_additional_paths=True, ncpu=8, version="v", appliance="a", memory_gb=None,
                                queue_type="q", run_type="r", mpi="m", single_precision=False)
    gw = types.SimpleNamespace(cfg=cfg)
    p = _scx.RunStage(run_key="r1", input_dir="", starter="DROP_0000.RAD", job_name="j", client_ref={},
                      files=[{"name": n} for n in ("DROP_0000.RAD", "drop_0001.rad", "a.inc")], remote_dir="p/j",
                      request_id="pai-x", hid="x")
    req = _scx.build_request(types.SimpleNamespace(params={}), gw, p)
    assert req.engine_paths == ("p/j/drop_0001.rad",) and req.additional_paths == ("p/j/a.inc",)


def test_scx_upload_odd_file_names(p2_scx):
    """M2: 비ASCII·공백·괄호·+·긴 파일 이름도 올린다(X-Request-Id는 순번, 이름은 쿼리 UTF-8)."""
    c, mk, ai, lc, d, fake = p2_scx
    w = mk()
    sid, doe_id = _ready_doe(c, w, ai, "sx9", num_runs=2)
    names = ["메시 파일.inc", "a (1)+b.inc", "L" * 120 + ".inc"]
    for st in sorted((ai / "sx9" / "01_train" / "doe" / doe_id).rglob("drop_0000.rad")):
        for n in names:
            (st.parent / n).write_text("x", encoding="utf-8")
    j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id, "run_keys": ["run__00001"]})
    assert w.run_once_slot() == "WAITING_HPC", job(c, j["id"])
    jd0 = next((fake.drive / "sx9").iterdir())
    up = {p.name for p in jd0.iterdir()}
    assert set(names) <= up
    rids = [h["x-request-id"] for h in fake.headers_seen if "x-request-id" in h]
    assert rids and all(re.fullmatch(r"pai-[0-9a-f-]{36}:f:\d+", r) for r in rids)
