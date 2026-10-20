"""쉘 판금 모핑 플랫폼 연동(shell-morph.md §8)·형상 3D 가시화(geometry-view.md §6)·결과 3D 컨투어 변환(§13.4) 순수 함수 시험."""

from __future__ import annotations

import json
import math
import os
import struct

import pytest

from physicsai_core.commands import render_argv, validate_template
from physicsai_core.config.schema import Settings


# ---- 쉘 옵션·파라미터 표 ---------------------------------------------------------------------------------------------


def test_shell_options_defaults_and_ranges():
    from physicsai_core.geometry.shell_options import effective_shell_options, prep_options_sha256

    opts, probs = effective_shell_options({}, None)
    assert probs == [] and opts["fixed"]["kinds"][:2] == ["INTER_TYPE2", "RBE2"] and opts["quality"]["max_warpage_deg"] == 15.0
    _o, probs = effective_shell_options(None, {"fixed": {"kinds": ["RBE2"]}})
    assert [p["key"] for p in probs] == ["fixed.kinds"]  # INTER_TYPE2·RBE2 필수(SM §4.10)
    _o, probs = effective_shell_options(None, {"quality": {"min_stretch": 0.1}, "thickness_ref": "x"})
    assert {p["key"] for p in probs} == {"quality.min_stretch", "thickness_ref"}  # 솔리드 키는 모르는 키
    a, _ = effective_shell_options(None, {"fixed": {"transition_mm": 9.0}})
    b, _ = effective_shell_options(None, {"tag": {"tol_abs_mm": 0.07}})
    assert prep_options_sha256(a) == prep_options_sha256(opts) != prep_options_sha256(b)  # 전이 폭은 준비본 무관


def _shell_doc():
    return {"kind": "shell", "parts": [{"body": "CHASSIS_REAR", "part_id": 2001, "title": "CHASSIS_REAR"},
                                       {"body": "BRKT", "part_id": 2002, "title": "BRKT"}],
            "features": [
                {"name": "CHASSIS_REAR_BEAD_D_1", "body": "CHASSIS_REAR", "nominal": 4.0, "range": {"min": 3.8, "max": 4.2}},
                {"name": "CHASSIS_REAR_BEAD_D_2", "body": "CHASSIS_REAR", "nominal": 3.0, "range": {"min": 2.9, "max": 3.1},
                 "use_default": False},
                {"name": "BRKT_BEAD_D_1", "body": "BRKT", "nominal": 2.0, "range": {"min": 1.9, "max": 2.1}}],
            "groups": []}


def test_shell_rows_component_filter_and_use_default():
    from physicsai_core.geometry.shell_native import shell_rows, target_part_ids

    rows, warns = shell_rows(_shell_doc(), "chassis_rear")  # 대소문자 무시(설정 shell.default_component)
    assert [r["name"] for r in rows] == ["CHASSIS_REAR_BEAD_D_1", "CHASSIS_REAR_BEAD_D_2"]
    assert all(r["source"] == "shell" for r in rows) and rows[1]["use"] is False and "use" not in rows[0]
    assert warns and "BRKT_BEAD_D_1" in warns[0]
    assert shell_rows(_shell_doc(), "nothing")[0] == []
    assert target_part_ids(_shell_doc(), "CHASSIS_REAR") == [2001]


def test_kind_mix_and_thickness_document():
    from physicsai_core.geometry.shell_native import kind_mix_problems, thickness_document

    solid = {"name": "A_THK_1"}
    shell = {"name": "CHASSIS_REAR_BEAD_D_1", "source": "shell"}
    prop = {"name": "PANEL_T", "source": "prop"}
    assert kind_mix_problems([shell, prop], "shell") == [] and kind_mix_problems([solid, prop], "solid") == []
    assert kind_mix_problems([shell, solid], "shell")[0]["code"] == "GEOM_KIND_MIXED"
    assert kind_mix_problems([shell, solid], "solid")[0]["code"] == "GEOM_KIND_MIXED"
    props = {"props": [{"parameter": "CH_T", "parts": [{"id": 2001}]}, {"parameter": "BR_T", "parts": [{"id": 9}]}]}
    assert thickness_document([], props, {"CH_T": 0.9, "BR_T": 1.1}, [2001]) == {"schema_version": 1, "parts": {"2001": 0.9}}
    assert thickness_document([], props, {"BR_T": 1.1}, [2001]) is None


def test_assem_digest_deterministic_and_sensitive(tmp_path):
    from physicsai_core.geometry.shell_native import assem_digest

    (tmp_path / "a.rad").write_text("/BEGIN\n")
    (tmp_path / "inc").mkdir()
    (tmp_path / "inc" / "chassis.inc").write_text("/NODE\n1 0 0 0\n")
    (tmp_path / "note.txt").write_text("ignored")
    d1 = assem_digest(str(tmp_path))
    assert d1 == assem_digest(str(tmp_path)) and d1.startswith("sha256:")
    (tmp_path / "note.txt").write_text("changed")  # *.rad·*.inc만
    assert assem_digest(str(tmp_path)) == d1
    (tmp_path / "inc" / "chassis.inc").write_text("/NODE\n1 0 0 1\n")
    assert assem_digest(str(tmp_path)) != d1
    assert assem_digest(str(tmp_path / "none")) is None


def test_shell_prep_state_ready_stale(tmp_path):
    from physicsai_core.geometry.prep import prep_document, prep_state
    from physicsai_core.geometry.shell_options import effective_shell_options

    S = tmp_path / "S"
    for rel in ("cad/mid.step", "radioss_assem/model_0000.rad", "native/extract/shell_features.json", "native/tag/shell_tag.json",
                "native/fixed/shell_scan.json"):
        (S / rel).parent.mkdir(parents=True, exist_ok=True)
        (S / rel).write_text("{}" if rel.endswith(".json") else "x")
    opts, _ = effective_shell_options(None, None)
    doc = prep_document(str(S), step_exts=[".step"], mesh_include_name="m.inc", renum_csv_name="R.csv", opts=opts, engine_version="0.8.0",
                        ocp_version=None, job_id=None, created_at="t", kind="shell", component="chassis_rear")
    assert doc["kind"] == "shell" and doc["inputs"]["baseline_inc"] is None and doc["inputs"]["assem_digest"].startswith("sha256:")
    (S / "native" / "prep.json").write_text(json.dumps(doc))
    kw = dict(step_exts=[".step"], mesh_include_name="m.inc", renum_csv_name="R.csv")
    assert prep_state(str(S), opts=opts, current_engine_version="0.8.3", **kw).status == "READY"
    assert prep_state(str(S), opts=opts, current_engine_version="0.9.0", **kw).status == "STALE"
    other, _ = effective_shell_options(None, {"fixed": {"tol_mm": 0.01}})
    assert prep_state(str(S), opts=other, **kw).status == "STALE"
    (S / "radioss_assem" / "model_0000.rad").write_text("y")  # 조립 폴더 변경 → assem_digest 불일치
    assert prep_state(str(S), opts=opts, **kw).status == "STALE"


def test_shell_messages_korean_and_fixed_category():
    from physicsai_core.geometry.messages import category_of, korean_message

    assert category_of("SHELL_FIXED_REGION_VIOLATION") == "FIXED"
    assert korean_message("SHELL_FIXED_REGION_VIOLATION", "fixed node 12 moved").startswith("고정 영역(tie·RBE2) 침범")
    assert korean_message("SHELL_BODY_NOT_SHEET").startswith("중립면") and korean_message("VIEW_TOO_LARGE").startswith("3D 형상")


# ---- 명령 템플릿 ---------------------------------------------------------------------------------------------------


def test_shell_and_view_templates_render_optional_pairs():
    s = Settings()
    exe = {"paicad_path": "/opt/paicad"}
    for k in ("paicad_shell_fixed_scan", "paicad_shell_extract", "paicad_shell_tag", "paicad_shell_update", "paicad_shell_morph",
              "paicad_shell_check", "paicad_shell_run", "paicad_view_export", "paicad_view_preview", "contour_extract"):
        assert validate_template(k, getattr(s.commands, k)) == [], k
    assert s.commands.paicad_shell_view_export is None  # paicad 0.9.0에는 shell view가 없다(기본 꺼짐)
    v = {"cad_input": "/s/cad/m.step", "assem_dir": "", "options_json": "/s/o.json", "out_dir": "/s/x"}
    argv = render_argv("paicad_shell_extract", s.commands.paicad_shell_extract, v, executables=exe, is_windows=False)
    assert "--assem-dir" not in argv and argv[1:3] == ["shell", "extract"]  # ①-1: 조립 폴더 없음 → 쌍 생략
    chk = {k: f"/s/{k}" for k in ("assem_dir", "morph_dir", "update_dir", "tag_dir", "fixed_dir", "features_json", "values_json",
                                  "options_json", "check_dir", "out_files_dir")}
    argv = render_argv("paicad_shell_check", s.commands.paicad_shell_check, {**chk, "thickness_json": ""}, executables=exe, is_windows=False)
    assert "--thickness" not in argv and "--out-files-dir" in argv
    argv = render_argv("paicad_shell_check", s.commands.paicad_shell_check, {**chk, "thickness_json": "/s/t.json"}, executables=exe,
                       is_windows=False)
    assert argv[argv.index("--thickness") + 1] == "/s/t.json"
    pv = {k: f"/s/{k}" for k in ("cad_input", "features_json", "values_json", "tag_dir", "options_json", "view_options_json",
                                 "baseline_inc", "renum_csv", "assem_dir", "out_dir")}
    argv = render_argv("paicad_view_preview", s.commands.paicad_view_preview, {**pv, "nominal_manifest": "", "fe_mode": "off",
                                                                                "threads": "2"}, executables=exe, is_windows=False)
    assert "--nominal-manifest" not in argv and argv[argv.index("--fe") + 1] == "off" and argv[argv.index("--threads") + 1] == "2"
    argv = render_argv("contour_extract", s.commands.contour_extract, {"contour_extract_tcl": "C:\\c\\x.tcl"},
                       executables={"hw_exe_path": "C:\\hw.exe"}, is_windows=True)
    assert argv[-1] == "C:/c/x.tcl"  # '/' 표기(capture_tcl과 같은 규칙)


def test_config_validation_view_contour_shell():
    from physicsai_core.config import load_config_dict

    base = {"storage": {"ai_root": "/tmp"}}
    bad = load_config_dict({**base, "geometry": {"view": {"tess": {"linear_mm": 0, "angular_deg": 50}, "max_concurrent": 0},
                                                 "shell_defaults": {"fixed": {"kinds": ["RBE3"]}},
                                                 "timeout_s": {"shell_update": -1, "bogus": 1}},
                            "shell": {"default_component": "a b"}, "contour3d": {"max_frames": 1}}, environ={})
    keys = {i.key for i in bad.issues}
    assert {"geometry.view.tess.linear_mm", "geometry.view.tess.angular_deg", "geometry.view.max_concurrent", "geometry.shell_defaults",
            "geometry.timeout_s.shell_update", "geometry.timeout_s.bogus", "shell.default_component", "contour3d.max_frames"} <= keys
    ok = load_config_dict({**base, "geometry": {"view": {"max_glb_bytes": 99999999999}}}, environ={})
    assert "geometry.view.max_glb_bytes" in {w.key for w in ok.warnings}
    from physicsai_core.geometry.view import view_options_document

    assert view_options_document(ok.settings)["max_glb_bytes"] == ok.settings.ui.max_artifact_bytes  # ui 상한으로 자름


# ---- 미리보기 캐시 키·판정·정리 경로 -------------------------------------------------------------------------------------


def test_preview_cache_key_and_judge():
    from physicsai_core.geometry.view import judge_preview, prep_digest, preview_cache_key

    pd = prep_digest({"inputs": {"a": 1}, "tag_options_sha256": "t"}, {"tag": {}})
    kw = dict(param_set_id="p", kind="solid", prep_digest=pd, view_tess={"linear_mm": 0.1, "angular_deg": 20}, fe="off",
              engine_version="0.9.0")
    k1 = preview_cache_key(values={"A": 1, "B": 2.0}, **kw)
    assert k1 == preview_cache_key(values={"B": 2, "A": 1.0}, **kw) and len(k1) == 64  # 정규 JSON(키 정렬·float)
    assert k1 != preview_cache_key(values={"A": 1.0000001, "B": 2.0}, **kw)
    assert k1 != preview_cache_key(values={"A": 1, "B": 2.0}, **{**kw, "fe": "check"})
    assert k1 != preview_cache_key(values={"A": 1, "B": 2.0}, **{**kw, "engine_version": "0.9.1"})
    assert prep_digest({"inputs": {"a": 1}}, {"quality": {"x": 1}}) != prep_digest({"inputs": {"a": 1}}, {"quality": {"x": 2}})
    assert judge_preview({"status": "OK"})["cacheable"]
    j = judge_preview({"status": "FAIL", "code": "GEOM_FEATURE_COLLISION", "category": "CAD_FAILED"})
    assert j["cacheable"] and j["result_status"] == "FAIL"  # GV-10 결정적 실패도 캐시
    assert not judge_preview({"status": "FAIL", "code": "VIEW_TOO_LARGE", "category": "VIEW"})["cacheable"]
    assert not judge_preview(None)["cacheable"]


def test_safe_cache_dir_rejects_escape_and_links(tmp_path):
    from physicsai_core.geometry.view import PREVIEW_CACHE, safe_cache_dir

    root = tmp_path / "study"
    ok = root / "_cache" / "geom_preview" / "ab" / "abc"
    ok.mkdir(parents=True)
    assert safe_cache_dir(str(root), str(ok), PREVIEW_CACHE)
    assert not safe_cache_dir(str(root), str(root / "04_params"), PREVIEW_CACHE)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "_cache" / "geom_preview" / "cd"
    os.symlink(outside, link)
    assert not safe_cache_dir(str(root), str(link / "x"), PREVIEW_CACHE)


# ---- 결과 3D 컨투어 변환 ---------------------------------------------------------------------------------------------


def _extract(d, *, frames=5, disp=True, faces=True, nan=False, rows_short=False, status="OK"):
    d.mkdir(parents=True, exist_ok=True)
    coords = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0)]
    (d / "nodes.csv").write_text("node_id,x,y,z\n" + "".join(f"{101 + i},{c[0]},{c[1]},{c[2]}\n" for i, c in enumerate(coords)))
    if faces:
        (d / "faces.csv").write_text("elem_id,n1,n2,n3,n4\n1,101,102,105,104\n2,102,103,106,105\n3,101,101,102,\n")
    lines = ["# contour_extract 1", f"STATUS={status}", "UNIT=MPa", "FIELD=Stress", "DCOMP=vonMises", "AVGMODE=simple",
             f"NODES={len(coords)}", "FACES=2", f"FRAMES_TOTAL={frames}"]
    for i in range(frames):
        lines.append(f"FRAME={i}|{i * 2}|Time = {0.001 * i:g}")
        n = len(coords) - (1 if rows_short else 0)
        body = "".join((("" if nan else repr(float(j * i))) + (f",0,0,{0.1 * i}" if disp else "") + "\n") for j in range(n))
        (d / f"frame_{i:05d}.csv").write_text(("value,dx,dy,dz\n" if disp else "value\n") + body)
    (d / "extract_result.txt").write_text("\n".join(lines) + "\n")


def _conv(tmp_path, **kw):
    from physicsai_core.contour3d.convert import convert

    lim = {"max_nodes": 1000, "max_bin_bytes": 1 << 20, "max_frames": 50}
    lim.update({k: kw.pop(k) for k in list(kw) if k in lim})
    _extract(tmp_path / "x", **kw)
    return convert(str(tmp_path / "x"), str(tmp_path / "out"), source={"kind": "PREDICT_H3D", "ref": {"job_id": "j"}}, **lim)


def test_contour_convert_ok_glb_and_frame_major_bin(tmp_path):
    from physicsai_core.contour3d.glb import read_glb_json

    man = _conv(tmp_path)
    assert man["status"] == "OK" and man["unit"] == "MPa" and man["display"]["comp"] == "vonMises"
    assert man["mesh"]["nodes"] == 6 and man["mesh"]["triangles"] == 4  # 쿼드 2개 → 4, 퇴화 면 1개 건너뜀
    assert [w["code"] for w in man["warnings"]] == ["CONTOUR3D_FACE_SKIPPED"]
    data = (tmp_path / "out" / "contour.glb").read_bytes()
    doc = read_glb_json(data)
    acc = doc["accessors"]
    assert doc["meshes"][0]["primitives"][0]["attributes"] == {"POSITION": 0, "NORMAL": 1, "_NODE_ID": 2}
    assert acc[0]["min"] == [0.0, 0.0, 0.0] and acc[0]["max"] == [2.0, 1.0, 0.0] and acc[3]["count"] == 12 and acc[3]["componentType"] == 5123
    assert "extensionsUsed" not in doc and len(data) % 4 == 0
    fr = man["frames"]
    assert fr["count"] == 5 and fr["has_disp"] and fr["record_bytes"] == 4 * 6 * 4
    raw = (tmp_path / "out" / "contour_frames.bin").read_bytes()
    assert len(raw) == fr["bytes"] == 5 * fr["record_bytes"]
    rec3 = struct.unpack_from("<6f", raw, 3 * fr["record_bytes"])  # 프레임 3 스칼라(노드 j → j·3)
    assert list(rec3) == [0.0, 3.0, 6.0, 9.0, 12.0, 15.0]
    dz = struct.unpack_from("<18f", raw, 3 * fr["record_bytes"] + 4 * 6)[2]
    assert math.isclose(dz, 0.3, rel_tol=1e-6)
    assert fr["list"][2] == {"i": 2, "src": 4, "time": 0.002, "min": 0.0, "max": 10.0} and man["range"] == {"min": 0.0, "max": 20.0}
    man2 = _conv(tmp_path / "again")
    assert (tmp_path / "again" / "out" / "contour.glb").read_bytes() == data and man2["frames"]["sha256"] == fr["sha256"]  # 결정적


def test_contour_convert_elements_external_faces(tmp_path):
    from physicsai_core.contour3d.convert import convert

    d = tmp_path / "x"
    _extract(d, faces=False, frames=2, disp=False)
    coords = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1), (2, 0, 0), (2, 1, 0), (5, 5, 5)]
    (d / "nodes.csv").write_text("node_id,x,y,z\n" + "".join(f"{101 + i},{c[0]},{c[1]},{c[2]}\n" for i, c in enumerate(coords)))
    for i in range(2):
        (d / f"frame_{i:05d}.csv").write_text("value\n" + "".join(f"{j}\n" for j in range(len(coords))))
    # 육면체 1개(외부 면 6) + 쿼드 쉘 1 + 노드 111(어느 요소에도 안 쓰임 → 제외)
    (d / "elements.csv").write_text("elem_id,config,n1,n2,n3,n4,n5,n6,n7,n8\n1,208,101,102,103,104,105,106,107,108\n"
                                    "2,104,102,109,110,103,,,,\n")
    man = convert(str(d), str(tmp_path / "out"), source={"kind": "SOLVER_H3D", "ref": {}}, max_nodes=100, max_bin_bytes=1 << 20,
                  max_frames=50)
    assert man["status"] == "OK" and man["mesh"]["nodes"] == 10 and man["mesh"]["triangles"] == 6 * 2 + 2


def test_contour_convert_limits_and_failures(tmp_path):
    from physicsai_core.contour3d.convert import ConvertError, resample

    assert resample(200, 50)[:3] == [0, 4, 8] and resample(200, 50)[-1] == 199 and resample(3, 50) == [0, 1, 2]
    assert _conv(tmp_path / "a", max_nodes=5)["code"] == "CONTOUR3D_TOO_LARGE"
    m = _conv(tmp_path / "b", frames=10, max_bin_bytes=4 * 6 * 4 * 4)  # 프레임 4개만 들어감 → 균등 재샘플링
    assert m["status"] == "OK" and m["frames"]["count"] == 4 and m["sampling"]["total_frames"] == 10
    m = _conv(tmp_path / "c", frames=10, max_bin_bytes=4 * 6 * 3)  # 변위 포함 1프레임도 못 넣음 → 변위 제외 → 3프레임
    assert m["frames"]["has_disp"] is False and m["frames"]["count"] == 3 and "CONTOUR3D_DISP_DROPPED" in [w["code"] for w in m["warnings"]]
    assert _conv(tmp_path / "d", frames=4, max_bin_bytes=10)["code"] == "CONTOUR3D_TOO_LARGE"
    m = _conv(tmp_path / "e", nan=True)
    assert m["status"] == "FAIL" and m["code"] == "CONTOUR3D_FIELD_EMPTY" and not (tmp_path / "e" / "out" / "contour_frames.bin").exists()
    with pytest.raises(ConvertError) as ei:
        _conv(tmp_path / "f", rows_short=True)
    assert ei.value.code == "CONTOUR3D_EXTRACT_INVALID"
    with pytest.raises(ConvertError) as ei:
        _conv(tmp_path / "g", status="OPEN_ERROR")
    assert ei.value.code == "CONTOUR3D_OPEN_ERROR"


def test_contour_settings_text_and_cache_key():
    from physicsai_core.contour3d.settings import cache_key, parse_result, settings_text

    t = settings_text(h3d_path="C:\\결과 폴더\\pred.h3d", out_dir="C:\\x", display={"field": "Stress", "component": "vM", "avgmode": ""},
                      max_frames=50, include_disp=True)
    t.encode("ascii")
    assert 'set H3D_PATH     "C:/\\uacb0\\uacfc \\ud3f4\\ub354/pred.h3d"' in t and "set MAX_FRAMES   50" in t and "INCLUDE_DISP 1" in t
    r = parse_result("# contour_extract 1\nSTATUS=OK\nNODES=6\nFRAME=0|0|Time = 0\nFRAME=1|4|0.0012\n")
    assert r["header_ok"] and r["nodes"] == 6 and r["frames"] == [(0, 0, 0.0), (1, 4, 0.0012)]
    kw = dict(source_kind="PREDICT_H3D", source_id="job:1", h3d_size=10, h3d_mtime_ns=5, display={"field": "S"}, max_frames=50,
              include_disp=True)
    assert cache_key(**kw) == cache_key(**kw) != cache_key(**{**kw, "h3d_mtime_ns": 6})


def test_contour_phase_mapping():
    from physicsai_api.services.contour3d_api import phase_of

    assert phase_of("QUEUED", "QUEUED", None, None) == "waiting"
    assert phase_of("RUNNING", "RUNNING", "C3_EXTRACT", 40) == "reading_h3d"
    assert phase_of("RUNNING", "RUNNING", "C3_CONVERT", 10) == "geometry"
    assert phase_of("RUNNING", "RUNNING", "C3_CONVERT", 55) == "frames"
    assert phase_of("DONE", "SUCCEEDED", None, None) == "done" and phase_of("CANCELED", "CANCELED", None, None) == "canceled"
