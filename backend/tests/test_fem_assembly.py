"""V3-S16-6(함수): 조립 원본 검사 `plan_assembly`(starter 0/2개, 크기·개수 한도, csv·기준본·참조 경고, 참조 검사 크기 한도 → null,
파일 이름 안전), custom 경로 규칙(AI 루트·가져오기 루트·SPDM 허용, 밖·_backup·링크·공백 거부), 스냅숏(원본 목록·mtime 불변),
메시 /PART id, 메시 원천 규칙."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from physicsai_test_support import make_phase2_settings

MESH_INC = "104_replace_node_elem.inc"


@pytest.fixture()
def settings(tmp_path, fake_tools):
    from physicsai_core.config import load_config_dict

    d = make_phase2_settings(tmp_path, fake_tools)
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    return lc.settings


def _assem(d: Path, *, starters=1, csv=True, base=True, ref=True) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for i in range(starters):
        (d / f"Face{i}_0000.rad").write_text((f"#include {MESH_INC}\n" if ref else "#include other.inc\n") + "/BEGIN\n")
    (d / "Face_0001.rad").write_text("/ENGINE\n")
    (d / "material.inc").write_text("mat\n")
    if base:
        (d / MESH_INC).write_text("/NODE\n")
    if csv:
        (d / "RENUM_INIT.csv").write_text("a,b\n")
    (d / "EPS_mesh_0000.rad").write_text("old\n")
    (d / "notes.txt").write_text("x\n")
    (d / "sub").mkdir(exist_ok=True)
    (d / "sub" / "deep.rad").write_text("x\n")
    return d


def _codes(items):
    return [x["code"] for x in items]


def test_v3_s16_6_plan_ok_and_files(settings, tmp_path):
    from physicsai_core.stage4_predict.fem_assembly import plan_assembly, summary

    d = _assem(tmp_path / "ai_root" / "S" / "assem")
    p = plan_assembly(str(d), settings)
    assert p["problems"] == [] and p["warnings"] == []
    assert p["files"] == ["Face0_0000.rad", "Face_0001.rad", "RENUM_INIT.csv", "material.inc"]  # eps_mesh·기준본·txt·하위 제외
    assert p["starter"] == "Face0_0000.rad" and p["inc_count"] == 1 and p["renum_csv"] is True
    assert p["include_baseline"] is True and p["include_referenced"] is True and p["file_count"] == 4
    assert p["total_bytes"] == sum(os.path.getsize(d / n) for n in p["files"])
    assert set(summary(p)) == {"starter", "rad", "inc_count", "renum_csv", "include_baseline", "include_referenced",
                               "file_count", "total_bytes"}


def test_v3_s16_6_plan_problems_and_warnings(settings, tmp_path):
    from physicsai_core.stage4_predict.fem_assembly import plan_assembly

    p0 = plan_assembly(str(_assem(tmp_path / "a0", starters=0)), settings)
    assert _codes(p0["problems"]) == ["ASSEM_STARTER_COUNT"]
    p2 = plan_assembly(str(_assem(tmp_path / "a2", starters=2)), settings)
    assert _codes(p2["problems"]) == ["ASSEM_STARTER_COUNT"] and "Face0_0000.rad, Face1_0000.rad" in p2["problems"][0]["message"]
    w = plan_assembly(str(_assem(tmp_path / "w", csv=False, base=False, ref=False)), settings)
    assert _codes(w["warnings"]) == ["RENUM_CSV_MISSING", "MESH_INCLUDE_NOT_IN_ASSEM", "MESH_INCLUDE_NOT_REFERENCED"]
    assert w["include_referenced"] is False
    settings.fem_verify.include_scan_max_bytes = 1024
    big = _assem(tmp_path / "big", ref=False)
    for n in ("Face0_0000.rad", "Face_0001.rad", "material.inc"):
        (big / n).write_bytes(b"x" * 2048)
    pb = plan_assembly(str(big), settings)
    assert pb["include_referenced"] is None and "MESH_INCLUDE_NOT_REFERENCED" not in _codes(pb["warnings"])
    settings.fem_verify.max_assem_files = 2
    settings.fem_verify.max_assem_bytes = 1048576
    lim = plan_assembly(str(_assem(tmp_path / "lim")), settings)
    assert _codes(lim["problems"]) == ["ASSEM_TOO_MANY_FILES"]
    settings.fem_verify.max_assem_files = 500
    (tmp_path / "lim" / "huge.inc").write_bytes(b"0" * (1048576 + 1))
    assert _codes(plan_assembly(str(tmp_path / "lim"), settings)["problems"]) == ["ASSEM_TOO_LARGE"]
    bad = _assem(tmp_path / "bad")
    (bad / "a&b.inc").write_text("x\n")
    assert _codes(plan_assembly(str(bad), settings)["problems"]) == ["FILE_NAME_UNSAFE"]


def test_v3_s16_6_custom_path_rules(settings, tmp_path):
    from physicsai_core.paths import PathError
    from physicsai_core.stage4_predict.fem_assembly import check_custom_path

    ai = Path(settings.storage.ai_root)
    imp = Path(settings.storage.allowed_import_roots[0])
    spdm = Path(settings.storage.spdm_roots[0])
    a1, a2, a3 = _assem(ai / "S" / "x"), _assem(imp / "y"), _assem(spdm / "proj" / "assem")
    assert check_custom_path(str(a1), settings) == (str(a1), "ai")
    assert check_custom_path(str(a2), settings) == (str(a2), "ai")
    assert check_custom_path(str(a3), settings) == (str(a3), "spdm")
    outside = _assem(tmp_path / "elsewhere")
    bk = _assem(ai / "S" / "_backup" / "z")
    sb = _assem(spdm / "_backup" / "z")
    sp = spdm / "with space"
    sp.mkdir()
    cases = [(str(outside), "PATH_OUTSIDE_ROOT"), (str(bk), "PATH_UNSAFE"), (str(sb), "PATH_UNSAFE"), (str(sp), "PATH_UNSAFE")]
    link = ai / "S" / "lnk"
    try:
        os.symlink(a1, link, target_is_directory=True)
        cases.append((str(link), "PATH_UNSAFE"))
    except OSError:  # Windows 권한 없음 — 링크 경우만 건너뜀
        pass
    for raw, code in cases:
        with pytest.raises(PathError) as ei:
            check_custom_path(raw, settings)
        assert ei.value.code == code, raw


def test_v3_s16_6_snapshot_reads_only(settings, tmp_path):
    from physicsai_core.stage4_predict.fem_assembly import changed, plan_assembly, snapshot

    src = _assem(Path(settings.storage.spdm_roots[0]) / "p" / "assem")
    before = {p.name: p.stat().st_mtime_ns for p in src.iterdir()}
    plan = plan_assembly(str(src), settings)
    dst = tmp_path / "snap"
    assert snapshot(str(src), str(dst), plan["files"]) == plan["files"]
    assert sorted(os.listdir(dst)) == plan["files"]
    assert all((dst / n).read_bytes() == (src / n).read_bytes() for n in plan["files"])
    assert all(os.stat(dst / n).st_ino != os.stat(src / n).st_ino for n in plan["files"])     # 하드링크 아님
    assert {p.name: p.stat().st_mtime_ns for p in src.iterdir()} == before                  # 원본 불변
    assert not changed(plan["signature"], plan_assembly(str(src), settings)["signature"])
    (src / "material.inc").write_text("changed content\n")
    assert changed(plan["signature"], plan_assembly(str(src), settings)["signature"])


def test_v3_s16_6_mesh_parts_and_source_rule(settings, tmp_path):
    from physicsai_core.stage4_predict.fem_assembly import mesh_part_ids, mesh_source_rel, predict_input_ok

    inc = tmp_path / "m.inc"
    inc.write_text("/PART/3000001\nCushion\n/PART/3000002\nx\n/PART/3000001\n/PART/abc\n")
    assert mesh_part_ids(str(inc)) == ["3000001", "3000002"]
    assert mesh_part_ids(str(tmp_path / "none.inc")) == []
    pj = {"params": {"values": {}}}
    assert mesh_source_rel(pj, "J1", settings) == "04_predict/J1/geom/EPS_mesh_0000.rad"
    child = {"params": {"input_mode": "prepared", "batch_run": {"batch_id": "b", "doe_no": 3}}}
    assert mesh_source_rel(child, "J2", settings, batch_dir_rel="04_batch/B-001", run_key="run__00003") == \
        "04_batch/B-001/run__00003/m_1/EPS_mesh_0000.rad"
    assert mesh_source_rel({"params": {"input_mode": "prepared"}}, "J3", settings) is None
    d = tmp_path / "INPUT"
    d.mkdir()
    (d / "Face_0000.rad").write_text("x")
    (d / "EPS_mesh_0000.rad").write_text("x")
    assert predict_input_ok(str(d), "Face_0000.rad") and not predict_input_ok(str(d), "EPS_mesh_0000.rad")
