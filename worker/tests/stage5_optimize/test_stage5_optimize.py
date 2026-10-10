"""⑤ 최적화(V2-OP-1~4): RESPONSES 검증, INPUT_HST_RUN.json 키, env, @cmd_c, 진행률, 결과 파일·요약 파서, 응답 후보."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from helpers_stage1 import job, study, submit
from physicsai_test_support import API, H, make_model_folder, make_param_set_folder, read_record

PW, P = H("tok-power", write=True), H("tok-power")

RESP = [
    {"name": "MAX_VM", "source": "H3D", "subcase": 1, "datatype": "Stress", "component": "vonMises", "layer": "",
     "stat": "MAX", "goal": "MINIMIZE"},
    {"name": "DISP_X", "source": "XYDATA", "request": "Node 100", "component": "X", "stat": "ABSMAX", "goal": "CONSTRAINT",
     "bound": "<=", "value": 5.0},
    {"name": "INFO", "source": "XYDATA", "request": "R", "component": "Y", "stat": "MIN", "goal": "NONE", "bound": ">=", "value": 1},
]


def _setup_opt(c, w, ai: Path, name: str) -> tuple[str, str, str]:
    sid = study(c, name)
    sroot = ai / name
    mf = make_model_folder(sroot / "00_inbox")
    jid = submit(c, sid, "MODEL_REGISTER", {"model_path": str(mf)})["id"]
    assert w.run_once_light() == "SUCCEEDED"
    mid = job(c, jid)["result"]["model_id"]
    assert c.put(f"{API}/studies/{sid}/final-model", headers=PW, json={"model_id": mid}).status_code == 200
    psf = make_param_set_folder(sroot / "00_inbox")
    ps = c.post(f"{API}/studies/{sid}/param-sets", headers=PW, json={"path": str(psf)}).json()
    return sid, mid, ps["id"]


def test_responses_validation_units():
    """V2-OP-1: 이름·중복(대소문자 무시)·'|'·CONSTRAINT·OPT 목적 필수·비제약 행 BOUND/VALUE 제거."""
    from physicsai_core.stage5_optimize.optimize import responses_for_run, validate_responses

    rows, probs = validate_responses(RESP, "OPT")
    assert probs == []
    assert "bound" not in rows[2] and "value" not in rows[2] and rows[1]["value"] == 5.0
    run = responses_for_run(rows)
    assert run[0] == {"NAME": "MAX_VM", "SOURCE": "H3D", "COMPONENT": "vonMises", "STAT": "MAX", "GOAL": "MINIMIZE",
                      "SUBCASE": 1, "DATATYPE": "Stress", "LAYER": ""}
    assert run[1] == {"NAME": "DISP_X", "SOURCE": "XYDATA", "COMPONENT": "X", "STAT": "ABSMAX", "GOAL": "CONSTRAINT",
                      "BOUND": "<=", "VALUE": 5.0, "REQUEST": "Node 100"}
    for bad in (
        [{**RESP[0], "name": "1abc"}], [RESP[0], {**RESP[0], "name": "max_vm"}], [{**RESP[0], "component": "a|b"}],
        [{**RESP[1], "value": "x"}], [{**RESP[1], "bound": "<"}], [{**RESP[0], "stat": "AVG"}], [{**RESP[0], "source": "CSV"}],
        [{**RESP[0], "subcase": 0}], [{**RESP[0], "extra": 1}], [],
    ):
        assert validate_responses(bad, "OPT")[1], bad
    assert validate_responses([RESP[2]], "OPT")[1] == [{"row": "", "message": "OBJECTIVE_REQUIRED"}]
    assert validate_responses([RESP[2]], "DOE")[1] == []


def test_optimize_chain(p2_env, fake_record, monkeypatch, engine):
    """V2-OP-2·V2-OP-3·V2-OP-4."""
    c, mk, ai, lc, d = p2_env
    w = mk()
    sid, mid, psid = _setup_opt(c, w, ai, "op1")
    r = submit(c, sid, "OPTIMIZE", {"responses": [RESP[2]]}, expect=422)
    assert r["detail"]["code"] == "OBJECTIVE_REQUIRED"
    r = submit(c, sid, "OPTIMIZE", {"responses": [{**RESP[0], "name": "bad name"}]}, expect=422)
    assert r["detail"]["code"] == "RESPONSES_INVALID" and r["detail"]["problems"]
    j = submit(c, sid, "OPTIMIZE", {"responses": RESP, "max_designs": 4})
    assert j["params"]["model_id"] == mid and j["params"]["param_set_id"] == psid
    assert j["params"]["study_folder"] == "HST_PHYSICSAI_OPTIMIZATION" and j["stage"] == 5
    O = ai / "op1" / "05_opt" / j["id"]
    (O / "HST_PHYSICSAI_OPTIMIZATION").mkdir(parents=True)
    (O / "HST_PHYSICSAI_OPTIMIZATION" / "old.txt").write_text("old")
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    cfg = json.loads((O / "INPUT_HST_RUN.json").read_text())
    from physicsai_core.stage5_optimize.optimize import RUN_CONFIG_KEYS

    assert set(cfg) == set(RUN_CONFIG_KEYS) and "MAX_STRAIN" not in cfg
    S = ai / "op1" / "04_params" / psid
    F = lambda p: str(p).replace("\\", "/")  # noqa: E731 - INPUT_HST_RUN.json 경로는 '/' 표기(원본 replace)
    assert cfg["TPL_FILE"] == F(S / "simlab_parametered_mesh.tpl") and cfg["CAD_PARAM"] == F(S / "cad" / "bracket.x_t")
    assert cfg["PHYSICSAI_INPUT_FILE"] == F(S / "radioss_assem" / "model0_0000.rad")
    assert cfg["PREDICTED_H3D"] == "model0_0000_pred.h3d" and cfg["PREDICTED_XYDATA"] == "model0_0000_pred.xydata"
    assert cfg["HYPERVIEW_TCL"] == F(O / "H3D_StaticMinMax_to_CSV_FAST.tcl") and (O / "H3D_StaticMinMax_to_CSV_FAST.tcl").is_file()
    assert cfg["ALTAIR_PATHS"] == {"simlab_path": F(d["altair"]["simlab_path"])} and cfg["PHYSICSAI_OVERRIDE_ENV"] is False
    assert cfg["OPT_SETTINGS"] == {"ABS_CONVERGENCE": 0.001, "REL_CONVERGENCE": 1.0, "DV_CONVERGENCE": 0.001}
    assert cfg["MAX_DESIGNS"] == 4 and cfg["APPROACH"] == "OPT" and cfg["ON_FAILED"] == "IGNORE" and len(cfg["RESPONSES"]) == 3
    assert cfg["PHYSICSAI_MODEL"].endswith("cushion_TNS.psmdl")
    tools_dir = Path(d["altair"]["hstpy_path"]).parent
    assert cfg["ALTAIR_HOME"] == "/".join(F(tools_dir).split("/")[:-3])  # hstpy 폴더/../../..
    rec = [r for r in read_record(fake_record) if r["tool"] == "hstpy"][-1]
    assert rec["argv"][1:] == [str(O / "BATCHRUN_hst_physicsai_optimization.py")]  # Linux: @cmd_c → 없음
    assert rec["env"]["EDS_TNS_ACTVN_CHCKPT"] == "1" and rec["env"]["ALTAIR_HOME"] == cfg["ALTAIR_HOME"] and rec["cwd"] == str(O)
    assert list((ai / "op1" / "_backup").rglob("old.txt"))  # 기존 Study 폴더 백업
    jd = job(c, j["id"])
    oid = jd["result"]["optimization_id"]
    opt = c.get(f"{API}/optimizations/{oid}", headers=P).json()
    assert opt["status"] == "DONE" and opt["runs_started"] == 4 and opt["summary_status"] == "PARSED"
    assert opt["summary_meta"]["columns"] == ["iter", "THK_1", "MAX_VM"] and opt["summary_meta"]["row_count"] == 3
    assert opt["file_count"] == 3 and opt["file_list_artifact_id"] and opt["summary_artifact_id"]
    summary = c.get(f"{API}/artifacts/{opt['summary_artifact_id']}/content", headers=P).json()
    assert summary["rows"][0] == ["1", "3.0", "120.5"]
    arts = c.get(f"{API}/jobs/{j['id']}/artifacts", headers=P).json()
    kinds = sorted(a["kind"] for a in arts)
    assert kinds == ["FILE_LIST", "OPT_FILE", "OPT_FILE", "OPT_SUMMARY", "RUN_CONFIG"]  # big.bin은 보기 대상 아님
    steps = {s["step_key"]: s for s in jd["steps"]}
    assert steps["HST_OPTIMIZE"]["progress_label"] == "run 4 / 4 시작" and steps["HST_OPTIMIZE"]["progress_pct"] == 100.0
    assert c.get(f"{API}/studies/{sid}/optimizations", headers=P).json()[0]["id"] == oid
    # 오류 줄이 있어도 종료코드 0이면 성공(가정 A-8), DOE면 진행률 NULL·라벨
    monkeypatch.setenv("FAKE_TOOL_MODE_HSTPY", "error_lines")
    j2 = submit(c, sid, "OPTIMIZE", {"responses": RESP, "approach": "DOE", "max_designs": 3, "study_folder": "MY_DOE"})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j2["id"])
    jd2 = job(c, j2["id"])
    assert jd2["result"]["log_error_lines"] == 1
    assert next(s for s in jd2["steps"] if s["step_key"] == "HST_OPTIMIZE")["progress_label"] == "run 3 시작"
    monkeypatch.setenv("FAKE_TOOL_MODE_HSTPY", "fail")
    j3 = submit(c, sid, "OPTIMIZE", {"responses": RESP})
    assert w.run_once_slot() == "FAILED"
    assert c.get(f"{API}/optimizations/{job(c, j3['id'])['result']['optimization_id']}", headers=P).json()["status"] == "FAILED"


def test_optimize_unrecognized_and_candidates(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch):
    """V2-OP-4: 요약 파서 없음 → UNRECOGNIZED, 응답 후보(PREDICT 미리보기 있음/없음), Final 없음 409."""
    from physicsai_test_support import _p2_env

    gen = _p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, {"optimize": {"summary_parsers": []}})
    c, mk, ai, lc, d = next(gen)
    try:
        w = mk()
        sid = study(c, "op2")
        assert submit(c, sid, "OPTIMIZE", {"responses": RESP}, expect=409)["detail"]["code"] == "PREREQUISITE_MISSING"
        sid, mid, psid = _setup_opt(c, w, ai, "op3")
        cand = c.get(f"{API}/studies/{sid}/optimize/response-candidates", headers=P).json()
        assert cand == {"source_job_id": None, "h3d": None, "xydata": None}
        pj = submit(c, sid, "PREDICT", {"values": {"THK_1": 3, "N_RIB": 4}, "value_source": "nominal"})
        assert w.run_once_slot() == "SUCCEEDED"
        cand = c.get(f"{API}/studies/{sid}/optimize/response-candidates?model_id={mid}", headers=P).json()
        assert cand["source_job_id"] == pj["id"]
        assert cand["h3d"]["subcases"][0]["label"] == "Subcase 1" and cand["h3d"]["subcases"][0]["datatypes"][0]["components"] == ["vonMises"]
        assert cand["xydata"] == {"requests": {"Impact_force": []}}
        j = submit(c, sid, "OPTIMIZE", {"responses": RESP, "max_designs": 2})
        assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
        opt = c.get(f"{API}/optimizations/{job(c, j['id'])['result']['optimization_id']}", headers=P).json()
        assert opt["summary_status"] == "UNRECOGNIZED" and opt["summary_artifact_id"] is None
        # 모델 파일 변경 → INPUT_CHANGED(sha256 재확인)
        psmdl = ai / "op3" / "03_model" / "models" / mid / "cushion_TNS.psmdl"
        psmdl.write_bytes(b"tampered")
        j = submit(c, sid, "OPTIMIZE", {"responses": RESP, "model_id": mid})
        assert w.run_once_slot() == "FAILED" and job(c, j["id"])["failure_code"] == "INPUT_CHANGED"
    finally:
        for _ in gen:
            pass


@pytest.mark.parametrize("missing", ["hst_optimization", "extract_minmax_tcl"])
def test_optimize_feature_gate(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, missing):
    """V2-API-2: 템플릿·자원 비우면 409 + /status.features enabled=false."""
    from physicsai_test_support import _p2_env, make_resources

    over = {"commands": {"hst_optimization": None}} if missing == "hst_optimization" else {}
    if missing == "extract_minmax_tcl":
        res = make_resources(tmp_path / "r2")
        res["extract_minmax_tcl"] = ""
        over = {"resources": res}
    gen = _p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, over)
    c, mk, ai, lc, d = next(gen)
    try:
        w = mk()
        sid, _mid, _ps = _setup_opt(c, w, ai, "fg1")
        r = submit(c, sid, "OPTIMIZE", {"responses": RESP}, expect=409)
        exp = "TEMPLATE_NOT_CONFIGURED" if missing == "hst_optimization" else "RESOURCE_NOT_CONFIGURED"
        assert r["detail"]["code"] == exp
        feat = c.get(f"{API}/status", headers=P).json()["features"]["optimize"]
        assert feat["enabled"] is False and any(missing in m for m in feat["missing"])
        assert c.get(f"{API}/status", headers=P).json()["features"]["train_extract"]["enabled"] is True
    finally:
        for _ in gen:
            pass
