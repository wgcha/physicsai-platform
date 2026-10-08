"""2차 단위·정적 시험: V2-CFG-1·2, V2-CMD-1·2, V2-TD-3, V2-LCH-1, V2-SEC-1~3, V2-SPDM-3, T10b(V-SM-1 확장), V2-NT-1, V2-DEP-1."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from physicsai_test_support import REPO, SIMLAB_TPL_TEMPLATE, make_phase2_settings

CODE_DIRS = [REPO / "backend" / "physicsai_core", REPO / "backend" / "physicsai_api", REPO / "worker" / "physicsai_worker"]


def _py(dirs=CODE_DIRS):
    for d in dirs:
        yield from d.rglob("*.py")


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
    assert lc.settings.train_data.run_dir_glob == "approaches/*/run__*" and lc.settings.env_check.expire_s == 900
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


# ---------------------------------------------------------------------------
# tpl 재구현 골든(V2-TD-3)
# ---------------------------------------------------------------------------


def _original():
    spec = importlib.util.spec_from_file_location("original_create_tpl", REPO / "backend" / "tests" / "data" / "original_create_tpl.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


PARAMS = [
    {"name": "THK_1", "nominal": 3.0, "min": 2.85, "max": 3.15, "format": "%3i", "use": True},
    {"name": "RIB_H", "nominal": 12.5, "min": 11.875, "max": 13.125, "format": "%3i", "use": False},
    {"name": "N_RIB", "nominal": 4.0, "min": 2.0, "max": 8.0, "format": "%3i", "use": True},
]


@pytest.mark.parametrize("use_all", [True, False])
def test_tpl_generate_matches_original(tmp_path, use_all):
    from physicsai_core.config import TrainDataCfg
    from physicsai_core.train_tpl import TplRules, generate, num_text

    used = [p for p in PARAMS if use_all or p["use"]]
    tmpl = tmp_path / "TEMAPLATE.tpl"
    tmpl.write_text(SIMLAB_TPL_TEMPLATE, encoding="utf-8")
    out = tmp_path / "orig.tpl"
    rows = {i: {"param": p["name"], "nominal": num_text(p["nominal"]), "min": num_text(p["min"]), "max": num_text(p["max"])}
            for i, p in enumerate(used)}
    _original().update_parameter_file(str(tmpl), str(out), rows, "cad.prt")
    ours = generate(SIMLAB_TPL_TEMPLATE, used, "cad.prt", TplRules.from_settings(TrainDataCfg()))
    assert ours == out.read_text(encoding="utf-8")
    assert "OLD_PARAM" not in ours and ('RIB_H' in ours) == use_all


def test_tpl_generate_errors_and_validation():
    from physicsai_core.config import TrainDataCfg
    from physicsai_core.train_tpl import TplRules, TplTemplateInvalid, generate, validate_generated

    rules = TplRules.from_settings(TrainDataCfg())
    with pytest.raises(TplTemplateInvalid) as ei:
        generate(SIMLAB_TPL_TEMPLATE.replace("#*****", "#-----"), PARAMS[:1], "c.prt", rules)
    assert ei.value.problems[0]["code"] == "TPL_MARKER_MISSING"
    with pytest.raises(TplTemplateInvalid) as ei:
        generate(SIMLAB_TPL_TEMPLATE.replace('<Parameters Value="">', "<Parameters>"), PARAMS[:1], "c.prt", rules)
    assert ei.value.problems[0]["code"] == "TPL_ANCHOR_MISSING"
    p = [{**PARAMS[0], "format": "%8.4f"}]
    text = generate(SIMLAB_TPL_TEMPLATE, p, "c.prt", rules)
    assert 'NewValue="{var_1, %8.4f}"' in text and validate_generated(text, p) == []
    assert validate_generated(text, PARAMS) != []


def test_train_params_units(tmp_path):
    """V2-TD-1·2: XML 파싱(mm 제거·비숫자·이름 규칙·DOCTYPE), 기본 범위, 정수 형식 경고."""
    from physicsai_core import train_params as tp
    from physicsai_core.errors import StepFailure

    x = tmp_path / "p.xml"
    x.write_text("<Root><Model><Parameter><Name> A </Name><Value>-2 MM</Value></Parameter>"
                 "<Parameter><Name>B</Name><Value>abc</Value></Parameter><Parameter><Name>C</Name></Parameter></Model></Root>")
    pairs = tp.read_extracted_xml(str(x), 4096)
    assert pairs == [("A", "-2"), ("B", "abc")]
    rows = tp.build_from_extracted(pairs, 0.05, "%3i")
    assert rows[0]["min"] == -2.1 and rows[0]["max"] == -1.9 and rows[0]["valid"] and rows[0]["use"]
    assert rows[1]["nominal"] is None and not rows[1]["valid"] and not rows[1]["use"]
    with pytest.raises(StepFailure):
        tp.read_extracted_xml(str(x), 10)
    x.write_text('<!DOCTYPE r [<!ENTITY e "x">]><Root/>')
    with pytest.raises(StepFailure):
        tp.read_extracted_xml(str(x), 4096)
    assert tp.integer_format_warnings([{"name": "A", "use": True, "format": "%3i", "nominal": 3.0, "min": 2.0, "max": 4.0}]) == []
    assert tp.integer_format_warnings([{"name": "A", "use": True, "format": "%d", "nominal": 3.0, "min": 2.5, "max": 4.0}])


def test_doe_types_parse_original_json():
    from physicsai_core.doe_types import find, parse_doe_types, validate_options
    from physicsai_test_support import DOE_TYPES

    t = parse_doe_types(DOE_TYPES)
    sob = find(t, "Sobol")
    assert sob["fields"][1] == {"key": "SCRAMBLE", "label": "Scramble", "type": "bool", "default": False}
    assert validate_options(sob, {"SEQUENCE_OFFSET": 1, "SCRAMBLE": True, "SEED": 0}) == []
    assert validate_options(sob, {"SEQUENCE_OFFSET": 1, "SCRAMBLE": 1, "SEED": 0})
    assert validate_options(find(t, "FracFact"), {"RESOLUTION": "4"}) == []


# ---------------------------------------------------------------------------
# 상태 머신·알림(T10b, V2-NT-1)
# ---------------------------------------------------------------------------


def test_t10b_rules():
    from physicsai_core.state_machine import CONDITIONAL_TRANSITIONS, check_transition, hpc_terminal_transition

    assert check_transition(*CONDITIONAL_TRANSITIONS["T10b"]) == "T10"
    f = hpc_terminal_transition
    assert f("TD_SOLVE", "collect_partial", ["SUCCEEDED", "FAILED"]) == "T10b"
    assert f("TD_SOLVE", "collect_partial", ["SUCCEEDED", "LOST"]) == "T10b"
    assert f("TD_SOLVE", "fail", ["SUCCEEDED", "FAILED"]) == "T13"
    assert f("TD_SOLVE", None, ["FAILED", "FAILED"]) == "T13"
    assert f("PREDICT_VERIFY", None, ["SUCCEEDED", "FAILED"]) == "T13"
    assert f("TD_SOLVE", None, ["SUCCEEDED", "SUCCEEDED"]) == "T10"
    assert f("TD_SOLVE", None, ["SUCCEEDED", "RUNNING"]) is None


def test_notification_titles():
    from physicsai_core.db.repositories.notifications import _title
    from physicsai_core.job_types import job_label

    assert _title("JOB_SUCCEEDED", job_label("TD_DOE_GEN"), "cushion", None)[0] == "완료: DOE·Radioss 입력 생성 (cushion)"
    assert _title("JOB_FAILED", job_label("CU_H3D_CURATE"), "cushion", "EXIT_NONZERO")[0] == "실패: 큐레이션 (cushion) — EXIT_NONZERO"
    assert _title("JOB_SUCCEEDED", job_label("OPTIMIZE"), "cushion", None)[0] == "완료: 최적화 (cushion)"
    assert _title("HPC_COLLECTED", "PBS 해석", "c", None, {"submitted": 30, "failed": 1, "collected": 29})[0] == \
        "PBS 결과 회수 완료 — 30개 중 29개 회수"
    assert _title("HPC_PARTIAL_FAILED", "PBS 해석", "c", None, {"submitted": 30, "failed": 1})[0] == \
        "PBS 해석 일부 실패 — 30개 중 1개 실패, 나머지 회수 진행"
    labels = {k: job_label(k) for k in ("TD_EXTRACT_PARAMS", "TD_SOLVE", "TD_RESULT_IMPORT", "TD_RESP_EXTRACT", "CU_H3D_PREVIEW",
                                        "CU_T01_PREVIEW", "CU_T01_CURVES", "SPDM_IMPORT")}
    assert labels == {"TD_EXTRACT_PARAMS": "파라미터 추출", "TD_SOLVE": "PBS 해석", "TD_RESULT_IMPORT": "결과 가져오기",
                      "TD_RESP_EXTRACT": "run 응답 추출", "CU_H3D_PREVIEW": "h3d 미리보기", "CU_T01_PREVIEW": "T01 미리보기",
                      "CU_T01_CURVES": "곡선 추출", "SPDM_IMPORT": "SPDM 가져오기"}


# ---------------------------------------------------------------------------
# 정적(V2-SEC-1~3, V2-LCH-1, V2-SPDM-3)
# ---------------------------------------------------------------------------


def test_platform_never_imports_or_execs_launchers():
    """V2-LCH-1·V2-SEC-2: pyd·런처를 import·exec하지 않는다(importlib·runpy·exec 사용 금지)."""
    for f in _py():
        src = f.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("exec", "eval", "__import__"):
                raise AssertionError(f"{f}: {n.func.id}")
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
                assert not any(m.split(".")[0] in ("runpy", "importlib") for m in mods), f
        assert "import_module(" not in src and ".pyd\")" not in src.replace("*.pyd\")", ""), f


def test_spdm_access_only_in_spdm_module():
    """V2-SPDM-3: SPDM 경로를 읽는 코드는 spdm.py 하나(나머지는 설정 검증·기능 판정·보호 루트 등록만)."""
    allowed = {"spdm.py", "config.py", "features.py", "env_check.py", "__main__.py", "runtime.py", "main.py",
               "phase2_params.py", "inspect2.py", "spdm_import.py"}
    for f in _py():
        src = f.read_text(encoding="utf-8")
        if "spdm_roots" in src:
            assert f.name in allowed, f
    # SPDM 경로 접근은 spdm.check_spdm_path/scan/open_read/probe_roots로만
    for rel in ("backend/physicsai_api/services/phase2_params.py", "backend/physicsai_api/services/inspect2.py",
                "worker/physicsai_worker/steps/spdm_import.py", "worker/physicsai_worker/env_check.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        assert re.search(r"spdm\.(check_spdm_path|scan|open_read|probe_roots)", src), rel
    tree = ast.parse((REPO / "backend" / "physicsai_core" / "spdm.py").read_text(encoding="utf-8"))
    banned = {"link", "symlink", "replace", "copy2", "copyfile", "utime", "chmod", "rename", "makedirs", "mkdir", "remove",
              "unlink", "write", "write_text", "write_bytes"}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
            owner = getattr(getattr(n.func, "value", None), "id", None)
            if owner in ("os", "shutil", "pathlib") or name in ("write_text", "write_bytes", "copy2", "copyfile"):
                assert name not in banned, name
            if owner == "os" and name == "open":  # 읽기 전용 플래그만
                flags = ast.unparse(n.args[1])
                assert "O_RDONLY" in flags and not re.search(r"O_(WRONLY|RDWR|CREAT|TRUNC|APPEND)", flags), flags
            if owner == "os" and name == "fdopen":
                assert [a.value for a in n.args[1:2] if isinstance(a, ast.Constant)] == ["rb"]
            if isinstance(n.func, ast.Name) and name == "open":
                modes = [a.value for a in n.args[1:2] if isinstance(a, ast.Constant)]
                assert modes == ["rb"], modes


def test_no_new_delete_calls_and_no_hardcoded_paths_in_deploy():
    """V2-SEC-1·V2-SEC-3: 삭제 호출 0(1차 정적 시험과 같은 규칙) + deploy/에 Program Files·평문 비밀번호 인자 없음."""
    pat = re.compile(r"\b(os\.remove|os\.unlink|\.unlink\(|shutil\.rmtree|os\.rmdir|\.rmdir\()")
    for f in _py():
        assert not pat.search(f.read_text(encoding="utf-8")), f
    for f in (REPO / "deploy").rglob("*"):
        if f.is_file():
            t = f.read_text(encoding="utf-8")
            assert "Program Files" not in t, f
            assert not re.search(r"(?i)PASSWORD\s*=\s*['\"][^'\"$]+['\"]", t), f
            assert not re.search(r"(?i)--password[= ]", t), f  # psql 등에 비밀번호를 명령 인자로 넘기지 않는다
            assert not re.search(r"(?i)PASSWORD\s+'[A-Za-z0-9]", t), f  # SQL 평문 비밀번호 리터럴 없음


# ---------------------------------------------------------------------------
# 배포(V2-DEP-1·2)
# ---------------------------------------------------------------------------

DEPLOY = REPO / "deploy"


def test_deploy_files_and_keys():
    for n in ("deploy.example.json", "collect-offline.sh", "collect-offline.ps1", "requirements.lock", "install.ps1", "install.bat",
              "update.ps1", "update.bat", "caddy/physicsai.caddy", "uninstall-tasks.ps1"):
        assert (DEPLOY / n).is_file(), n
    cfg = json.loads((DEPLOY / "deploy.example.json").read_text(encoding="utf-8"))
    keys = {"install_root", "python_exe", "pg_bin", "pg_host", "pg_port", "db_name", "db_role", "config_path", "service_user",
            "run_mode", "backend_port", "caddy_frontend_root"}
    assert set(cfg) == keys and cfg["db_name"] == "physicsai" and cfg["db_role"] == "physicsai_app" and cfg["backend_port"] == 8100
    used = set()
    for n in ("install.ps1", "update.ps1", "uninstall-tasks.ps1"):
        used |= set(re.findall(r"\$cfg\.([A-Za-z_]+)", (DEPLOY / n).read_text(encoding="utf-8")))
    assert used <= keys and used >= keys - {"caddy_frontend_root"} | set(), used ^ keys
    inst = (DEPLOY / "install.ps1").read_text(encoding="utf-8")
    assert "ExecutionTimeLimit" in inst and "New-TimeSpan -Seconds 0" in inst and "RestartCount 999" in inst
    assert "Read-Host" in inst and "-AsSecureString" in inst and "PGPASSWORD" in inst and "IgnoreNew" in inst
    assert "physicsai_api.serve" in inst and "physicsai_worker" in inst and "/physicsai/api/health" in inst
    upd = (DEPLOY / "update.ps1").read_text(encoding="utf-8")
    assert "_backup" in upd and "Remove-Item" not in upd and "/physicsai/api/queue" in upd
    assert "Remove-Item" not in inst and "Remove-Item" not in (DEPLOY / "uninstall-tasks.ps1").read_text(encoding="utf-8")
    for b in ("install.bat", "update.bat"):
        assert "powershell -NoProfile -ExecutionPolicy Bypass -File" in (DEPLOY / b).read_text(encoding="utf-8")
    caddy = (DEPLOY / "caddy" / "physicsai.caddy").read_text(encoding="utf-8")
    assert "redir /physicsai /physicsai/ 308" in caddy and "handle /physicsai/api/*" in caddy and "reverse_proxy 127.0.0.1:{$PHYSICSAI_PORT:8100}" in caddy
    lock = (DEPLOY / "requirements.lock").read_text(encoding="utf-8")
    for pkg in ("fastapi==", "uvicorn==", "pydantic==", "sqlalchemy==", "psycopg==", "alembic==", "pyyaml==", "httpx==", "psutil=="):
        assert pkg in lock.lower(), pkg


def test_collect_offline_dry_run():
    r = subprocess.run(["bash", str(DEPLOY / "collect-offline.sh"), "--dry-run"], capture_output=True, text=True, cwd=REPO, timeout=60)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "pip download -r deploy/requirements.lock --only-binary=:all: --platform win_amd64 --python-version 3.13 -d dist/wheels" in out
    assert "pip wheel . --no-deps -w dist/wheels" in out and "npm ci" in out and "npm run build" in out
    assert "physicsai-offline-" in out and ".zip" in out


def test_powershell_syntax():
    """V2-DEP-2: pwsh가 있으면 구문 검사. 없으면 미수행(통과로 치지 않음 — skip)."""
    import os

    pwsh = os.environ.get("PHYSICSAI_PWSH") or shutil.which("pwsh")
    if not pwsh:
        pytest.skip("pwsh 없음 — PowerShell 구문 검사 미수행(사용자 E2E)")
    for f in DEPLOY.rglob("*.ps1"):
        cmd = ("$e=$null; [System.Management.Automation.Language.Parser]::ParseFile('" + str(f) +
               "', [ref]$null, [ref]$e) | Out-Null; if ($e.Count) { $e | ForEach-Object { $_.Message }; exit 1 }")
        r = subprocess.run([pwsh, "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, (f, r.stdout, r.stderr)
