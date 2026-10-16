"""시험 공용 가짜 도구 설치·1차 설정 dict, fixture fake_tools·fake_record·settings_dict·loaded_config, read_record."""

from __future__ import annotations

import json
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from support_base import FAKE_TOOLS, IS_WINDOWS, LIMITER

# ---------------------------------------------------------------------------
# 가짜 도구·설정
# ---------------------------------------------------------------------------


def _windows_tool_exe(src: Path, dest: Path) -> str:
    """Windows: 가짜 도구를 실행 파일(<이름>.exe)로 만든다 — pip 콘솔 스크립트와 같은 distlib 런처(+#!python + zip).
    .bat/.cmd 래퍼는 cmd.exe 재해석(B24)과 PBS 실행 파일 규칙(.bat·.cmd 금지)에 걸리므로 쓰지 않는다."""
    from pip._vendor.distlib.scripts import ScriptMaker

    staging = dest / "_src"
    staging.mkdir(parents=True, exist_ok=True)
    body = src.read_text(encoding="utf-8").split("\n", 1)[1]
    (staging / src.name).write_text("#!python\n" + body, encoding="utf-8")
    maker = ScriptMaker(str(staging), str(dest))  # source_dir 필수(None이면 경로 결합 실패)
    maker.executable = sys.executable
    maker.variants = {""}
    maker.clobber = True
    maker.add_launchers = True
    maker.make(src.name)
    exe = dest / f"{src.name}.exe"
    assert exe.is_file(), exe
    return str(exe)


_EXE_CACHE: dict[str, Path] = {}


def _install_fake_tools(dest: Path) -> dict[str, str]:
    """fake_tools를 공백 없는 폴더로 복사하고 실행 권한을 준다(Windows는 .exe 런처, 세션당 1번 만들고 복사)."""
    dest.mkdir(parents=True, exist_ok=True)
    out = {}
    for src in FAKE_TOOLS.iterdir():
        if src.is_file() and src.name.startswith("fake_"):
            if IS_WINDOWS and src.suffix != ".py":  # .py = 가짜 도구가 import하는 보조 모듈(fake_hw_capture.py) — 그대로 복사
                if src.name not in _EXE_CACHE:
                    cache = Path(tempfile.mkdtemp(prefix="physicsai-fake-exe-"))
                    _EXE_CACHE[src.name] = Path(_windows_tool_exe(src, cache))
                dst = dest / _EXE_CACHE[src.name].name
                shutil.copyfile(_EXE_CACHE[src.name], dst)
                out[src.name] = str(dst)
                continue
            dst = dest / src.name
            shutil.copyfile(src, dst)
            dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            out[src.name] = str(dst)
    return out


def make_settings_dict(base: Path, tools: dict[str, str], **overrides: Any) -> dict[str, Any]:
    ai_root = base / "ai_root"
    ai_root.mkdir(exist_ok=True)
    imports = base / "hpc_results"
    imports.mkdir(exist_ok=True)
    res = base / "resources"
    res.mkdir(exist_ok=True)
    tcl = res / "BATCHRUN_preview_pred_h3d.tcl"
    tcl.write_text("# fake tcl\n")
    inc_tcl = res / "BATCHRUN_create_include_node_elem.tcl"  # 원본 m_2 include 변환 TCL(phase3 §11.4) 자리
    inc_tcl.write_text("# fake include tcl\n")
    d: dict[str, Any] = {
        "schema_version": 1,
        "profile": "dev",
        "server": {"host": "127.0.0.1", "port": 8100},
        "auth": {"mode": "dashboard", "cache_ttl_s": 30, "timeout_s": 3},
        "storage": {"ai_root": str(ai_root), "allowed_import_roots": [str(imports)], "spdm_roots": [str(base / "spdm")]},
        "altair": {
            "version_label": "fake",
            "edspy_path": tools["fake_edspy"],
            "simlab_path": tools["fake_simlab"],
            "hw_exe_path": tools["fake_hw"],
            "hyperstudy_path": "",
            "hvtrans_exe_path": "",
        },
        "resources": {"preview_pred_h3d_tcl": str(tcl), "hypermesh_include_tcl": str(inc_tcl)},
        "worker": {
            "limiter": LIMITER,
            "max_logical_cores": 4,
            "max_memory_gb": 8,
            "heartbeat_interval_s": 0.3,
            "lease_ttl_s": 3,
            "claim_interval_s": 0.1,
            "cancel_check_interval_s": 0.2,
            "resource_sample_interval_s": 0.5,
            "state_dir": str(base / "state"),
            "gpu_query": [tools["fake_nvidia_smi"]],
            "env_passthrough": ["FAKE_*"],
        },
        "dataset": {"holdout_ratio": 0.1, "seed": 20261008, "split_group": "file", "min_h3d_files": 2, "min_psdata_bytes": 1048576},
        "training_log": {
            "log_globs": ["*.log", "*.txt"],
            "max_curve_points": 2000,
            "parsers": [{"name": "physicsai_default", "pattern": r"epoch=\s*(?P<epoch>\d+)\s*/\s*(?P<total>\d+)\s+loss=(?P<loss>[0-9.eE+\-]+)"}],
        },
        "score": {"write_files": False, "parsers": [{"name": "generic", "pattern": r"^\s*(?P<name>[A-Za-z][A-Za-z0-9_ ]{0,40}?)\s*[:=]\s*(?P<value>[-+0-9.eE]+)\s*$"}]},
        "commands": {
            "edspy_create_dataset": ["{edspy}", "--physicsai", "--create-dataset", "{out_psdata}", "--spec", "{spec_yaml}"],
            "edspy_score": ["{edspy}", "--physicsai", "--score", "{score_path}", "--model", "{model_psmdl}", "--dataset", "{eval_psdata}", "@write_files"],
            "geom_update": ["{simlab}", "-auto", "{rendered_script}", "-nographics"],
            "mesh": ["{hw}", "-clientconfig", "hwfepre.dat", "-b", "-tcl", "{include_tcl}", "{simlab_mesh}", "{mesh_inc}", "{renum_csv}"],
            "rad_assemble": None,
            "edspy_predict": ["@cmd_c", "{edspy}", "--physicsai", "--predict-write", "{pred_h3d}", "--model", "{model_psmdl}", "--input-file", "{starter}", "@hooks_arg"],
            "contour_preview": ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{preview_tcl}", "-input", "{pred_h3d_fwd}", "-output", "{preview_json_fwd}"],
            "response_extract": None,
        },
        "hpc": {"gateway": "none"},
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            d[k] = {**d[k], **v}
        else:
            d[k] = v
    return d


@pytest.fixture()
def fake_tools(tmp_path):
    return _install_fake_tools(tmp_path / "tools")


@pytest.fixture()
def fake_record(tmp_path, monkeypatch):
    rec = tmp_path / "fake_record.jsonl"
    monkeypatch.setenv("FAKE_TOOL_RECORD", str(rec))
    monkeypatch.delenv("FAKE_TOOL_MODE", raising=False)
    monkeypatch.delenv("FAKE_TOOL_DELAY_S", raising=False)
    return rec


def read_record(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


@pytest.fixture()
def settings_dict(tmp_path, fake_tools):
    return make_settings_dict(tmp_path, fake_tools)


@pytest.fixture()
def loaded_config(settings_dict):
    from physicsai_core.config import load_config_dict

    lc = load_config_dict(settings_dict, environ={})
    assert lc.ok, lc.issues
    return lc
