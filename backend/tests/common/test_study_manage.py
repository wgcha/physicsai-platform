"""phase3 §3 S1: Study 보관 해제(V3-S1-1), 이름 변경의 study.json 갱신(V3-S1-2)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

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


def test_patch_title_without_folder_does_not_create_it(client, loaded_config, caplog):
    """D3-20: Study 폴더가 없으면 study.json을 만들지 않고(폴더 생성 금지) 경고만. 보관 해제의 STUDY_FOLDER_MISSING은 유지."""
    from physicsai_api.services import studies as svc

    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client, "M5")
    client.post(f"{API}/studies/{sid}/archive", headers=PW)
    (ai / "M5").rename(ai / "M5_moved")  # 시험 준비: 폴더를 치운다(삭제 아님)
    v = client.get(f"{API}/studies/{sid}", headers=P).json()["version"]
    with caplog.at_level(logging.WARNING, logger=svc.__name__):
        r = client.patch(f"{API}/studies/{sid}", headers=PW, json={"version": v, "title": "폴더 없음"})
    assert r.status_code == 200 and r.json()["title"] == "폴더 없음"
    assert not (ai / "M5").exists() and not (ai / "M5").is_symlink()
    assert any("Study 폴더 없음" in rec.getMessage() for rec in caplog.records)
    r = client.post(f"{API}/studies/{sid}/unarchive", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "STUDY_FOLDER_MISSING"
    assert not (ai / "M5").exists()


def test_write_json_atomic_random_temp_no_makedirs(tmp_path, monkeypatch):
    """D3-21: 임시 파일은 같은 폴더의 무작위 이름(mkstemp), 폴더를 만들지 않음, 예전 고정 임시 이름이 있어도 건드리지 않음."""
    import tempfile

    from physicsai_core import fileutil

    p = tmp_path / "a.json"
    decoy = tmp_path / ".a.json.tmp"  # 예전 고정 이름 — 미리 있어도 덮어쓰지 않는다
    decoy.write_text("decoy", encoding="utf-8")
    made: list[str] = []
    real = tempfile.mkstemp

    def spy(*a, **kw):
        fd, name = real(*a, **kw)
        made.append(name)
        return fd, name

    monkeypatch.setattr(tempfile, "mkstemp", spy)
    fileutil.write_json_atomic(str(p), {"a": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1} and decoy.read_text(encoding="utf-8") == "decoy"
    assert len(made) == 1 and Path(made[0]).parent == tmp_path and Path(made[0]).name != ".a.json.tmp"
    assert sorted(x.name for x in tmp_path.iterdir()) == [".a.json.tmp", "a.json"]
    with pytest.raises(FileNotFoundError):
        fileutil.write_json_atomic(str(tmp_path / "no_dir" / "b.json"), {})
    assert not (tmp_path / "no_dir").exists()


def test_write_json_atomic_and_assert_writable_reject_links(tmp_path):
    """D3-21: 대상·폴더가 링크면 거부(링크를 따라 밖에 쓰지 않음). assert_writable도 마지막 요소 링크를 거부.
    backup_existing은 링크 자체를 옮기므로 허용(따라가지 않음)."""
    from physicsai_core.errors import StepFailure
    from physicsai_core.fileutil import write_json_atomic
    from physicsai_core.paths import assert_writable, backup_existing

    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "victim.json"
    target.write_text("{}", encoding="utf-8")
    study = tmp_path / "S"
    study.mkdir()
    try:
        os.symlink(target, study / "study.json")
        os.symlink(outside, study / "lnkdir", target_is_directory=True)
    except OSError as exc:  # Windows에서 심볼릭 링크 권한이 없으면 만들 수 없다
        pytest.skip(f"심볼릭 링크를 만들 수 없음: {exc}")
    for p in (study / "study.json", study / "lnkdir" / "x.json"):
        with pytest.raises(StepFailure) as ei:
            write_json_atomic(str(p), {"title": "x"})
        assert ei.value.code == "PATH_UNSAFE"
    assert target.read_text(encoding="utf-8") == "{}" and not (outside / "x.json").exists()
    with pytest.raises(StepFailure):
        assert_writable(str(study / "study.json"))
    assert_writable(str(study / "study.json"), allow_final_link=True)
    moved = backup_existing(str(study), [str(study / "study.json")], "job1", "20260101T000000Z")
    assert moved == ["study.json"] and target.read_text(encoding="utf-8") == "{}"
