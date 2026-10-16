"""④ 예측 시험 공용(phase3 §11.6): 설정을 바꾼 앱·워커 + Study·Final 모델·파라미터 세트 준비."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from physicsai_test_support import API, H, make_model_folder, make_param_set_folder

PW = H("tok-power", write=True)
P = H("tok-power")


@dataclass
class PredictEnv:
    c: Any
    w: Any
    lc: Any
    sid: str = ""
    sroot: Path = field(default_factory=Path)
    model_id: str = ""

    @property
    def ai(self) -> Path:
        return Path(self.lc.settings.storage.ai_root)

    @property
    def imports(self) -> Path:
        return Path(self.lc.settings.storage.allowed_import_roots[0])

    def submit(self, job_type: str, params: dict[str, Any], expect: int = 201) -> dict[str, Any]:
        r = self.c.post(f"{API}/studies/{self.sid}/jobs", headers=PW, json={"job_type": job_type, "params": params})
        assert r.status_code == expect, r.text
        return r.json()

    def job(self, jid: str) -> dict[str, Any]:
        return self.c.get(f"{API}/jobs/{jid}", headers=P).json()

    def steps(self, jid: str) -> dict[str, dict[str, Any]]:
        return {s["step_key"]: s for s in self.job(jid)["steps"]}

    def param_set(self, **kw: Any) -> dict[str, Any]:
        psf = make_param_set_folder(self.sroot / "00_inbox", **kw)
        r = self.c.post(f"{API}/studies/{self.sid}/param-sets", headers=PW, json={"path": str(psf)})
        assert r.status_code == 201, r.text
        return r.json()

    def predict_dir(self, jid: str) -> Path:
        return self.sroot / "04_predict" / jid


@pytest.fixture()
def predict_env(settings_dict, engine, fake_dashboard, fake_record):
    """predict_env(commands=…, predict=…, resources=…, hpc=…, folder=…, final_model=True) → PredictEnv(Study·Final 모델 준비)."""
    from fastapi.testclient import TestClient

    from physicsai_api.context import build_context
    from physicsai_api.main import create_app
    from physicsai_core.config import load_config_dict
    from physicsai_worker.runtime import Worker

    stack = contextlib.ExitStack()
    workers: list[Any] = []

    def make(*, commands: dict[str, Any] | None = None, predict: dict[str, Any] | None = None,
             resources: dict[str, Any] | None = None, hpc: dict[str, Any] | None = None, folder: str = "pred",
             final_model: bool = True, model_pscfg: int = 1) -> PredictEnv:
        d = dict(settings_dict)
        if hpc:
            d["hpc"] = hpc
        for k, v in (("commands", commands), ("predict", predict), ("resources", resources)):
            if v:
                d[k] = {**(d.get(k) or {}), **v}
        lc = load_config_dict(d, environ={})
        assert lc.ok, lc.issues
        c = stack.enter_context(TestClient(create_app(build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler))),
                                           base_url="http://127.0.0.1"))
        w = Worker(lc, engine)
        workers.append(w)
        env = PredictEnv(c, w, lc)
        r = c.post(f"{API}/studies", headers=PW, json={"project_id": "p-1", "folder_name": folder, "title": "예측"})
        assert r.status_code == 201, r.text
        env.sid, env.sroot = r.json()["id"], Path(lc.settings.storage.ai_root) / folder
        if final_model:
            mf = make_model_folder(env.sroot / "00_inbox", name="M1", pscfg=model_pscfg)
            jb = env.submit("MODEL_REGISTER", {"model_path": str(mf)})
            assert w.run_once_light() == "SUCCEEDED"
            env.model_id = env.job(jb["id"])["result"]["model_id"]
            r = c.put(f"{API}/studies/{env.sid}/final-model", headers=PW, json={"model_id": env.model_id})
            assert r.status_code == 200, r.text
        return env

    yield make
    for w in workers:
        w.stop()
    stack.close()


@pytest.fixture()
def pbs_state(tmp_path, monkeypatch):
    p = tmp_path / "pbs_state.json"
    monkeypatch.setenv("FAKE_PBS_STATE", str(p))
    monkeypatch.delenv("FAKE_TOOL_MODE_PBS", raising=False)
    return p
