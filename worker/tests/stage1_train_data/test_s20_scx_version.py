"""S20(D3-68) SCX Radioss 버전 작업별 입력 — V3-S20-3(워커 build_request: params hpc.version > 설정)·
V3-S20-4(command 모드는 무시 로그 1줄, 제출 인자 불변)·V3-S20-5(/status.hpc.scx_version: scx면 설정값, none·command면 null)."""

from __future__ import annotations

import types

import pytest
from sqlalchemy import text

from helpers_stage1 import _ready_doe, job, submit
from physicsai_test_support import API, H, read_record

P = H("tok-power")
IGNORE_LINE = "command 모드는 hpc.version을 쓰지 않습니다(무시)"


def _step_log(c, jid, key="HPC_SUBMIT"):
    no = next(s["step_no"] for s in job(c, jid)["steps"] if s["step_key"] == key)
    return c.get(f"{API}/jobs/{jid}/steps/{no}/log", headers=P).json()["text"]


# ---- V3-S20-3 워커 build_request ----------------------------------------------------------------------------------


@pytest.mark.parametrize("params,want", [({}, "26.1"), ({"hpc": None}, "26.1"), ({"hpc": {"version": None, "ncpus": 4}}, "26.1"),
                                         ({"hpc": {"version": "2026 R2"}}, "2026 R2")])
def test_v3_s20_3_build_request_version(params, want):
    from physicsai_worker.steps import _scx

    cfg = types.SimpleNamespace(list_additional_paths=True, ncpu=8, version="26.1", appliance="a", memory_gb=None,
                                queue_type="q", run_type="r", mpi="m", single_precision=False)
    p = _scx.RunStage(run_key="r1", input_dir="", starter="d_0000.rad", job_name="j", client_ref={},
                      files=[{"name": "d_0000.rad"}], remote_dir="p/j", request_id="pai-x", hid="x")
    req = _scx.build_request(types.SimpleNamespace(params=params), types.SimpleNamespace(cfg=cfg), p)
    assert req.version == want and req.to_json()["version"] == want


def test_v3_s20_3_td_solve_scx_uses_params_version(p2_scx, engine):
    """API(trim·pattern 422) → 워커 제출 요청·제출 기록(staged.request)에 작업별 버전."""
    c, mk, ai, lc, d, fake = p2_scx
    assert lc.settings.hpc.scx.version == "2026.1"  # 가짜 relay 설정값
    w = mk()
    sid, doe_id = _ready_doe(c, w, ai, "sv20", num_runs=2)
    r = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id, "hpc": {"version": "26;1"}}, expect=422)
    assert any(e["loc"][-1] == "version" for e in r["detail"]["errors"]), r
    j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id, "hpc": {"version": "  2026 R2 "}})
    assert job(c, j["id"])["params"]["hpc"]["version"] == "2026 R2"
    assert w.run_once_slot() == "WAITING_HPC", job(c, j["id"])
    assert [b["version"] for b in fake.adapter_calls] == ["2026 R2", "2026 R2"]
    with engine.connect() as conn:
        staged = [s for (s,) in conn.execute(text("select staged from hpc_jobs where job_id=:j"), {"j": j["id"]})]
    assert [s["request"]["version"] for s in staged] == ["2026 R2", "2026 R2"]
    assert IGNORE_LINE not in _step_log(c, j["id"])


# ---- V3-S20-4 command 모드 무시 ---------------------------------------------------------------------------------


def test_v3_s20_4_command_mode_ignores_version(p2_pbs, fake_record):
    c, mk, ai, lc, d = p2_pbs
    w = mk()
    sid, doe_id = _ready_doe(c, w, ai, "sv21", num_runs=2)
    j = submit(c, sid, "TD_SOLVE", {"doe_id": doe_id, "hpc": {"ncpus": 4, "version": "2026 R2"}})
    assert w.run_once_slot() == "WAITING_HPC", job(c, j["id"])
    assert _step_log(c, j["id"]).count(IGNORE_LINE) == 1
    subs = [r["argv"] for r in read_record(fake_record) if r["tool"] == "qsub"]
    assert len(subs) == 2 and not any("2026" in a for argv in subs for a in argv)
    assert all("select=1:ncpus=4" in argv for argv in subs)


def test_v3_s20_4_verify_submit_spec_unchanged():
    """④ 검증 PBS 제출(_verify_hpc.submit): version 유무와 관계없이 HpcSubmitSpec 같음, 무시 로그는 version 있을 때만 1줄."""
    from physicsai_worker.signals import EnterWaitingHpc
    from physicsai_worker.steps.stage4_predict import _verify_hpc

    def run(hpc):
        specs, logs = [], []
        gw = types.SimpleNamespace(
            availability=lambda: types.SimpleNamespace(configured=True, mode="command", message=""),
            submit=lambda spec: specs.append(spec) or types.SimpleNamespace(external_job_id="1.pbs"))
        ctx = types.SimpleNamespace(
            ex=types.SimpleNamespace(w=types.SimpleNamespace(hpc=gw), db=lambda fn: None, job_id="j"),
            settings=types.SimpleNamespace(hpc=types.SimpleNamespace(transfer=types.SimpleNamespace(path_map=[]))),
            params={"hpc": hpc}, study={"folder_name": "S"}, step={"id": "s"}, log=logs.append)
        with pytest.raises(EnterWaitingHpc):
            _verify_hpc.submit(ctx, input_dir="/in", result_dir="/out", starter="m_0000.rad", job_name="jn", attempt=1,
                               scx_job_name=lambda ts: ts)
        return specs, [x for x in logs if x == IGNORE_LINE]

    base, l0 = run({"ncpus": 2, "version": None})
    got, l1 = run({"ncpus": 2, "version": "2026 R2"})
    assert base == got and len(got) == 1 and l0 == [] and l1 == [IGNORE_LINE]


# ---- V3-S20-5 /status.hpc.scx_version ----------------------------------------------------------------------------


def test_v3_s20_5_status_scx(p2_scx):
    c, mk, ai, lc, d, fake = p2_scx
    h = c.get(f"{API}/status", headers=P).json()["hpc"]
    assert h["mode"] == "scx" and h["scx_version"] == lc.settings.hpc.scx.version == "2026.1"


def test_v3_s20_5_status_command(p2_pbs):
    h = p2_pbs[0].get(f"{API}/status", headers=P).json()["hpc"]
    assert h["mode"] == "command" and h["scx_version"] is None


def test_v3_s20_5_status_none(p2_env):
    h = p2_env[0].get(f"{API}/status", headers=P).json()["hpc"]
    assert h["mode"] == "none" and h["scx_version"] is None
