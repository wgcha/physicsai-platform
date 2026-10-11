"""phase3 §3 S1: Study 보관 해제(V3-S1-1), 이름 변경의 study.json 갱신(V3-S1-2)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import text

from physicsai_test_support import API, H, make_h3d_tree

PW, P = H("tok-power", write=True), H("tok-power")


def _sid(c, name="M1") -> str:
    r = c.post(f"{API}/studies", headers=PW, json={"project_id": "p-1", "folder_name": name, "title": "제목"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _actions(engine, sid: str) -> list[str]:
    with engine.connect() as c:
        return [a for (a,) in c.execute(text("select action from audit_events where target_id=:t order by occurred_at, id"), {"t": sid})]


def test_unarchive_power_idempotent_and_job_create(client, loaded_config, engine):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    # ACTIVE에서 보관 해제 = 그대로 200(멱등), 감사 없음
    r = client.post(f"{API}/studies/{sid}/unarchive", headers=PW)
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE"
    assert "STUDY_UNARCHIVE" not in _actions(engine, sid)
    assert client.post(f"{API}/studies/{sid}/archive", headers=PW).json()["status"] == "ARCHIVED"
    inp = make_h3d_tree(ai / "M1", 4)
    r = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "DATASET_CREATE", "params": {"input_path": str(inp)}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "STUDY_ARCHIVED"
    r = client.post(f"{API}/studies/{sid}/unarchive", headers=PW)
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE" and r.json()["can_execute"] is True
    assert client.post(f"{API}/studies/{sid}/unarchive", headers=PW).status_code == 200
    assert _actions(engine, sid).count("STUDY_UNARCHIVE") == 1
    r = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "DATASET_CREATE", "params": {"input_path": str(inp)}})
    assert r.status_code == 201, r.text


def test_unarchive_permission_and_not_found(client):
    sid = _sid(client)
    client.post(f"{API}/studies/{sid}/archive", headers=PW)
    for tok in ("tok-general", "tok-nonmember"):
        r = client.post(f"{API}/studies/{sid}/unarchive", headers=H(tok, write=True))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "PERMISSION_DENIED"
    r = client.post(f"{API}/studies/no-such/unarchive", headers=PW)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "NOT_FOUND"
    assert client.get(f"{API}/studies/{sid}", headers=P).json()["status"] == "ARCHIVED"


def test_unarchive_folder_missing(client, loaded_config, engine):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client, "M2")
    client.post(f"{API}/studies/{sid}/archive", headers=PW)
    (ai / "M2").rename(ai / "M2_moved")  # 시험 준비: 폴더를 치운다(삭제 아님)
    r = client.post(f"{API}/studies/{sid}/unarchive", headers=PW)
    assert r.status_code == 409
    assert r.json()["detail"] == {"code": "STUDY_FOLDER_MISSING", "message": "AI 루트에서 Study 폴더를 찾을 수 없습니다"}
    assert client.get(f"{API}/studies/{sid}", headers=P).json()["status"] == "ARCHIVED"
    assert "STUDY_UNARCHIVE" not in _actions(engine, sid)


def test_patch_title_updates_study_json(client, loaded_config):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client, "M3")
    v = client.get(f"{API}/studies/{sid}", headers=P).json()["version"]
    r = client.patch(f"{API}/studies/{sid}", headers=PW, json={"version": v, "title": "새 이름"})
    assert r.status_code == 200 and r.json()["title"] == "새 이름" and r.json()["folder_name"] == "M3"
    meta = json.loads((ai / "M3" / "study.json").read_text(encoding="utf-8"))
    assert meta["title"] == "새 이름" and meta["id"] == sid and "created_at" in meta
    assert not (ai / "M3" / ".study.json.tmp").exists()
    # 보관된 Study도 이름 변경 허용(가정 A3-1)
    client.post(f"{API}/studies/{sid}/archive", headers=PW)
    v = client.get(f"{API}/studies/{sid}", headers=P).json()["version"]
    r = client.patch(f"{API}/studies/{sid}", headers=PW, json={"version": v, "title": "보관 중 이름"})
    assert r.status_code == 200 and r.json()["status"] == "ARCHIVED"
    assert json.loads((ai / "M3" / "study.json").read_text(encoding="utf-8"))["title"] == "보관 중 이름"


def test_patch_title_study_json_write_failure_is_warning(client, loaded_config, monkeypatch, caplog):
    from physicsai_api.services import studies as svc

    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client, "M4")

    def _ro(path, data):
        raise PermissionError("읽기 전용")

    monkeypatch.setattr(svc, "write_json_atomic", _ro)
    v = client.get(f"{API}/studies/{sid}", headers=P).json()["version"]
    with caplog.at_level(logging.WARNING, logger=svc.__name__):
        r = client.patch(f"{API}/studies/{sid}", headers=PW, json={"version": v, "title": "DB만"})
    assert r.status_code == 200 and r.json()["title"] == "DB만"
    assert client.get(f"{API}/studies/{sid}", headers=P).json()["title"] == "DB만"
    assert json.loads((ai / "M4" / "study.json").read_text(encoding="utf-8"))["title"] == "제목"
    assert any("study.json" in rec.getMessage() for rec in caplog.records)


def test_write_json_atomic_replaces(tmp_path):
    from physicsai_core.fileutil import write_json_atomic

    p = tmp_path / "a.json"
    p.write_text("{}", encoding="utf-8")
    write_json_atomic(str(p), {"title": "가"})
    assert json.loads(p.read_text(encoding="utf-8")) == {"title": "가"}
    assert sorted(x.name for x in tmp_path.iterdir()) == ["a.json"]
