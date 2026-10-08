"""Verifier 결함 회귀(워커·통합): 매핑 AI 루트, 모델 등록 재검증, ResumeThread 실패, 자식 환경, 다운로드 상한, 하드링크 실패→복사."""

from __future__ import annotations

import copy
import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from physicsai_core.config import load_config_dict
from physicsai_test_support import API, H, make_h3d_tree, make_model_folder, read_record

PW, P = H("tok-power", write=True), H("tok-power")


def _app(lc, engine, fake_dashboard):
    from physicsai_api.context import build_context
    from physicsai_api.main import create_app

    return TestClient(create_app(build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler))),
                      base_url="http://127.0.0.1")


def _study(c, name):
    r = c.post(f"{API}/studies", headers=PW, json={"project_id": "p-1", "folder_name": name, "title": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_mapped_ai_root_end_to_end(settings_dict, engine, fake_dashboard, tmp_path):
    """1: ai_root가 다른 실경로로 풀리는 매핑 드라이브·SUBST여도 데이터셋 생성·산출물 다운로드가 동작."""
    from physicsai_worker.runtime import Worker

    (tmp_path / "vol" / "AI").mkdir(parents=True)
    os.symlink(tmp_path / "vol", tmp_path / "Edrive")
    d = copy.deepcopy(settings_dict)
    d["storage"]["ai_root"] = str(tmp_path / "Edrive" / "AI")
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    with _app(lc, engine, fake_dashboard) as c:
        sid = _study(c, "MAP")
        inp = make_h3d_tree(tmp_path / "Edrive" / "AI" / "MAP", n=4)
        j = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "DATASET_CREATE", "params": {"input_path": str(inp)}}).json()
        assert Worker(lc, engine).run_once_slot() == "SUCCEEDED", c.get(f"{API}/jobs/{j['id']}", headers=P).json()
        arts = c.get(f"{API}/jobs/{j['id']}/artifacts", headers=P).json()
        assert c.get(f"{API}/artifacts/{arts[0]['id']}/content", headers=P).status_code == 200
        with engine.connect() as conn:
            rels = [r for (r,) in conn.execute(text("select rel_path from artifacts"))]
        assert rels and not any(r.startswith("..") for r in rels)


def test_worker_revalidates_log_file(client, engine, loaded_config, worker_factory, tmp_path):
    """3: API 검증을 거치지 않은 params(log_file 경로·링크)도 워커가 거부."""
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _study(client, "MRV")
    w = worker_factory()
    mf = make_model_folder(ai / "MRV" / "00_inbox", extra_log=True)
    secret = tmp_path / "secret.log"
    secret.write_text("epoch=  1/ 1 loss=1.0\n")
    os.symlink(secret, mf / "link.log")
    for bad in ("../../../secret.log", "sub/train.log", "link.log", "a b.log"):
        r = client.post(f"{API}/studies/{sid}/jobs", headers=PW,
                        json={"job_type": "MODEL_REGISTER", "params": {"model_path": str(mf), "log_file": "train.log"}})
        assert r.status_code == 201
        with engine.begin() as conn:  # API를 우회해 params 변조
            conn.execute(text("update jobs set params = jsonb_set(params, '{log_file}', to_jsonb(cast(:v as text))) where id=:i"),
                         {"v": bad, "i": r.json()["id"]})
        assert w.run_once_light() == "FAILED"
        jd = client.get(f"{API}/jobs/{r.json()['id']}", headers=P).json()
        assert jd["failure_code"] == "INPUT_INVALID", (bad, jd["failure_message"])
    assert not list((ai / "MRV").rglob("secret.log"))


def test_resume_thread_failure_terminates():
    """4: ResumeThread가 (DWORD)-1이면 TerminateProcess 후 JOB_OBJECT_ASSIGN_FAILED."""
    from physicsai_core.limits import compute_limits
    from physicsai_worker.limiter.base import LimiterError
    from physicsai_worker.limiter.windows_job import WindowsJobLimiter

    class K:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            def f(*a):
                self.calls.append(name)
                if name == "Thread32First":
                    a[1]._obj.th32OwnerProcessID = 4242
                    a[1]._obj.th32ThreadID = 7
                    return 1
                if name == "Thread32Next":
                    return 0
                if name == "ResumeThread":
                    return 0xFFFFFFFF
                return 1 if name != "CreateToolhelp32Snapshot" else 55
            return f

    class Pop:
        def __init__(self, argv, **kw):
            self.pid, self._handle = 4242, 99

        def wait(self, timeout=None):
            return 1

    k = K()
    with pytest.raises(LimiterError) as ei:
        WindowsJobLimiter(kernel32=k, popen=Pop).launch(["edspy.bat"], ".", {}, compute_limits(4, 2, "below_normal", False, 0.7, 8, 16))
    assert ei.value.code == "JOB_OBJECT_ASSIGN_FAILED" and "ResumeThread" in ei.value.message
    assert k.calls.index("ResumeThread") < k.calls.index("TerminateProcess")
    assert "TerminateJobObject" in k.calls


def test_child_env_has_no_secrets(client, engine, loaded_config, worker_factory, fake_record, monkeypatch):
    """7: DB URL 등 비밀·허용목록 밖 변수는 외부 프로그램에 전달하지 않는다."""
    monkeypatch.setenv("PHYSICSAI_DATABASE_URL", "postgresql://u:pw@h/db")
    monkeypatch.setenv("RANDOM_VAR", "x")
    monkeypatch.setenv("LM_LICENSE_FILE", "6200@lic")
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _study(client, "ENV")
    inp = make_h3d_tree(ai / "ENV", n=4)
    client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "DATASET_CREATE", "params": {"input_path": str(inp)}})
    assert worker_factory().run_once_slot() == "SUCCEEDED"
    keys = set(read_record(fake_record)[0]["env_keys"])
    assert "PHYSICSAI_DATABASE_URL" not in keys and "RANDOM_VAR" not in keys
    assert {"PATH", "LM_LICENSE_FILE", "FAKE_TOOL_RECORD"} <= keys


def test_artifact_download_size_limit(client, engine, loaded_config, settings_dict, worker_factory, fake_dashboard):
    """9: V-SEC-2 — 등록 후 크기 상한을 넘는 산출물은 내려주지 않는다(404)."""
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _study(client, "SZ")
    inp = make_h3d_tree(ai / "SZ", n=4)
    j = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "DATASET_CREATE", "params": {"input_path": str(inp)}}).json()
    assert worker_factory().run_once_slot() == "SUCCEEDED"
    aid = client.get(f"{API}/jobs/{j['id']}/artifacts", headers=P).json()[0]["id"]
    assert client.get(f"{API}/artifacts/{aid}/content", headers=P).status_code == 200
    d = copy.deepcopy(settings_dict)
    d["ui"] = {"max_artifact_bytes": 10}
    with _app(load_config_dict(d, environ={}), engine, fake_dashboard) as c2:
        r = c2.get(f"{API}/artifacts/{aid}/content", headers=P)
        assert r.status_code == 404 and r.json()["detail"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("link_fails", [False, True])
def test_package_hardlink_or_copy(client, engine, loaded_config, worker_factory, monkeypatch, link_fails):
    """9: V-DS-3 — 하드링크 성공 시 같은 inode, 실패 시 복사(내용 동일·다른 inode)."""
    ai = Path(loaded_config.settings.storage.ai_root)
    name = "HLF" if link_fails else "HLO"
    sid = _study(client, name)
    inp = make_h3d_tree(ai / name, n=4)
    j = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "DATASET_CREATE", "params": {"input_path": str(inp)}}).json()
    w = worker_factory()
    assert w.run_once_slot() == "SUCCEEDED"
    ds_id = client.get(f"{API}/jobs/{j['id']}", headers=P).json()["result"]["dataset_id"]
    if link_fails:
        from physicsai_worker.steps import package

        def no_link(*a, **k):
            raise OSError(18, "Invalid cross-device link")

        monkeypatch.setattr(package.os, "link", no_link)
    pj = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "PACKAGE_EXPORT", "params": {"dataset_id": ds_id}}).json()
    assert w.run_once_light() == "SUCCEEDED"
    src = ai / name / "03_dataset" / ds_id / "train" / "dataset.psdata"
    dst = ai / name / "03_package" / ds_id / "dataset_train.psdata"
    assert dst.read_bytes() == src.read_bytes()
    assert os.path.samefile(src, dst) is (not link_fails)
    assert client.get(f"{API}/jobs/{pj['id']}", headers=P).json()["result"]["linked"] is (not link_fails)
