"""v0.2.13 — 이슈 #11(3D contour INVALID 상세·2차 요소 config·관대한 입력)·#13(자식 환경 ProgramFiles)."""

from __future__ import annotations

from pathlib import Path

import pytest

from physicsai_core.childenv import child_env
from physicsai_core.contour3d.convert import ConvertError, convert

SRC = {"kind": "SOLVER_H3D", "ref": {}, "h3d_name": "a.h3d"}
RESULT = ("# contour_extract 1\nSTATUS=OK\nUNIT=Invalid command syntax: \"result scalar unit\"\nFIELD=CornerStress\nDCOMP=vonMises\n"
          "AVGMODE=\nNODES={n}\nFACES={f}\nFRAMES_TOTAL={t}\n{frames}")
# 4절점 사면체 하나(+ 중간 노드 6개 → config 210은 n1..n8 중 앞 4개가 꼭짓점)
NODES = [(1, 0, 0, 0), (2, 1, 0, 0), (3, 0, 1, 0), (4, 0, 0, 1), (5, .5, 0, 0), (6, .5, .5, 0), (7, 0, .5, 0), (8, 0, 0, .5)]


def _mk(d: Path, *, config: int = 210, frames: int = 2, times=None, value: str | None = None, nodes=NODES, conn=(1, 2, 3, 4, 5, 6, 7, 8)):
    d.mkdir(parents=True, exist_ok=True)
    (d / "nodes.csv").write_text("node_id,x,y,z\n" + "".join(f"{i},{x},{y},{z}\n" for i, x, y, z in nodes))
    (d / "elements.csv").write_text("elem_id,config,n1,n2,n3,n4,n5,n6,n7,n8\n1," + f"{config}," + ",".join(map(str, conn)) + "\n")
    lines = ""
    for i in range(frames):
        t = (times or [0.0025 * i for i in range(frames)])[i]
        lines += f"FRAME={i}|{i}|Time = {t:f}\n"
        (d / f"frame_{i:05d}.csv").write_text("value\n" + "".join(f"{value if value is not None else n[0] + i}\n" for n in nodes))
    (d / "extract_result.txt").write_text(RESULT.format(n=len(nodes), f=1, t=frames, frames=lines))


def _conv(d: Path, out: Path):
    return convert(str(d), str(out), source=SRC, max_nodes=10_000_000, max_bin_bytes=1 << 30, max_frames=55)


def test_tetra10_config_210_uses_corner_nodes_and_duplicate_times_ok(tmp_path):
    _mk(tmp_path / "x", times=[0.05, 0.05])  # 마지막 두 프레임 시간이 같아도 허용, UNIT 오류 문구 → 단위 없음
    m = _conv(tmp_path / "x", tmp_path / "o")
    assert m["status"] == "OK" and m["mesh"]["nodes"] == 4 and m["mesh"]["triangles"] == 4 and m["unit"] == ""
    assert m["frames"]["count"] == 2


@pytest.mark.parametrize("config", [106, 108, 213, 215, 220])
def test_second_order_aliases_recognized(tmp_path, config):
    from physicsai_core.contour3d.convert import CONFIG_ALIAS
    assert CONFIG_ALIAS[config] == {106: 103, 108: 104, 213: 205, 215: 206, 220: 208}[config]


def test_all_unknown_config_detail_lists_counts(tmp_path):
    _mk(tmp_path / "x", config=999)
    with pytest.raises(ConvertError) as ei:
        _conv(tmp_path / "x", tmp_path / "o")
    assert ei.value.code == "CONTOUR3D_EXTRACT_INVALID" and "미지원 요소 config {999: 1}" in ei.value.message


def test_partially_unknown_config_warns(tmp_path):
    d = tmp_path / "x"
    _mk(d)
    (d / "elements.csv").write_text((d / "elements.csv").read_text() + "2,999,1,2,3,4,5,6,7,8\n")
    m = _conv(d, tmp_path / "o")
    assert m["status"] == "OK" and any("{999: 1}" in w["message"] for w in m["warnings"])


def test_faces_with_missing_nodes_skipped_not_fatal(tmp_path):
    d = tmp_path / "x"
    _mk(d)
    (d / "faces.csv").write_text("elem_id,n1,n2,n3,n4\n1,1,2,3,\n2,1,2,77,\n")
    m = _conv(d, tmp_path / "o")
    assert m["mesh"]["triangles"] == 1 and any("nodes.csv에 없는 노드" in w["message"] for w in m["warnings"])
    (d / "faces.csv").write_text("elem_id,n1,n2,n3,n4\n2,1,2,77,\n")
    with pytest.raises(ConvertError, match="모든 면이 nodes.csv에 없는 노드"):
        _conv(d, tmp_path / "o2")


def test_nan_like_frame_tokens_and_details(tmp_path):
    d = tmp_path / "x"
    _mk(d)
    (d / "frame_00001.csv").write_text("value\n1\n-1.#IND\n1.#QNAN\n4\n5\n6\n7\n8\n")
    assert _conv(d, tmp_path / "o")["frames"]["nan_count"] == 2
    (d / "frame_00001.csv").write_text("value\n1\n2\nabc\n4\n5\n6\n7\n8\n")
    with pytest.raises(ConvertError, match=r"frame_00001.csv \d+번째 줄"):
        _conv(d, tmp_path / "o2")
    (d / "frame_00001.csv").write_text("value\n1\n2\n")
    with pytest.raises(ConvertError, match=r"frame_00001.csv 데이터 행 수가 nodes.csv\(8\)와 다릅니다"):
        _conv(d, tmp_path / "o3")
    (d / "frame_00001.csv").unlink()
    with pytest.raises(ConvertError, match="frame_00001.csv"):
        _conv(d, tmp_path / "o4")


@pytest.mark.parametrize("tok", ["Error: info missing", "banana", "(inf)", "nanx", "1.#IND5"])
def test_nan_like_requires_full_match(tmp_path, tok):
    d = tmp_path / "x"
    _mk(d)
    (d / "frame_00001.csv").write_text(f"value\n1\n{tok}\n3\n4\n5\n6\n7\n8\n")
    with pytest.raises(ConvertError, match="숫자가 아닙니다"):
        _conv(d, tmp_path / "o")


def test_nan_like_accepted_forms(tmp_path):
    d = tmp_path / "x"
    _mk(d)
    (d / "frame_00001.csv").write_text("value\n NaN \n-nan\n-INF\n1.#QNAN\n#QNAN\n1.#INF\n-1.#IND\n\n")
    assert _conv(d, tmp_path / "o")["frames"]["nan_count"] > 0


@pytest.mark.parametrize("config, conn", [(213, (1, 2, 3, 4, 5, 6, 7, 8)), (215, (1, 2, 3, 4, 5, 6, 7, 8))])
def test_pyramid13_penta15_synthetic(tmp_path, config, conn):
    nodes = [(1, 0, 0, 0), (2, 1, 0, 0), (3, 1, 1, 0), (4, 0, 1, 0), (5, .5, .5, 1), (6, 0, 0, 1), (7, 1, 0, 1), (8, 0, 0, .5)]
    d = tmp_path / "x"
    _mk(d, config=config, nodes=nodes, conn=conn)
    m = _conv(d, tmp_path / "o")
    assert m["status"] == "OK" and m["mesh"]["nodes"] == (5 if config == 213 else 6)


def test_duplicate_node_ids_allowed(tmp_path):
    d = tmp_path / "x"
    _mk(d, nodes=NODES + [(1, 0, 0, 0)])
    assert _conv(d, tmp_path / "o")["status"] == "OK"


def test_status_detail_names_file(tmp_path):
    d = tmp_path / "x"
    _mk(d)
    (d / "extract_result.txt").write_text("STATUS=\n")
    with pytest.raises(ConvertError, match=r"extract_result.txt STATUS=None"):
        _conv(d, tmp_path / "o")


def test_child_env_programfiles_pass_secrets_blocked():
    src = {"ProgramFiles": "C:\\Program Files", "PROGRAMFILES(X86)": "C:\\x86", "CommonProgramFiles": "c", "CommonProgramFiles(x86)": "c2",
           "PGPASSWORD": "p", "DATABASE_URL": "postgres://u:p@h/d", "PHYSICSAI_DATABASE_URL": "x", "MY_TOKEN": "t"}
    env = child_env(source=src)
    assert set(env) == {"ProgramFiles", "PROGRAMFILES(X86)", "CommonProgramFiles", "CommonProgramFiles(x86)"}
