"""시험 공용 원본 반입 자원(resources.*)·①~⑤ 명령 템플릿·PBS 설정, fixture p2_env(phase2 §16)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from support_tools import make_settings_dict

# ---------------------------------------------------------------------------
# 2차(phase2 §16): 원본 반입 자원·설정
# ---------------------------------------------------------------------------

# 원본 CONFIG/DATA/DATA_doe_design_type.json 사본
DOE_TYPES = {
    "FullFact": {"value": "TYPE_FULLFACT", "default_runs": 4, "runs_editable": False, "fields": []},
    "FracFact": {"value": "TYPE_FRACFACT", "default_runs": 4, "runs_editable": False,
                 "fields": [{"key": "RESOLUTION", "label": "Resolution", "type": "combo", "items": ["3", "4", "5"], "default": "3"}]},
    "LatinHyperCube": {"value": "TYPE_LATINHYPERCUBE", "default_runs": 7, "runs_editable": True,
                       "fields": [{"key": "RANDOM_SEED", "label": "Random Seed", "type": "int", "default": 1, "min": 0, "max": 10000}]},
    "Sobol": {"value": "TYPE_SOBOL", "default_runs": 7, "runs_editable": True, "fields": [
        {"key": "SEQUENCE_OFFSET", "label": "Sequence Offset", "type": "int", "default": 1, "min": 0, "max": 999999},
        {"key": "SCRAMBLE", "label": "Scramble", "type": "bool", "default": False},
        {"key": "SEED", "label": "Seed", "type": "int", "default": 0, "min": 0, "max": 999999}]},
}

# 원본 런처(CONFIG/BATCHRUN/BATCHRUN_*.py) 형식
LAUNCHER_TEXT = """# Generated launcher; the core is a compiled extension.
import importlib
import pathlib
import sys

script_dir = (
    pathlib.Path(__file__).resolve().parent
    if '__file__' in globals()
    else pathlib.Path.cwd().resolve()
)
sys.path.insert(0, str(script_dir))
importlib.import_module('{core}')
"""

# SimLab tpl 템플릿(원본 TEMAPLATE_simlab_parametered_mesh.tpl은 업로드본에 없음 — 구조만 흉내, U19)
SIMLAB_TPL_TEMPLATE = """\ufeff
{parameter(var_1, "OLD_PARAM", 1, 0, 2)}
# header comment
#***************************************************************
import simlab
dir_file_prt = r"C:/old/place/old_part.prt"
dir_file_export = "EPS_mesh_0000.rad"
xml = '''
<Parameters Value="">
   <paramitem Name="OLD_PARAM" NewValue="{var_1, %3i}" Value="1"/>
</Parameters>
'''


simlab.run(xml)
"""

LAUNCHERS = {
    "extract_params": ("BATCHRUN_get_parameter_from_cad.py", "get_parameter_from_cad_core"),
    "gen_radioss": ("BATCHRUN_hst_gen_radioss_input.py", "hst_gen_radioss_core"),
    "optimization": ("BATCHRUN_hst_physicsai_optimization.py", "hst_physicsai_optimization_core"),
}

PHASE2_COMMANDS = {
    "simlab_extract_params": ["{simlab}", "-auto", "{launcher}", "{cad_file}", "{xml_out}", "-nographics"],
    "hst_gen_radioss": ["{hstbatch}", "-multiexec", "{multi_execution}", "-pyfile", "{launcher}"],
    "h3d_preview": ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{preview_tcl}", "-h3d", "{h3d}", "-result", "{result_json}"],
    "hvtrans_curate": ["{hvtrans}", "-c", "{cfg}", "{h3d}", "{h3d}", "-o", "{out_h3d}", "-z0"],
    "t01_preview": ["{hw}", "-clientconfig", "hwplot.dat", "-b", "-c", "-tcl", "{preview_tcl}", "-input", "{t01}", "-output", "{result_json}"],
    "t01_curve_export": ["{hw}", "-clientconfig", "hwplot.dat", "-b", "-c", "-tcl", "{curate_tcl}", "-config", "{config_json}"],
    "hst_optimization": ["@cmd_c", "{hstpy}", "{launcher}"],
}


def make_resources(base: Path, pyd: bool = True) -> dict[str, Any]:
    """원본 반입 자원 폴더(resources.*)를 만든다. pyd=False면 BUILD_PYD를 비운다."""
    res = base / "resources"
    br, pd, dt, tp = res / "BATCHRUN", res / "BUILD_PYD", res / "DATA", res / "TEMPLATE"
    for d in (br, pd, dt, tp):
        d.mkdir(parents=True, exist_ok=True)
    for _k, (script, core) in LAUNCHERS.items():
        (br / script).write_text(LAUNCHER_TEXT.replace("{core}", core), encoding="utf-8")
        if pyd:
            (pd / f"{core}.cp313-win_amd64.pyd").write_bytes(os.urandom(64))
    for n in ("BATCHRUN_create_include_node_elem.tcl", "BATCHRUN_preview_h3d.tcl", "BATCHRUN_preview_hg.tcl",
              "BATCHRUN_curate_hg.tcl", "H3D_StaticMinMax_to_CSV_FAST.tcl"):
        (br / n).write_text(f"# fake {n}\n")
    (dt / "DATA_doe_design_type.json").write_text(json.dumps(DOE_TYPES), encoding="utf-8")
    (tp / "TEMAPLATE_simlab_parametered_mesh.tpl").write_text(SIMLAB_TPL_TEMPLATE, encoding="utf-8")
    return {
        "preview_pred_h3d_tcl": str(res / "BATCHRUN_preview_pred_h3d.tcl"),
        "batchrun_dir": str(br), "pyd_dir": str(pd),
        "simlab_tpl_template": str(tp / "TEMAPLATE_simlab_parametered_mesh.tpl"),
        "doe_design_type_json": str(dt / "DATA_doe_design_type.json"),
        "hypermesh_include_tcl": str(br / "BATCHRUN_create_include_node_elem.tcl"),
        "preview_h3d_tcl": str(br / "BATCHRUN_preview_h3d.tcl"),
        "preview_hg_tcl": str(br / "BATCHRUN_preview_hg.tcl"),
        "curate_hg_tcl": str(br / "BATCHRUN_curate_hg.tcl"),
        "extract_minmax_tcl": str(br / "H3D_StaticMinMax_to_CSV_FAST.tcl"),
    }


def pbs_command_cfg(tools: dict[str, str], ai_root: str) -> dict[str, Any]:
    return {
        "gateway": "command", "lost_after_polls": 2,
        "command": {
            "allowed_executables": [tools["fake_qsub"], tools["fake_qstat"], tools["fake_qdel"]],
            "submit": [tools["fake_qsub"], "-N", "{job_name}", "-q", "{queue}", "-l", "select=1:ncpus={ncpus}", "-l",
                       "walltime={walltime}", "-v", "INPUT_FILE={input_file},RESULT_DIR={result_dir}", "/shared/scripts/radioss_run.pbs"],
            "status": [tools["fake_qstat"], "-x", "-f", "{external_job_id}"],
            "cancel": [tools["fake_qdel"], "{external_job_id}"],
            "state_map": {"Q": "QUEUED", "R": "RUNNING", "F": "FINISHED"},
        },
        "transfer": {"path_map": [{"local": ai_root, "remote": "/shared/AI_WORK"}]},
    }


def make_phase2_settings(base: Path, tools: dict[str, str], **overrides: Any) -> dict[str, Any]:
    d = make_settings_dict(base, tools)
    (base / "spdm").mkdir(exist_ok=True)
    res = make_resources(base)
    d["resources"] = res
    d["altair"] = {**d["altair"], "hyperstudy_path": tools["fake_hstbatch"], "hvtrans_exe_path": tools["fake_hvtrans"],
                   "hstpy_path": tools["fake_hstpy"]}
    d["commands"] = {**d["commands"], **PHASE2_COMMANDS}
    d["optimize"] = {"summary_parsers": [{"name": "opt_csv", "glob": "opt_summary.csv", "kind": "csv_table"}]}
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            d[k] = {**d[k], **v}
        else:
            d[k] = v
    return d


@pytest.fixture()
def p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch):
    """2차 설정의 (client, worker 생성기, ai_root Path, LoadedConfig, settings dict) — HPC none."""
    yield from _p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, {})


def _p2_env(tmp_path, fake_tools, engine, fake_dashboard, monkeypatch, overrides):
    from fastapi.testclient import TestClient

    from physicsai_api.context import build_context
    from physicsai_api.main import create_app
    from physicsai_core.config import load_config_dict
    from physicsai_worker.runtime import Worker
    from physicsai_worker.steps import _collect

    monkeypatch.setattr(_collect, "COLLECT_STABLE_INTERVAL_S", 0.02)
    monkeypatch.setenv("FAKE_SIMLAB_STEP_S", "0.01")
    d = make_phase2_settings(tmp_path, fake_tools, **overrides)
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    ctx = build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler))
    workers: list[Any] = []

    def mk() -> Any:
        w = Worker(lc, engine)
        workers.append(w)
        return w

    with TestClient(create_app(ctx), base_url="http://127.0.0.1") as c:
        yield c, mk, Path(lc.settings.storage.ai_root), lc, d
    for w in workers:
        w.stop()
