"""API 시험 공용 도우미: 인증 헤더(PW·P·AW), Study 생성(_study·_sid), 작업 생성(_job), 모델 등록(_model)."""

from __future__ import annotations

from pathlib import Path

from physicsai_test_support import API, H, make_model_folder

PW, P = H("tok-power", write=True), H("tok-power")
AW = H("tok-admin", write=True)


def _study(c, name="S1", token="tok-power"):
    r = c.post(f"{API}/studies", headers=H(token, write=True), json={"project_id": "p-1", "folder_name": name, "title": "제목"})
    return r


def _sid(c, name="S1"):
    r = _study(c, name)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _job(c, sid, jt, params, token="tok-power"):
    return c.post(f"{API}/studies/{sid}/jobs", headers=H(token, write=True), json={"job_type": jt, "params": params})


def _model(c, w, sid, root: Path, name="cushion_TNS", **kw):
    mf = make_model_folder(root, name=name, **kw)
    r = _job(c, sid, "MODEL_REGISTER", {"model_path": str(mf)})
    assert r.status_code == 201, r.text
    assert w.run_once_light() == "SUCCEEDED", c.get(f"{API}/jobs/{r.json()['id']}", headers=P).json()
    return c.get(f"{API}/jobs/{r.json()['id']}", headers=P).json()["result"]["model_id"]
