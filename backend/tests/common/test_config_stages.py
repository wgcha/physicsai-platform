"""단계 설정·명령 단위 시험: 설정 검증(V2-CFG-1·2, 파생 hstpy·altair_home, 예시 YAML), 명령 argv 골든(V2-CMD-1·2)."""

from __future__ import annotations

import copy

import pytest

from physicsai_test_support import REPO, make_phase2_settings

# ---------------------------------------------------------------------------
# 설정(V2-CFG-1·2)
# ---------------------------------------------------------------------------


@pytest.fixture()
def p2_dict(tmp_path, fake_tools):
    return make_phase2_settings(tmp_path, fake_tools)


def _keys(d):
    from physicsai_core.config import load_config_dict

    return load_config_dict(d, environ={}).error_keys()


def test_phase2_settings_valid(p2_dict):
    assert _keys(p2_dict) == []


@pytest.mark.parametrize(
    "mutate,key",
    [
        (lambda d: d.update(train_data={"hst_progress_regex": "Finished run (\\d+)"}), "train_data.hst_progress_regex"),
        (lambda d: d.update(train_data={"paramitem_regex": "(?P<name>x)"}), "train_data.paramitem_regex"),
        (lambda d: d.update(train_data={"result_run_dir_regex": "run__\\d+"}), "train_data.result_run_dir_regex"),
        (lambda d: d.update(train_data={"hst_log_error_patterns": ["(bad"]}), "train_data.hst_log_error_patterns[0]"),
        (lambda d: d.update(train_data={"max_multi_execution": 65}), "train_data.max_multi_execution"),
        (lambda d: d.update(train_data={"samples_extractor": "magic"}), "train_data.samples_extractor"),
        (lambda d: d.update(optimize={"progress_regex": "Started"}), "optimize.progress_regex"),
        (lambda d: d.update(optimize={"summary_parsers": [{"name": "x", "glob": "*.csv", "kind": "xml"}]}), "optimize.summary_parsers[0].kind"),
        (lambda d: d["resources"].update(launchers={"gen_radioss": {"script": "../x.py", "core": "c"}}), "resources.launchers.gen_radioss.script"),
        (lambda d: d["resources"].update(launchers={"gen_radioss": {"script": "a.py", "core": "1bad"}}), "resources.launchers.gen_radioss.core"),
        (lambda d: d["resources"].update(launchers={"other": {"script": "a.py", "core": "c"}}), "resources.launchers.other"),
        (lambda d: d["resources"].update(pyd_dir="relative/dir"), "resources.pyd_dir"),
        (lambda d: d["resources"].update(curate_hg_tcl="/x y/a.tcl"), "resources.curate_hg_tcl"),
        (lambda d: d["resources"].update(batchrun_dir=d["storage"]["spdm_roots"][0]), "resources.batchrun_dir"),
        (lambda d: d["env_check"].update(probes={"hw": ["{edspy}"]}) if "env_check" in d else d.update(env_check={"probes": {"hw": ["{edspy}"]}}),
         "env_check.probes.hw"),
        (lambda d: d["commands"].update(hst_gen_radioss=["{hstbatch}", "{launcher}", "{cfg}"]), "commands.hst_gen_radioss"),
        (lambda d: d["commands"].update(hst_optimization=["{hstpy}", "@cmd_c", "{launcher}"]), "commands.hst_optimization"),
        (lambda d: d["commands"].update(edspy_score=None), "commands.edspy_score"),  # 1차 확정 템플릿 null 금지 유지
        (lambda d: d["altair"].update(hstpy_path="relative.bat"), "altair.hstpy_path"),
        (lambda d: d.update(profile="prod") or d["resources"].update(extract_minmax_tcl="/no/such.tcl"), "resources.extract_minmax_tcl"),
    ],
)
def test_phase2_validation_failures(p2_dict, mutate, key):
    d = copy.deepcopy(p2_dict)
    mutate(d)
    assert key in _keys(d), _keys(d)


def test_phase2_templates_nullable(p2_dict):
    from physicsai_core.commands import PHASE2_TEMPLATE_KEYS

    d = copy.deepcopy(p2_dict)
    for k in PHASE2_TEMPLATE_KEYS:
        d["commands"][k] = None
    d["resources"] = {"preview_pred_h3d_tcl": d["resources"]["preview_pred_h3d_tcl"]}
    assert _keys(d) == []


def test_derived_hstpy_and_altair_home():
    """V2-CFG-2."""
    from physicsai_core.config import AltairCfg, derived_altair_home, derived_hstpy_path

    a = AltairCfg(hyperstudy_path="C:/Altair/2026.1/hwdesktop/hst/bin/win64/hstbatch.exe")
    assert derived_hstpy_path(a) == "C:/Altair/2026.1/hwdesktop/hst/bin/win64/hstpy.bat"
    assert derived_altair_home(a) == "C:/Altair/2026.1/hwdesktop"
    b = AltairCfg(hyperstudy_path="C:\\A\\hwdesktop\\hst\\bin\\win64\\hstbatch.exe", hstpy_path="D:/x/hstpy.bat", altair_home="E:/h")
    assert derived_hstpy_path(b) == "D:/x/hstpy.bat" and derived_altair_home(b) == "E:/h"
    assert derived_hstpy_path(AltairCfg()) == "" and derived_altair_home(AltairCfg()) == ""


def test_example_yaml_has_phase2_defaults(tmp_path):
    """§8.2 예시 키 반영 + 원본 기본 템플릿."""
    import yaml

    from physicsai_core.config import load_config_dict
    from physicsai_test_support import PHASE2_COMMANDS

    data = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    data["storage"]["ai_root"] = str(tmp_path)
    lc = load_config_dict(data, environ={})
    assert lc.ok, lc.issues
    for k, v in PHASE2_COMMANDS.items():
        assert getattr(lc.settings.commands, k) == v, k
    assert lc.settings.train_data.run_dir_glob == ["approaches/doe_*/run__*", "*/approaches/doe_*/run__*"] and lc.settings.env_check.expire_s == 900
    assert set(lc.settings.resources.launchers) == {"extract_params", "gen_radioss", "optimization"}


# ---------------------------------------------------------------------------
# 명령(V2-CMD-1·2)
# ---------------------------------------------------------------------------

EXE = {"simlab_path": "C:/Altair/SimLab.bat", "hyperstudy_path": "C:/Altair/hstbatch.exe", "hw_exe_path": "C:/Altair/hw.exe",
       "hvtrans_exe_path": "C:/Altair/io/hvtrans.exe", "hstpy_path": "C:/Altair/hstpy.bat", "edspy_path": "C:/Altair/edspy.bat"}


def test_phase2_argv_golden_windows():
    """원본 인용 argv와 정확히 일치 + 키별 경로 표기('/' vs OS) + Windows argv[0] '\\'."""
    from physicsai_core.commands import render_argv
    from physicsai_test_support import PHASE2_COMMANDS as T

    env = {"SystemRoot": "C:\\Windows"}
    r = lambda k, v: render_argv(k, T[k], v, executables=EXE, is_windows=True, environ=env)  # noqa: E731
    assert r("simlab_extract_params", {"launcher": "E:/w/X/L.py", "cad_file": "E:/w/cad/a.prt", "xml_out": "E:/w/X/p.xml"}) == \
        ["C:\\Altair\\SimLab.bat", "-auto", "E:\\w\\X\\L.py", "E:\\w\\cad\\a.prt", "E:\\w\\X\\p.xml", "-nographics"]
    assert r("hst_gen_radioss", {"multi_execution": "2", "launcher": "E:\\w\\D\\L.py"}) == \
        ["C:\\Altair\\hstbatch.exe", "-multiexec", "2", "-pyfile", "E:/w/D/L.py"]
    assert r("h3d_preview", {"preview_tcl": "D:\\r\\p.tcl", "h3d": "E:\\a.h3d", "result_json": "E:\\W\\PREVIEW_H3D.json"}) == \
        ["C:\\Altair\\hw.exe", "-clientconfig", "hwpost.dat", "-b", "-tcl", "D:/r/p.tcl", "-h3d", "E:/a.h3d", "-result", "E:/W/PREVIEW_H3D.json"]
    assert r("hvtrans_curate", {"cfg": "E:/C/work/CURATE_H3D.cfg", "h3d": "E:/s/a.h3d", "out_h3d": "E:/C/CURATED_DATA/r/a.h3d"}) == \
        ["C:\\Altair\\io\\hvtrans.exe", "-c", "E:\\C\\work\\CURATE_H3D.cfg", "E:\\s\\a.h3d", "E:\\s\\a.h3d", "-o",
         "E:\\C\\CURATED_DATA\\r\\a.h3d", "-z0"]
    assert r("t01_preview", {"preview_tcl": "D:\\r\\hg.tcl", "t01": "E:\\t\\xT01", "result_json": "E:\\W\\P.json"}) == \
        ["C:\\Altair\\hw.exe", "-clientconfig", "hwplot.dat", "-b", "-c", "-tcl", "D:/r/hg.tcl", "-input", "E:/t/xT01", "-output", "E:/W/P.json"]
    assert r("t01_curve_export", {"curate_tcl": "D:\\r\\c.tcl", "config_json": "E:\\C\\work\\I.json"}) == \
        ["C:\\Altair\\hw.exe", "-clientconfig", "hwplot.dat", "-b", "-c", "-tcl", "D:/r/c.tcl", "-config", "E:/C/work/I.json"]
    assert r("hst_optimization", {"launcher": "E:/w/O/L.py"}) == \
        ["C:\\Windows\\System32\\cmd.exe", "/c", "C:\\Altair\\hstpy.bat", "E:\\w\\O\\L.py"]


def test_bat_extra_chars_rejected():
    """B24: SimLab.bat·hstpy.bat 템플릿은 ; , = ( ) 거부."""
    from physicsai_core.commands import render_argv
    from physicsai_core.errors import StepFailure
    from physicsai_test_support import PHASE2_COMMANDS as T

    for k, v in (("simlab_extract_params", {"launcher": "E:/a(1)/L.py", "cad_file": "E:/c.prt", "xml_out": "E:/x.xml"}),
                 ("hst_optimization", {"launcher": "E:/a,b/L.py"})):
        with pytest.raises(StepFailure) as ei:
            render_argv(k, T[k], v, executables=EXE, is_windows=True, environ={"SystemRoot": "C:\\Windows"})
        assert ei.value.code == "INPUT_INVALID"
    # hw.exe는 .bat이 아니므로 괄호 허용
    assert render_argv("t01_curve_export", T["t01_curve_export"], {"curate_tcl": "D:/r/c.tcl", "config_json": "E:/a(1)/I.json"},
                       executables=EXE, is_windows=False)[-1] == "E:/a(1)/I.json"
