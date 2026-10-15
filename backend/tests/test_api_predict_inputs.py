"""④ 예측 입력 API(phase3 §11.4·§11.5, V3-S6-6·9·10·12): 폴더 등록 규칙, 준비된 입력 경로 검사, params 조합, 경로 확인 응답 모양."""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

import httpx
import pytest

from helpers_api import P, PW, _job, _model, _sid
from physicsai_test_support import API, MESH_INC, REPO, make_param_set_folder

OK = {"input_mode": "prepared"}


def _case(root: Path, name: str = "case_A", *, starters: tuple[str, ...] = ("Face_Drop_0000.rad",)) -> Path:
    d = root / name
    d.mkdir(parents=True)
    for s in starters:
        (d / s).write_text("#include part.inc\n")
    (d / "Face_Drop_0001.rad").write_text("/ENGINE\n")
    (d / "part.inc").write_text("/NODE\n")
    (d / "EPS_mesh_0000.rad").write_text("mesh\n")
    return d


def _inspect(c, sid, path):
    return c.post(f"{API}/studies/{sid}/paths/inspect", headers=PW, json={"purpose": "PREDICT_INPUT", "path": str(path)})


@contextlib.contextmanager
def _client(settings_dict, engine, fake_dashboard, **over):
    from fastapi.testclient import TestClient

    from physicsai_api.context import build_context
    from physicsai_api.main import create_app
    from physicsai_core.config import load_config_dict

    d = dict(settings_dict)
    for k, v in over.items():
        d[k] = {**(d.get(k) or {}), **v}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    with TestClient(create_app(build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler))),
                    base_url="http://127.0.0.1") as c:
        yield c, lc


# ---- V3-S6-6 폴더 등록(§15.4 갱신) -------------------------------------------------------------------------------------


def test_v3_s6_6_param_set_folder_ignores_eps_mesh_and_copies_csv(client, loaded_config):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    d = make_param_set_folder(ai / "S1" / "00_inbox")
    assert (d / "radioss_assem" / "EPS_mesh_0000.rad").is_file()          # *_0000.rad 일치지만 starter로 세지 않음
    insp = client.post(f"{API}/studies/{sid}/paths/inspect", headers=PW, json={"purpose": "PARAM_SET", "path": str(d)}).json()
    assert insp["ok"] and insp["summary"]["starter_name"] == "model0_0000.rad" and insp["summary"]["renum_csv"] == "RENUM_INIT.csv"
    r = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(d)})
    assert r.status_code == 201, r.text
    assert r.json()["starter_name"] == "model0_0000.rad"
    S = ai / "S1" / "04_params" / r.json()["id"] / "radioss_assem"
    assert sorted(os.listdir(S)) == sorted([MESH_INC, "RENUM_INIT.csv", "material.inc", "model0_0000.rad", "model_0001.rad"])
    # csv·include 기준본이 없어도 등록 성공(④ 실행 때 경고)
    d2 = make_param_set_folder(ai / "S1" / "00_inbox", renum_csv=False, include_base=False)
    r = client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(d2)})
    assert r.status_code == 201, r.text
    assert sorted(os.listdir(ai / "S1" / "04_params" / r.json()["id"] / "radioss_assem")) == [
        "material.inc", "model0_0000.rad", "model_0001.rad"]


def test_d3_35_param_set_file_names(client, loaded_config):
    """phase3 D3-35: 파라미터 세트의 CAD·radioss_assem 파일 이름도 `; , = ( ) '`·공백 거부(외부 명령 인자·INPUT 복사본)."""
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = _sid(client)
    d = make_param_set_folder(ai / "S1" / "00_inbox")
    os.replace(d / "cad" / "bracket.x_t", d / "cad" / "bracket(v2).x_t")
    (d / "radioss_assem" / "extra=1.inc").write_text("x")
    insp = client.post(f"{API}/studies/{sid}/paths/inspect", headers=PW, json={"purpose": "PARAM_SET", "path": str(d)}).json()
    assert not insp["ok"]
    got = [(p["code"], p.get("file"), p["message"]) for p in insp["problems"]]
    assert ("PATH_UNSAFE", "cad/bracket(v2).x_t", "CAD 파일 이름에 쓸 수 없는 문자(( ))가 있습니다") in got
    assert ("PATH_UNSAFE", "radioss_assem/extra=1.inc", "파일 이름에 쓸 수 없는 문자(=)가 있습니다") in got
    assert client.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(d)}).status_code == 422


# ---- V3-S6-9 준비된 입력 경로 검사 --------------------------------------------------------------------------------------


def test_v3_s6_9_prepared_path_rejections(client, loaded_config, worker_factory, tmp_path):
    s = loaded_config.settings
    ai, imp = Path(s.storage.ai_root), Path(s.storage.allowed_import_roots[0])
    sid = _sid(client)
    w = worker_factory()
    _model_final(client, w, sid, ai / "S1" / "00_inbox")
    outside = _case(tmp_path / "elsewhere")
    spaced = _case(imp / "has space")
    meta = _case(imp / "a&b")
    backup = _case(ai / "S1" / "_backup")
    real = _case(imp / "real")
    os.symlink(real, imp / "link")
    cases = [(outside, "PATH_OUTSIDE_ROOT"), (spaced, "PATH_UNSAFE"), (meta, "PATH_UNSAFE"), (backup, "PATH_UNSAFE"),
             (imp / "link", "PATH_UNSAFE"), (imp / "nope", "PATH_NOT_FOUND"), (imp / "real" / "nope.rad", "PATH_NOT_FOUND")]
    for path, code in cases:
        r = _job(client, sid, "PREDICT", {**OK, "input_path": str(path)})
        assert r.status_code == 422 and r.json()["detail"]["code"] == code, (path, r.text)
        r = _inspect(client, sid, path)
        assert r.status_code == 422 and r.json()["detail"]["code"] == code, (path, r.text)
    # 허용 가져오기 루트·AI 루트 모두 허용
    r = _job(client, sid, "PREDICT", {**OK, "input_path": str(real)})
    assert r.status_code == 201, r.text
    assert w.run_once_slot() == "SUCCEEDED"                                # 같은 Study 같은 유형은 하나씩(STUDY_JOB_BUSY)
    r = _job(client, sid, "PREDICT", {**OK, "input_path": str(_case(ai / "S1" / "00_inbox"))})
    assert r.status_code == 201, r.text
    assert w.run_once_slot() == "SUCCEEDED"

    def problems(path):
        r = _job(client, sid, "PREDICT", {**OK, "input_path": str(path)})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "PREDICT_INPUT_INVALID", r.text
        assert r.json()["detail"]["message"] == "준비된 입력을 쓸 수 없습니다"
        insp = _inspect(client, sid, path).json()
        assert not insp["ok"]
        assert [(p["code"], p["message"]) for p in insp["problems"]] == [(p["code"], p["message"]) for p in r.json()["detail"]["problems"]]
        return [p["code"] for p in r.json()["detail"]["problems"]]

    bad_name = _case(imp / "badname")
    (bad_name / "x;y.inc").write_text("x")                                # .bat 재해석 문자는 경로 단계에서 통과 → 이름 검사
    (bad_name / "has space.inc").write_text("x")
    (bad_name / "run(1),v=2'.inc").write_text("x")                       # D3-35: ; , = ( ) ' 도 거부
    assert problems(bad_name) == ["FILE_NAME_UNSAFE"] * 3
    insp = _inspect(client, sid, bad_name).json()
    assert [p["message"] for p in insp["problems"]] == [
        "has space.inc: 파일 이름에 쓸 수 없는 문자(공백)가 있습니다",
        "run(1),v=2'.inc: 파일 이름에 쓸 수 없는 문자(' ( ) , =)가 있습니다",
        "x;y.inc: 파일 이름에 쓸 수 없는 문자(;)가 있습니다",
    ]
    ok_names = _case(imp / "한글_case-1.v2")                              # 영숫자·_·-·.·한글은 허용
    (ok_names / "브래킷-부품_1.inc").write_text("x")
    assert _job(client, sid, "PREDICT", {**OK, "input_path": str(ok_names)}).status_code == 201
    assert w.run_once_slot() == "SUCCEEDED"
    assert problems(_case(imp / "zero", starters=())) == ["STARTER_COUNT"]
    assert problems(_case(imp / "two", starters=("A_0000.rad", "B_0000.rad"))) == ["STARTER_COUNT"]
    assert problems(real / "part.inc") == ["INPUT_EXT"]
    os.symlink(imp / "real" / "part.inc", real / "linked.inc")
    assert problems(real) == ["FILE_NAME_UNSAFE"]


def test_v3_s6_9_prepared_limits(settings_dict, engine, fake_dashboard, worker_factory, loaded_config):
    with _client(settings_dict, engine, fake_dashboard, predict={"prepared_max_files": 2, "prepared_max_total_bytes": 20}) as (c, lc):
        ai, imp = Path(lc.settings.storage.ai_root), Path(lc.settings.storage.allowed_import_roots[0])
        sid = _sid(c, "LIM")
        _model_final(c, worker_factory(), sid, ai / "LIM" / "00_inbox")
        case = _case(imp / "big")
        r = _job(c, sid, "PREDICT", {**OK, "input_path": str(case)})
        assert r.status_code == 422
        assert sorted(p["code"] for p in r.json()["detail"]["problems"]) == ["TOO_LARGE", "TOO_MANY_FILES"]
        # .hm은 그 파일만 → 개수 한도 안
        (case / "m.hm").write_bytes(b"H" * 10)
        assert _job(c, sid, "PREDICT", {**OK, "input_path": str(case / "m.hm")}).status_code == 201


def _model_final(c, w, sid, root):
    mid = _model(c, w, sid, root)
    assert c.put(f"{API}/studies/{sid}/final-model", headers=PW, json={"model_id": mid}).status_code == 200
    return mid


# ---- V3-S6-10 params 조합 ---------------------------------------------------------------------------------------------


def test_v3_s6_10_params_combinations(client, loaded_config, worker_factory):
    s = loaded_config.settings
    ai, imp = Path(s.storage.ai_root), Path(s.storage.allowed_import_roots[0])
    sid = _sid(client)
    case = _case(imp)
    bad = [
        ({"values": {"THK_1": 3}, "value_source": "manual", "input_path": str(case)}, "input_path"),
        ({"values": {"THK_1": 3}}, "value_source"),
        ({"value_source": "manual"}, "values"),
        ({**OK}, "input_path"),
        ({**OK, "input_path": str(case), "values": {"A": 1}}, "values"),
        ({**OK, "input_path": str(case), "value_source": "manual"}, "value_source"),
        ({**OK, "input_path": str(case), "source_run_key": "run_1"}, "source_run_key"),
    ]
    for params, loc in bad:
        r = _job(client, sid, "PREDICT", params)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS", (params, r.text)
        assert ["params", loc] in [e["loc"] for e in r.json()["detail"]["errors"]], (params, r.text)
    assert _job(client, sid, "PREDICT", {"input_mode": "other", "input_path": str(case)}).status_code == 422
    # 사전조건: Final 없음 → 409, 세트 지정했는데 없음 → 409
    r = _job(client, sid, "PREDICT", {**OK, "input_path": str(case)})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FINAL_MODEL_REQUIRED"
    w = worker_factory()
    mid = _model_final(client, w, sid, ai / "S1" / "00_inbox")
    r = _job(client, sid, "PREDICT", {**OK, "input_path": str(case), "param_set_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 409 and r.json()["detail"]["missing"] == ["PARAM_SET"]
    # 세트 없이 생성, values 빈 dict 허용, 저장 params 모양
    r = _job(client, sid, "PREDICT", {**OK, "input_path": str(case) + "/", "values": {}, "model_id": mid})
    assert r.status_code == 201, r.text
    assert r.json()["params"] == {"input_mode": "prepared", "input_path": str(case), "input_kind": "dir",
                                  "starter_name": "Face_Drop_0000.rad", "model_id": mid, "param_set_id": None}
    assert w.run_once_slot() == "SUCCEEDED"
    # parametric(input_mode 생략)은 기존대로: 세트 없음 409
    r = _job(client, sid, "PREDICT", {"values": {"THK_1": 3}, "value_source": "manual"})
    assert r.status_code == 409 and r.json()["detail"]["missing"] == ["PARAM_SET"]
    ps = client.post(f"{API}/studies/{sid}/param-sets", headers=PW,
                     json={"path": str(make_param_set_folder(ai / "S1" / "00_inbox"))}).json()
    r = _job(client, sid, "PREDICT", {"values": {"THK_1": 3, "N_RIB": 4}, "value_source": "manual"})
    assert r.status_code == 201 and r.json()["params"]["input_mode"] == "parametric"
    assert w.run_once_slot() == "SUCCEEDED"
    r = _job(client, sid, "PREDICT", {**OK, "input_path": str(case)})
    assert r.status_code == 201 and r.json()["params"]["param_set_id"] == ps["id"]       # 현재 세트 = 응답 목록용


def test_v3_s6_10_prepared_without_geom_update_and_parametric_gate(settings_dict, engine, fake_dashboard, worker_factory):
    with _client(settings_dict, engine, fake_dashboard, commands={"geom_update": None}) as (c, lc):
        ai, imp = Path(lc.settings.storage.ai_root), Path(lc.settings.storage.allowed_import_roots[0])
        sid = _sid(c, "NG")
        w = worker_factory()
        _model_final(c, w, sid, ai / "NG" / "00_inbox")
        assert c.get(f"{API}/status", headers=P).json()["features"]["predict_parametric"] == {
            "enabled": False, "missing": ["commands.geom_update"]}
        assert any(w.key == "commands.geom_update" for w in lc.warnings)
        assert _job(c, sid, "PREDICT", {**OK, "input_path": str(_case(imp))}).status_code == 201
        assert w.run_once_slot() == "SUCCEEDED"
        c.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(make_param_set_folder(ai / "NG" / "00_inbox"))})
        r = _job(c, sid, "PREDICT", {"values": {"THK_1": 3, "N_RIB": 4}, "value_source": "manual"})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "TEMPLATE_NOT_CONFIGURED"
    # mesh가 {include_tcl}을 쓰는데 자원이 비면 predict_parametric=false + 경고, 작업 생성 409
    with _client(settings_dict, engine, fake_dashboard, resources={"hypermesh_include_tcl": ""}) as (c, lc):
        st = c.get(f"{API}/status", headers=P).json()["features"]
        assert st["predict_parametric"] == {"enabled": False, "missing": ["resources.hypermesh_include_tcl"]}
        assert st["predict"]["enabled"] is True
        assert [w.key for w in lc.warnings] == ["resources.hypermesh_include_tcl"]
        ai = Path(lc.settings.storage.ai_root)
        sid = _sid(c, "NI")
        _model_final(c, worker_factory(), sid, ai / "NI" / "00_inbox")
        c.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(make_param_set_folder(ai / "NI" / "00_inbox"))})
        r = _job(c, sid, "PREDICT", {"values": {"THK_1": 3, "N_RIB": 4}, "value_source": "manual"})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "TEMPLATE_NOT_CONFIGURED"
        assert r.json()["detail"]["missing"] == ["resources.hypermesh_include_tcl"]


def test_v3_s6_config_deprecated_and_validation(settings_dict):
    from physicsai_core.config import load_config_dict

    d = dict(settings_dict)
    d["predict"] = {"mesh_output_glob": "eps_mesh*"}
    lc = load_config_dict(d, environ={})
    assert lc.ok and [w.key for w in lc.warnings] == ["predict.mesh_output_glob"] and "폐지" in lc.warnings[0].message
    for bad in ({"mesh_include_name": "a/b.inc"}, {"simlab_mesh_name": "a b.rad"}, {"renum_csv_name": ""},
                {"prepared_input_exts": ["rad"]}, {"prepared_max_files": 0}, {"prepared_max_total_bytes": 0}):
        d["predict"] = bad
        key = "predict." + next(iter(bad))
        assert any(k.startswith(key) for k in load_config_dict(d, environ={}).error_keys()), bad
    d["predict"] = {}
    d["commands"] = {**d["commands"], "mesh": ["{hw}", "-tcl", "{include_tcl}", "{starter}"]}
    assert "commands.mesh" in load_config_dict(d, environ={}).error_keys()            # 허용 밖 placeholder


# ---- V3-S6-12 경로 확인 응답 모양·openapi ----------------------------------------------------------------------------------


def test_v3_s6_12_inspect_predict_input_shape(client, loaded_config):
    imp = Path(loaded_config.settings.storage.allowed_import_roots[0])
    sid = _sid(client)
    case = _case(imp)
    (case / "sub").mkdir()
    (case / "sub" / "deep.inc").write_text("x")
    body = _inspect(client, sid, case).json()
    assert set(body) == {"normalized_path", "ok", "problems", "summary"}
    assert body["ok"] and body["problems"] == [] and body["normalized_path"] == str(case)
    sm = body["summary"]
    assert set(sm) == {"kind", "starter", "starter_ok", "rad", "inc_count", "file_count", "total_bytes"}
    assert sm["kind"] == "dir" and sm["starter"] == ["Face_Drop_0000.rad"] and sm["starter_ok"] is True
    assert sm["rad"] == ["Face_Drop_0000.rad", "Face_Drop_0001.rad"] and sm["inc_count"] == 1 and sm["file_count"] == 3
    assert sm["total_bytes"] == sum((case / n).stat().st_size for n in ("Face_Drop_0000.rad", "Face_Drop_0001.rad", "part.inc"))
    f = _inspect(client, sid, case / "Face_Drop_0000.rad").json()["summary"]
    assert f["kind"] == "file" and f["starter"] == ["Face_Drop_0000.rad"] and f["file_count"] == 3
    two = _case(imp / "two", starters=("A_0000.rad", "B_0000.rad"))
    t = _inspect(client, sid, two).json()
    assert not t["ok"] and t["summary"]["starter"] == ["A_0000.rad", "B_0000.rad"] and t["summary"]["starter_ok"] is False
    assert t["problems"][0]["code"] == "STARTER_COUNT"
    spec = json.loads((REPO / "backend" / "openapi.json").read_text(encoding="utf-8"))
    comp = spec["components"]["schemas"]
    assert "PREDICT_INPUT" in comp["PathInspectRequest"]["properties"]["purpose"]["enum"]
    assert "predict_parametric" in comp["StatusFeatures"]["properties"]


@pytest.mark.parametrize("purpose", ["PREDICT_INPUT"])
def test_v3_s6_12_inspect_requires_power(client, purpose):
    sid = _sid(client)
    r = client.post(f"{API}/studies/{sid}/paths/inspect", headers={**P, "X-PhysicsAI-Request": "1", "Authorization": "Bearer tok-general"},
                    json={"purpose": purpose, "path": "/x"})
    assert r.status_code == 403
