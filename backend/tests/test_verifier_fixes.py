"""Verifier 조건부 Pass 결함 회귀 시험(1·2·5·6·7·8 단위, 9 다운로드 상한)."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from physicsai_core import paths as paths_mod
from physicsai_core.childenv import child_env
from physicsai_core.commands import render_argv
from physicsai_core.errors import StepFailure
from physicsai_core.paths import (
    PathError,
    backup_existing,
    check_dataset_input,
    check_user_path,
    is_link_or_reparse,
    to_rel,
    windows_reserved_name,
)
from physicsai_core.stage3_model.dataset_split import collect_h3d
from physicsai_test_support import API, H

# ---- 1. 매핑 드라이브·SUBST(루트가 다른 형태로 풀리는 경우) --------------------------------


def _mapped(tmp_path):
    real_root = tmp_path / "vol" / "AI_WORK"
    (real_root / "s" / "in").mkdir(parents=True)
    mapped = tmp_path / "E_drive"  # 매핑 드라이브·SUBST 모사: 루트 자체가 다른 실경로로 풀림
    os.symlink(tmp_path / "vol", mapped)
    return real_root, mapped / "AI_WORK"


def test_mapped_root_accepts_both_forms(tmp_path):
    real_root, mapped_root = _mapped(tmp_path)
    a = check_user_path(str(mapped_root / "s" / "in"), [str(mapped_root)])
    assert a.path == str(mapped_root / "s" / "in")
    b = check_user_path(str(real_root / "s" / "in"), [str(mapped_root)])  # UNC·실경로 형태로 입력해도 허용
    assert b.path == str(real_root / "s" / "in")
    outside = tmp_path / "other"
    outside.mkdir()
    os.symlink(outside, real_root / "s" / "lnk")
    with pytest.raises(PathError) as ei:
        check_user_path(str(mapped_root / "s" / "lnk"), [str(mapped_root)])
    assert ei.value.code == "PATH_UNSAFE"
    with pytest.raises(PathError) as ei:
        check_user_path(str(outside), [str(mapped_root)])
    assert ei.value.code == "PATH_OUTSIDE_ROOT"


def test_to_rel_and_backup_under_mapped_root(tmp_path):
    real_root, mapped_root = _mapped(tmp_path)
    study_mapped = str(mapped_root / "s")
    f = real_root / "s" / "in" / "x.json"
    f.write_text("1")
    assert to_rel(study_mapped, str(f)) == "in/x.json"
    assert to_rel(str(real_root / "s"), str(mapped_root / "s" / "in" / "x.json")) == "in/x.json"
    assert backup_existing(study_mapped, [str(f)], "j1", "T") == ["in/x.json"]
    assert (real_root / "s" / "_backup" / "T_j1" / "in" / "x.json").exists()


def test_reparse_only_real_links(monkeypatch, tmp_path):
    def fake_lstat(tag):
        return lambda p: SimpleNamespace(st_mode=0o040755, st_file_attributes=0x400, st_reparse_tag=tag)

    monkeypatch.setattr(paths_mod.os, "lstat", fake_lstat(0x80000013))  # dedup
    assert is_link_or_reparse(str(tmp_path)) is False
    monkeypatch.setattr(paths_mod.os, "lstat", fake_lstat(0x9000601A))  # OneDrive 클라우드 파일
    assert is_link_or_reparse(str(tmp_path)) is False
    monkeypatch.setattr(paths_mod.os, "lstat", fake_lstat(0xA000000C))  # symlink
    assert is_link_or_reparse(str(tmp_path)) is True
    monkeypatch.setattr(paths_mod.os, "lstat", fake_lstat(0xA0000003))  # junction
    assert is_link_or_reparse(str(tmp_path)) is True


# ---- 2. 백업 고유 접미사, Study 밖 항상 거부 -------------------------------------------------


def test_backup_unique_suffix_and_outside_always(tmp_path):
    study = tmp_path / "s"
    study.mkdir()
    for content in ("v1", "v2", "v3"):
        (study / "a.txt").write_text(content)
        backup_existing(str(study), [str(study / "a.txt")], "j", "SAME")
    d = study / "_backup" / "SAME_j"
    assert sorted(p.name for p in d.iterdir()) == ["a.txt", "a~1.txt", "a~2.txt"]
    assert {p.read_text() for p in d.iterdir()} == {"v1", "v2", "v3"}
    with pytest.raises(StepFailure):  # 존재하지 않아도 Study 밖이면 거부
        backup_existing(str(study), [str(tmp_path / "nope.txt")], "j")
    with pytest.raises(StepFailure):
        backup_existing(str(study), [str(study)], "j")


# ---- 5. Windows 예약 이름 -------------------------------------------------------------------


@pytest.mark.parametrize("name,bad", [("CON", True), ("con", True), ("Com1", True), ("LPT9", True), ("NUL.txt", True),
                                      ("aux.tar.gz", True), ("abc.", True), ("abc ", True), ("CONSOLE", False),
                                      ("COM10", False), ("cushion", False)])
def test_windows_reserved(name, bad):
    assert windows_reserved_name(name) is bad


@pytest.mark.parametrize("name", ["CON", "con", "Prn", "AUX", "NUL", "COM1", "lpt3"])
def test_study_reserved_name_rejected(client, name):
    r = client.post(f"{API}/studies", headers=H("tok-power", write=True), json={"project_id": "p-1", "folder_name": name, "title": "t"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS"


# ---- 6. 데이터셋 입력 제한 ---------------------------------------------------------------------


def test_dataset_input_restrictions(tmp_path):
    ai = tmp_path / "ai"
    st = ai / "S1"
    for d in ("00_inbox/h3d/run1", "03_dataset/x", "04_predict/j/RESULT", "_backup/T_j/00_inbox", "00_inbox/h3d/_backup"):
        (st / d).mkdir(parents=True)
    (st / "00_inbox" / "h3d" / "run1" / "a.h3d").write_text("x")
    (st / "00_inbox" / "h3d" / "_backup" / "old.h3d").write_text("x")
    (st / "04_predict" / "j" / "RESULT" / "p_pred.h3d").write_text("x")
    (st / "_backup" / "T_j" / "00_inbox" / "b.h3d").write_text("x")
    with pytest.raises(PathError):
        check_dataset_input(str(ai), str(ai))
    for sub in ("03_dataset/x", "04_predict/j", "_backup", "logs"):
        (st / sub).mkdir(parents=True, exist_ok=True)
        with pytest.raises(PathError) as ei:
            check_dataset_input(str(st / sub), str(ai))
        assert ei.value.code == "PATH_UNSAFE"
    assert check_dataset_input(str(st / "00_inbox" / "h3d"), str(ai)) == []
    assert collect_h3d(str(st / "00_inbox" / "h3d")) == [str(st / "00_inbox" / "h3d" / "run1" / "a.h3d")]
    exclude = check_dataset_input(str(st), str(ai))
    assert collect_h3d(str(st), exclude) == [str(st / "00_inbox" / "h3d" / "run1" / "a.h3d")]


def test_dataset_input_api_rejects_root_and_outputs(client, loaded_config):
    ai = Path(loaded_config.settings.storage.ai_root)
    sid = client.post(f"{API}/studies", headers=H("tok-power", write=True), json={"project_id": "p-1", "folder_name": "DI", "title": "t"}).json()["id"]
    (ai / "DI" / "03_dataset").mkdir()
    for p in (ai, ai / "DI" / "03_dataset"):
        r = client.post(f"{API}/studies/{sid}/jobs", headers=H("tok-power", write=True),
                        json={"job_type": "DATASET_CREATE", "params": {"input_path": str(p)}})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_UNSAFE"
        r = client.post(f"{API}/studies/{sid}/paths/inspect", headers=H("tok-power", write=True),
                        json={"purpose": "DATASET_INPUT", "path": str(p)})
        assert r.status_code == 422


# ---- 7. 자식 환경 허용목록 ------------------------------------------------------------------


def test_child_env_allowlist():
    src = {"PATH": "/bin", "SystemRoot": "C:\\Windows", "TEMP": "/t", "USERPROFILE": "u", "ALTAIR_HOME": "a",
           "LM_LICENSE_FILE": "6200@lic", "ALTAIR_LICENSE_PATH": "x", "EDS_TNS_ACTVN_CHCKPT": "1",
           "PHYSICSAI_DATABASE_URL": "postgresql://u:pw@h/db", "MY_DB_URL": "secret", "AWS_SECRET_ACCESS_KEY": "s",
           "RANDOM_VAR": "r", "SITE_EXTRA": "e"}
    env = child_env(["SITE_*"], source=src, deny_names=["MY_DB_URL"])
    assert set(env) == {"PATH", "SystemRoot", "TEMP", "USERPROFILE", "ALTAIR_HOME", "LM_LICENSE_FILE",
                        "ALTAIR_LICENSE_PATH", "EDS_TNS_ACTVN_CHCKPT", "SITE_EXTRA"}
    assert child_env(["PHYSICSAI_*"], source=src) .get("PHYSICSAI_DATABASE_URL") is None  # 설정으로도 비밀 전달 불가
    assert child_env([], add={"EDS_X": "1"}, source={})["EDS_X"] == "1"


# ---- 8. .bat 대상 추가 메타문자 -------------------------------------------------------------

T = ["{edspy}", "--physicsai", "--create-dataset", "{out_psdata}", "--spec", "{spec_yaml}"]


@pytest.mark.parametrize("ch", [";", ",", "=", "(", ")"])
def test_bat_extra_chars_rejected(ch):
    vals = {"out_psdata": f"E:/AI/a{ch}b.psdata", "spec_yaml": "E:/AI/s.yaml"}
    with pytest.raises(StepFailure) as ei:
        render_argv("edspy_create_dataset", T, vals, executables={"edspy_path": "C:/Altair/edspy.bat"})
    assert ei.value.code == "INPUT_INVALID"
    with pytest.raises(StepFailure):
        render_argv("edspy_create_dataset", T, vals, executables={"edspy_path": "C:/Altair/EDSPY.CMD"})
    # .exe 직접 실행이면 cmd 재해석이 없으므로 허용
    assert render_argv("edspy_create_dataset", T, vals, executables={"edspy_path": "C:/Altair/edspy.exe"})[3] == vals["out_psdata"]
    # @cmd_c 경유면 실행 파일 확장자와 무관하게 거부
    tp = ["@cmd_c", "{edspy}", "--predict-write", "{pred_h3d}", "--model", "{model_psmdl}", "--input-file", "{starter}"]
    with pytest.raises(StepFailure):
        render_argv("edspy_predict", tp, {"pred_h3d": f"/p/a{ch}.h3d", "model_psmdl": "/m", "starter": "/s"},
                    executables={"edspy_path": "/opt/edspy"}, is_windows=False)


def test_bat_executable_path_with_parentheses_ok():
    argv = render_argv("edspy_create_dataset", T, {"out_psdata": "E:/AI/a.psdata", "spec_yaml": "E:/AI/s.yaml"},
                       executables={"edspy_path": "C:/Program Files (x86)/Altair/edspy.bat"})
    assert argv[0] == ("C:\\Program Files (x86)\\Altair\\edspy.bat" if os.name == "nt" else "C:/Program Files (x86)/Altair/edspy.bat")
