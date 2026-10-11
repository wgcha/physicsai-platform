"""V3-S4-3: map_path·resolve_collect_dirs 표 시험, 설정 변환, 경로 문자열 규칙."""

from __future__ import annotations

import os

import pytest

from simdash_adapters import PathMapEntry, TransferConfig, fwd, is_abs_path_str, map_path, resolve_collect_dirs

PM = (PathMapEntry("D:\\AI_WORK", "/shared/AI_WORK/"), PathMapEntry("D:/AI_WORK/sub", "/never"), PathMapEntry("/data", "/mnt/data"))


@pytest.mark.parametrize("path,expected", [
    ("D:\\AI_WORK\\S1\\01_train\\results", "/shared/AI_WORK/S1/01_train/results"),
    ("d:/ai_work/S1/x.rad", "/shared/AI_WORK/S1/x.rad"),          # 대소문자 무시, 나머지 부분은 원래 표기
    ("D:/AI_WORK", "/shared/AI_WORK"),                            # 같은 경로
    ("D:/AI_WORK/sub/a", "/shared/AI_WORK/sub/a"),                # 첫 일치 접두가 이긴다
    ("D:/AI_WORKX/a", "D:/AI_WORKX/a"),                           # 접두 문자열이어도 경로 경계가 아니면 불일치
    ("/data/a/b", "/mnt/data/a/b"),
    ("E:\\other\\a", "E:/other/a"),                               # 불일치 → '/' 표기만
])
def test_map_path_table(path, expected):
    assert map_path(path, PM) == expected


def test_map_path_duck_typed_entries():
    class E:
        local, remote = "C:/w", "/r"

    assert map_path("C:\\w\\x", [E()]) == "/r/x"
    assert map_path("C:/w/x", []) == "C:/w/x"


@pytest.mark.parametrize("mode", ["shared_folder", "drive"])
def test_resolve_collect_dirs_shared(mode):
    t = TransferConfig(mode, "\\\\nas\\pbs_out\\", "D:/collect", PM)
    remote, local = resolve_collect_dirs(t, study_folder="S1", doe_id="doe-1", run_key="run_001",
                                         local_result_dir="D:/AI_WORK/S1/01_train/results/doe-1/run_001")
    assert remote == "//nas/pbs_out/S1/doe-1/run_001"
    assert local == os.path.join(os.path.normpath("D:/collect"), "S1", "doe-1", "run_001")


@pytest.mark.parametrize("mode", ["in_place", "anything_else"])
def test_resolve_collect_dirs_in_place(mode):
    t = TransferConfig(mode, "", "", PM)
    assert resolve_collect_dirs(t, study_folder="S1", doe_id="d", run_key="r",
                                local_result_dir="D:\\AI_WORK\\S1\\01_train\\results\\d\\r") == (
        "/shared/AI_WORK/S1/01_train/results/d/r", None)


def test_transfer_from_mapping_and_obj():
    d = {"collect_mode": "drive", "collect_root_remote": "/r", "collect_root_local": "/l",
         "path_map": [{"local": "/a", "remote": "/b"}]}
    t = TransferConfig.from_mapping(d)
    assert t == TransferConfig("drive", "/r", "/l", (PathMapEntry("/a", "/b"),))

    class O:
        collect_mode, collect_root_remote, collect_root_local = "in_place", "", ""
        path_map = [PathMapEntry("/a", "/b")]
        extra = "무시"

    assert TransferConfig.from_obj(O()).path_map == (PathMapEntry("/a", "/b"),)
    with pytest.raises(KeyError):
        TransferConfig.from_mapping({"collect_mode": "in_place"})


@pytest.mark.parametrize("p,ok", [("C:\\x", True), ("c:/x", True), ("/x", True), ("x/y", False), ("C:x", False),
                                  ("\\\\nas\\s", False), ("", False)])
def test_is_abs_path_str(p, ok):
    assert is_abs_path_str(p) is ok


def test_fwd():
    assert fwd("C:\\a\\b/c") == "C:/a/b/c"
