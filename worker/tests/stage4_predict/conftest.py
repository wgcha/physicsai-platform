"""④ 예측 시험 공용(phase3 §11.6·§14.9): 설정을 바꾼 앱·워커 + Study·Final 모델·파라미터 세트 준비, 일괄 예측 배치 직접 생성
(API 미구현 구간은 저장소 함수로 — 미리보기·작업 생성과 같은 `batch_matrix`·`predict_batches.create_batch`)."""

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
    engine: Any = None

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

    # ---- S9(phase3 §14) ----
    def sql(self, q: str, **kw: Any) -> Any:
        from sqlalchemy import text

        with self.engine.begin() as conn:
            return conn.execute(text(q), kw).all() if q.lstrip().lower().startswith("select") else conn.execute(text(q), kw)

    def to_mesh_only(self, ps_id: str) -> None:
        """등록된 세트를 mesh_only 템플릿으로(API 등록 경로는 Impl-Backend) — 조립 폴더 사본도 치워 쓰지 않음을 확인."""
        import shutil

        self.sql("update param_sets set input_kind='mesh_only', assem_rel=null, starter_name=null where id=:i", i=ps_id)
        shutil.rmtree(self.sroot / "04_params" / ps_id / "radioss_assem", ignore_errors=True)

    def set_responses(self, ps_id: str, responses: list[dict[str, Any]]) -> None:
        import json

        self.sql("update param_sets set responses=cast(:r as jsonb) where id=:i", r=json.dumps(responses), i=ps_id)

    def make_batch(self, ps_id: str, text: str, *, multi: int = 2, input_kind: str | None = None) -> tuple[str, str]:
        """표 붙여넣기 조합으로 부모 PREDICT_BATCH 작업 + 배치·run 행을 만든다 → (batch_id, 부모 job_id).
        input_kind = 실행의 입력 종류(assembly|mesh_only, input-kind.md IK-2) — 생략 시 세트 값."""
        from physicsai_core.db.repositories import jobs as jobs_repo
        from physicsai_core.db.repositories import param_sets as ps_repo
        from physicsai_core.db.repositories import predict_batches as pb
        from physicsai_core.db.repositories import studies as studies_repo
        from physicsai_core.stage4_predict.batch_matrix import batch_dir_rel, build_matrix_for

        s = self.lc.settings
        with self.engine.begin() as conn:
            study = studies_repo.require(conn, self.sid, for_update=True)
            ps = ps_repo.get(conn, ps_id)
            source = {"kind": "table", "text": text}
            mx = build_matrix_for(source, ps, s)
            assert mx.ok, mx.problems
            bid, no = pb.new_batch_id(), pb.next_batch_no(conn, self.sid)
            job = jobs_repo.insert_job(conn, study=study, job_type="PREDICT_BATCH", user_id="u-power", user_name="파워",
                                       params={"param_set_id": ps_id, "model_id": self.model_id, "multi_execution": multi,
                                               "source": source, "batch_id": bid, "batch_no": no})
            pb.create_batch(conn, batch_id=bid, batch_no=no, study_id=self.sid, job_id=job["id"], param_set_id=ps_id,
                            model_id=self.model_id, input_kind=input_kind or ps["input_kind"], matrix=mx, multi_execution=multi,
                            dir_rel=batch_dir_rel(s.predict_batch.dir_name, no), simlab_mesh_name=s.predict.simlab_mesh_name,
                            user_id="u-power", user_name="파워")
        return bid, job["id"]

    def batch(self, bid: str) -> dict[str, Any]:
        from physicsai_core.db.repositories import predict_batches as pb

        with self.engine.connect() as conn:
            return {**pb.get(conn, bid), "runs": pb.runs_with_jobs(conn, bid)}  # type: ignore[dict-item]


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
             final_model: bool = True, model_pscfg: int = 1, train_data: dict[str, Any] | None = None,
             geometry: dict[str, Any] | None = None, extra: dict[str, Any] | None = None) -> PredictEnv:
        d = dict(settings_dict)
        if hpc:
            d["hpc"] = hpc
        for k, v in (("commands", commands), ("predict", predict), ("resources", resources), ("train_data", train_data),
                     ("geometry", geometry), *((extra or {}).items())):
            if v:
                d[k] = {**(d.get(k) or {}), **v}
        lc = load_config_dict(d, environ={})
        assert lc.ok, lc.issues
        c = stack.enter_context(TestClient(create_app(build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler))),
                                           base_url="http://127.0.0.1"))
        w = Worker(lc, engine)
        workers.append(w)
        env = PredictEnv(c, w, lc, engine=engine)
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


@pytest.fixture()
def native_env(predict_env, fake_tools, fake_record):
    """native 형상 엔진(가짜 paicad) 설정의 PredictEnv(geometry-engine.md §7.8). native_env(engine="native", geometry={…}, **predict_env 인자)."""

    def make(*, engine: str = "native", geometry: dict[str, Any] | None = None, **kw: Any) -> PredictEnv:
        geo = {"engine": engine, "paicad_path": fake_tools["fake_paicad"], **(geometry or {})}
        return predict_env(geometry=geo, **kw)

    return make

