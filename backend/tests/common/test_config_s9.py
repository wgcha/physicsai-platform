"""phase3 §14 S9 설정·명령·기능 판정: predict_batch 절, response_extract {extract_tcl}, features.predict_mesh_only·predict_responses."""

from __future__ import annotations

import pytest

from physicsai_test_support import REPO, make_phase2_settings


@pytest.fixture()
def p2_dict(tmp_path, fake_tools):
    return make_phase2_settings(tmp_path, fake_tools)


def _load(d):
    from physicsai_core.config import load_config_dict

    return load_config_dict(d, environ={})


def test_predict_batch_defaults_and_ranges(p2_dict):
    lc = _load(p2_dict)
    assert lc.ok and lc.settings.predict_batch.model_dump() == {
        "max_runs": 200, "table_max_bytes": 1048576, "dir_name": "04_batch", "curve_max_runs": 200}
    for k, v in (("max_runs", 1), ("max_runs", 2001), ("table_max_bytes", 100), ("curve_max_runs", 0),
                 ("dir_name", "04_predict"), ("dir_name", "a/b"), ("dir_name", "_backup"), ("dir_name", ""), ("dir_name", "LOGS"),
                 ("dir_name", "batch\n"), ("dir_name", "b\u0661")):  # D3-53: 끝 줄바꿈·유니코드 숫자 거부
        assert _load({**p2_dict, "predict_batch": {k: v}}).error_keys() == [f"predict_batch.{k}"], (k, v)
    assert _load({**p2_dict, "predict_batch": {"dir_name": "batch_runs", "max_runs": 2}}).ok
    assert _load({**p2_dict, "predict_batch": {"unknown": 1}}).error_keys()[0].startswith("predict_batch")  # 모르는 키는 오류


def test_example_yaml_s9_defaults(tmp_path):
    import yaml

    data = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    data["storage"]["ai_root"] = str(tmp_path)
    lc = _load(data)
    assert lc.ok, lc.issues
    assert lc.settings.commands.response_extract == ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"]
    assert lc.settings.predict_batch.dir_name == "04_batch" and lc.settings.predict_batch.max_runs == 200


def test_response_extract_extract_tcl_placeholder():
    from physicsai_core.commands import render_argv, validate_template

    new = ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"]
    old = ["{hw}", "--responses", "{responses_json}", "--input", "{pred_h3d}", "--out", "{out_csv}"]
    assert validate_template("response_extract", new) == [] and validate_template("response_extract", old) == []
    assert validate_template("mesh", ["{hw}", "{extract_tcl}"]) != []  # 다른 템플릿에는 없음
    exe = {"hw_exe_path": "C:/Altair/hw.exe"}
    assert render_argv("response_extract", new, {"extract_tcl": "E:\\S\\04_predict\\j\\RESULT\\H3D_StaticMinMax_to_CSV_FAST.tcl"},
                       executables=exe, is_windows=True) == [
        "C:\\Altair\\hw.exe", "-clientconfig", "hwpost.dat", "-b", "-tcl", "E:/S/04_predict/j/RESULT/H3D_StaticMinMax_to_CSV_FAST.tcl"]


def test_features_predict_mesh_only_and_responses(p2_dict):
    from physicsai_core.features import feature_status, predict_mesh_only_missing, predict_responses_missing

    s = _load(p2_dict).settings
    st = feature_status(s, False)
    # 시험 기본 설정: geom_update·edspy_predict·contour_preview 있음, response_extract null
    assert st["predict_mesh_only"] == {"enabled": True, "missing": []}
    assert st["predict_responses"] == {"enabled": False, "missing": ["commands.response_extract"]}
    # mesh_only는 commands.mesh·include TCL과 무관(parametric은 include TCL 필요)
    d = {**p2_dict, "commands": {**p2_dict["commands"], "mesh": ["{hw}", "-b", "-tcl", "{include_tcl}", "{simlab_mesh}"]},
         "resources": {**p2_dict["resources"], "hypermesh_include_tcl": ""}}
    s2 = _load(d).settings
    assert predict_mesh_only_missing(s2) == ([], [])
    assert feature_status(s2, False)["predict_parametric"]["enabled"] is False
    s3 = _load({**p2_dict, "commands": {**p2_dict["commands"], "geom_update": None}}).settings
    assert predict_mesh_only_missing(s3) == (["commands.geom_update"], [])
    # 새 방식({extract_tcl})은 resources.extract_minmax_tcl 필요, 옛 방식({out_csv})은 불필요
    new = ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}"]
    old = ["{hw}", "--responses", "{responses_json}", "--input", "{pred_h3d}", "--out", "{out_csv}"]
    with_tcl = _load({**p2_dict, "commands": {**p2_dict["commands"], "response_extract": new}}).settings
    assert with_tcl.resources.extract_minmax_tcl and predict_responses_missing(with_tcl) == ([], [])
    no_tcl = _load({**p2_dict, "commands": {**p2_dict["commands"], "response_extract": new},
                    "resources": {**p2_dict["resources"], "extract_minmax_tcl": ""}}).settings
    assert predict_responses_missing(no_tcl) == ([], ["resources.extract_minmax_tcl"])
    old_s = _load({**p2_dict, "commands": {**p2_dict["commands"], "response_extract": old},
                   "resources": {**p2_dict["resources"], "extract_minmax_tcl": ""}}).settings
    assert feature_status(old_s, False)["predict_responses"] == {"enabled": True, "missing": []}


def test_predict_batch_job_type_registered():
    from physicsai_core.job_types import JOB_TYPES, job_label, stage_label, step_label

    jt = JOB_TYPES["PREDICT_BATCH"]
    assert (jt.stage, jt.lane, jt.notify_success, job_label("PREDICT_BATCH"), stage_label("PREDICT_BATCH")) == (
        4, "SLOT", False, "일괄 예측 입력 생성", "④")
    assert [(s.key, s.kind, s.weight) for s in jt.steps] == [("BP_PREP", "INTERNAL", 3), ("BP_GEN", "LOCAL", 90),
                                                            ("BP_ENQUEUE", "INTERNAL", 2)]
    assert [jt.needs_slot(s) for s in jt.steps] == [True, True, True]
    assert {step_label(s.key) for s in jt.steps} == {"일괄 입력 준비", "run 입력 생성", "예측 대기열 등록"}


def test_predict_batch_job_feature_is_common_condition():
    from physicsai_core.features import FEATURES, JOB_FEATURE

    assert JOB_FEATURE["PREDICT_BATCH"] == FEATURES["predict_mesh_only"]
    assert set(JOB_FEATURE["PREDICT_BATCH"].templates) == {"geom_update", "edspy_predict", "contour_preview"}
