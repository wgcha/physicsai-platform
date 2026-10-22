"""대기열·lease 워커 시험 공용 도우미: 인증 헤더, Study·DATASET_CREATE 작업 생성, 작업 행 조회."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from physicsai_test_support import API, H, make_h3d_tree

PW = H("tok-power", write=True)
AW = H("tok-admin", write=True)
P = H("tok-power")


def _study(c, name):
    r = c.post(f"{API}/studies", headers=PW, json={"project_id": "p-1", "folder_name": name, "title": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _dataset_job(c, ai_root, name, n=4):
    sid = _study(c, name)
    inp = make_h3d_tree(Path(ai_root) / name, n=n)
    r = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "DATASET_CREATE", "params": {"input_path": str(inp)}})
    assert r.status_code == 201, r.text
    return sid, r.json()


def _state(engine, jid):
    with engine.connect() as c:
        return dict(c.execute(text("select * from jobs where id=:i"), {"i": jid}).one()._mapping)


def _to_lane(engine, jid, lane):
    """시험용: 대기 중 작업을 다른 대기열(GPU|CPU)로 옮긴다(슬롯·lease 시험을 GPU 구간으로 만들 때)."""
    with engine.begin() as c:
        c.execute(text("update jobs set lane=:l where id=:i and state='QUEUED'"), {"l": lane, "i": jid})
