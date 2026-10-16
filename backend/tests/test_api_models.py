"""API 시험(③·④): 모델 등록·Final(V-EV-2, V-MR-1/3), 평가 백업·점수 미인식, 파라미터 세트(V-PS-1),
예측 사전조건(V-PR-3), HPC none(V-HPC-1), 감사(V-SEC-5), 단위 문자열."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from helpers_api import PW, P, _job, _model, _sid
from physicsai_test_support import API, H, make_h3d_tree, make_model_folder, make_param_set_folder

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
    # D3-43: pscfg 0개 → 확인 ok·등록 성공, 2개 → 확인 PSCFG_COUNT·등록 실패(모호)
    dn = make_model_folder(inbox, name="NoCfg", pscfg=0)
    insp = client.post(f"{API}/studies/{sid}/paths/inspect", headers=PW, json={"purpose": "MODEL_FOLDER", "path": str(dn)}).json()
    assert insp["ok"] and insp["summary"]["pscfg"] == [] and insp["problems"] == []
    r = _job(client, sid, "MODEL_REGISTER", {"model_path": str(dn)})
    assert w.run_once_light() == "SUCCEEDED"
    res = client.get(f"{API}/jobs/{r.json()['id']}", headers=P).json()["result"]
    assert res["files"]["pscfg"] is None and client.get(f"{API}/models/{res['model_id']}", headers=P).json()["status"] == "ACTIVE"
    dp = make_model_folder(inbox, name="TwoCfg", pscfg=2)
    insp = client.post(f"{API}/studies/{sid}/paths/inspect", headers=PW, json={"purpose": "MODEL_FOLDER", "path": str(dp)}).json()
    assert not insp["ok"] and [p["code"] for p in insp["problems"]] == ["PSCFG_COUNT"] and "여러 개" in insp["problems"][0]["message"]
    r = _job(client, sid, "MODEL_REGISTER", {"model_path": str(dp)})
    assert w.run_once_light() == "FAILED"
    msg = client.get(f"{API}/jobs/{r.json()['id']}", headers=P).json()["failure_message"]
    assert "settings.pscfg" in msg and "settings_1.pscfg" in msg
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
    from physicsai_core.config import load_config_dict
    from physicsai_worker.runtime import Worker

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
