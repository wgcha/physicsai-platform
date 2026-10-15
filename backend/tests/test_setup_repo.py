"""git 폴더 설치(deploy/setup.ps1·update-repo.ps1, GitHub #1): 설정 계획·작성(deploy/setup_config.py)과 정적 규칙.

Windows 실제 실행(가짜 대시보드·가짜 원본 앱·가짜 pyenv shim, Windows PowerShell 5.1 -File)은 CI windows 잡 "git 폴더 설치" 단계."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from physicsai_test_support import REPO

DEPLOY = REPO / "deploy"
SCRIPT = DEPLOY / "setup_config.py"
ALTAIR_REL = {
    "hyperstudy_path": "hwdesktop/hst/bin/win64/hstbatch.exe",
    "simlab_path": "SimLab/bin/win64/SimLab.bat",
    "edspy_path": "common/eds/win64/bin/win64/edspy.bat",
    "hw_exe_path": "hwdesktop/hw/bin/win64/hw.exe",
    "hvtrans_exe_path": "hwdesktop/io/result_readers/bin/win64/hvtrans.exe",
}
ORIG_FILES = [
    "CONFIG/BATCHRUN/BATCHRUN_preview_pred_h3d.tcl", "CONFIG/BATCHRUN/BATCHRUN_create_include_node_elem.tcl",
    "CONFIG/BATCHRUN/BATCHRUN_preview_h3d.tcl", "CONFIG/BATCHRUN/BATCHRUN_preview_hg.tcl", "CONFIG/BATCHRUN/BATCHRUN_curate_hg.tcl",
    "CONFIG/TEMPLATE/TEMAPLATE_simlab_parametered_mesh.tpl", "CONFIG/DATA/DATA_doe_design_type.json",
    "tools/H3D_StaticMinMax_to_CSV_FAST.tcl",   # RESOURCES.txt 위치(루트)에 없음 → 이름으로 찾음
]


def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    return p


def _fake_tree(tmp: Path, *, altair: bool = True, orig: bool = True) -> dict[str, Path]:
    pf = tmp / "pf"
    (pf / "Altair").mkdir(parents=True)
    if altair:
        for rel in ALTAIR_REL.values():
            _touch(pf / "Altair" / "2026.1" / rel)
        _touch(pf / "Altair" / "2025" / ALTAIR_REL["hw_exe_path"])          # 예전 버전(일부만) — 고르면 안 됨
        (pf / "Altair" / "2027.0").mkdir()                                  # 실행 파일 없는 새 버전 폴더 — 고르면 안 됨
    o = tmp / "orig"
    if orig:
        for rel in ORIG_FILES:
            _touch(o / rel)
        (o / "BUILD_PYD").mkdir(parents=True)
    return {"pf": pf, "orig": o, "rt": tmp / "rt", "data": tmp / "data"}


def _inputs(t: dict[str, Path], **over) -> dict:
    rt = t["rt"]
    d = {
        "repo_root": str(REPO), "runtime_dir": str(rt), "stamp": "20261014T010203Z",
        "deploy_defaults": {
            "install_mode": "repo", "repo_root": str(REPO), "install_root": str(rt), "dashboard_root": "", "python_exe": "py",
            "pg_bin": "pgbin", "pg_host": "127.0.0.1", "pg_port": 5434, "db_name": "physicsai", "db_role": "physicsai_app",
            "config_path": str(rt / "config" / "platform.yaml"), "service_user": "CORP\\me", "run_mode": "Interactive",
            "caddy_frontend_root": str(rt / "frontend"), "ai_root": str(t["data"]), "original_app_root": str(t["orig"]), "altair_root": "",
        },
        "deploy_explicit": {}, "legacy_config": "", "program_files_dirs": [str(t["pf"])],
    }
    d.update(over)
    return d


def _run(tmp: Path, t: dict[str, Path], inputs: dict, action: str = "write") -> dict:
    f = tmp / "in.json"
    f.write_text(json.dumps(inputs, ensure_ascii=False), encoding="utf-8")
    out = tmp / "out.json"
    sep = os.pathsep
    # Program Files 폴더는 입력으로 넘긴다(setup.ps1과 같음). Windows는 자식 프로세스의 ProgramFiles 환경변수를 시스템 값으로 다시 정하므로
    # 환경변수로 가짜 폴더를 넘기면 Windows에서만 못 찾는다(CI run 38558961016).
    env = {**os.environ, "PYTHONPATH": sep.join(str(REPO / p) for p in ("backend", "worker", "packages/simdash_adapters/src"))}
    r = subprocess.run([sys.executable, str(SCRIPT), action, "--inputs", str(f), "--out", str(out)],
                       capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def _cfg(t: dict[str, Path]) -> dict:
    return yaml.safe_load((t["rt"] / "config" / "platform.yaml").read_text(encoding="utf-8"))


def test_setup_config_generates_prod_config(tmp_path):
    t = _fake_tree(tmp_path)
    res = _run(tmp_path, t, _inputs(t))
    assert res["config_source"] == "example" and res["warnings"] == []
    assert res["write"]["validation"] == {"ok": True, "issues": [], "warnings": []}, res["write"]["validation"]
    assert t["data"].is_dir()                                              # AI 루트 폴더 생성
    for sub in ("config", "logs", "state"):
        assert (t["rt"] / sub).is_dir()
    c = _cfg(t)
    fwd = lambda p: str(p).replace("\\", "/")  # noqa: E731
    assert c["profile"] == "prod" and c["server"]["port"] == 8100 and c["hpc"]["gateway"] == "none"
    assert c["storage"]["ai_root"] == fwd(t["data"])
    assert c["altair"]["version_label"] == "2026.1"
    for k, rel in ALTAIR_REL.items():
        assert c["altair"][k] == fwd(t["pf"] / "Altair" / "2026.1" / rel), k
    assert c["resources"]["batchrun_dir"] == fwd(t["orig"] / "CONFIG" / "BATCHRUN")
    assert c["resources"]["pyd_dir"] == fwd(t["orig"] / "BUILD_PYD")
    assert c["resources"]["extract_minmax_tcl"] == fwd(t["orig"] / "tools" / "H3D_StaticMinMax_to_CSV_FAST.tcl")
    assert "이름으로 찾음" in res["resources"]["extract_minmax_tcl"]["note"]
    assert all(v["found"] for v in res["resources"].values())
    assert c["worker"]["max_logical_cores"] == 32 and c["worker"]["priority"] == "below_normal" and c["demo"]["enabled"] is False
    assert c["server"]["frontend_root"] == fwd(t["rt"] / "frontend")      # 백엔드가 /physicsai/ 직접 서빙(배치 폴더)
    text = (t["rt"] / "config" / "platform.yaml").read_text(encoding="utf-8")
    assert text.startswith("# PhysicsAI 설정 — deploy/setup.ps1") and "# dev | prod" in text   # 예시 주석 유지
    altair_block = text.split("\naltair:")[1].split("\nresources:")[0]
    assert "Program Files" not in altair_block and "D:/physicsai/resources" not in text and "E:/shared/AI_WORK\"" not in text.split("path_map")[0]
    dj = json.loads((t["rt"] / "deploy.json").read_text(encoding="utf-8"))
    assert dj["install_mode"] == "repo" and dj["pg_port"] == 5434 and dj["config_path"].endswith("platform.yaml")
    assert list(dj)[:3] == ["install_mode", "repo_root", "install_root"]

    # 다시 실행: 바꾸는 것이 없다(파일·백업 그대로)
    before = {p: p.read_bytes() for p in (t["rt"] / "config" / "platform.yaml", t["rt"] / "deploy.json")}
    res2 = _run(tmp_path, t, _inputs(t))
    assert res2["config_source"] == "existing" and not res2["config_changed"] and not res2["deploy_changed"]
    assert res2["write"]["written"] == [] and res2["write"]["backups"] == []
    assert {p: p.read_bytes() for p in before} == before
    assert not (t["rt"] / "_backup").exists()


def test_setup_config_preserves_user_values_and_fills_missing(tmp_path):
    t = _fake_tree(tmp_path)
    _run(tmp_path, t, _inputs(t))
    cfg_path = t["rt"] / "config" / "platform.yaml"
    original = cfg_path.read_text(encoding="utf-8")
    edited = original.replace("max_logical_cores: 32", "max_logical_cores: 7")
    edited = re.sub(r"(?m)^  gateway: none.*\n", "", edited)                         # 키 삭제 → 보충
    edited = re.sub(r'(?m)^(  preview_hg_tcl: )".*?"', r'\1""', edited)               # 빈 값 → 채움
    edited = re.sub(r'(?m)^(  ai_root: )".*?"', r'\1"' + str(tmp_path / "mine").replace("\\", "/") + '"', edited)   # 사용자 값 → 유지
    (tmp_path / "mine").mkdir()
    cfg_path.write_text(edited, encoding="utf-8")
    dj_path = t["rt"] / "deploy.json"
    dj = json.loads(dj_path.read_text(encoding="utf-8"))
    dj["note"] = "사용자 메모"
    dj.pop("altair_root")
    dj_path.write_text(json.dumps(dj, ensure_ascii=False), encoding="utf-8")

    res = _run(tmp_path, t, _inputs(t, deploy_explicit={"ai_root": str(tmp_path / "other")}))
    c = _cfg(t)
    assert c["worker"]["max_logical_cores"] == 7
    assert c["hpc"]["gateway"] == "none" and "gateway: none  # setup.ps1이 보충" in cfg_path.read_text(encoding="utf-8")
    assert c["resources"]["preview_hg_tcl"].endswith("CONFIG/BATCHRUN/BATCHRUN_preview_hg.tcl")
    assert c["storage"]["ai_root"] == str(tmp_path / "mine").replace("\\", "/")        # 설정 파일 값 유지(인자로 바꾸지 않음)
    row = next(r for r in res["config_rows"] if r["key"] == "storage.ai_root")
    assert "설정 파일 값" in row["action"]
    assert sorted(res["config_changed_keys"]) == ["hpc.gateway", "resources.preview_hg_tcl"]
    # 바뀌기 전 파일은 _backup\<stamp>로 복사
    bak = t["rt"] / "_backup" / "20261014T010203Z"
    assert (bak / "platform.yaml").read_text(encoding="utf-8") == edited
    # deploy.json: 사용자 키 유지, 빠진 키 보충, 명시 인자는 반영
    dj2 = json.loads(dj_path.read_text(encoding="utf-8"))
    assert dj2["note"] == "사용자 메모" and "altair_root" in dj2 and dj2["ai_root"] == str(tmp_path / "other")
    assert res["deploy_added"] == ["altair_root"] and res["deploy_overridden"] == ["ai_root"]
    assert (bak / "deploy.json").is_file()


def test_setup_config_frontend_root_merge(tmp_path):
    """server.frontend_root: 새 파일 = 배치 폴더, 키 없음 = 보충(주석 표시), 사용자 값(null·다른 경로) = 유지. 배치 폴더가 아직 없어도 검증 경고 없음."""
    t = _fake_tree(tmp_path)
    fwd = lambda p: str(p).replace("\\", "/")  # noqa: E731
    res = _run(tmp_path, t, _inputs(t))
    assert not (t["rt"] / "frontend").exists() and res["write"]["validation"]["ok"] is True
    assert res["write"]["validation"]["warnings"] == []
    row = next(r for r in res["config_rows"] if r["key"] == "server.frontend_root")
    assert row["action"] == "새로 씀" and row["value"] == fwd(t["rt"] / "frontend")
    cfg_path = t["rt"] / "config" / "platform.yaml"
    text = cfg_path.read_text(encoding="utf-8")
    assert re.search(r"(?m)^  frontend_root: .*# 백엔드가 /physicsai/ 아래에", text)          # 예시 주석 유지

    # 이전 버전 설정(키 없음) → 보충
    cfg_path.write_text(re.sub(r"(?m)^  frontend_root: .*\n", "", text), encoding="utf-8")
    res = _run(tmp_path, t, _inputs(t))
    assert res["config_changed_keys"] == ["server.frontend_root"]
    assert _cfg(t)["server"]["frontend_root"] == fwd(t["rt"] / "frontend")
    assert "frontend_root: " in cfg_path.read_text(encoding="utf-8") and "# setup.ps1이 보충" in cfg_path.read_text(encoding="utf-8")

    # 사용자가 null(Caddy 등 외부 서빙) 또는 다른 경로로 바꾼 값은 유지
    for user_value, expect in (("null", None), ('"E:/web/physicsai"', "E:/web/physicsai")):
        cur = cfg_path.read_text(encoding="utf-8")
        cfg_path.write_text(re.sub(r"(?m)^(  frontend_root: )\S+", lambda m: m.group(1) + user_value, cur), encoding="utf-8")
        res = _run(tmp_path, t, _inputs(t))
        assert "server.frontend_root" not in res["config_changed_keys"] and not res["config_changed"]
        assert _cfg(t)["server"]["frontend_root"] == expect
        row = next(r for r in res["config_rows"] if r["key"] == "server.frontend_root")
        assert row["action"].startswith("유지")

    # deploy.json의 caddy_frontend_root(사용자 지정 배치 폴더)를 따른다
    t2 = _fake_tree(tmp_path / "b")
    inp = _inputs(t2)
    inp["deploy_defaults"]["caddy_frontend_root"] = str(tmp_path / "b" / "web")
    _run(tmp_path / "b", t2, inp)
    assert _cfg(t2)["server"]["frontend_root"] == fwd(tmp_path / "b" / "web")


def test_setup_config_inherits_legacy_bundle_config(tmp_path):
    t = _fake_tree(tmp_path)
    legacy = tmp_path / "old" / "config" / "platform.yaml"
    legacy.parent.mkdir(parents=True)
    (tmp_path / "olddata").mkdir()
    legacy_text = ("# 묶음 설치 설정\nschema_version: 1\nprofile: prod\nstorage:\n  ai_root: \"" + str(tmp_path / "olddata").replace("\\", "/") +
                   "\"\nworker:\n  max_memory_gb: 12\n")
    legacy.write_text(legacy_text, encoding="utf-8")
    res = _run(tmp_path, t, _inputs(t, legacy_config=str(legacy)))
    assert res["config_source"] == "legacy" and res["config_changed"]
    c = _cfg(t)
    assert c["storage"]["ai_root"] == str(tmp_path / "olddata").replace("\\", "/") and c["worker"]["max_memory_gb"] == 12
    assert c["resources"]["batchrun_dir"].endswith("CONFIG/BATCHRUN") and c["altair"]["version_label"] == "2026.1"   # 빠진 키 보충
    assert c["hpc"]["gateway"] == "none"
    assert (t["rt"] / "config" / "platform.yaml").read_text(encoding="utf-8").startswith("# 묶음 설치 설정")
    assert legacy.read_text(encoding="utf-8") == legacy_text                       # 원본은 그대로


def test_setup_config_program_files_from_inputs_not_env(tmp_path, monkeypatch):
    """Program Files 폴더는 입력(program_files_dirs)이 환경변수보다 우선 — 환경변수 쪽 미끼(더 새 버전 2099)를 고르면 안 된다.
    PowerShell 5.1 ConvertTo-Json이 원소 1개 배열을 문자열로 내도 같게 동작. 입력이 없을 때만 환경변수(이름 대소문자 무시)."""
    t = _fake_tree(tmp_path)
    decoy = tmp_path / "decoy"
    for rel in ALTAIR_REL.values():
        _touch(decoy / "Altair" / "2099" / rel)
    monkeypatch.setenv("ProgramFiles", str(decoy))
    for given in ([str(t["pf"])], str(t["pf"])):
        res = _run(tmp_path, t, _inputs(t, program_files_dirs=given), action="plan")
        assert res["altair"]["version_label"] == "2026.1" and res["altair"]["found"] == len(ALTAIR_REL), res["altair"]
    m = _module()
    assert m.program_files_dirs([str(t["pf"]), ""]) == [str(t["pf"])] and m.program_files_dirs([]) == []
    monkeypatch.delenv("ProgramFiles")
    monkeypatch.delenv("ProgramW6432", raising=False)
    monkeypatch.setenv("PROGRAMFILES", str(t["pf"]))                                  # Windows os.environ 키 표기(대문자)
    assert m.program_files_dirs(None) == [str(t["pf"])]
    alt = m.detect_altair("", m.altair_layout(yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))))
    assert alt["version_label"] == "2026.1" and alt["found"] == len(ALTAIR_REL)


def test_setup_config_altair_names_case_insensitive(tmp_path):
    """Windows 파일 이름 규칙: 실제 폴더·파일 대소문자가 예시 배치(SimLab/…/SimLab.bat, hw.exe)와 달라도 찾는다(Linux에서도 같은 규칙)."""
    t = _fake_tree(tmp_path, altair=False)
    root = tmp_path / "alt"
    for rel in ALTAIR_REL.values():
        _touch(root / "2026.1" / rel.lower().replace("hw.exe", "HW.EXE"))
    inp = _inputs(t)
    inp["deploy_defaults"]["altair_root"] = str(root)
    res = _run(tmp_path, t, inp, action="plan")
    assert res["altair"]["found"] == len(ALTAIR_REL) and res["warnings"] == [], res
    assert res["altair"]["paths"]["simlab_path"].endswith("2026.1/simlab/bin/win64/simlab.bat") or sys.platform == "win32"
    assert Path(res["altair"]["paths"]["hw_exe_path"]).is_file()


def test_setup_config_legacy_without_altair_keeps_altair_section(tmp_path):
    """이어받은 설정에 altair 절이 없고 Altair도 못 찾으면: altair 키를 빈 값으로 보충(절은 항상 존재) + 경고."""
    t = _fake_tree(tmp_path, altair=False)
    legacy = tmp_path / "old" / "platform.yaml"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("schema_version: 1\nprofile: prod\nworker:\n  max_memory_gb: 12\n", encoding="utf-8")
    res = _run(tmp_path, t, _inputs(t, legacy_config=str(legacy)))
    c = _cfg(t)
    assert c["altair"]["version_label"] == "" and all(c["altair"][k] == "" for k in ALTAIR_REL)
    assert {"altair.version_label", *(f"altair.{k}" for k in ALTAIR_REL)} <= set(res["config_changed_keys"])
    assert any("Altair 실행 파일을 찾지 못했습니다" in w for w in res["warnings"])
    assert not any(i.startswith("altair.") for i in res["write"]["validation"]["issues"])
    # 다시 실행: 빈 값 그대로(바꾸는 것 없음), Altair를 설치한 뒤 다시 실행하면 빈 값을 채운다
    res2 = _run(tmp_path, t, _inputs(t))
    assert not res2["config_changed"]
    for rel in ALTAIR_REL.values():
        _touch(t["pf"] / "Altair" / "2026.1" / rel)
    res3 = _run(tmp_path, t, _inputs(t))
    assert res3["config_changed"] and _cfg(t)["altair"]["version_label"] == "2026.1" and res3["warnings"] == []


def test_setup_config_without_original_app_and_altair(tmp_path):
    t = _fake_tree(tmp_path, altair=False, orig=False)
    inp = _inputs(t)
    inp["deploy_defaults"]["original_app_root"] = ""
    res = _run(tmp_path, t, inp)
    c = _cfg(t)
    assert all(v == "" for v in c["resources"].values() if isinstance(v, str))
    assert all(c["altair"][k] == "" for k in ALTAIR_REL)
    w = " ".join(res["warnings"])
    assert "Altair 실행 파일을 찾지 못했습니다" in w and "preview_pred_h3d_tcl" in w and "-AltairRoot" in w
    v = res["write"]["validation"]
    assert v["ok"] is False and any(i.startswith("resources.preview_pred_h3d_tcl") for i in v["issues"])
    assert not any(i.startswith("altair.") for i in v["issues"])                 # 빈 Altair 경로는 오류가 아님(기능 비활성)


def test_setup_config_explicit_altair_root_plan_only(tmp_path):
    t = _fake_tree(tmp_path, altair=False)
    good = tmp_path / "altair_ok"
    for rel in ALTAIR_REL.values():
        _touch(good / "2026.1" / rel)
    inp = _inputs(t)
    inp["deploy_defaults"]["altair_root"] = str(good)
    res = _run(tmp_path, t, inp, action="plan")
    assert res["altair"]["version_label"] == "2026.1" and res["altair"]["root"].endswith("altair_ok/2026.1")
    assert not (t["rt"] / "config" / "platform.yaml").exists()                      # plan은 파일을 쓰지 않는다
    assert "config_text" not in res


def _module():
    # deploy/ 아래에 __pycache__를 만들지 않는다(정적 시험이 deploy/ 파일을 텍스트로 읽음)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("setup_config_under_test", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


def test_setup_yaml_editing_keeps_comments_crlf_and_detects_unsupported_layout():
    m = _module()
    text = "a: 1\r\nworker:\r\n  # 주석\r\n  priority: normal   # 끝 주석\r\nstorage:\r\n  ai_root: \"x\"\r\n"
    out = m.set_yaml_value(text, ("worker", "priority"), "idle")
    assert out == text.replace("priority: normal", "priority: idle")
    out = m.set_yaml_value(out, ("hpc", "gateway"), "none", "보충")
    assert out.endswith("hpc:\r\n  gateway: none  # 보충\r\n") and "\n" not in out.replace("\r\n", "")
    out = m.set_yaml_value(out, ("storage", "spdm"), "E:/a b")
    assert yaml.safe_load(out)["storage"] == {"spdm": "E:/a b", "ai_root": "x"}
    assert m.literal("prod") == "prod" and m.literal("yes") == '"yes"' and m.literal("C:/x") == '"C:/x"' and m.literal(8100) == "8100"
    # 흐름 표기(worker: {...})처럼 예상과 다른 형식은 고치지 않고 안내만(원래 내용 그대로)
    table = m.resource_table(DEPLOY / "RESOURCES.txt")
    assert table["batchrun_dir"] == "CONFIG/BATCHRUN" and table["preview_pred_h3d_tcl"] == "CONFIG/BATCHRUN/BATCHRUN_preview_pred_h3d.tcl"
    assert len(table) == 10
    example = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    assert m.altair_layout(example) == ALTAIR_REL


def test_setup_config_flow_style_section_is_left_untouched(tmp_path):
    t = _fake_tree(tmp_path)
    cfg = t["rt"] / "config" / "platform.yaml"
    cfg.parent.mkdir(parents=True)
    (tmp_path / "d2").mkdir()
    body = ("schema_version: 1\nprofile: prod\nstorage: {ai_root: \"" + str(tmp_path / "d2").replace("\\", "/") + "\"}\n"
            "worker: {max_logical_cores: 4}\n")
    cfg.write_text(body, encoding="utf-8")
    res = _run(tmp_path, t, _inputs(t))
    assert any("자동으로 보충하지 못했습니다" in w for w in res["warnings"])
    assert cfg.read_text(encoding="utf-8") == body and res["write"]["backups"] == []


def test_setup_scripts_static():
    """setup.ps1·update-repo.ps1: 5.1 -File 실행 규칙, 공용 함수 재사용(코드 중복 없음), 삭제 없음, 런타임 폴더 git 제외."""
    common = (DEPLOY / "install-common.ps1").read_text(encoding="utf-8-sig")
    for n in ("setup.ps1", "update-repo.ps1"):
        t = (DEPLOY / n).read_text(encoding="utf-8-sig")
        param = t[t.index("param("): t.index(")\n$ErrorActionPreference")]
        assert "$PSScriptRoot" not in param, n                  # PS 5.1 -File: param 기본값에서 $PSScriptRoot가 빔(이슈 #1)
        assert "Remove-Item" not in t and "Program Files" not in t, n
        assert "Assert-PhysicsAIAdmin" in t and "Install-PhysicsAIRepoPackages" in t and "Invoke-PhysicsAIFrontendBuild" in t, n
        assert "Invoke-PhysicsAIMigration" in t and "Invoke-PhysicsAISetupConfig" in t, n
        assert "New-ScheduledTaskSettingsSet" not in t and "CREATE ROLE" not in t, n     # 공용 함수만
        assert "powershell -NoProfile -ExecutionPolicy Bypass -File .\\deploy\\" in t, n
    setup = (DEPLOY / "setup.ps1").read_text(encoding="utf-8-sig")
    for s in ("Initialize-PhysicsAIDatabase", "-ReuseExisting", "Set-PhysicsAIMachineEnv", "Register-PhysicsAITasks", "Start-PhysicsAITasksAndWait",
              "Export-PhysicsAITasks", "SIMDASH_PHYSICSAI_ENABLED=true", "physicsai.caddy", "'simdashboard'", "'physicsai-data'",
              "[switch]$NonInteractive", "[switch]$PasswordsFromEnv", "Read-Host '이대로 설치할까요? (Y/N)'", "Assert-PhysicsAINoActiveJobs"):
        assert s in setup, s
    upd = (DEPLOY / "update-repo.ps1").read_text(encoding="utf-8-sig")
    # 접속 연결 안내(대시보드 Vite 프록시 + 백엔드 정적 서빙, Caddy는 대안)는 공용 함수 하나로
    for n, t in (("setup.ps1", setup), ("update-repo.ps1", upd)):
        assert "Write-PhysicsAIConnectGuide -Port $port" in t and "PHYSICSAI_FRONTEND_ROOT=$(" not in t, n
    guide = common[common.index("function Write-PhysicsAIConnectGuide"):]
    for s in ("VITE_PHYSICSAI_TARGET=$target", "SIMDASH_PHYSICSAI_ENABLED=true", "http://<대시보드 주소>/physicsai/", "'physicsai.caddy'",
              "server.frontend_root"):
        assert s in guide, s
    assert "Set-Content" not in guide and "Add-Content" not in guide and "Out-File" not in guide   # 대시보드 .env는 읽기만
    assert upd.index("Assert-PhysicsAINoActiveJobs") < upd.index("Stop-PhysicsAITasks") < upd.index("Install-PhysicsAIRepoPackages")
    assert upd.index("Install-PhysicsAIRepoPackages") < upd.index("Invoke-PhysicsAIFrontendBuild") < upd.index("Invoke-PhysicsAIMigration")
    assert upd.index("Invoke-PhysicsAIMigration") < upd.index("Start-PhysicsAITasksAndWait")
    assert "Remove-Item" not in common and "--no-deps', '--force-reinstall'" in common and "'-r', (Join-Path $RepoRoot 'deploy\\requirements.lock')" in common
    assert "-e'" not in common and "'--editable'" not in common                       # 일반 설치(editable 아님)
    gi = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".runtime/" in gi and "/build/" in gi
    src = SCRIPT.read_text(encoding="utf-8")
    assert "Program Files" not in src and "sys.dont_write_bytecode = True" in src


def _pwsh() -> str | None:
    return os.environ.get("PHYSICSAI_PWSH") or shutil.which("pwsh")


@pytest.mark.posix  # Windows는 CI windows 잡 "git 폴더 설치"에서 실제 실행
def test_install_common_helpers(tmp_path):
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("pwsh 없음 — install-common.ps1 실행 시험 미수행(CI linux·windows 잡은 pwsh 있음)")
    common = (DEPLOY / "install-common.ps1").as_posix()
    body = (
        f". '{common}'; "
        "$p = ConvertFrom-PhysicsAIDbUrl 'postgresql+psycopg://physicsai_app:a%40b%3Ac@127.0.0.1:5434/physicsai'; "
        "$p.User; $p.Password; $p.Host; $p.Port; $p.Db; "
        "[string](ConvertFrom-PhysicsAIDbUrl 'nonsense'); "
        f"Test-PhysicsAIUnderPath '{tmp_path.as_posix()}/rt/config/x.yaml' '{tmp_path.as_posix()}/rt'; "
        f"Test-PhysicsAIUnderPath '{tmp_path.as_posix()}/rt2/x' '{tmp_path.as_posix()}/rt'; "
        "$PhysicsAITag = 'T'; Write-PhysicsAIStep 'hello'; "
        "try { Read-PhysicsAISecret 'pw' 'PHYSICSAI_X_NOT_SET' -NonInteractive } catch { $_.Exception.Message }"
    )
    r = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", body], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    assert lines[:5] == ["physicsai_app", "a@b:c", "127.0.0.1", "5434", "physicsai"]
    assert lines[5] == "" and lines[6] == "True" and lines[7] == "False" and lines[8] == "[T] hello"
    assert "-PasswordsFromEnv" in lines[9]


@pytest.mark.posix  # Windows는 CI windows 잡 "git 폴더 설치"에서 실제 실행
def test_install_common_connect_guide(tmp_path):
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("pwsh 없음 — install-common.ps1 실행 시험 미수행(CI linux·windows 잡은 pwsh 있음)")
    common = (DEPLOY / "install-common.ps1").as_posix()
    dash = tmp_path / "dash"
    dash.mkdir()

    def run(env_text: str | None) -> str:
        env = dash / ".env"
        if env_text is None:
            env.unlink(missing_ok=True)
        else:
            env.write_text(env_text, encoding="utf-8")
        body = (f". '{common}'; $PhysicsAITag = 'T'; "
                f"Write-PhysicsAIConnectGuide -Port 8123 -DashboardRoot '{dash.as_posix()}' -FrontendRoot 'D:/g/.runtime/frontend' -RepoRoot 'D:/g'")
        r = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", body], capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout

    out = run(None)
    assert "VITE_PHYSICSAI_TARGET=http://127.0.0.1:8123 , SIMDASH_PHYSICSAI_ENABLED=true 를 넣고 대시보드를 다시 시작하세요" in out
    assert "http://<대시보드 주소>/physicsai/" in out and "http://127.0.0.1:8123/physicsai/api/health" in out
    assert "PHYSICSAI_PORT=8123, PHYSICSAI_FRONTEND_ROOT=D:/g/.runtime/frontend" in out and "physicsai.caddy" in out
    assert "이미 들어 있음" not in out
    out = run('SIMDASH_PHYSICSAI_ENABLED=true\nVITE_PHYSICSAI_TARGET="http://127.0.0.1:8123"\n')
    assert "이미 들어 있음" in out
    out = run("SIMDASH_PHYSICSAI_ENABLED=true\nVITE_PHYSICSAI_TARGET=http://127.0.0.1:8100\n")   # 포트가 다르면 다시 안내
    assert "이미 들어 있음" not in out
    assert (dash / ".env").read_text(encoding="utf-8").startswith("SIMDASH")                       # 읽기만
