"""시연 `init`: 가짜 도구 설치(.exe 런처/실행 스크립트), 가짜 반입 자원(resources.*), 설정 템플릿 채우기·검증."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path

from demo_common import (
    DELAY_PROLOGUE,
    PKG_ROOT,
    TOOLS,
    UNSAFE,
    _log,
    _write_if_missing,
    find_fake_tools,
    find_template,
    fwd,
    move_to_backup,
)

# ---------------------------------------------------------------------------
# 가짜 도구 설치
# ---------------------------------------------------------------------------


def _windows_exe(src_text: str, name: str, dest_dir: Path) -> Path:
    """pip 내장 distlib 런처로 name.exe 를 만든다(pip 콘솔 스크립트와 같은 방식: 런처 + #!python + zip(__main__.py))."""
    from pip._vendor.distlib.scripts import ScriptMaker  # pip은 venv에 항상 있다

    staging = dest_dir / "_src"
    staging.mkdir(parents=True, exist_ok=True)
    src = staging / name
    src.write_text(src_text, encoding="utf-8")
    maker = ScriptMaker(str(staging), str(dest_dir))  # source_dir 필수(None이면 경로 결합 실패)
    maker.executable = sys.executable
    maker.variants = {""}
    maker.clobber = True
    maker.add_launchers = True
    made = maker.make(name)
    exe = dest_dir / f"{name}.exe"
    if not exe.is_file():
        raise SystemExit(f"가짜 도구 실행 파일을 만들지 못했습니다: {name} ({made})")
    return exe


def install_tools(src_dir: Path, dest_dir: Path) -> dict[str, str]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for name in TOOLS:
        lines = (src_dir / name).read_text(encoding="utf-8").splitlines(keepends=True)
        body = "".join(lines[1:]) if lines and lines[0].startswith("#!") else "".join(lines)
        if os.name == "nt":
            out[name] = str(_windows_exe("#!python\n" + DELAY_PROLOGUE + body, name, dest_dir))
        else:
            dst = dest_dir / name
            dst.write_text(f"#!{sys.executable}\n" + DELAY_PROLOGUE + body, encoding="utf-8")
            dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            out[name] = str(dst)
    return out


# ---------------------------------------------------------------------------
# 가짜 원본 반입 자원(resources.*) — 실제 원본 대신 형식만 흉내
# ---------------------------------------------------------------------------

DOE_TYPES = {
    "FullFact": {"value": "TYPE_FULLFACT", "default_runs": 4, "runs_editable": False, "fields": []},
    "FracFact": {"value": "TYPE_FRACFACT", "default_runs": 4, "runs_editable": False,
                 "fields": [{"key": "RESOLUTION", "label": "Resolution", "type": "combo", "items": ["3", "4", "5"], "default": "3"}]},
    "LatinHyperCube": {"value": "TYPE_LATINHYPERCUBE", "default_runs": 5, "runs_editable": True,
                       "fields": [{"key": "RANDOM_SEED", "label": "Random Seed", "type": "int", "default": 1, "min": 0, "max": 10000}]},
    "Sobol": {"value": "TYPE_SOBOL", "default_runs": 5, "runs_editable": True, "fields": [
        {"key": "SEQUENCE_OFFSET", "label": "Sequence Offset", "type": "int", "default": 1, "min": 0, "max": 999999},
        {"key": "SCRAMBLE", "label": "Scramble", "type": "bool", "default": False},
        {"key": "SEED", "label": "Seed", "type": "int", "default": 0, "min": 0, "max": 999999}]},
}
LAUNCHER_TEXT = """# Generated launcher; the core is a compiled extension.
# 시연용 가짜 런처(원본 BATCHRUN_*.py 형식). 플랫폼은 이 파일을 실행·import하지 않는다.
import importlib
import pathlib
import sys

script_dir = pathlib.Path(__file__).resolve().parent if '__file__' in globals() else pathlib.Path.cwd().resolve()
sys.path.insert(0, str(script_dir))
importlib.import_module('{core}')
"""
LAUNCHERS = (("BATCHRUN_get_parameter_from_cad.py", "get_parameter_from_cad_core"),
             ("BATCHRUN_hst_gen_radioss_input.py", "hst_gen_radioss_core"),
             ("BATCHRUN_hst_physicsai_optimization.py", "hst_physicsai_optimization_core"))
SIMLAB_TPL_TEMPLATE = """\ufeff
{parameter(var_1, "OLD_PARAM", 1, 0, 2)}
# 시연용 tpl 템플릿(원본 TEMAPLATE_simlab_parametered_mesh.tpl 구조 흉내)
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


def make_resources(res: Path) -> None:
    br, pd = res / "BATCHRUN", res / "BUILD_PYD"
    for script, core in LAUNCHERS:
        _write_if_missing(br / script, LAUNCHER_TEXT.replace("{core}", core))
        _write_if_missing(pd / f"{core}.cp313-win_amd64.pyd", b"FAKE-PYD-NOT-LOADABLE " + core.encode())
    for n in ("BATCHRUN_create_include_node_elem.tcl", "BATCHRUN_preview_h3d.tcl", "BATCHRUN_preview_hg.tcl",
              "BATCHRUN_curate_hg.tcl", "H3D_StaticMinMax_to_CSV_FAST.tcl", "BATCHRUN_preview_pred_h3d.tcl"):
        _write_if_missing(br / n, f"# 시연용 가짜 {n}\n")
    _write_if_missing(res / "DATA" / "DATA_doe_design_type.json", json.dumps(DOE_TYPES, ensure_ascii=False, indent=1))
    _write_if_missing(res / "TEMPLATE" / "TEMAPLATE_simlab_parametered_mesh.tpl", SIMLAB_TPL_TEMPLATE)


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def render_config(template: str, values: dict[str, str]) -> str:
    lines = template.splitlines(keepends=True)
    while lines and (lines[0].startswith("#") or not lines[0].strip()):
        lines.pop(0)  # 템플릿 설명 머리말은 빼고 생성 표시로 바꾼다
    out = ("# PhysicsAI 시연 모드 설정 — deploy/demo/demo_setup.py init 이 config/platform.demo.yaml 에서 생성.\n"
           "# 시연 전용(demo.enabled=true). 운영 설정으로 쓰지 않는다.\n\n") + "".join(lines)
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", out)
    if left:
        raise SystemExit(f"설정 템플릿 자리 채우기 실패: {sorted(set(left))}")
    return out


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if UNSAFE.search(str(root)):
        raise SystemExit(f"시연 폴더 경로에 공백·특수문자를 쓸 수 없습니다: {root}")
    for d in ("ai_root", "import", "spdm", "state", "config", "logs"):
        (root / d).mkdir(parents=True, exist_ok=True)
    tools = install_tools(find_fake_tools(), root / "tools")
    make_resources(root / "resources")
    frontend = ""
    if args.frontend:
        fr = Path(args.frontend).resolve()
        if not (fr / "index.html").is_file():
            raise SystemExit(f"프런트 빌드 폴더에 index.html이 없습니다: {fr}")
        frontend = fwd(fr)
    text = render_config(find_template().read_text(encoding="utf-8"), {
        "DEMO_ROOT": fwd(root), "TOOL_EXT": ".exe" if os.name == "nt" else "", "PORT": str(int(args.port)),
        "FRONTEND_ROOT": frontend,
    })
    cfg = root / "config" / "platform.yaml"
    if cfg.is_file() and cfg.read_text(encoding="utf-8") != text:
        move_to_backup(root, cfg)
        _log(f"기존 설정을 _backup으로 옮겼습니다: {cfg}")
    if not cfg.is_file():
        cfg.write_text(text, encoding="utf-8")
    sys.path[:0] = [str(PKG_ROOT / "backend"), str(PKG_ROOT / "worker")]
    try:
        from physicsai_core.config import load_config

        lc = load_config(str(cfg), environ={})
        if not lc.ok:
            raise SystemExit("시연 설정 검증 실패: " + "; ".join(f"{i.key}: {i.message}" for i in lc.issues))
    except ImportError:
        _log("physicsai_core를 찾지 못해 설정 검증을 건너뜁니다(백엔드 기동 시 검증)")
    _log(f"설정: {cfg}")
    print(json.dumps({"config": str(cfg), "ai_root": str(root / "ai_root"), "tools": tools}, ensure_ascii=False))
    return 0
