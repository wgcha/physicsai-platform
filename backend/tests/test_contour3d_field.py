"""v0.2.10 결과 3D 컨투어 현장 보정(contour3d-field.md) — 코어: 추출 TCL(정적·tclsh 가짜 hw), extract_settings·extract_result 해석, 캐시 키,
설정 키·검증, 표시 설정 unit, 새 artifact kind. (워커·API 흐름은 worker/tests/stage4_predict/test_contour3d_field.py)"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from physicsai_test_support import REPO

TCL = REPO / "resources" / "hyperview" / "contour_extract.tcl"
CAPTURE_TCL = REPO / "resources" / "hyperview" / "contour_capture.tcl"
STUB = REPO / "backend" / "tests" / "fake_tools" / "hw_tcl_stub.tcl"
CAPTURE_TCL_SHA256 = "7cc676b9e5b59a93e347d4ebf22e626472da1dd00a3ae2e61cd6acc23a816784"  # v0.2.9(75f38b8) 원본 — 바뀌면 V-GV-16 위반(contour_capture.tcl은 건드리지 않는다)


def _tcl() -> str:
    return TCL.read_text(encoding="utf-8")


def test_v_c3f_1_tcl_static_contract():
    t = _tcl()
    code = "\n".join(ln for ln in t.splitlines() if not ln.lstrip().startswith("#"))
    assert "result scalar unit" not in code  # C3F-14: 단위 조회를 지웠다(F7)
    i_exists, i_source = code.index("file exists $_cfg"), code.index("source $_cfg")
    assert i_exists < i_source  # source 전에 설정 파일 확인(F8)
    assert "extract_settings.tcl not found - run from the platform job folder" in code
    assert "extract_settings.tcl 없음 - 플랫폼 작업 폴더" in code and "실행하세요" in code
    for tok in ("COMPS", "DISP_MAX_NODES", "DISP=$EX_DISP", "DISP_REASON=", "DISP_MISSING_FRAMES=", "SCOPE=$EX_SCOPE", "displayed",
                "GetDataTypeList", "SKIPPED_NODES", "no displacement result type"):
        assert tok in code, tok
    # 변위 조회는 EXTRACT_ERROR로 이어지지 않는다 — node.displacement 조회 주변(±4줄)에 EXTRACT_ERROR 종료가 없다(스칼라 조회와 분리)
    lines = code.splitlines()
    hits = [n for n, ln in enumerate(lines) if "node.displacement" in ln]
    assert len(hits) == 2
    for n in hits:
        assert "ex_finish EXTRACT_ERROR" not in "\n".join(lines[max(0, n - 4): n + 5]), lines[n]
    scal = [n for n, ln in enumerate(lines) if "contour.value" in ln]
    assert scal and "ex_finish EXTRACT_ERROR" in "\n".join(lines[scal[0]: scal[0] + 6])  # 스칼라 조회 실패는 지금처럼 EXTRACT_ERROR
    # NODES·FACES 뜻 정정(F2)
    assert "사용 노드 수" in t and "요소 수" in t
    # 캡처 TCL은 바뀌지 않는다(V-GV-16): COMPS 처리 코드만 재사용(복사)한다
    assert "hwc hide component all" in code and "hwc show component" in code
    assert hashlib.sha256(CAPTURE_TCL.read_bytes()).hexdigest() == CAPTURE_TCL_SHA256


def _tclsh() -> str | None:
    return os.environ.get("PAI_TEST_TCLSH") or shutil.which("tclsh") or shutil.which("tclsh8.6")


needs_tclsh = pytest.mark.skipif(_tclsh() is None, reason="tclsh 없음 — 정적 시험(V-C3F-1)만 돈다")


def _run_tcl(tmp: Path, *, comps: str = "[list]", include_disp: int = 1, disp_max: int = 0, max_frames: int = 3,
             env: dict[str, str] | None = None, with_settings: bool = True) -> tuple[subprocess.CompletedProcess, dict[str, str], dict[str, list[str]]]:
    shutil.copy(TCL, tmp / "contour_extract.tcl")
    if with_settings:
        (tmp / "extract_settings.tcl").write_text(
            f'set H3D_PATH "/x.h3d"\nset OUTDIR "{tmp.as_posix()}"\nset FIELD "Stress"\nset DCOMP "vonMises"\nset AVGMODE ""\n'
            f"set MAX_FRAMES {max_frames}\nset INCLUDE_DISP {include_disp}\nset COMPS {comps}\nset DISP_MAX_NODES {disp_max}\n", encoding="utf-8")
    r = subprocess.run([_tclsh(), str(STUB), str(tmp / "contour_extract.tcl")], capture_output=True, text=True, timeout=60,
                       env={**os.environ, **(env or {})}, cwd=tmp)
    res: dict[str, str] = {}
    rp = tmp / "extract_result.txt"
    if rp.is_file():
        for ln in rp.read_text(encoding="utf-8").splitlines():
            k, _s, v = ln.partition("=")
            if _s:
                res.setdefault(k, v)
    heads = {p.name: p.read_text(encoding="utf-8").splitlines() for p in sorted(tmp.glob("frame_*.csv"))}
    return r, res, heads


@needs_tclsh
def test_v_c3f_1_tcl_runtime_standalone_prints_guide_and_exits(tmp_path):
    r, res, _h = _run_tcl(tmp_path, with_settings=False)
    assert r.returncode == 0 and not res
    assert "extract_settings.tcl not found" in r.stdout and "플랫폼 작업 폴더" in r.stdout


@needs_tclsh
def test_v_c3f_13_tcl_runtime_disp_judged_once_on_first_frame(tmp_path):
    cases = [
        ({}, "ON", "value,dx,dy,dz", {"DISP_MISSING_FRAMES": "0"}),
        ({"STUB_DISP": "error"}, "NONE", "value", {"DISP_REASON": "Invalid command syntax: displacement not available"}),
        ({"STUB_DISP": "empty"}, "NONE", "value", {"DISP_REASON": "empty"}),
        ({"STUB_DISP": "none0"}, "NONE", "value", {"DISP_REASON": "empty"}),
        ({"STUB_DTL": "nodisp"}, "NONE", "value", {"DISP_REASON": "no displacement result type"}),
        ({"STUB_DTL": "error"}, "ON", "value,dx,dy,dz", {}),  # GetDataTypeList 미동작 → 사전 확인 건너뜀, 첫 프레임 판정
        ({"STUB_DTL": "empty"}, "ON", "value,dx,dy,dz", {}),
        ({"STUB_DISP_FAIL_AT": "2"}, "ON", "value,dx,dy,dz", {"DISP_MISSING_FRAMES": "1"}),  # 첫 프레임 이후 누락 → 빈 칸 + 계속
    ]
    partial: dict[str, list[str]] = {}
    for n, (env, disp, head, extra) in enumerate(cases):
        d = tmp_path / f"c{n}"
        d.mkdir()
        r, res, heads = _run_tcl(d, env=env)
        if env.get("STUB_DISP_FAIL_AT"):
            partial = heads
        assert res["STATUS"] == "OK" and res["DISP"] == disp, (env, res)
        assert res["UNIT"] == "" and res["NODES"] == "6" and res["FACES"] == "2" and res["SCOPE"] == "ALL"
        assert len(heads) == 3 and {ln[0] for ln in heads.values()} == {head}, (env, {k: v[0] for k, v in heads.items()})  # 헤더가 모든 프레임에서 같다
        for k, v in extra.items():
            assert res.get(k) == v, (env, k, res)
        assert ("DISP_REASON" in res) == (disp == "NONE")
    # 누락 프레임은 dx,dy,dz가 빈 칸
    assert partial["frame_00001.csv"][1].endswith(",,,") and not partial["frame_00000.csv"][1].endswith(",,,")


@needs_tclsh
def test_v_c3f_13_tcl_runtime_disp_off_and_node_cap_and_errors(tmp_path):
    for n, (kw, env, status, disp) in enumerate([
        ({"include_disp": 0}, {}, "OK", "OFF"),
        ({"disp_max": 5}, {}, "OK", "SKIPPED_NODES"),  # 사용 노드 6 > 5
        ({"disp_max": 6}, {}, "OK", "ON"),
        ({}, {"STUB_SCALAR_FAIL": "1"}, "EXTRACT_ERROR", None),  # 스칼라 조회 실패는 EXTRACT_ERROR
        ({}, {"STUB_OPEN_FAIL": "1"}, "OPEN_ERROR", None),
        ({}, {"STUB_FIELD_FAIL": "1"}, "FIELD_ERROR", None),
    ]):
        d = tmp_path / f"d{n}"
        d.mkdir()
        r, res, heads = _run_tcl(d, env=env, **kw)
        assert res["STATUS"] == status, (kw, env, res)
        if disp:
            assert res["DISP"] == disp and ({ln[0] for ln in heads.values()} == {"value,dx,dy,dz" if disp == "ON" else "value"})
        else:
            assert not heads


@needs_tclsh
def test_v_c3f_13_tcl_runtime_comps_scope_and_fallback(tmp_path):
    d = tmp_path / "ok"
    d.mkdir()
    _r, res, _h = _run_tcl(d, comps='[list "A"]')
    assert res["STATUS"] == "OK" and res["SCOPE"] == "COMPS" and res["NODES"] == "4" and res["FACES"] == "1"
    assert len((d / "nodes.csv").read_text(encoding="utf-8").splitlines()) == 5  # 헤더 + 부품 A 노드 4
    d = tmp_path / "both"
    d.mkdir()
    _r, res, _h = _run_tcl(d, comps='[list "A" "B"]')
    assert res["SCOPE"] == "COMPS" and res["NODES"] == "6" and res["FACES"] == "2"
    for n, env in enumerate(({"STUB_DISPLAYED": "error"}, {"STUB_DISPLAYED": "empty"})):  # 26.1 미확인 명령 폴백 → 전체 + SCOPE=ALL
        d = tmp_path / f"fb{n}"
        d.mkdir()
        _r, res, heads = _run_tcl(d, comps='[list "A"]', env=env)
        assert res["STATUS"] == "OK" and res["SCOPE"] == "ALL" and res["NODES"] == "6" and res["FACES"] == "2" and len(heads) == 3


def test_v_c3f_2_settings_text_comps_ascii_and_disp_max_nodes():
    from physicsai_core.contour3d.settings import settings_text

    t = settings_text(h3d_path="C:\\결과\\a.h3d", out_dir="C:\\x", display={"field": "S", "comps": ["부품b", "a", "a"], "unit": "MPa"},
                      max_frames=5, include_disp=True, disp_max_nodes=1500000)
    t.encode("ascii")
    assert 'set COMPS        [list "a" "\\ubd80\\ud488b"]' in t and "set DISP_MAX_NODES 1500000" in t
    assert "MPa" not in t  # 단위는 TCL에 넘기지 않는다(C3F-14)
    names = [ln.split()[1] for ln in t.splitlines() if ln.startswith("set ")]
    assert names == ["H3D_PATH", "OUTDIR", "FIELD", "DCOMP", "AVGMODE", "MAX_FRAMES", "INCLUDE_DISP", "COMPS", "DISP_MAX_NODES"]  # 기존 키 뒤에 추가
    e = settings_text(h3d_path="/h.h3d", out_dir="/o", display={"field": "S", "comps": []}, max_frames=5, include_disp=False)  # 쿠션 입력
    assert "set COMPS        [list]" in e and "set DISP_MAX_NODES 0" in e and "set INCLUDE_DISP 0" in e


def test_v_c3f_3_parse_result_unit_sanitize_and_new_keys():
    from physicsai_core.contour3d.settings import clean_unit, parse_result

    for bad in ('Invalid command syntax: "result scalar unit"', "ERROR something", "a b", 'x"y', "m:s", "x" * 17, "invalid"):
        assert clean_unit(bad) == "", bad
    assert clean_unit("MPa") == "MPa" and clean_unit(" mm ") == "mm" and clean_unit("N/mm^2") == "N/mm^2"
    r = parse_result('# contour_extract 1\nSTATUS=OK\nUNIT=Invalid command syntax: "result scalar unit"\nNODES=5\nFACES=2\nFRAMES_TOTAL=22\n'
                     "DISP=none\nDISP_REASON=no displacement result type\nDISP_MISSING_FRAMES=2\nSCOPE=comps\nFRAME=0|0|Time = 0\n")
    assert r["unit"] == "" and r["disp"] == "NONE" and r["disp_reason"] == "no displacement result type"
    assert r["disp_missing_frames"] == 2 and r["scope"] == "COMPS" and r["nodes"] == 5 and r["header_ok"]
    assert parse_result("# contour_extract 1\nUNIT=MPa\n")["unit"] == "MPa"
    old = parse_result("# contour_extract 1\nSTATUS=OK\nNODES=6\n")  # 예전 TCL(새 키 없음)
    assert old["disp"] is None and old["scope"] is None and old["disp_missing_frames"] == 0 and old["disp_reason"] == ""
    assert parse_result("DISP=BOGUS\nSCOPE=X\nDISP_MISSING_FRAMES=a\n")["disp"] is None


def test_v_c3f_4_cache_key_elements():
    from physicsai_core.contour3d.settings import CONVERTER_VERSION, cache_key, limits_of, tcl_hash
    from physicsai_core.config import load_config_dict

    assert CONVERTER_VERSION == 2
    c3 = load_config_dict({"storage": {"ai_root": "/tmp"}}, environ={}).settings.contour3d
    base = dict(source_kind="PREDICT_H3D", source_id="job:1", h3d_size=10, h3d_mtime_ns=5, display={"field": "S", "component": "vM"},
                max_frames=55, include_disp=True, comps=["a", "b"], limits=limits_of(c3), lod_min_nodes=500000,
                lod_target_vertices=100000, meshopt=True, extract_tcl="0123456789abcdef")
    k0 = cache_key(**base)
    assert k0 == cache_key(**base)
    assert cache_key(**{**base, "comps": ["b", "a", "a", " b "]}) == k0  # 순서·중복·공백은 영향 없음
    changes = {
        "comps": ["a"], "max_frames": 50, "include_disp": False, "lod_min_nodes": 1, "lod_target_vertices": 2000, "meshopt": False,
        "extract_tcl": "ffffffffffffffff", "h3d_size": 11, "h3d_mtime_ns": 6, "source_id": "job:2",
        "display": {"field": "S", "component": "vM", "unit": "MPa"},
    }
    for k, v in changes.items():
        assert cache_key(**{**base, k: v}) != k0, k
    for lk in ("max_nodes", "max_glb_bytes", "max_bin_bytes", "max_disp_bytes", "disp_max_nodes"):  # 상한이 키에 들어간다(F4)
        assert cache_key(**{**base, "limits": {**base["limits"], lk: base["limits"][lk] + 1}}) != k0, lk
    # 오류 문구 단위는 빈 값과 같다(키가 오류 문구로 갈라지지 않는다)
    assert cache_key(**{**base, "display": {"field": "S", "component": "vM", "unit": 'Invalid "x"'}}) == k0
    f = REPO / "resources" / "hyperview" / "contour_extract.tcl"
    h = tcl_hash(str(f))
    assert len(h) == 16 and h == hashlib.sha256(f.read_bytes()).hexdigest()[:16] and tcl_hash("") == "" and tcl_hash("/nope/x.tcl") == ""


def test_v_c3f_tcl_hash_follows_content_change(tmp_path):
    from physicsai_core.contour3d.settings import tcl_hash

    p = tmp_path / "x.tcl"
    p.write_text("a", encoding="utf-8")
    h1 = tcl_hash(str(p))
    p.write_text("bb", encoding="utf-8")
    assert tcl_hash(str(p)) != h1  # 크기가 달라진 파일은 메모를 쓰지 않는다


def test_c3f_messages_and_codes():
    from physicsai_core.contour3d.settings import DETERMINISTIC_FAILS, message_ko

    assert "변위가 없어" in message_ko("CONTOUR3D_DISP_UNAVAILABLE") and "부품 이름" in message_ko("CONTOUR3D_COMPS_IGNORED")
    assert message_ko("CONTOUR3D_DISP_DROPPED") and message_ko(None) is None
    assert DETERMINISTIC_FAILS == ("CONTOUR3D_TOO_LARGE", "CONTOUR3D_FIELD_EMPTY")


def test_c3f_config_defaults_and_validation():
    from physicsai_core.config import load_config_dict

    base = {"storage": {"ai_root": "/tmp"}}
    ok = load_config_dict(base, environ={})
    c = ok.settings.contour3d
    assert (c.max_frames, c.max_nodes, c.max_glb_bytes, c.max_bin_bytes, c.max_disp_bytes) == (55, 2000000, 67108864, 268435456, 1073741824)
    assert (c.disp_max_nodes, c.lod_min_nodes, c.lod_target_vertices, c.meshopt, c.include_disp, c.timeout_s) == (1500000, 500000, 100000, True, True, 1800)
    assert ok.settings.geometry.view.cache.max_total_bytes == 4294967296 and c.enabled is False
    old = load_config_dict({**base, "contour3d": {"max_nodes": 300000}}, environ={})  # 현장 yaml의 예전 값은 그대로(경고·오류 없음)
    assert old.ok and old.settings.contour3d.max_nodes == 300000
    bad = load_config_dict({**base, "contour3d": {"max_frames": 501, "max_glb_bytes": 1023, "max_disp_bytes": 5, "disp_max_nodes": -1,
                                                   "lod_min_nodes": -1, "lod_target_vertices": 999}}, environ={})
    keys = {i.key for i in bad.issues}
    assert {"contour3d.max_frames", "contour3d.max_glb_bytes", "contour3d.max_disp_bytes", "contour3d.disp_max_nodes",
            "contour3d.lod_min_nodes", "contour3d.lod_target_vertices"} <= keys
    edge = load_config_dict({**base, "contour3d": {"max_frames": 500, "disp_max_nodes": 0, "lod_min_nodes": 0, "lod_target_vertices": 1000,
                                                    "max_glb_bytes": 1024, "max_disp_bytes": 1024}}, environ={})
    assert edge.ok, edge.issues
    assert load_config_dict({**base, "contour3d": {"lod_target_vertices": 1000001}}, environ={}).ok is False
    yaml_text = (REPO / "config" / "platform.example.yaml").read_text(encoding="utf-8")
    import yaml

    ex = yaml.safe_load(yaml_text)["contour3d"]
    assert ex["max_frames"] == 55 and ex["max_nodes"] == 2000000 and ex["max_glb_bytes"] == 67108864 and ex["meshopt"] is True
    assert yaml.safe_load(yaml_text)["geometry"]["view"]["cache"]["max_total_bytes"] == 4294967296


def test_c3f_display_unit_key():
    from physicsai_core.stage4_predict import contour_capture as cc

    assert "unit" in cc.DISPLAY_KEYS
    assert cc.validate_display({"unit": "MPa"}) == [] and cc.clean_display({"unit": "MPa", "field": "S"}) == {"field": "S", "unit": "MPa"}
    assert cc.validate_display({"unit": "x" * 17}) and cc.validate_display({"unit": 'a"b'}) and cc.validate_display({"unit": 3})
    from physicsai_core.config import load_config_dict

    cap = load_config_dict({"storage": {"ai_root": "/tmp"}}, environ={}).settings.capture
    d, _ = cc.resolve_display(cap, {"display": {"unit": "MPa"}}, {"comps": ["A"]})
    assert d["unit"] == "MPa" and d["comps"] == ["A"]
    assert cc.resolve_display(cap, None)[0]["unit"] == ""
    # PNG 캡처 설정에는 단위가 들어가지 않는다
    t = cc.settings_text(h3d_path="/h.h3d", out_dir="/o", display={**d, "legend": {"mode": "auto"}}, views=["iso"], save_video=False,
                         video_ext="mp4", use_last=True)
    assert "MPa" not in t and "UNIT" not in t


def test_c3f_artifact_kinds_in_metadata_and_media_lists():
    from physicsai_core.db.tables import artifacts
    from physicsai_core.geometry.view import CONTOUR_KINDS, GLB_KINDS, MEDIA_KINDS

    chk = str([c.sqltext for c in artifacts.constraints if getattr(c, "name", "") == "ck_artifacts_kind"][0])
    for k in ("CONTOUR3D_DISP", "CONTOUR3D_LOD"):
        assert k in chk and k in CONTOUR_KINDS and k in MEDIA_KINDS
    assert "CONTOUR3D_LOD" in GLB_KINDS and "CONTOUR3D_DISP" not in GLB_KINDS
    mig = (REPO / "migrations" / "versions" / "0024_contour3d_field.py").read_text(encoding="utf-8")
    assert re.search(r'^revision = "0024_contour3d_field"', mig, re.M) and re.search(r'^down_revision = "0023_doe_methods"', mig, re.M)
    from physicsai_core.db import MIGRATION_HEAD

    assert MIGRATION_HEAD == "0024_contour3d_field"
