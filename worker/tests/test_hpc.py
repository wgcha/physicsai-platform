"""V-HPC-1~3: HpcJobGateway none·command(가짜 qsub/qstat/qdel)·adapter, 폴러·회수기(T5·T10·T13·T14·T12)."""

from __future__ import annotations

import copy
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from physicsai_core.config import load_config_dict
from physicsai_core.hpc.command import CommandHpcGateway
from physicsai_core.hpc.gateway import HpcGatewayError, HpcSubmitSpec, get_hpc_gateway
from physicsai_test_support import API, H, make_h3d_tree, make_model_folder, make_param_set_folder, read_record

PW, P, AW = H("tok-power", write=True), H("tok-power"), H("tok-admin", write=True)


def _hpc_settings(settings_dict, tools, ai_root, **cmd_over):
    d = copy.deepcopy(settings_dict)
    cmd = {
        "allowed_executables": [tools["fake_qsub"], tools["fake_qstat"], tools["fake_qdel"]],
        "submit": [tools["fake_qsub"], "-N", "{job_name}", "-q", "{queue}", "-l", "select=1:ncpus={ncpus}", "-l",
                   "walltime={walltime}", "-v", "INPUT_FILE={input_file},RESULT_DIR={result_dir}", "/shared/scripts/radioss_run.pbs"],
        "status": [tools["fake_qstat"], "-x", "-f", "{external_job_id}"],
        "cancel": [tools["fake_qdel"], "{external_job_id}"],
        "state_map": {"Q": "QUEUED", "R": "RUNNING", "F": "FINISHED"},
    }
    cmd.update(cmd_over)
    d["hpc"] = {"gateway": "command", "lost_after_polls": 2, "command": cmd,
                "transfer": {"path_map": [{"local": ai_root, "remote": "/shared/AI_WORK"}]}}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    return lc


@pytest.fixture()
def pbs_state(tmp_path, monkeypatch):
    p = tmp_path / "pbs_state.json"
    monkeypatch.setenv("FAKE_PBS_STATE", str(p))
    monkeypatch.delenv("FAKE_TOOL_MODE_PBS", raising=False)
    return p


def test_none_and_adapter():
    from physicsai_core.config import Settings

    s = Settings()
    assert get_hpc_gateway(s).availability().configured is False
    s2 = Settings.model_validate({"hpc": {"gateway": "adapter"}})
    av = get_hpc_gateway(s2).availability()
    assert av.mode == "adapter" and not av.configured and "미구현" in av.message
    with pytest.raises(HpcGatewayError):
        get_hpc_gateway(s).submit(None)  # type: ignore[arg-type]


def test_adapter_imports_nothing():
    src = (Path(__file__).resolve().parents[2] / "backend" / "physicsai_core" / "hpc" / "adapter.py").read_text()
    assert "import_module" not in src and "__import__" not in src


def test_command_validation_and_injection(settings_dict, fake_tools, tmp_path):
    lc = _hpc_settings(settings_dict, fake_tools, str(tmp_path))
    gw = CommandHpcGateway(lc.settings.hpc)
    assert gw.availability().configured
    base = dict(job_name="s_1_a1", run_key="verify", study="s", input_file="/shared/a.rad", input_dir="/shared",
                result_dir="/shared/r", queue=None, ncpus=None, walltime=None)
    for field, bad in [("job_name", "a;rm"), ("job_name", "a\nb"), ("input_file", "/a/$(id)"), ("result_dir", "/a&b"),
                       ("queue", "q;x"), ("walltime", "1h"), ("ncpus", 5000)]:
        spec = HpcSubmitSpec(**{**base, field: bad})
        with pytest.raises(HpcGatewayError):
            gw.submit(spec)
    with pytest.raises(HpcGatewayError):
        gw.status("12345; rm -rf /")
    # 설정 검증: .bat, 허용 목록 밖, 미허용 placeholder, 문자열 템플릿
    d = copy.deepcopy(settings_dict)
    for over in ({"submit": "qsub -N x"}, {"status": ["/usr/bin/qstat", "{external_job_id}"]},
                 {"cancel": [fake_tools["fake_qdel"], "{evil}"]}, {"allowed_executables": ["C:/PBS/qsub.bat"]}):
        dd = copy.deepcopy(d)
        dd["hpc"] = {"gateway": "command", "command": {
            "allowed_executables": [fake_tools["fake_qsub"], fake_tools["fake_qstat"], fake_tools["fake_qdel"]],
            "submit": [fake_tools["fake_qsub"]], "status": [fake_tools["fake_qstat"], "{external_job_id}"],
            "cancel": [fake_tools["fake_qdel"], "{external_job_id}"], **over}}
        assert "hpc.command" in load_config_dict(dd, environ={}).error_keys(), over


def test_command_status_parsing(settings_dict, fake_tools, tmp_path, pbs_state, monkeypatch):
    gw = CommandHpcGateway(_hpc_settings(settings_dict, fake_tools, str(tmp_path)).settings.hpc)
    r = gw.submit(HpcSubmitSpec("j1", "verify", "s", "/shared/a.rad", "/shared", "/shared/r", None, None, None))
    assert r.external_job_id == "12345.pbs01"
    assert [gw.status("12345.pbs01").state for _ in range(3)] == ["QUEUED", "RUNNING", "FINISHED"]
    st = gw.status("12345.pbs01")
    assert st.exit_code == 0 and st.raw_state == "F"
    monkeypatch.setenv("FAKE_TOOL_MODE_PBS", "not_found")
    assert gw.status("12345.pbs01").not_found
    monkeypatch.setenv("FAKE_TOOL_MODE_PBS", "unknown")
    assert gw.status("12345.pbs01").state == "UNKNOWN"
    monkeypatch.setenv("FAKE_TOOL_MODE_PBS", "submit_fail")
    with pytest.raises(HpcGatewayError) as ei:
        gw.submit(HpcSubmitSpec("j1", "verify", "s", "/shared/a.rad", "/shared", "/shared/r", None, None, None))
    assert ei.value.code == "SUBMIT_FAILED"


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


@pytest.fixture()
def hpc_env(settings_dict, fake_tools, engine, fake_dashboard, pbs_state, monkeypatch, tmp_path):
    from physicsai_api.context import build_context
    from physicsai_api.main import create_app
    from physicsai_worker.steps import _collect
    from physicsai_worker.runtime import Worker

    monkeypatch.setattr(_collect, "COLLECT_STABLE_INTERVAL_S", 0.05)
    ai = settings_dict["storage"]["ai_root"]
    lc = _hpc_settings(settings_dict, fake_tools, ai)
    ctx = build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler))
    with TestClient(create_app(ctx), base_url="http://127.0.0.1") as c:
        yield c, Worker(lc, engine), Path(ai), lc


def test_verify_full_cycle(hpc_env, engine, fake_record):
    c, w, ai, _lc = hpc_env
    sid, pj = _setup_predict(c, w, ai, "HV1")
    r = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "PREDICT_VERIFY", "params": {"predict_job_id": pj, "hpc": {"ncpus": 8}}})
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    assert w.run_once_slot() == "WAITING_HPC"
    with engine.connect() as conn:
        assert conn.execute(text("select holder_job_id from worker_slot")).scalar() is None
    sub = [x for x in read_record(fake_record) if x["tool"] == "qsub"][-1]["argv"]
    assert sub[sub.index("-l") + 1] == "select=1:ncpus=8" and sub[sub.index("-q") + 1] == "workq"
    v_arg = sub[sub.index("-v") + 1]
    assert v_arg.startswith("INPUT_FILE=/shared/AI_WORK/HV1/04_predict/") and v_arg.endswith("/result")
    # 슬롯이 풀렸으므로 다른 SLOT 작업이 claim된다
    inp = make_h3d_tree(ai / "HV1", 4)
    dj = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "DATASET_CREATE", "params": {"input_path": str(inp)}}).json()["id"]
    assert w.run_once_slot() == "SUCCEEDED"
    hj = c.get(f"{API}/jobs/{vid}/hpc-jobs", headers=P).json()
    assert hj[0]["external_job_id"] == "12345.pbs01" and hj[0]["state"] == "QUEUED"
    w.poll_hpc_once()
    assert c.get(f"{API}/jobs/{vid}/hpc-jobs", headers=P).json()[0]["external_state_raw"] == "Q"
    w.poll_hpc_once()
    assert c.get(f"{API}/jobs/{vid}/hpc-jobs", headers=P).json()[0]["state"] == "RUNNING"
    # PBS가 결과를 쓴다(in_place)
    V = ai / "HV1" / "04_predict" / pj / "verify" / "1"
    (V / "result" / "model0_0000.h3d").write_bytes(b"H3D")
    (V / "result" / "model0_0000.out").write_text("x")
    w.poll_hpc_once()
    j = c.get(f"{API}/jobs/{vid}", headers=P).json()
    assert j["state"] == "COLLECTING"
    assert w.run_once_collect() == "QUEUED"  # T14: 회수 후 다시 대기열 뒤
    j = c.get(f"{API}/jobs/{vid}", headers=P).json()
    assert j["state"] == "QUEUED" and j["queue_position"] == 1
    assert w.run_once_slot() == "SUCCEEDED"
    j = c.get(f"{API}/jobs/{vid}", headers=P).json()
    steps = {s["step_key"]: s["state"] for s in j["steps"]}
    assert steps == {"PV_PREP": "SUCCEEDED", "HPC_SUBMIT": "SUCCEEDED", "HPC_WAIT": "SUCCEEDED", "COLLECT": "SUCCEEDED",
                     "PV_EXTRACT": "SKIPPED", "PV_TABLE": "SUCCEEDED"}
    assert j["result"]["collected"] == ["model0_0000.h3d", "model0_0000.out"]
    with engine.connect() as conn:
        ev = [e for (e,) in conn.execute(text("select event from notifications where job_id=:j order by seq"), {"j": vid})]
    assert ev == ["JOB_STARTED", "HPC_COLLECTED", "JOB_SUCCEEDED"]
    del dj


def test_verify_run_failed(hpc_env, monkeypatch):
    c, w, ai, _ = hpc_env
    sid, pj = _setup_predict(c, w, ai, "HV2")
    vid = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "PREDICT_VERIFY", "params": {"predict_job_id": pj}}).json()["id"]
    assert w.run_once_slot() == "WAITING_HPC"
    monkeypatch.setenv("FAKE_TOOL_MODE_PBS", "exit1")
    for _ in range(3):
        w.poll_hpc_once()
    j = c.get(f"{API}/jobs/{vid}", headers=P).json()
    assert j["state"] == "FAILED" and j["failure_code"] == "HPC_RUN_FAILED"


def test_verify_unknown_becomes_lost(hpc_env, monkeypatch):
    c, w, ai, _ = hpc_env
    sid, pj = _setup_predict(c, w, ai, "HV3")
    vid = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "PREDICT_VERIFY", "params": {"predict_job_id": pj}}).json()["id"]
    assert w.run_once_slot() == "WAITING_HPC"
    monkeypatch.setenv("FAKE_TOOL_MODE_PBS", "unknown")
    w.poll_hpc_once()
    assert c.get(f"{API}/jobs/{vid}", headers=P).json()["state"] == "WAITING_HPC"
    w.poll_hpc_once()
    assert c.get(f"{API}/jobs/{vid}/hpc-jobs", headers=P).json()[0]["state"] == "LOST"
    assert c.get(f"{API}/jobs/{vid}", headers=P).json()["failure_code"] == "HPC_RUN_FAILED"


def test_verify_cancel_while_waiting(hpc_env, fake_record):
    c, w, ai, _ = hpc_env
    sid, pj = _setup_predict(c, w, ai, "HV4")
    vid = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "PREDICT_VERIFY", "params": {"predict_job_id": pj}}).json()["id"]
    assert w.run_once_slot() == "WAITING_HPC"
    assert c.post(f"{API}/jobs/{vid}/cancel", headers=AW).status_code == 202
    w.poll_hpc_once()
    assert c.get(f"{API}/jobs/{vid}", headers=P).json()["state"] == "CANCELED"
    assert [x for x in read_record(fake_record) if x["tool"] == "qdel"][-1]["argv"][-1] == "12345.pbs01"
    assert c.get(f"{API}/status", headers=P).json()["hpc"]["configured"] is True
