"""native 형상 엔진 설정·명령 템플릿(geometry-engine.md §7.1): geometry 절, paicad_* 템플릿, {paicad} 규칙, 상태."""

from __future__ import annotations

import os

import pytest
import yaml

from physicsai_core.commands import TEMPLATE_SPECS, render_argv, validate_template
from physicsai_core.config import derived_paicad_path, effective_executables, load_config_dict
from physicsai_core.errors import StepFailure
from physicsai_core.features import feature_status, geometry_status
from physicsai_test_support import REPO

PAICAD_KEYS = ("paicad_extract", "paicad_tag", "paicad_update", "paicad_morph", "paicad_check", "paicad_run", "paicad_version", "paicad_cushion_write")


def _example(tmp_path, **over):
    data = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    data["storage"]["ai_root"] = str(tmp_path)
    data["storage"]["allowed_import_roots"] = []
    data.update(over)
    return load_config_dict(data, environ={})


def test_example_has_geometry_and_paicad_templates(tmp_path):
    lc = _example(tmp_path)
    assert lc.ok, lc.issues
    g = lc.settings.geometry
    assert g.engine == "altair" and g.step_extensions == [".step", ".stp"] and g.timeout_s["run"] == 3600
    for k in PAICAD_KEYS:
        assert getattr(lc.settings.commands, k) is not None and k in TEMPLATE_SPECS
        assert not TEMPLATE_SPECS[k].required and not TEMPLATE_SPECS[k].tokens


def test_defaults_without_section_equal_example(tmp_path):
    data = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    ex = _example(tmp_path).settings
    data.pop("geometry", None)
    for x in PAICAD_KEYS:
        data["commands"].pop(x, None)
    data["storage"]["ai_root"] = str(tmp_path)
    data["storage"]["allowed_import_roots"] = []
    s = load_config_dict(data, environ={}).settings
    assert s.geometry.model_dump() == ex.geometry.model_dump()
    assert [getattr(s.commands, x) for x in PAICAD_KEYS] == [getattr(ex.commands, x) for x in PAICAD_KEYS]


@pytest.mark.parametrize("over,key", [
    ({"engine": "x"}, "geometry.engine"),
    ({"paicad_path": "relative/paicad"}, "geometry.paicad_path"),
    ({"step_extensions": ["step"]}, "geometry.step_extensions"),
    ({"max_report_bytes": 10}, "geometry.max_report_bytes"),
    ({"progress_regex": "(?P<pct>"}, "geometry.progress_regex"),
    ({"progress_regex": "^x$"}, "geometry.progress_regex"),
    ({"timeout_s": {"extract": 0}}, "geometry.timeout_s.extract"),
    ({"timeout_s": {"nope": 5}}, "geometry.timeout_s.nope"),
    ({"env": {"1BAD": "x"}}, "geometry.env"),
    ({"defaults": {"quality": {"max_aspect": -1}}}, "geometry.defaults"),
    ({"defaults": {"unknown": 1}}, "geometry.defaults"),
])
def test_geometry_validation(tmp_path, over, key):
    data = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    data["storage"]["ai_root"] = str(tmp_path)
    data["storage"]["allowed_import_roots"] = []
    data["geometry"].update(over)
    assert key in load_config_dict(data, environ={}).error_keys()


def test_timeout_null_allowed(tmp_path):
    data = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    data["storage"]["ai_root"] = str(tmp_path)
    data["storage"]["allowed_import_roots"] = []
    data["geometry"]["timeout_s"] = {"run": None}
    assert load_config_dict(data, environ={}).ok


def test_paicad_head_rules():
    assert validate_template("paicad_version", ["{paicad}", "version", "--json"]) == []
    assert validate_template("paicad_version", None) == []
    assert any("argv[0]" in p for p in validate_template("paicad_version", ["{edspy}", "version"]))
    assert any("argv[0]" in p for p in validate_template("paicad_version", ["python", "version"]))
    # {paicad}는 paicad_* 밖에서 금지
    assert validate_template("geom_update", ["{paicad}", "x"])
    assert validate_template("paicad_update", ["{paicad}", "--cad", "{rendered_script}"])  # 허용 목록 밖 placeholder
    assert validate_template("paicad_version", ["{paicad}", "{paicad}"])  # argv[0]에만


def test_derived_path_and_executables(tmp_path):
    s = _example(tmp_path).settings
    exe = derived_paicad_path(s, python="/opt/venv/bin/python")
    assert exe.replace("\\", "/").endswith("bin/paicad") or exe.endswith("paicad.exe")
    s2 = s.model_copy(update={"geometry": s.geometry.model_copy(update={"paicad_path": "/x/paicad"})})
    assert derived_paicad_path(s2) == "/x/paicad"
    assert effective_executables(s2)["paicad_path"] == "/x/paicad" and "simlab_path" in effective_executables(s2)


def _values(tmp):
    return {k: os.path.join(tmp, k) for k in ("cad_input", "renum_csv", "options_json", "out_dir")}


def test_render_extract_and_optional_renum_pair(tmp_path):
    s = _example(tmp_path).settings
    exes = {"paicad_path": "/x/paicad"}
    v = _values(str(tmp_path))
    argv = render_argv("paicad_extract", s.commands.paicad_extract, v, executables=exes, is_windows=False)
    assert argv[:2] == ["/x/paicad", "extract"] and "--renum-csv" in argv and v["renum_csv"] in argv
    del v["renum_csv"]
    argv = render_argv("paicad_extract", s.commands.paicad_extract, v, executables=exes, is_windows=False)
    assert "--renum-csv" not in argv and argv.count("--options") == 1 and argv[-1] == v["out_dir"]
    # 다른 키에서는 같은 쌍을 생략하지 않는다(값이 없으면 내부 오류)
    with pytest.raises(StepFailure) as ei:
        render_argv("paicad_tag", s.commands.paicad_tag, {k: "/a" for k in TEMPLATE_SPECS["paicad_tag"].placeholders if k != "renum_csv"},
                    executables=exes, is_windows=False)
    assert ei.value.code == "INTERNAL_ERROR"


def test_render_extra_args_and_executable_missing(tmp_path):
    s = _example(tmp_path).settings
    v = _values(str(tmp_path))
    argv = render_argv("paicad_extract", s.commands.paicad_extract, v, executables={"paicad_path": "/x/paicad"}, is_windows=False,
                       extra_args=["--body-map", str(tmp_path / "body_map.json")])
    assert argv[-2:] == ["--body-map", str(tmp_path / "body_map.json")]
    with pytest.raises(StepFailure) as ei:
        render_argv("paicad_extract", s.commands.paicad_extract, v, executables={"paicad_path": ""}, is_windows=False)
    assert ei.value.code == "EXECUTABLE_MISSING" and "geometry.paicad_path" in ei.value.message
    bad = dict(v, out_dir="/a/b&c")
    with pytest.raises(StepFailure) as ei:
        render_argv("paicad_extract", s.commands.paicad_extract, bad, executables={"paicad_path": "/x/paicad"}, is_windows=False)
    assert ei.value.code == "INPUT_INVALID"
    with pytest.raises(StepFailure):
        render_argv("paicad_extract", s.commands.paicad_extract, v, executables={"paicad_path": "/x/paicad"}, is_windows=False,
                    extra_args=["--body-map", "/a/b;c|d"])


def test_status_and_warning(tmp_path):
    lc = _example(tmp_path)
    st = geometry_status(lc.settings)
    assert st["engine_default"] == "altair" and st["native_available"] is False and st["reason"]  # 이 PC의 venv에 paicad 실행 파일 없음 가정
    fake = tmp_path / "paicad"
    fake.write_text("#!/bin/sh\n")
    data = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    data["storage"]["ai_root"] = str(tmp_path)
    data["storage"]["allowed_import_roots"] = []
    data["geometry"]["paicad_path"] = str(fake)
    data["geometry"]["engine"] = "native"
    ok = load_config_dict(data, environ={})
    assert ok.ok and geometry_status(ok.settings) == {"engine_default": "native", "native_available": True, "reason": None}
    assert feature_status(ok.settings, False)["geometry_native"]["enabled"] is True
    assert not [w for w in ok.warnings if w.key == "geometry.engine"]
    data["commands"]["paicad_run"] = lc.settings.commands.paicad_run
    data["commands"]["paicad_morph"] = None
    assert feature_status(load_config_dict(data, environ={}).settings, False)["geometry_native"]["enabled"] is False  # 단건 예측이 단계별 명령을 쓰므로 paicad_run이 있어도 morph 필요
    data["commands"]["paicad_run"] = None
    off = load_config_dict(data, environ={})
    assert off.ok and feature_status(off.settings, False)["geometry_native"]["enabled"] is False
    assert any(w.key == "geometry.engine" for w in off.warnings)
    data["commands"]["paicad_morph"] = lc.settings.commands.paicad_morph
    data["geometry"]["paicad_path"] = str(tmp_path / "nope")
    assert any(w.key == "geometry.engine" and "paicad" in w.message for w in load_config_dict(data, environ={}).warnings)
