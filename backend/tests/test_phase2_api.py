"""V2-API-1·2: 2차 API 모양·권한·오류 코드, /status 확장, 경로 확인 purpose, 작업 요약 확장."""

from __future__ import annotations

from phase2_helpers import make_inputs, study, submit
from physicsai_test_support import API, H

PW, P, G = H("tok-power", write=True), H("tok-power"), H("tok-general", write=True)


def test_status_extensions(p2_env):
    c, mk, ai, lc, d = p2_env
    st = c.get(f"{API}/status", headers=P).json()
    assert {a["key"] for a in st["altair"]} >= {"hstpy_path"} and next(a for a in st["altair"] if a["key"] == "hstpy_path")["ok"]
    res = {r["key"]: r for r in st["resources"]}
    assert res["pyd_dir"] == {"key": "pyd_dir", "configured": True, "ok": True}
    assert set(st["features"]) == {"train_extract", "train_tpl", "train_doe", "train_solve", "train_import", "train_resp",
                                   "curation_h3d", "curation_t01", "spdm_import", "optimize"}
    assert st["features"]["train_doe"]["enabled"] and st["features"]["train_resp"] == {"enabled": False, "missing": ["commands.response_extract"]}
    assert st["hpc"]["collect_mode"] == "in_place" and st["env_check"] is None
    assert c.get(f"{API}/status", headers=H("tok-admin")).json()["env_check"]["latest_id"] is None


def test_status_features_missing(client):
    """1차만 설정된 설치: 2차 기능은 비활성 + missing(가정 A-11)."""
    f = client.get(f"{API}/status", headers=P).json()["features"]
    assert f["train_extract"]["enabled"] is False
    assert "commands.simlab_extract_params" in f["train_extract"]["missing"] and "resources.pyd_dir" in f["train_extract"]["missing"]
    assert f["train_import"] == {"enabled": True, "missing": []}
    assert f["optimize"]["enabled"] is False and "altair.hstpy_path" in f["optimize"]["missing"]


def test_phase2_job_permissions_and_errors(p2_env):
    c, mk, ai, lc, d = p2_env
    sid = study(c, "ap1")
    cad, assem = make_inputs(ai / "ap1")
    r = c.post(f"{API}/studies/{sid}/jobs", headers=G, json={"job_type": "TD_EXTRACT_PARAMS", "params": {"cad_path": str(cad)}})
    assert r.status_code == 403
    r = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(cad), "extra": 1}, expect=422)
    assert r["detail"]["code"] == "INVALID_PARAMS"
    assert c.put(f"{API}/studies/{sid}/train/params", headers=PW, json={"version": 0, "parameters": []}).json()["detail"]["code"] == "TRAIN_PARAMS_REQUIRED"
    assert c.post(f"{API}/studies/{sid}/train/tpl", headers=PW, json={"version": 0}).json()["detail"]["code"] == "TRAIN_PARAMS_REQUIRED"
    assert c.put(f"{API}/studies/{sid}/train/params", headers=G, json={"version": 0, "parameters": []}).status_code == 403
    r = submit(c, sid, "TD_DOE_GEN", {"doe_label": "LatinHyperCube", "options": {"RANDOM_SEED": 1}, "radioss_assem_path": str(assem)}, expect=409)
    assert r["detail"]["code"] == "TPL_REQUIRED"
    r = submit(c, sid, "CU_H3D_PREVIEW", {"source": {"kind": "FOLDER", "path": str(ai / "ap1" / "00_inbox")}}, expect=409)
    assert r["detail"] == {"code": "PREREQUISITE_MISSING", "message": "사전 조건이 충족되지 않았습니다", "missing": ["SOURCE_FILES"]}
    r = submit(c, sid, "CU_H3D_PREVIEW", {"source": {"kind": "TRAIN_DOE", "doe_id": "nope"}}, expect=409)
    assert r["detail"]["code"] == "DOE_NOT_READY"
    r = submit(c, sid, "CU_T01_CURVES", {"source": {"kind": "FOLDER", "path": str(ai)}, "curves": [{"type": "a", "request": "b", "component": "c"}]}, expect=422)
    assert r["detail"]["code"] == "PATH_UNSAFE"  # AI 루트 전체
    r = submit(c, sid, "CU_T01_CURVES", {"source": {"kind": "OTHER"}, "curves": []}, expect=422)
    assert r["detail"]["code"] == "INVALID_PARAMS"
    # 경로 확인 purpose
    insp = c.post(f"{API}/studies/{sid}/paths/inspect", headers=PW, json={"purpose": "CAD_FILE", "path": str(cad)}).json()
    assert insp["ok"] and insp["summary"] == {"file_name": "cushion_parametric.prt", "size": 300, "extension_ok": True}
    insp = c.post(f"{API}/studies/{sid}/paths/inspect", headers=PW, json={"purpose": "RADIOSS_ASSEM", "path": str(assem)}).json()
    assert insp["ok"] and insp["summary"]["starter"] == ["drop_0000.rad"] and insp["summary"]["inc_count"] == 1
    assert insp["summary"]["rad"] == ["drop_0000.rad", "drop_0001.rad", "eps_mesh_0000.rad"]
    r = c.post(f"{API}/studies/{sid}/paths/inspect", headers=PW, json={"purpose": "CAD_FILE", "path": str(ai / "_platform" / "x.prt")})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_UNSAFE"
    # 작업 요약 확장
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(cad)})
    assert j["stage_label"] == "①-1" and j["current_step_key"] is None and j["hpc_summary"] is None
    assert j["can_download_error_bundle"] is False
    q = c.get(f"{API}/queue", headers=P).json()
    assert q["queued"][0]["stage_label"] == "①-1"
    lst = c.get(f"{API}/jobs?study_id={sid}", headers=P).json()
    assert lst[0]["stage_label"] == "①-1"
    # 조회 API 404
    for path in ("/train-does/x", "/curations/x", "/optimizations/x", "/train-does/x/runs", "/curations/x/files"):
        assert c.get(API + path, headers=P).status_code == 404, path
    assert c.get(f"{API}/studies/{sid}/train/does", headers=P).json() == []
    assert c.get(f"{API}/studies/{sid}/curations?kind=H3D", headers=P).json() == []
    assert c.get(f"{API}/studies/{sid}/optimizations", headers=P).json() == []
    assert c.get(f"{API}/studies/{sid}/spdm-imports", headers=P).json() == []
    assert c.get(f"{API}/studies/{sid}/train", headers=P).json()["parameters"] == []


def test_doe_types_errors(client):
    r = client.get(f"{API}/train/doe-types", headers=P)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "RESOURCE_NOT_CONFIGURED"
