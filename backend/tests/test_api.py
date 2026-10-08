"""API 시험: 권한 표(V-AUTH-3), Study, 모델·Final(V-EV-2, V-MR-1/3), 파라미터 세트(V-PS-1), 예측 사전조건(V-PR-3),
HPC none(V-HPC-1), 알림(V-NT-1), 로그·ETag(V-API-2), 산출물(V-SEC-2), 감사(V-SEC-5), 단위 문자열."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from sqlalchemy import text

from physicsai_test_support import API, IS_WINDOWS, LIMITER, H, make_h3d_tree, make_model_folder, make_param_set_folder

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


# ---- 모델·Final ------------------------------------------------------------------


def test_model_register_validation(client, loaded_config, worker_factory, engine):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    w = worker_factory()
    inbox = ai / "S1" / "00_inbox"
    # psmdl 0개
    d0 = inbox / "m0"
    d0.mkdir()
    (d0 / "a.pscfg").write_text("x")
    r = _job(client, sid, "MODEL_REGISTER", {"model_path": str(d0)})
    assert r.status_code == 422  # 이름 기본값(psmdl stem) 불가 → 이름 입력 요구
    r = _job(client, sid, "MODEL_REGISTER", {"model_path": str(d0), "name": "M0"})
    assert r.status_code == 201
    assert w.run_once_light() == "FAILED"
    # psmdl 2개
    d2 = make_model_folder(inbox, name="A1")
    (d2 / "B2.psmdl").write_text("x")
    r = _job(client, sid, "MODEL_REGISTER", {"model_path": str(d2), "name": "A1"})
    assert w.run_once_light() == "FAILED"
    insp = client.post(f"{API}/studies/{sid}/paths/inspect", headers=PW, json={"purpose": "MODEL_FOLDER", "path": str(d2)}).json()
    assert not insp["ok"] and insp["problems"][0]["code"] == "PSMDL_COUNT"
    # 로그 2개 → 선택 필요, 지정하면 성공
    d3 = make_model_folder(inbox, name="C3", extra_log=True)
    r = _job(client, sid, "MODEL_REGISTER", {"model_path": str(d3)})
    assert w.run_once_light() == "FAILED"
    msg = client.get(f"{API}/jobs/{r.json()['id']}", headers=P).json()["failure_message"]
    assert "other.txt" in msg and "train.log" in msg
    r = _job(client, sid, "MODEL_REGISTER", {"model_path": str(d3), "log_file": "train.log", "label": "표시명"})
    assert w.run_once_light() == "SUCCEEDED"
    # 로그 없음 → MISSING, 로그 형식 불일치 → UNRECOGNIZED (둘 다 등록 성공)
    m_missing = _model(client, w, sid, inbox, name="NoLog", log=None)
    m_garbage = _model(client, w, sid, inbox, name="Garbage", log="garbage")
    assert client.get(f"{API}/models/{m_missing}", headers=P).json()["log_status"] == "MISSING"
    g = client.get(f"{API}/models/{m_garbage}", headers=P).json()
    assert g["log_status"] == "UNRECOGNIZED" and g["status"] == "ACTIVE" and g["dataset_id"] is None
    # 같은 이름 재등록 → version 2
    m_v2 = _model(client, w, sid, inbox, name="Garbage", log="garbage")
    assert client.get(f"{API}/models/{m_v2}", headers=P).json()["version"] == 2
    lst = client.get(f"{API}/studies/{sid}/models", headers=P).json()
    assert all(m["loss_curve"] is None for m in lst)
    # V-MR-3: 허용 루트 밖·링크·..
    import os

    r = _job(client, sid, "MODEL_REGISTER", {"model_path": str(Path(client.app.state.ctx.settings.storage.ai_root).parent)})
    assert r.json()["detail"]["code"] == "PATH_OUTSIDE_ROOT"
    os.symlink(d3, inbox / "lnk")
    r = _job(client, sid, "MODEL_REGISTER", {"model_path": str(inbox / "lnk")})
    assert r.json()["detail"]["code"] == "PATH_UNSAFE"
    r = _job(client, sid, "MODEL_REGISTER", {"model_path": str(inbox) + "/../00_inbox/m0", "name": "Z"})
    assert r.json()["detail"]["code"] == "PATH_UNSAFE"


def test_final_model_rules(client, loaded_config, worker_factory, engine):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    w = worker_factory()
    m1 = _model(client, w, sid, ai / "S1" / "00_inbox", name="A1")
    m2 = _model(client, w, sid, ai / "S1" / "00_inbox", name="A2")
    assert client.put(f"{API}/studies/{sid}/final-model", headers=H("tok-general", write=True), json={"model_id": m1}).status_code == 403
    assert client.put(f"{API}/studies/{sid}/final-model", headers=PW, json={"model_id": m1}).json()["final_model_id"] == m1
    assert client.put(f"{API}/studies/{sid}/final-model", headers=PW, json={"model_id": m2}).json()["final_model_id"] == m2
    models = {m["id"]: m for m in client.get(f"{API}/studies/{sid}/models", headers=P).json()}
    assert models[m2]["is_final"] and not models[m1]["is_final"]
    r = client.patch(f"{API}/models/{m2}", headers=PW, json={"row_version": models[m2]["row_version"], "status": "ARCHIVED"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "MODEL_IS_FINAL"
    r = client.patch(f"{API}/models/{m1}", headers=PW, json={"row_version": models[m1]["row_version"], "status": "ARCHIVED"})
    assert r.status_code == 200 and r.json()["status"] == "ARCHIVED", r.text
    r = client.put(f"{API}/studies/{sid}/final-model", headers=PW, json={"model_id": m1})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "MODEL_NOT_ACTIVE"
    assert client.put(f"{API}/studies/{sid}/final-model", headers=PW, json={"model_id": "zzz"}).status_code == 404
    assert client.put(f"{API}/studies/{sid}/final-model", headers=PW, json={"model_id": None}).json()["final_model_id"] is None
    r = client.patch(f"{API}/models/{m2}", headers=PW, json={"row_version": 999, "label": "x"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "VERSION_CONFLICT"
    with engine.connect() as c:
        acts = {a for (a,) in c.execute(text("select action from audit_events"))}
    assert {"STUDY_CREATE", "JOB_CREATE", "FINAL_MODEL_SET", "MODEL_UPDATE"} <= acts


def test_sha_change_marks_invalid(client, loaded_config, worker_factory, engine):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    w = worker_factory()
    inp = make_h3d_tree(ai / "S1", 4)
    _job(client, sid, "DATASET_CREATE", {"input_path": str(inp)})
    assert w.run_once_slot() == "SUCCEEDED"
    mid = _model(client, w, sid, ai / "S1" / "00_inbox")
    stored = next((ai / "S1" / "03_model" / "models" / mid).glob("*.psmdl"))
    stored.write_bytes(b"tampered")
    r = _job(client, sid, "EVALUATE", {"model_id": mid})
    assert r.status_code == 201
    assert w.run_once_slot() == "FAILED"
    j = client.get(f"{API}/jobs/{r.json()['id']}", headers=P).json()
    assert j["failure_code"] == "INPUT_CHANGED"
    m = client.get(f"{API}/models/{mid}", headers=P).json()
    assert m["status"] == "INVALID" and m["eval_status"] != "RUNNING"


def test_evaluate_backup_and_unrecognized_score(client, loaded_config, settings_dict, worker_factory, engine, fake_dashboard):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    w = worker_factory()
    inp = make_h3d_tree(ai / "S1", 4)
    _job(client, sid, "DATASET_CREATE", {"input_path": str(inp)})
    assert w.run_once_slot() == "SUCCEEDED"
    mid = _model(client, w, sid, ai / "S1" / "00_inbox")
    jid = _job(client, sid, "EVALUATE", {"model_id": mid}).json()["id"]
    assert w.run_once_slot() == "SUCCEEDED"
    # 같은 작업 폴더에 기존 산출물이 있는 재시도 상황: 실패 후 재시도하면 psscr·predictions가 백업으로 이동
    from physicsai_worker.runtime import Worker
    from physicsai_core.config import load_config_dict

    d = dict(settings_dict)
    d["score"] = {"write_files": True, "parsers": []}
    w2 = Worker(load_config_dict(d, environ={}), engine)
    jid2 = _job(client, sid, "EVALUATE", {"model_id": mid}).json()["id"]
    E = ai / "S1" / "03_model" / "score" / mid / jid2
    E.mkdir(parents=True)
    (E / "cushion_TNS.psscr").write_text("old")
    (E / "predictions.psdata").write_text("old")
    assert w2.run_once_slot() == "SUCCEEDED"
    backed = sorted(p.name for p in (ai / "S1" / "_backup").rglob("*") if p.is_file())
    assert backed == ["cushion_TNS.psscr", "predictions.psdata"]
    m = client.get(f"{API}/models/{mid}", headers=P).json()
    assert m["eval_score"]["status"] == "UNRECOGNIZED" and m["eval_score"]["metrics"] == {}
    with engine.connect() as c:
        cmd = c.execute(text("select command from job_steps where job_id=:j and step_key='EDSPY_SCORE'"), {"j": jid2}).scalar()
    assert cmd["argv"][-1] == "--write-files"
    del jid


# ---- 파라미터 세트 -------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda d: (d / "parameters.json").unlink(), "PARAMETERS_MISSING"),
        (lambda d: (d / "parameters.json").write_text(json.dumps({"parameters": [{"name": "1bad", "nominal": 1, "min": 0, "max": 2}]})), "PARAMETER_NAME_INVALID"),
        (lambda d: (d / "parameters.json").write_text(json.dumps({"parameters": [{"name": "A", "nominal": 5, "min": 0, "max": 2}]})), "PARAMETER_RANGE_INVALID"),
        (lambda d: (d / "parameters.json").write_text(json.dumps({"parameters": [{"name": "A", "nominal": "x", "min": 0, "max": 2}]})), "PARAMETER_VALUE_INVALID"),
        (lambda d: (d / "simlab_parametered_mesh.tpl").write_text('{parameter(var_1, "OTHER", 1, 0, 2)}\nx={var_1, %3i}\n'), "PARAM_TPL_MISMATCH"),
        (lambda d: (d / "simlab_parametered_mesh.tpl").write_text('{parameter(var_1, "THK_1", 1, 0, 2)}\n{parameter(var_2, "N_RIB", 1, 0, 2)}\nx={var_1, %3s}\n'), "TPL_FORMAT_INVALID"),
        (lambda d: (d / "samples.csv").write_text("run_key,THK_1\nr1,1\n"), "SAMPLES_COLUMNS_MISMATCH"),
        (lambda d: (d / "samples.csv").write_text("run_key,THK_1,N_RIB,resp:Nope\nr1,1,2,3\n"), "SAMPLES_RESPONSE_UNKNOWN"),
        (lambda d: (d / "samples.csv").write_text("run_key,THK_1,N_RIB\nr1,1,inf\n"), "SAMPLES_INVALID"),
        (lambda d: (d / "cad" / "second.x_t").write_text("x"), "CAD_COUNT"),
        (lambda d: (d / "radioss_assem" / "model0_0000.rad").unlink(), "STARTER_COUNT"),
    ],
)
def test_param_set_validation(client, loaded_config, mutate, code):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    d = make_param_set_folder(ai / "S1" / "00_inbox")
    mutate(d)
    r = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(d)})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "PARAM_SET_INVALID"
    assert code in [p["code"] for p in r.json()["detail"]["problems"]]
    insp = client.post(f"{API}/studies/{sid}/paths/inspect", headers=PW, json={"purpose": "PARAM_SET", "path": str(d)}).json()
    assert not insp["ok"]


def test_param_set_register_current_and_units(client, loaded_config):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    d1 = make_param_set_folder(ai / "S1" / "00_inbox")
    a = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(d1)}).json()
    d2 = make_param_set_folder(ai / "S1" / "00_inbox", with_samples=False, with_responses=False)
    b = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(d2)}).json()
    sets = {x["id"]: x for x in client.get(f"{API}/studies/{sid}/param-sets", headers=P).json()}
    assert sets[b["id"]]["is_current"] and not sets[a["id"]]["is_current"]
    assert client.get(f"{API}/studies/{sid}", headers=P).json()["current_param_set_id"] == b["id"]
    # 단위 문자열은 변환 없이 그대로(빈 단위는 빈칸)
    assert a["unit_system"] == "mm-ton-s"
    assert [(p["name"], p["unit"]) for p in a["parameters"]] == [("THK_1", "mm"), ("N_RIB", "")]
    assert [(r_["name"], r_["unit"]) for r_ in a["responses"]] == [("MaxStress", "MPa"), ("Disp", "mm")]
    stored = ai / "S1" / "04_params" / a["id"]
    for f in ("parameters.json", "samples.csv", "responses.json", "source.json", "simlab_parametered_mesh.tpl",
              "cad/bracket.x_t", "radioss_assem/model0_0000.rad", "original/samples.csv"):
        assert (stored / f).is_file(), f
    assert not (stored / "samples.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    page = client.get(f"{API}/param-sets/{a['id']}/samples?limit=3", headers=P).json()
    assert len(page["rows"]) == 3 and page["next_cursor"] and page["columns"][0] == "run_key"
    assert page["rows"][0]["measured"] == {"MaxStress": 100.0, "Disp": 1.5}
    nxt = client.get(f"{API}/param-sets/{a['id']}/samples?limit=3&cursor={page['next_cursor']}", headers=P).json()
    assert len(nxt["rows"]) == 1 and nxt["next_cursor"] is None
    chk = client.post(f"{API}/studies/{sid}/predict/check", headers=PW, json={"values": {"THK_1": 3.0, "N_RIB": 4}}).json()
    assert chk["nearest"] is None and chk["out_of_range"] == []
    r = client.post(f"{API}/studies/{sid}/predict/check", headers=PW, json={"values": {"BOGUS": 1}})
    assert r.status_code == 422


# ---- 예측 사전조건·HPC ----------------------------------------------------------------


def test_predict_prerequisites_and_hpc_none(client, loaded_config, worker_factory, engine, settings_dict, fake_dashboard):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    w = worker_factory()
    r = _job(client, sid, "PREDICT", {"values": {"THK_1": 3}, "value_source": "manual"})
    assert r.status_code == 409 and r.json()["detail"]["missing"] == ["PARAM_SET"]
    d = make_param_set_folder(ai / "S1" / "00_inbox")
    client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(d)})
    r = _job(client, sid, "PREDICT", {"values": {"THK_1": 3, "N_RIB": 4}, "value_source": "manual"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FINAL_MODEL_REQUIRED"
    mid = _model(client, w, sid, ai / "S1" / "00_inbox")
    client.put(f"{API}/studies/{sid}/final-model", headers=PW, json={"model_id": mid})
    r = _job(client, sid, "PREDICT", {"values": {"THK_1": 3}, "value_source": "manual"})
    assert r.status_code == 422  # 모든 파라미터 값 필수
    r = _job(client, sid, "PREDICT", {"values": {"THK_1": 3, "N_RIB": 4}, "value_source": "run"})
    assert r.status_code == 422  # source_run_key 필요
    # V-HPC-1: none → 409 HPC_NOT_CONFIGURED, status message
    r = _job(client, sid, "PREDICT_VERIFY", {"predict_job_id": "x"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "HPC_NOT_CONFIGURED"
    st = client.get(f"{API}/status", headers=P).json()
    assert st["hpc"] == {"mode": "none", "configured": False, "message": "PBS 연결 안 됨", "collect_mode": "in_place"}
    # V-PR-3: geom_update null → 409 TEMPLATE_NOT_CONFIGURED
    import httpx
    from fastapi.testclient import TestClient

    from physicsai_api.context import build_context
    from physicsai_api.main import create_app
    from physicsai_core.config import load_config_dict

    dd = dict(settings_dict)
    dd["commands"] = {**dd["commands"], "geom_update": None}
    lc = load_config_dict(dd, environ={})
    with TestClient(create_app(build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler))), base_url="http://127.0.0.1") as c2:
        r = c2.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "PREDICT", "params": {"values": {"THK_1": 3, "N_RIB": 4}, "value_source": "manual"}})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "TEMPLATE_NOT_CONFIGURED"


# ---- 알림 ---------------------------------------------------------------------------


def test_notifications_read_and_purge(client, engine, loaded_config, worker_factory):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    inp = make_h3d_tree(ai / "S1", 4)
    _job(client, sid, "DATASET_CREATE", {"input_path": str(inp)})
    w = worker_factory()
    assert w.run_once_slot() == "SUCCEEDED"
    u = client.get(f"{API}/notifications/unread-count", headers=P).json()
    assert u["unread_count"] == 2 and u["max_seq"] > 0
    lst = client.get(f"{API}/notifications", headers=P).json()
    assert [i["event"] for i in lst["items"]] == ["JOB_SUCCEEDED", "JOB_STARTED"]
    assert lst["items"][0]["title"] == "완료: 데이터셋 생성 (제목)"
    # 본인 것만
    assert client.get(f"{API}/notifications", headers=H("tok-general")).json()["items"] == []
    after = client.get(f"{API}/notifications?after_seq={lst['items'][1]['seq']}", headers=P).json()
    assert [i["event"] for i in after["items"]] == ["JOB_SUCCEEDED"]
    r = client.post(f"{API}/notifications/read", headers=PW, json={"seqs": [lst["items"][0]["seq"]]})
    assert r.json() == {"unread_count": 1}
    assert client.post(f"{API}/notifications/read", headers=H("tok-general", write=True), json={"all": True}).json() == {"unread_count": 0}
    assert client.get(f"{API}/notifications/unread-count", headers=P).json()["unread_count"] == 1
    assert client.post(f"{API}/notifications/read", headers=PW, json={"all": True}).json() == {"unread_count": 0}
    assert client.post(f"{API}/notifications/read", headers=PW, json={}).status_code == 422
    # 30일 정리
    with engine.begin() as c:
        c.execute(text("update notifications set created_at = now() - interval '31 days' where seq = :s"), {"s": lst["items"][1]["seq"]})
    assert len(client.get(f"{API}/notifications", headers=P).json()["items"]) == 1
    w.housekeeping_once(force_purge=True)
    with engine.connect() as c:
        assert c.execute(text("select count(*) from notifications")).scalar() == 1


# ---- 로그·ETag·산출물·자원 --------------------------------------------------------------


def test_logs_etag_artifacts(client, loaded_config, worker_factory, engine):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    inp = make_h3d_tree(ai / "S1", 4)
    jid = _job(client, sid, "DATASET_CREATE", {"input_path": str(inp)}).json()["id"]
    r = client.get(f"{API}/jobs/{jid}/log", headers=P)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "LOG_NOT_FOUND"
    r = client.get(f"{API}/jobs/{jid}", headers=P)
    etag = r.headers["ETag"]
    assert etag.startswith(f'"{jid}:')
    assert client.get(f"{API}/jobs/{jid}", headers={**P, "If-None-Match": etag}).status_code == 304
    w = worker_factory()
    assert w.run_once_slot() == "SUCCEEDED"
    assert client.get(f"{API}/jobs/{jid}", headers={**P, "If-None-Match": etag}).status_code == 200
    # 한글 로그를 UTF-8 경계에서 자르기
    logf = ai / "S1" / "logs" / jid / "job.log"
    with open(logf, "a", encoding="utf-8") as fh:
        fh.write("한글로그끝\n")
    size = logf.stat().st_size
    text_all, cur = "", 0
    while True:
        chunk = client.get(f"{API}/jobs/{jid}/log?cursor={cur}&limit=7", headers=P).json()
        text_all += chunk["text"]
        assert chunk["next_cursor"] > cur
        cur = chunk["next_cursor"]
        if chunk["eof"]:
            break
    assert cur == size and text_all == logf.read_bytes().decode("utf-8") and "�" not in text_all  # Windows 텍스트 모드 CRLF 그대로
    assert client.get(f"{API}/jobs/{jid}/log?limit=262145", headers=P).status_code == 422
    st = client.get(f"{API}/jobs/{jid}/steps/3/log", headers=P).json()
    assert "[CMD]" in st["text"]
    assert client.get(f"{API}/jobs/{jid}/steps/99/log", headers=P).status_code == 404
    # 산출물: id로만, 크기 상한, 화이트리스트
    arts = client.get(f"{API}/jobs/{jid}/artifacts", headers=P).json()
    assert len(arts) == 1 and arts[0]["content_type"] == "application/json" and "rel_path" not in arts[0]
    assert client.get(f"{API}/artifacts/does-not-exist/content", headers=P).status_code == 404
    with engine.begin() as c:
        c.execute(text("update artifacts set content_type='application/octet-stream'"))
    assert client.get(f"{API}/artifacts/{arts[0]['id']}/content", headers=P).status_code == 404
    with engine.begin() as c:
        c.execute(text("update artifacts set content_type='application/json', rel_path='../../etc/passwd'"))
    assert client.get(f"{API}/artifacts/{arts[0]['id']}/content", headers=P).status_code in (404, 422)
    # 관리자 include=commands
    j_admin = client.get(f"{API}/jobs/{jid}?include=commands", headers=H("tok-admin")).json()
    assert j_admin["steps"][2]["command"]["argv"][1] == "--physicsai"
    assert client.get(f"{API}/jobs/{jid}?include=commands", headers=P).status_code == 403
    assert client.get(f"{API}/jobs/{jid}", headers=P).json()["steps"][2].get("command") is None
    # 자원: 샘플 없으면 404, 하트비트 후 값
    assert client.get(f"{API}/resources", headers=P).json()["detail"]["code"] == "NO_SAMPLE"
    w.heartbeat_once()
    res = client.get(f"{API}/resources", headers=P).json()
    assert res["gpu"] == [{"name": "RTX A6000", "util_pct": 12.0, "mem_used_mb": 2048.0, "mem_total_mb": 49140.0}]
    assert res["limits"]["cpu_cap_enforced"] is IS_WINDOWS and res["limits"]["cores"] >= 1
    st = client.get(f"{API}/status", headers=P).json()
    assert st["worker"]["online"] and st["worker"]["limiter"] == LIMITER and st["limits"]["effective"]["cpu_cap_enforced"] is IS_WINDOWS
    assert {t["key"]: t["configured"] for t in st["templates"]}["mesh"] is False
    assert st["ui"]["poll_queue_ms"] == 5000
    time.sleep(0)
