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
        # phase3 D3-41: 관리자 권한 확인 없음 / D3-40: 프런트는 저장소 빌드본 우선(공용 함수 하나)
        assert "Assert-PhysicsAIAdmin" not in t and "IsInRole" not in t and "Install-PhysicsAIRepoPackages" in t, n
        assert "Install-PhysicsAIFrontendFromRepo -RepoRoot $repo" in t and "Select-PhysicsAINode" not in t, n
        assert "Invoke-PhysicsAIMigration" in t and "Invoke-PhysicsAISetupConfig" in t, n
        assert "New-ScheduledTaskSettingsSet" not in t and "CREATE ROLE" not in t, n     # 공용 함수만
        assert "powershell -NoProfile -ExecutionPolicy Bypass -File" in t and "관리자 권한 Windows PowerShell" not in t, n
    setup = (DEPLOY / "setup.ps1").read_text(encoding="utf-8-sig")
    for s in ("Initialize-PhysicsAIDatabase", "-ReuseExisting -ExistingUrl $existingUrl", "Write-PhysicsAIRuntimeSecret -RuntimeDir $rt",
              "Register-PhysicsAITasks", "-RuntimeDir $rt -ConfigPath $d.config_path", "Start-PhysicsAITasksAndWait",
              "Export-PhysicsAITasks", "SIMDASH_PHYSICSAI_ENABLED=true", "physicsai.caddy", "'simdashboard'", "'physicsai-data'",
              "[switch]$NonInteractive", "[switch]$PasswordsFromEnv", "Read-Host '이대로 설치할까요? (Y/N)'", "Assert-PhysicsAINoActiveJobs"):
        assert s in setup, s
    upd = (DEPLOY / "update-repo.ps1").read_text(encoding="utf-8-sig")
    # 접속 연결 안내(대시보드 Vite 프록시 + 백엔드 정적 서빙, Caddy는 대안)는 공용 함수 하나로
    assert "Write-PhysicsAIConnectGuide -Port $port" in setup and "PHYSICSAI_FRONTEND_ROOT=$(" not in setup
    # phase3 D3-39: 업데이트는 인자·질문 없이 한 번(값은 deploy.json), 끝은 성공/실패 + 접속 주소 한 줄
    assert "Get-PhysicsAIAccessUrl -Dash $dash" in upd and '"업데이트 성공 — 접속: $accessUrl"' in upd and "Write-PhysicsAIConnectGuide" not in upd
    for n in ("update-repo.ps1", "update.ps1"):
        assert "Read-Host" not in (DEPLOY / n).read_text(encoding="utf-8-sig"), n
    jobs = common[common.index("function Get-PhysicsAIActiveJobCount"):common.index("# ---- git 폴더 설치")]
    assert "Read-Host" not in jobs and "Invoke-LoopbackRest" not in jobs and "NonInteractive" not in jobs and "FROM jobs WHERE state IN" in jobs
    # npm은 콘솔 그대로(파이프·리다이렉트 없음), 프런트 빌드 결과를 변수에 받지 않음(받으면 npm 출력이 파이프)
    nsel = (DEPLOY / "node-select.ps1").read_text(encoding="utf-8-sig")
    npm_fn = nsel[nsel.index("function Invoke-PhysicsAINpm"):nsel.index("function Invoke-PhysicsAIFrontendBuild")]
    assert "& $Npm @Arguments; $rc = $LASTEXITCODE" in npm_fn and "2>" not in npm_fn.split("#>")[1] and "|" not in npm_fn.split("#>")[1]
    build_fn = nsel[nsel.index("function Invoke-PhysicsAIFrontendBuild"):]
    assert "Invoke-PhysicsAINative" not in build_fn and "return" not in build_fn.split("#>")[1]
    for n in ("setup.ps1", "update-repo.ps1", "collect-offline.ps1"):
        t = (DEPLOY / n).read_text(encoding="utf-8-sig")
        assert "= Invoke-PhysicsAIFrontendBuild" not in t and "= Install-PhysicsAIFrontendFromRepo" not in t and "Invoke-Native 'npm" not in t, n
    assert "Invoke-PhysicsAINpm -Npm $npm.Source -Arguments @('run', 'build')" in (DEPLOY / "collect-offline.ps1").read_text(encoding="utf-8-sig")
    # migration 전 실패면 이전 프런트 복구 + 작업 재시작(표식은 Publish 뒤·migration 바로 앞에서만 켬)
    assert upd.index("$migrationStarted = $false") < upd.index("\ntry {") < upd.index("Assert-PhysicsAINoActiveJobs")
    assert upd.index("Install-PhysicsAIFrontendFromRepo") < upd.index("$migrationStarted = $true") < upd.index("Invoke-PhysicsAIMigration -VenvPy")
    catch = upd[upd.index("} catch {"):]
    assert "elseif (-not $migrationStarted)" in catch and "Restore-PhysicsAIAfterFailedUpdate" in catch and "-NoStart:$NoStart" in catch and "exit 1" in catch
    guide = common[common.index("function Write-PhysicsAIConnectGuide"):]
    for s in ("VITE_PHYSICSAI_TARGET=$target", "SIMDASH_PHYSICSAI_ENABLED=true", "http://<대시보드 주소>/physicsai/", "'physicsai.caddy'",
              "server.frontend_root"):
        assert s in guide, s
    assert "Set-Content" not in guide and "Add-Content" not in guide and "Out-File" not in guide   # 대시보드 .env는 읽기만
    assert upd.index("Sync-UpdateRepo)") < upd.index("Move-PhysicsAIMachineEnvToRuntime") < upd.index("Assert-PhysicsAINoActiveJobs")
    assert upd.index("Assert-PhysicsAINoActiveJobs") < upd.index("Stop-PhysicsAITasks") < upd.index("Update-PhysicsAITaskRegistration") < upd.index("Install-PhysicsAIRepoPackages")
    assert upd.index("Install-PhysicsAIRepoPackages") < upd.index("Install-PhysicsAIFrontendFromRepo") < upd.index("Invoke-PhysicsAIMigration")
    assert upd.rstrip().endswith('Write-Step "업데이트 성공 — 접속: $accessUrl"') and 'Write-Step "업데이트 실패 — 접속: $accessUrl"\n    exit 1' in upd
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


def test_setup_config_upgrades_old_predict_defaults(tmp_path):
    """phase3 §11.8: 기존 설정의 이전 기본값(commands.mesh: null, predict.mesh_output_glob: "eps_mesh*")은 새 기본으로 갱신,
    사용자가 바꾼 값은 보존."""
    t = _fake_tree(tmp_path)
    _run(tmp_path, t, _inputs(t))
    cfg_path = t["rt"] / "config" / "platform.yaml"
    text = cfg_path.read_text(encoding="utf-8")
    old = re.sub(r'(?m)^  mesh: \[.*$', "  mesh: null                 # 사내 확인 후 교체(U2)", text)
    old = old.replace("  starter_glob:", '  mesh_output_glob: "eps_mesh*"   # 사내 확인 후 교체(U3)\n  starter_glob:', 1)
    old = re.sub(r"(?m)^  (simlab_mesh_name|mesh_include_name|renum_csv_name|mesh_log_complete_marker): .*\n", "", old)  # S6 이전 설정
    cfg_path.write_text(old, encoding="utf-8")
    res = _run(tmp_path, t, _inputs(t))
    c = _cfg(t)
    example = yaml.safe_load((REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    assert c["commands"]["mesh"] == example["commands"]["mesh"] and "mesh_output_glob" not in c["predict"]
    assert sorted(res["config_changed_keys"]) == ["commands.mesh", "predict.mesh_include_name", "predict.mesh_output_glob"]
    assert c["predict"]["mesh_include_name"] == example["predict"]["mesh_include_name"]
    assert res["write"]["validation"]["ok"] and res["write"]["validation"]["warnings"] == []
    new_text = cfg_path.read_text(encoding="utf-8")
    assert "# 사내 확인 후 교체(U2)" in new_text                                   # 줄 끝 주석 유지
    assert (t["rt"] / "_backup" / "20261014T010203Z" / "platform.yaml").read_text(encoding="utf-8") == old
    # 갱신 뒤에는 사용자 값 보존(폐지 키는 경고만): 일부러 끈 mesh: null·mesh_output_glob
    line = next(ln for ln in new_text.split("\n") if ln.startswith("  mesh: "))
    user = new_text.replace(line, "  mesh: null   # 일부러 끔", 1)
    user = user.replace("  starter_glob:", '  mesh_output_glob: "*.inc"\n  starter_glob:', 1)
    cfg_path.write_text(user, encoding="utf-8")
    res = _run(tmp_path, t, _inputs(t))
    c = _cfg(t)
    assert c["commands"]["mesh"] is None
    assert c["predict"]["mesh_output_glob"] == "*.inc" and res["config_changed_keys"] == []
    assert any(w.startswith("predict.mesh_output_glob:") and "폐지" in w for w in res["write"]["validation"]["warnings"])


def test_setup_config_dashboard_login_url_merge(tmp_path):
    """phase3 D3-38: auth.dashboard_public_login_url = 대시보드 .env WINDOWS_WEB_BASE_PATH(없으면 /home/).
    키가 없거나 이전 기본값 "/"일 때만 바꾸고, 사용자가 넣은 다른 값은 보존. .env에서는 그 키만 읽는다."""
    t = _fake_tree(tmp_path)
    cfg_path = t["rt"] / "config" / "platform.yaml"

    # 대시보드 없음 → 대시보드 Vite 기본 base /home/
    res = _run(tmp_path, t, _inputs(t))
    assert _cfg(t)["auth"]["dashboard_public_login_url"] == "/home/" and res["warnings"] == []
    assert "# 로그인·\"대시보드로\" 링크" in cfg_path.read_text(encoding="utf-8")       # 예시 줄 끝 주석 유지

    # 이전 기본값 "/" → 대시보드 .env 값(앞뒤 '/' 보정, 따옴표 제거)
    dash = tmp_path / "simdashboard"
    dash.mkdir()
    (dash / ".env").write_text("DATABASE_URL=postgresql://u:secret@h:5433/d\nWINDOWS_WEB_PORT=8080\n"
                               "WINDOWS_WEB_BASE_PATH=\"workbench\"\n", encoding="utf-8")
    cfg_path.write_text(cfg_path.read_text(encoding="utf-8").replace('dashboard_public_login_url: "/home/"',
                                                                     'dashboard_public_login_url: "/"'), encoding="utf-8")
    inp = _inputs(t, deploy_explicit={"dashboard_root": str(dash)})
    res = _run(tmp_path, t, inp)
    assert _cfg(t)["auth"]["dashboard_public_login_url"] == "/workbench/"
    assert "auth.dashboard_public_login_url" in res["config_changed_keys"] and res["write"]["validation"]["ok"]
    assert "secret" not in json.dumps(res, ensure_ascii=False)

    # 다시 실행: 그대로
    res = _run(tmp_path, t, inp)
    assert res["config_changed_keys"] == []

    # 사용자 값 보존(.env가 바뀌어도)
    text = cfg_path.read_text(encoding="utf-8").replace('"/workbench/"', '"/my/login"')
    cfg_path.write_text(text, encoding="utf-8")
    res = _run(tmp_path, t, inp)
    assert _cfg(t)["auth"]["dashboard_public_login_url"] == "/my/login" and res["config_changed_keys"] == []

    # 키가 없으면 보충 — 입력 dashboard_web_base_path(setup.ps1이 dashboard-env.ps1로 읽은 값)가 .env보다 우선
    text = re.sub(r"(?m)^  dashboard_public_login_url: .*\n", "", cfg_path.read_text(encoding="utf-8"))
    cfg_path.write_text(text, encoding="utf-8")
    res = _run(tmp_path, t, {**inp, "dashboard_web_base_path": "/home"})
    c = _cfg(t)
    assert c["auth"]["dashboard_public_login_url"] == "/home/" and c["auth"]["mode"] == "dashboard"
    assert res["config_changed_keys"] == ["auth.dashboard_public_login_url"]

    # 링크로 쓸 수 없는 값 → 경고만, 설정 그대로
    cfg_path.write_text(cfg_path.read_text(encoding="utf-8").replace('"/home/"', '"/"', 1), encoding="utf-8")
    res = _run(tmp_path, t, {**inp, "dashboard_web_base_path": "/a b/../"})
    assert _cfg(t)["auth"]["dashboard_public_login_url"] == "/" and res["config_changed_keys"] == []
    assert any("WINDOWS_WEB_BASE_PATH" in w for w in res["warnings"])


def test_setup_config_web_base_helpers():
    m = _module()
    assert m.normalize_web_base(None) == ("/home/", None) and m.normalize_web_base("") == ("/home/", None)
    assert m.normalize_web_base("/home/")[0] == "/home/" and m.normalize_web_base("sim/wb")[0] == "/sim/wb/"
    assert m.normalize_web_base("/")[0] == "/"
    for bad in ("/a b/", "/x/../", "http://h/x", "/a?b"):
        assert m.normalize_web_base(bad)[0] == "" and m.normalize_web_base(bad)[1], bad



def _run_pwsh(pwsh: str, body: str, env: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    # -NonInteractive(호스트): Read-Host가 불리면 오류로 끝난다 → "묻지 않음" 확인
    return subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", body], capture_output=True, text=True,
                          timeout=120, env={**os.environ, **(env or {})}, stdin=subprocess.DEVNULL, cwd=cwd)


def _fake_exe(path: Path, script: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/bash\n" + script, encoding="utf-8")
    path.chmod(0o755)
    return path


# 가짜 npm: 부모(pwsh)의 stdout·stderr를 그대로 물려받았는지(파이프·리다이렉트 없음) 기록. FAKE_NPM=fail이면 run build 실패
_FAKE_NPM = r"""
o=$(readlink /proc/$$/fd/1); po=$(readlink /proc/$PPID/fd/1); e=$(readlink /proc/$$/fd/2); pe=$(readlink /proc/$PPID/fd/2)
echo "npm $* console=$([ "$o" = "$po" ] && [ "$e" = "$pe" ] && echo y || echo n)" >> "$NPM_LOG"
if [ "$1" = ci ]; then mkdir -p node_modules; echo "added 1 package"; exit 0; fi
if [ "$FAKE_NPM" = fail ]; then echo "Error: spawn EPERM" >&2; echo "    at ensureServiceIsRunning" >&2; exit 1; fi
mkdir -p dist; echo "<html></html>" > dist/index.html; echo "built in 1.00s"; exit 0
"""


@pytest.mark.posix  # 가짜 npm(bash, /proc). Windows 실제 빌드는 CI windows 잡 "git 폴더 설치"
def test_npm_runs_on_console_without_pipe_and_retries_once(tmp_path):
    """phase3 D3-39: npm ci·npm run build는 창에서 직접 친 것과 같이 콘솔을 물려받는다(파이프면 esbuild spawn EPERM).
    실패하면 한 번만 다시 실행하고, 그래도 실패면 '직접 실행해 결과를 알려 달라'는 안내로 중단."""
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("pwsh 없음 — node-select.ps1 실행 시험 미수행")
    repo = tmp_path / "repo"
    (repo / "frontend").mkdir(parents=True)
    (repo / "frontend" / "package-lock.json").write_text("{}", encoding="utf-8")
    npm = _fake_exe(tmp_path / "node" / "npm", _FAKE_NPM)
    log = tmp_path / "npm.log"
    stamp = tmp_path / "stamp"

    def run(call: str, mode: str = "") -> tuple[subprocess.CompletedProcess, list[str]]:
        log.unlink(missing_ok=True)
        shutil.rmtree(repo / "frontend" / "dist", ignore_errors=True)
        body = (f". '{DEPLOY.as_posix()}/node-select.ps1'; "
                f"$n = [pscustomobject]@{{ Label = 'x'; Exe = 'node'; Dir = '{npm.parent.as_posix()}'; Version = 'v22.12.0'; Npm = '{npm.as_posix()}' }}; "
                f"{call}; 'DONE'")
        r = _run_pwsh(pwsh, body, {"NPM_LOG": str(log), "FAKE_NPM": mode})
        return r, (log.read_text(encoding="utf-8").splitlines() if log.exists() else [])

    build = f"Invoke-PhysicsAIFrontendBuild -Node $n -RepoRoot '{repo.as_posix()}' -StampFile '{stamp.as_posix()}' -RetryDelaySec 0"
    r, calls = run(build)
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "DONE" in out, out
    assert calls == ["npm ci console=y", "npm run build console=y"]
    assert "built in 1.00s" in out and (repo / "frontend" / "dist" / "index.html").exists() and stamp.exists()

    r, calls = run(f"try {{ {build} }} catch {{ Write-Host ('ERR=' + $_.Exception.Message); exit 1 }}", "fail")   # 실패 → 한 번만 다시 → 안내와 함께 중단
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "DONE" not in out, out
    assert calls == ["npm run build console=y", "npm run build console=y"]               # npm ci는 기록 파일로 건너뜀
    assert "Error: spawn EPERM" in out and "한 번 더 실행합니다" in out and "(다시 실행)" in out
    assert f"ERR=실패: npm run build (종료코드 1)\n다음 행동: frontend 폴더({repo.as_posix()}/frontend)에서 npm run build를 직접 실행해 결과를 알려 주세요." in out

    # 대조: 결과를 변수에 받으면 출력이 파이프가 된다(이 시험이 파이프를 구별함을 확인 — 호출 쪽은 받지 않는다)
    r, calls = run(f"$x = Invoke-PhysicsAINpm -Npm '{npm.as_posix()}' -Arguments @('ci')")
    assert r.returncode == 0 and calls == ["npm ci console=n"], r.stdout + r.stderr


def _task_stubs(repo: Path) -> str:
    """작업 스케줄러 대역(Linux pwsh): 이미 --runtime 방식으로 등록된 두 작업(다시 등록하지 않음)."""
    rt = (repo / ".runtime").as_posix()
    py = (repo / ".runtime" / "venv" / "Scripts" / "python.exe").as_posix()
    return ("function Get-ScheduledTask { param($TaskName) "
            f"$m = if ($TaskName -eq 'PhysicsAI-Backend') {{ 'physicsai_api.serve' }} else {{ 'physicsai_worker' }}; "
            f"[pscustomobject]@{{ Actions = @([pscustomobject]@{{ Execute = '{py}'; Arguments = \"-m $m --runtime `\"{rt}`\"\"; WorkingDirectory = '{rt}' }}) }} }}; ")


def _update_repo_tree(tmp: Path, *, web_port: str | None = "8080") -> Path:
    """update-repo.ps1을 Linux pwsh로 끝까지 돌리는 가짜 git 폴더: deploy\\*.ps1 사본 + 가짜 venv python·대시보드 Node·npm.
    관리자 확인·대기열 DB 조회·pip·설정·migration·health는 사본 install-common.ps1 끝에 덧붙인 대역 함수(나머지 흐름은 실제 코드)."""
    repo = tmp / "git"
    shutil.copytree(DEPLOY, repo / "deploy", ignore=shutil.ignore_patterns("demo", "caddy", "*.lock", "__pycache__"))
    (repo / "frontend").mkdir(parents=True)
    (repo / "frontend" / "package-lock.json").write_text("{}", encoding="utf-8")
    (repo / ".node-version").write_text("v22.12.0", encoding="utf-8")
    rt = repo / ".runtime"
    _fake_exe(rt / "venv" / "Scripts" / "python.exe", 'echo "PHYSICSAI_PY=3.12.13 $0"\n')
    dash = tmp / "dash"
    dash.mkdir()
    (dash / ".env").write_text(f"WINDOWS_WEB_PORT={web_port}\n" if web_port else "SIMDASH_PHYSICSAI_ENABLED=true\n", encoding="utf-8")
    nd = dash / ".tools" / "node-v22.12.0-win-x64"
    _fake_exe(nd / "node.exe", "echo v22.12.0\n")
    _fake_exe(nd / "npm.cmd", _FAKE_NPM)
    _touch(rt / "frontend" / "old.txt")
    (rt / "deploy.json").write_text(json.dumps({
        "dashboard_root": str(dash), "config_path": str(rt / "config" / "platform.yaml"), "pg_bin": str(tmp / "pg"),
        "caddy_frontend_root": str(rt / "frontend"), "python_exe": "", "service_user": "CORP\\me", "run_mode": "Interactive"}), encoding="utf-8")
    _touch(rt / "secrets" / "database_url").write_text("postgresql+psycopg://physicsai_app:pw@127.0.0.1:5434/physicsai", encoding="utf-8")
    with open(repo / "deploy" / "install-common.ps1", "a", encoding="utf-8") as f:
        f.write(r"""
function Get-PhysicsAIActiveJobCount { param($Port, $PgBin, $DbUrl) if (-not $DbUrl) { throw 'NO DBURL' }; [int]$env:FAKE_ACTIVE }
function Install-PhysicsAIRepoPackages { param($VenvPy, $RepoRoot) Write-Host 'STUB packages' }
function Invoke-PhysicsAISetupConfig { param($VenvPy, $Action, $RuntimeDir, $Inputs)
    [pscustomobject]@{ warnings = @(); write = [pscustomobject]@{ backups = @(); written = @(); validation = [pscustomobject]@{ ok = $true; warnings = @(); issues = @() } } } }
function Invoke-PhysicsAIMigration { param($VenvPy, $AlembicIni) Write-Host 'STUB migration' }
function Start-PhysicsAITasksAndWait { param($Port, $LogDir) Write-Host 'STUB start+health' }
""")
    return repo


@pytest.mark.posix  # Windows 5.1 실제 실행은 CI windows 잡 "git 폴더 설치"(update-repo.ps1 인자 없이 -NoStart만)
def test_update_repo_one_click_no_prompt_and_restore_on_build_failure(tmp_path):
    """phase3 D3-39: update-repo.ps1은 인자·질문 없이 한 번(-NonInteractive 없이도 Read-Host 없음). npm은 콘솔 그대로.
    끝은 성공/실패 + 접속 주소 한 줄(대시보드 .env WINDOWS_WEB_PORT). 빌드가 끝내 실패하면 이전 프런트 그대로·작업 2개 다시 시작.
    대기열에 작업이 있으면 묻지 않고 안내 후 중단(아무것도 바꾸지 않음)."""
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("pwsh 없음 — update-repo.ps1 실행 시험 미수행")
    repo = _update_repo_tree(tmp_path)
    rt = repo / ".runtime"
    log = tmp_path / "npm.log"
    stubs = (_task_stubs(repo) +
             "function Stop-ScheduledTask { param($TaskName) Write-Host \"STOP $TaskName\" }; "
             "function Start-ScheduledTask { [CmdletBinding()] param($TaskName) Write-Host \"START $TaskName\" }; "
             "function Start-Sleep { param($Seconds) Write-Host \"SLEEP $Seconds\" }; ")

    def run(env: dict) -> tuple[subprocess.CompletedProcess, str]:
        log.unlink(missing_ok=True)
        r = _run_pwsh(pwsh, stubs + f"& '{(repo / 'deploy' / 'update-repo.ps1').as_posix()}'; \"EXIT=$LASTEXITCODE\"",
                      {"NPM_LOG": str(log), "FAKE_ACTIVE": "0", **env})
        return r, r.stdout + r.stderr

    # ① 성공: 인자 없이 끝까지, npm은 콘솔 그대로, 이전 프런트는 _backup, 끝은 한 줄
    r, out = run({})
    assert "EXIT=0" in out, out
    assert log.read_text(encoding="utf-8").splitlines() == ["npm ci console=y", "npm run build console=y"]
    assert (rt / "frontend" / "index.html").exists() and list(rt.glob("_backup/*/frontend/old.txt"))
    assert "STUB migration" in out and "STUB start+health" in out
    assert re.search(r"\[PhysicsAI 업데이트\] 업데이트 성공 — 접속: http://[^/:\s]+:8080/physicsai/\n", r.stdout), out
    assert "토큰" not in out and "Read-Host" not in out and "NonInteractive" not in out
    assert "git 저장소가 아니어서 git pull을 건너뜁니다" in out and "작업 등록 그대로" in out and "pw@" not in out

    # ② 빌드가 끝내 실패(spawn EPERM 2번): migration 없이 이전 프런트 그대로, 작업 2개 다시 시작, 직접 빌드 안내 + 접속 주소
    shutil.rmtree(rt / "frontend")
    _touch(rt / "frontend" / "old.txt")
    r, out = run({"FAKE_NPM": "fail"})
    assert "EXIT=1" in out, out
    assert log.read_text(encoding="utf-8").splitlines() == ["npm run build console=y", "npm run build console=y"]
    assert "SLEEP 10" in out and "STUB migration" not in out
    assert sorted(p.name for p in (rt / "frontend").iterdir()) == ["old.txt"]
    assert out.index("STOP PhysicsAI-Worker") < out.index("업데이트 실패(프런트 배치)") < out.index("START PhysicsAI-Backend")
    assert "START PhysicsAI-Worker" in out and "npm run build를 직접 실행해 결과를 알려 주세요" in out
    assert re.search(r"이전 상태로 계속 쓸 수 있습니다 — 접속: http://[^/:\s]+:8080/physicsai/", out), out
    assert re.search(r"업데이트 실패 — 접속: http://[^/:\s]+:8080/physicsai/\s*EXIT=1", out), out

    # ③ 대기열에 작업이 있으면: 묻지 않고 안내 후 중단(중지·빌드 없음)
    r, out = run({"FAKE_ACTIVE": "2"})
    assert "EXIT=1" in out and "STOP" not in out and not log.exists(), out
    assert "업데이트하지 않았습니다(바꾼 것 없음): 대기·실행 중 작업 또는 진행 중 환경 점검이 2 건 있습니다" in out and "-Force" in out


@pytest.mark.posix
def test_restore_after_failed_update_and_access_url(tmp_path):
    """phase3 D3-39: 배치 뒤·migration 전 실패면 이전 프런트를 원위치로(새 것은 frontend-failed — 삭제 없음), 작업 2개 다시 시작(-NoStart면 생략).
    접속 주소: 대시보드 .env WINDOWS_WEB_PORT(없으면 80 — 주소에 포트 생략), .env를 못 읽으면 <대시보드 주소>."""
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("pwsh 없음 — install-common.ps1 실행 시험 미수행")
    common = (DEPLOY / "install-common.ps1").as_posix()
    fe, bk = tmp_path / "rt" / "frontend", tmp_path / "rt" / "_backup" / "S"

    def restore(extra: str = "") -> str:
        shutil.rmtree(tmp_path / "rt", ignore_errors=True)
        _touch(bk / "frontend" / "old.txt")
        _touch(fe / "new.txt")
        body = (f". '{common}'; $PhysicsAITag = 'T'; "
                "function Start-ScheduledTask { [CmdletBinding()] param($TaskName) Write-Host \"START $TaskName\" }; "
                f"Restore-PhysicsAIAfterFailedUpdate -FrontendDest '{fe.as_posix()}' -BackupDir '{bk.as_posix()}' {extra}; 'DONE'")
        r = _run_pwsh(pwsh, body)
        assert r.returncode == 0 and "DONE" in r.stdout, r.stdout + r.stderr
        return r.stdout + r.stderr

    out = restore()
    assert (fe / "old.txt").exists() and not (fe / "new.txt").exists() and (bk / "frontend-failed" / "new.txt").exists()
    assert "이전 프런트로 되돌렸습니다" in out and "START PhysicsAI-Backend" in out and "START PhysicsAI-Worker" in out
    out = restore("-NoStart")
    assert (fe / "old.txt").exists() and "START" not in out

    dash = tmp_path / "dash"
    dash.mkdir()
    env_file = dash / ".env"
    denv = (DEPLOY / "dashboard-env.ps1").as_posix()

    def url(text: str | None) -> str:
        env_file.unlink(missing_ok=True)
        if text is not None:
            env_file.write_text(text, encoding="utf-8")
        body = (f". '{common}'; . '{denv}'; [Environment]::MachineName; "
                f"Get-PhysicsAIAccessUrl -Dash (Get-DashboardRuntimeDefaults -DashboardRoot '{dash.as_posix()}'); Get-PhysicsAIAccessUrl -Dash $null")
        r = _run_pwsh(pwsh, body)
        assert r.returncode == 0, r.stdout + r.stderr
        host, u, none = r.stdout.splitlines()
        assert none == "http://<대시보드 주소>/physicsai/"
        return u.replace(host, "<서버>")

    assert url('WINDOWS_WEB_PORT="8080"\n') == "http://<서버>:8080/physicsai/"
    assert url("WINDOWS_WEB_PORT=80\n") == "http://<서버>/physicsai/"
    assert url("SIMDASH_PHYSICSAI_ENABLED=true\n") == "http://<서버>/physicsai/"             # 기본 80
    assert url(None) == "http://<대시보드 주소>/physicsai/"
