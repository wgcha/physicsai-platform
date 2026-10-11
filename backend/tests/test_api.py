"""API 시험: 권한 표(V-AUTH-3), Study·페이지, job params 검증, 설정 무효 시 쓰기 차단.

③·④(모델·Final·파라미터 세트·예측 사전조건·HPC none)는 test_api_models, 알림·로그·산출물은 test_api_ops."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text

from helpers_api import AW, PW, P, _job, _sid, _study
from physicsai_test_support import API, H, make_h3d_tree

# ---- 권한 표 -------------------------------------------------------------------


def test_permission_matrix(client, loaded_config):
    sid = _sid(client)
    for tok in ("tok-general", "tok-nonmember", "tok-power", "tok-admin"):
        assert client.get(f"{API}/studies/{sid}", headers=H(tok)).status_code == 200
        assert client.get(f"{API}/queue", headers=H(tok)).status_code == 200
        assert client.get(f"{API}/jobs", headers=H(tok)).status_code == 200
    # general·비멤버: 실행 403
    for tok in ("tok-general", "tok-nonmember"):
        r = _study(client, "X" + tok[-3:], tok)
        assert r.status_code == 403 and r.json()["detail"] == {"code": "PERMISSION_DENIED", "message": "실행 권한(power 이상)이 필요합니다", "required": "power"}
        r = _job(client, sid, "DATASET_CREATE", {"input_path": "/x"}, tok)
        assert r.status_code == 403
        assert client.get(f"{API}/studies/{sid}", headers=H(tok)).json()["can_execute"] is False
    assert client.get(f"{API}/studies/{sid}", headers=P).json()["can_execute"] is True
    # 전역 관리자는 모든 프로젝트 admin
    assert _study(client, "AdminS", "tok-admin").status_code == 201
    assert client.get(f"{API}/admin/config", headers=P).status_code == 403
    cfg = client.get(f"{API}/admin/config", headers=H("tok-admin")).json()
    assert cfg["ok"] and "edspy_score" in cfg["templates"] and "postgresql" not in json.dumps(cfg)


def test_order_404_before_403(client):
    r = _job(client, "no-such-study", "DATASET_CREATE", {"input_path": "/x"}, "tok-general")
    assert r.status_code == 404


# ---- Study ----------------------------------------------------------------------


def test_study_lifecycle(client, loaded_config, engine):
    ai = Path(loaded_config.settings.storage.ai_root)
    r = client.post(f"{API}/studies", headers=PW, json={"project_id": "p-9", "folder_name": "A1", "title": "t"})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "PROJECT_NOT_FOUND"
    sid = _sid(client, "A1")
    meta = json.loads((ai / "A1" / "study.json").read_text())
    assert meta["id"] == sid and (ai / "A1" / "00_inbox").is_dir()
    assert _study(client, "A1").json()["detail"]["code"] == "STUDY_NAME_EXISTS"
    (ai / "Exists").mkdir()
    r = _study(client, "Exists")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FOLDER_EXISTS"
    with engine.connect() as c:
        assert c.execute(text("select count(*) from studies where folder_name='Exists'")).scalar() == 0
    for bad in ("_x", "a b", "한글", "a" * 65, "../x"):
        r = client.post(f"{API}/studies", headers=PW, json={"project_id": "p-1", "folder_name": bad, "title": "t"})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS"
    r = client.post(f"{API}/studies", headers=PW, json={"project_id": "p-1", "folder_name": "Z1", "title": "t", "extra": 1})
    assert r.status_code == 422
    s = client.get(f"{API}/studies/{sid}", headers=P).json()
    r = client.patch(f"{API}/studies/{sid}", headers=PW, json={"version": s["version"], "title": "새 제목"})
    assert r.status_code == 200 and r.json()["title"] == "새 제목"
    r = client.patch(f"{API}/studies/{sid}", headers=PW, json={"version": s["version"], "title": "x"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "VERSION_CONFLICT"
    inp = make_h3d_tree(ai / "A1", 4)
    assert _job(client, sid, "DATASET_CREATE", {"input_path": str(inp)}).status_code == 201
    r = _job(client, sid, "DATASET_CREATE", {"input_path": str(inp)})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "STUDY_JOB_BUSY"  # V-DB-3
    r = client.post(f"{API}/studies/{sid}/archive", headers=PW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "STUDY_HAS_ACTIVE_JOB"
    jid = client.get(f"{API}/jobs?study_id={sid}", headers=P).json()[0]["id"]
    client.post(f"{API}/jobs/{jid}/cancel", headers=AW)
    assert client.post(f"{API}/studies/{sid}/archive", headers=PW).json()["status"] == "ARCHIVED"
    r = _job(client, sid, "DATASET_CREATE", {"input_path": str(inp)})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "STUDY_ARCHIVED"
    lst = client.get(f"{API}/studies?project_id=p-1&status=ARCHIVED", headers=P).json()
    assert [x["id"] for x in lst] == [sid]


def test_paging_cursor(client):
    for i in range(3):
        _sid(client, f"PG{i}")
    r = client.get(f"{API}/studies?limit=2", headers=P)
    assert len(r.json()) == 2 and r.headers.get("X-Next-Cursor")
    r2 = client.get(f"{API}/studies?limit=2&cursor={r.headers['X-Next-Cursor']}", headers=P)
    assert len(r2.json()) == 1 and not r2.headers.get("X-Next-Cursor")


def test_job_params_validation(client, loaded_config):
    sid = _sid(client)
    ai = Path(loaded_config.settings.storage.ai_root)
    r = _job(client, sid, "DATASET_CREATE", {"input_path": "/x", "bogus": 1})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS" and r.json()["detail"]["errors"]
    r = _job(client, sid, "DATASET_CREATE", {"input_path": str(ai / "S1"), "holdout_ratio": 0.9})
    assert r.status_code == 422
    r = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "TRAIN", "params": {}})
    assert r.status_code == 422
    r = _job(client, sid, "DATASET_CREATE", {"input_path": str(ai.parent)})  # 루트 밖 절대경로(OS 무관)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_OUTSIDE_ROOT"
    r = _job(client, sid, "DATASET_CREATE", {"input_path": str(ai / "S1" / "missing")})
    assert r.json()["detail"]["code"] == "PATH_NOT_FOUND"
    r = _job(client, sid, "PACKAGE_EXPORT", {"dataset_id": "nope"})
    assert r.status_code == 409 and r.json()["detail"] == {"code": "PREREQUISITE_MISSING", "message": "사전 조건이 충족되지 않았습니다", "missing": ["READY_DATASET"]}
    r = _job(client, sid, "EVALUATE", {"model_id": "nope"})
    assert r.json()["detail"]["missing"] == ["ACTIVE_MODEL"]


def test_config_invalid_blocks_writes(engine, settings_dict, fake_dashboard):
    import httpx
    from fastapi.testclient import TestClient

    from physicsai_api.context import build_context
    from physicsai_api.main import create_app
    from physicsai_core.config import load_config_dict

    d = dict(settings_dict)
    d["commands"] = {**d["commands"], "edspy_score": None}
    lc = load_config_dict(d, environ={})
    assert not lc.ok
    with TestClient(create_app(build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler))),
                    base_url="http://127.0.0.1") as c:
        r = c.post(f"{API}/studies", headers=PW, json={"project_id": "p-1", "folder_name": "C1", "title": "t"})
        assert r.status_code == 503 and r.json()["detail"]["code"] == "CONFIG_INVALID"
        st = c.get(f"{API}/status", headers=P).json()
        assert st["config"]["ok"] is False and "commands.edspy_score" in st["config"]["errors"]
        assert c.get(f"{API}/studies", headers=P).status_code == 200


