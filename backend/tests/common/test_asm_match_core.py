"""조립 매칭 코어(asm-match.md): 명령 쌍 치환(AM-10)을 실제 paicad CLI 파서로 검증 · include 트리 digest가 paicad와 같은 규칙 ·
rows_sha256·행 검증(V-AM-9 사유 코드) · 확정본 문서 · 방식 판별."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from physicsai_core.commands import render_argv
from physicsai_core.commands_asm import ASM_EXTRA_PLACEHOLDERS, expand, is_matched
from physicsai_core.commands_spec import TEMPLATE_SPECS
from physicsai_core.config.schema import Settings
from physicsai_core.geometry import asm_match as am
from physicsai_core.geometry import asm_tree as at

EXE = {"paicad_path": "/opt/paicad"}


def _values(key: str, **over: str) -> dict[str, str]:
    base = {n: f"/s/{n}" for n in TEMPLATE_SPECS[key].placeholders if n != "paicad"}
    base.update({"threads": "2", "fe_mode": "off", "usage": "topology", "split_param": "", "user_map": "", "thickness_json": ""})
    base.update(over)
    return {k: v for k, v in base.items() if k in TEMPLATE_SPECS[key].placeholders | ASM_EXTRA_PLACEHOLDERS}


def _argv(key: str, **over: str) -> list[str]:
    s = Settings()
    return render_argv(key, getattr(s.commands, key), _values(key, **over), executables=EXE, is_windows=False)


def _parse(argv: list[str]):
    from paicad.cli import _parser

    return _parser().parse_args(argv[1:])


# ---- 쌍 치환(AM-10) -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("key,cmd", [("paicad_tag", "tag"), ("paicad_morph", "morph"), ("paicad_check", "check"), ("paicad_run", "run")])
def test_matched_templates_parse_with_real_paicad(key, cmd):
    """방식 M 인자(--asm-match·--assem-dir·--cache-dir·--out-patch)가 paicad 0.13.0 파서에서 그대로 받아들여진다. --renum-csv·--baseline-inc 없음."""
    argv = _argv(key, asm_match="/s/asm_match.json", asm_cache_dir="/s/cache", out_patch="/s/p.npz", baseline_inc="", renum_csv="",
                 assem_dir="/s/assem")
    ns = _parse(argv)
    assert ns.cmd == cmd and ns.asm_match == "/s/asm_match.json" and ns.cache_dir == "/s/cache" and ns.assem_dir
    assert not ns.baseline_inc and not getattr(ns, "renum_csv", None) and not getattr(ns, "out_inc", None)
    if cmd in ("check", "run"):
        assert ns.out_patch == "/s/p.npz"


def test_legacy_template_unchanged_without_asm_match():
    """방식 L(값에 asm_match 없음) argv는 기존 그대로 — --renum-csv·--baseline-inc가 남고 --asm-match가 생기지 않는다."""
    argv = _argv("paicad_tag")
    assert "--renum-csv" in argv and "--baseline-inc" in argv and "--asm-match" not in argv
    ns = _parse(argv)
    assert ns.renum_csv and ns.baseline_inc and ns.asm_match is None


def test_cushion_write_matched_patch_pair():
    argv = _argv("paicad_cushion_write", asm_match="/s/asm_match.json", asm_cache_dir="/s/c", cushion_inc="", renum_csv="", node_patch="/s/n.npz")
    assert argv[argv.index("--patch") + 1] == "/s/n.npz" and "--inc" not in argv and "--renum-csv" not in argv
    nominal = _argv("paicad_cushion_write", asm_match="/s/asm_match.json", asm_cache_dir="/s/c", cushion_inc="", renum_csv="", node_patch="")
    assert "--patch" not in nominal and "--asm-match" in nominal  # 공칭 = 패치 없음
    ns = _parse(nominal)
    assert ns.cmd == "cushion" and ns.asm_match == "/s/asm_match.json"


def test_asm_commands_parse_with_real_paicad():
    ns = _parse(_argv("paicad_asm_parts", features_json="/s/f.json", cad_input="", renum_csv=""))
    assert ns.cmd == "asm" and ns.features == "/s/f.json" and not ns.renum_csv
    cad = _parse(_argv("paicad_asm_parts", features_json="", cad_input="/s/m.step", renum_csv="/s/RENUM.csv"))  # ④: --features → --cad
    assert cad.cad == "/s/m.step" and cad.features is None and cad.renum_csv == "/s/RENUM.csv"
    chk = _parse(_argv("paicad_asm_check", features_json="", cad_input="/s/m.step", match_rows_json="/s/m.json"))
    assert chk.match == "/s/m.json" and chk.features is None
    wr = _parse(_argv("paicad_asm_write", asm_match="/s/a.json", node_patch="/s/n.npz"))
    assert wr.patch == "/s/n.npz" and wr.asm_match == "/s/a.json"
    assert "--patch" not in _argv("paicad_asm_write", asm_match="/s/a.json", node_patch="")


def test_is_matched_only_for_pair_keys():
    assert is_matched("paicad_tag", {"asm_match": "/x"}) and not is_matched("paicad_tag", {"asm_match": ""})
    assert not is_matched("paicad_extract", {"asm_match": "/x"})
    assert expand("paicad_extract", ["a"], {"asm_match": "/x"}) == ["a"]


# ---- include 트리 digest = paicad 규칙 -------------------------------------------------------------------------------


def _tree(root: Path) -> Path:
    a = root / "assem"
    (a / "nodes").mkdir(parents=True)
    (a / "MODEL_0000.rad").write_text("#RADIOSS STARTER\n/BEGIN\nm\n#include 101_parts.inc\n  #INCLUDE nodes\\102_nodes.inc\n/END\n")
    (a / "101_parts.inc").write_text("/PART/3000001\nCUSH_A\n")
    (a / "nodes" / "102_nodes.inc").write_text("/NODE\n  1 0 0 0\n/TETRA4/3000001\n 1 1 1 1 1\n")
    (a / "unused.inc").write_text("unused\n")
    return a


def test_tree_digest_matches_paicad(tmp_path):
    from paicad.mesh import asmtree as pt

    a = _tree(tmp_path)
    mine = at.build(str(a))
    theirs = pt.build(a)
    assert mine.starter == theirs.starter == "MODEL_0000.rad"
    assert mine.rels() == [f.rel for f in theirs.files] and "unused.inc" not in mine.rels()
    assert mine.digest == theirs.digest() and at.digest_of(str(a)) == mine.digest


def test_tree_digest_changes_on_edit_and_ignores_unused(tmp_path):
    a = _tree(tmp_path)
    d0 = at.digest_of(str(a))
    (a / "unused.inc").write_text("changed\n")
    assert at.digest_of(str(a)) == d0  # 트리 밖 파일은 digest에 들어가지 않는다
    (a / "nodes" / "102_nodes.inc").write_text("/NODE\n  1 0 0 1\n")
    assert at.digest_of(str(a)) != d0


def test_tree_errors_use_paicad_codes(tmp_path):
    a = _tree(tmp_path)
    (a / "MODEL_0000.rad").write_text("/BEGIN\n#include ../outside.inc\n")
    (tmp_path / "outside.inc").write_text("x")
    with pytest.raises(at.AsmTreeError) as ei:
        at.build(str(a))
    assert ei.value.code == "ASM_INCLUDE_OUTSIDE"
    (a / "MODEL_0000.rad").write_text("/BEGIN\n#include nope.inc\n")
    with pytest.raises(at.AsmTreeError) as ei:
        at.build(str(a))
    assert ei.value.code == "ASM_INCLUDE_MISSING"
    (a / "MODEL_0000.rad").write_text("/BEGIN\n#include 101_parts.inc\n#include 101_parts.inc\n")  # 같은 파일 두 번 = 입력 오류
    with pytest.raises(at.AsmTreeError) as ei:
        at.build(str(a))
    assert ei.value.code == "GEOM_INPUT_INVALID"


def test_copy_included_copies_tree_only(tmp_path):
    a = _tree(tmp_path)
    dst = tmp_path / "copy"
    got = at.copy_included(at.build(str(a)), str(dst))
    assert sorted(got) == ["101_parts.inc", "MODEL_0000.rad", "nodes/102_nodes.inc"]
    assert sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file()) == sorted(got)


# ---- rows_sha256 · 행 검증 · 확정본 ----------------------------------------------------------------------------------


def test_rows_sha256_is_hash_of_match_file_bytes():
    rows = [{"body": "A", "pids": [3000002, 3000001]}]
    data = am.canonical_rows(rows, ["B"])
    assert am.rows_sha256(rows, ["B"]) == hashlib.sha256(data).hexdigest() and "sha256:" not in am.rows_sha256(rows, ["B"])
    assert json.loads(data)["rows"][0]["body"] == "A"
    assert am.rows_sha256(rows, ["B"]) != am.rows_sha256(rows, [])


PARTS = [{"pid": 1, "title": "P1", "solid_ok": True}, {"pid": 2, "title": "P2", "solid_ok": True}, {"pid": 3, "title": "S3", "solid_ok": False}]


def _codes(rows, excl, bodies=("A", "B"), use=()):
    _r, _e, probs = am.validate_rows(rows, excl, list(bodies), PARTS, set(use))
    return sorted({p["code"] for p in probs})


def test_validate_rows_reasons():
    ok = [{"body": "A", "pids": [1]}, {"body": "B", "pids": [2]}]
    assert _codes(ok, []) == []
    assert _codes([], []) == [am.R_MISSING]  # 바디를 아무것도 정하지 않음
    assert _codes([], ["A", "B"]) == [am.R_EMPTY]  # 전부 매칭 안 함 = 매칭 행이 없음
    assert am.R_BODY in _codes([{"body": "Z", "pids": [1]}], ["A", "B"])
    assert am.R_BODY_DUP in _codes([{"body": "A", "pids": [1]}, {"body": "A", "pids": [2]}], ["B"])
    assert am.R_PID in _codes([{"body": "A", "pids": [99]}], ["B"])
    assert am.R_PID_DUP in _codes([{"body": "A", "pids": [1]}, {"body": "B", "pids": [1]}], [])
    assert am.R_SOLID in _codes([{"body": "A", "pids": [3]}], ["B"])
    assert am.R_MISSING in _codes([{"body": "A", "pids": [1]}], [])
    assert am.R_USE in _codes([{"body": "A", "pids": [1]}], ["B"], use={"B"})
    assert am.R_BODY_DUP in _codes([{"body": "A", "pids": [1]}], ["A", "B"])  # 매칭 행과 제외에 같은 바디


def test_confirmed_document_shape_and_summaries():
    match = {"match_id": "m1", "source": {"cad_name": "x.step", "cad_sha256": "c" * 64, "features_sha256": None},
             "assem": {"digest": "sha256:abc", "starter": "MODEL_0000.rad"}, "rows": [{"body": "A", "pids": [1, 2]}], "excluded_bodies": ["B"]}
    check = {"rows": [{"match_ratio": 0.99, "dist_mm": {"max": 0.04}, "shared": {"nodes": 0}},
                      {"match_ratio": 0.995, "dist_mm": {"max": 0.02}, "shared": {"nodes": 2}}], "rows_sha256": "r", "status": "PASS",
             "assem": {"node_files": [{"rel": "n.inc"}]}}
    doc = am.confirmed_document(match, PARTS, check, 3, "s" * 64, engine_version="0.13.0", user="u", now_iso="t")
    assert doc["cad"] == {"rel": "x.step", "sha256": "c" * 64} and doc["assem"]["digest"] == "sha256:abc"
    assert doc["rows"] == [{"body": "A", "pids": [1, 2], "titles": ["P1", "P2"]}] and doc["excluded_bodies"] == ["B"]
    assert doc["check"]["match_ratio_min"] == 0.99 and doc["check"]["dist_max_mm"] == 0.04 and doc["assem"]["node_files"] == ["n.inc"]
    assert am.check_summary(check) == {"status": "PASS", "rows": 2, "match_ratio_min": 0.99, "dist_max_mm": 0.04, "shared_nodes": 2}


def test_confirmed_document_without_check_is_null_check():
    """AM-C3: 검사를 실행한 적이 없으면 확정본 check = null(검사는 선택). 검사가 낡았으면 status·current로 구분한다."""
    match = {"match_id": "m1", "source": {"cad_name": "x.step", "cad_sha256": "c" * 64, "features_sha256": None},
             "assem": {"digest": "sha256:abc", "starter": "MODEL_0000.rad"}, "rows": [{"body": "A", "pids": [1]}], "excluded_bodies": []}
    doc = am.confirmed_document(match, PARTS, None, None, None, engine_version=None, user="u", now_iso="t")
    assert doc["check"] is None and doc["rows"] == [{"body": "A", "pids": [1], "titles": ["P1"]}] and doc["assem"]["node_files"] == []
    old = {"rows": [{"match_ratio": 0.5, "dist_mm": {"max": 3.0}}], "rows_sha256": "r", "status": "FAIL"}
    doc = am.confirmed_document(match, PARTS, old, 2, "s" * 64, engine_version="0.13.0", user="u", now_iso="t", check_status="FAIL", check_current=False)
    assert doc["check"]["status"] == "FAIL" and doc["check"]["current"] is False and doc["check"]["seq"] == 2


def test_asm_match_check_timeout_defaults_unlimited_and_is_validated():
    """AM-C3: asm check 시간 제한 기본 null(상한 없음), parts는 600초 유지. 0 이하는 설정 오류."""
    from physicsai_core.config.validate_geometry import _validate_asm_match

    s = Settings()
    assert s.asm_match.check_timeout_s is None and s.asm_match.timeout_s == 600
    issues: list = []
    _validate_asm_match(s, issues)
    assert issues == []
    for bad in (0, -5):
        s.asm_match.check_timeout_s = bad
        issues = []
        _validate_asm_match(s, issues)
        assert [i.key for i in issues] == ["asm_match.check_timeout_s"]
    s.asm_match.check_timeout_s = 3600.0
    issues = []
    _validate_asm_match(s, issues)
    assert issues == []


def test_example_config_asm_check_timeout_is_null():
    import yaml

    root = Path(__file__).resolve().parents[3]
    doc = yaml.safe_load((root / "config" / "platform.example.yaml").read_text(encoding="utf-8"))
    assert doc["asm_match"]["check_timeout_s"] is None and doc["asm_match"]["timeout_s"] == 600


def test_is_matched_detects_confirmed_copy(tmp_path):
    assert not am.is_matched(str(tmp_path))
    (tmp_path / "cad").mkdir()
    (tmp_path / "cad" / "asm_match.json").write_text(json.dumps({"schema_version": 1}))
    assert am.is_matched(str(tmp_path)) and am.matched_doc(str(tmp_path)) == {"schema_version": 1}


# ---- equiv: 조립 매칭 run의 부피(기준본 include 파일 없음, §6.4) ---------------------------------------------------------


def test_equiv_volume_reads_matched_parts_from_tree(tmp_path):
    from physicsai_core.equiv import volume as vol
    from physicsai_core.equiv.sides import Run, _set_tree, matched_parts

    d = tmp_path / "run"
    (d / "n").mkdir(parents=True)
    (d / "MODEL_0000.rad").write_text("/BEGIN\nm\n#include 101.inc\n#include n/102.inc\n")
    (d / "101.inc").write_text("/PART/10\nCUSH\n/PART/20\nOTHER\n")
    (d / "n" / "102.inc").write_text("/NODE\n1 0 0 0\n2 1 0 0\n3 0 1 0\n4 0 0 1\n5 0 0 2\n"
                                     "/TETRA4/10\n1 1 2 3 4\n/TETRA4/20\n2 1 2 3 5\n")
    mesh = vol.read_tree(str(d), max_bytes=10_000_000)
    assert mesh is not None and set(mesh.elems) == {"10", "20"}
    only = vol.part_volume(mesh, ["10"])
    assert only.n_elems == 1 and only.volume == pytest.approx(1 / 6)
    assert vol.part_volume(mesh, None).volume == pytest.approx(1 / 6 + 2 / 6)  # 전체 = 쿠션 + 다른 PART(그래서 매칭 pid만 쓴다)
    run = Run("r", 1, True)
    parts = matched_parts({"rows": [{"body": "A", "pids": [10]}]})
    assert parts == ["10"] and matched_parts({"rows": []}) is None and matched_parts(None) is None
    _set_tree(run, str(d), parts)
    assert run.mesh_tree == str(d) and run.mesh_parts == ["10"]
    other = Run("o", 2, True)
    _set_tree(other, str(d), None)  # 매칭 아님 = 설정 안 함(기존 mesh_inc 경로)
    assert other.mesh_tree is None
    assert vol.read_tree(str(tmp_path / "missing"), max_bytes=10) is None


def test_matched_path_modules_do_not_depend_on_include_file_names():
    """V-AM-10 정적 점검: 방식 M 전용 모듈은 `predict.mesh_include_name`(기준본 파일 이름)을 코드에서 쓰지 않는다(docstring·주석 제외).
    (`renum_csv_name`은 asm parts의 추천 보조 입력 전달에만 쓰는 asm_match 작업 모듈이 예외 — 확정·검사에 쓰이지 않는다.)"""
    import ast

    from physicsai_test_support import REPO

    files = ["backend/physicsai_core/geometry/asm_match.py", "backend/physicsai_core/geometry/asm_tree.py",
             "backend/physicsai_core/commands_asm.py", "backend/physicsai_api/services/asm_match_api.py",
             "backend/physicsai_api/services/asm_match_gate.py", "worker/physicsai_worker/steps/geometry_asm.py",
             "worker/physicsai_worker/steps/asm_match.py"]
    for rel in files:
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert "mesh_include_name" not in names, rel
        if rel != "worker/physicsai_worker/steps/asm_match.py":
            assert "renum_csv_name" not in names, rel
