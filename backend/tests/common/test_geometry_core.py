"""native 형상 엔진 순수 함수(geometry-engine.md §4·§6.5·§7.2, V-GE-1·5·6·8): 옵션·보고·판정·문구·파일·준비본·피처 요약."""

from __future__ import annotations

import json
import re

import pytest

from physicsai_core.geometry import features_view, messages, native_files, options, prep, reports
from physicsai_core.geometry.judge import judge_paicad, parse_result_line


def _w(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


# ---- options ----
def test_options_merge_validate_and_alias():
    opts, probs = options.effective_options({"tag": {"tol_abs_mm": 0.1}}, {"position_range_mm": 7.0, "quality": {"max_aspect": 8}})
    assert probs == [] and opts["tag"]["tol_abs_mm"] == 0.1 and opts["extract"]["position_range_mm"] == 7.0
    assert opts["quality"]["max_aspect"] == 8 and opts["quality"]["min_stretch"] == 0.1      # 깊은 병합
    _o, probs = options.effective_options(None, {"nope": 1, "tag": {"x": 1}, "engine": "native", "quality": {"max_aspect": -1}})
    keys = {p["key"] for p in probs}
    assert {"nope", "tag.x", "engine", "quality.max_aspect"} <= keys and all(p["message"] for p in probs)
    assert options.normalize_override("x")[1][0]["key"] == "(root)"


def test_options_tag_hash_and_change_detection():
    a, _ = options.effective_options(None, None)
    b, _ = options.effective_options(None, {"tag": {"tol_abs_mm": 0.09}})
    c, _ = options.effective_options(None, {"morph": {"poisson": 0.2}})
    assert options.tag_options_sha256(a) != options.tag_options_sha256(b) and options.tag_options_sha256(a) == options.tag_options_sha256(c)
    assert options.tag_section_changed(None, {"tag": {"tol_abs_mm": 0.09}}) and not options.tag_section_changed({}, {"morph": {}})
    doc = options.usage_document(a, "0.5.0")
    assert doc["engine"] == "native" and doc["engine_version"] == "0.5.0" and "engine" not in options.paicad_document(a)


def test_options_against_features():
    feats = {"features": [{"name": "A", "faces": {"moving": ["F1"], "fixed": ["F2"]}}], "groups": [{"id": "G1"}]}
    ok, _ = options.effective_options(None, {"thickness_ref_overrides": {"A": "F2"}, "symmetry_split": ["G1"]})
    assert options.check_against_features(ok, feats) == []
    bad, _ = options.effective_options(None, {"thickness_ref_overrides": {"A": "F9", "Z": "F1"}, "symmetry_split": ["G9"]})
    assert len(options.check_against_features(bad, feats)) == 3


# ---- reports ----
def test_read_report_limits_and_schema(tmp_path):
    p = _w(tmp_path / "r.json", {"schema_version": 1, "status": "PASS"})
    assert reports.read_report(p, 1000)["status"] == "PASS"
    with pytest.raises(reports.ReportError, match="상한"):
        reports.read_report(p, 5)
    for doc, msg in (({"schema_version": 2}, "schema_version"), ([1], "객체"), ({}, "schema_version")):
        with pytest.raises(reports.ReportError, match=msg):
            reports.read_report(_w(tmp_path / "b.json", doc), 1000)
    (tmp_path / "t.json").write_text("{", encoding="utf-8")
    with pytest.raises(reports.ReportError, match="형식"):
        reports.read_report(str(tmp_path / "t.json"), 1000)
    with pytest.raises(reports.ReportError):
        reports.read_report(str(tmp_path / "none.json"), 1000)


def test_version_parse_and_major_minor():
    d = reports.parse_version_json('noise\n{"paicad": "0.5.0", "ocp": "7.8", "python": "3.12"}')
    assert d["paicad"] == "0.5.0" and reports.version_display(d) == "paicad 0.5.0 · OCP 7.8"
    with pytest.raises(reports.ReportError):
        reports.parse_version_json("not json")
    with pytest.raises(reports.ReportError):
        reports.parse_version_json('{"ocp": "1"}')
    assert reports.same_major_minor("0.5.0", "0.5.9") and not reports.same_major_minor("0.5.0", "0.6.0")
    assert reports.same_major_minor(None, "0.6.0") and reports.same_major_minor("x", "0.6.0")


# ---- judge ----
def test_judge_matrix(tmp_path):
    rep, out = tmp_path / "check.json", tmp_path / "m.inc"
    ok = {"schema_version": 1, "status": "PASS"}
    v = judge_paicad(0, str(rep), [str(out)], max_bytes=1000)
    assert not v.ok and v.code == "OUTPUT_MISSING"                                   # 보고 없음 rc 0
    assert judge_paicad(3, str(rep), [], max_bytes=1000).code == "EXIT_NONZERO"
    _w(rep, ok)
    assert judge_paicad(0, str(rep), [str(out)], max_bytes=1000).code == "OUTPUT_MISSING"
    out.write_text("x")
    v = judge_paicad(0, str(rep), [str(out)], max_bytes=1000)
    assert v.ok and v.warnings == []
    v = judge_paicad(20, str(rep), [str(out)], max_bytes=1000)                       # 종료코드가 나빠도 출력·보고가 정상이면 성공
    assert v.ok and v.warnings[0][0] == "EXIT_NONZERO_IGNORED"
    _w(rep, {"schema_version": 1, "status": "FAIL", "code": "GEOM_QUALITY", "message": "stretch 0.02"})
    v = judge_paicad(11, str(rep), [str(out)], max_bytes=1000)
    assert not v.ok and v.code == "GEOM_QUALITY" and v.category == "QUALITY" and "품질 미달" in v.message
    _w(rep, {"schema_version": 1, "status": "FAIL", "skip": {"code": "GEOM_INTERFERENCE", "category": "INTERFERENCE", "step": "check",
                                                              "report": "m_2/check/check.json"}})
    v = judge_paicad(11, str(rep), [], max_bytes=1000)
    assert v.code == "GEOM_INTERFERENCE" and v.step == "check" and v.report_rel == "m_2/check/check.json"
    _w(rep, {"schema_version": 9})
    assert judge_paicad(0, str(rep), [], max_bytes=1000).code == "INPUT_INVALID"
    _w(rep, {"schema_version": 1, "features": []})                                    # 상태 없음 + 종료코드 13
    assert judge_paicad(13, str(rep), [], max_bytes=1000).code == "GEOM_EXTRACT_EMPTY"
    assert parse_result_line("PAICAD RESULT FAIL GEOM_QUALITY check.json") == ("FAIL", "GEOM_QUALITY")
    assert parse_result_line("PAICAD RESULT OK - tag.json") == ("OK", None) and parse_result_line("hello") is None


# ---- messages ----
def test_messages_table_complete_and_korean():
    assert messages.korean_message("GEOM_TOPOLOGY_CHANGED", "faces 12 -> 14").startswith("CAD 생성 불가(위상 변화: 면 수 12→14)")
    assert "0.07 mm" in messages.korean_message("GEOM_DEVIATION", "boundary deviation 0.07 mm over tol")
    assert len(messages.korean_message("GEOM_INTERNAL", "x" * 900)) == messages.MAX_MESSAGE
    assert messages.category_of("GEOM_QUALITY") == "QUALITY" and messages.category_of("???") is None
    assert messages.category_of("GEOM_QUALITY", "TIE") == "TIE" and messages.label_of("???") == "???"
    for code, (cat, ko) in messages.CODE_TABLE.items():
        assert cat in messages.CATEGORY_LABELS and re.search(r"[가-힣]", ko), code


# ---- native_files ----
def test_native_files_formats(tmp_path):
    v = native_files.values_document({"A": 1.5}, "doe", "d1", "0.5.0", doe_no=3)
    assert v["values"] == {"A": 1.5} and v["source"] == {"kind": "doe", "id": "d1", "doe_no": 3} and v["engine"] == "native"
    xml = native_files.native_params_xml({"A_THK_1": 10.123456789012}, {"A_THK_1": 10.0})
    assert '<paramitem Name="A_THK_1" NewValue="10.123456789012" Value="10.0"/>' in xml and xml.startswith('<Parameters Value="">')
    csv_text = native_files.doe_matrix_csv(["A", "B"], [(1, "run__00001", {"A": 1.0, "B": 2.5})])
    assert csv_text == "doe_no,run_key,A,B\n1,run__00001,1.0,2.5\n"
    s = native_files.skipped_document("GEOM_QUALITY", "x", "check", "m_2/check/check.json", "0.5.0")
    assert s["category"] == "QUALITY" and s["step"] == "check" and "품질 미달" in s["message"] and s["schema_version"] == 1


# ---- prep ----
def _set(tmp_path):
    S = tmp_path / "S"
    for rel, txt in (("cad/a.step", "STEP"), ("radioss_assem/inc.inc", "NODE"), ("radioss_assem/RENUM.csv", "1"),
                     ("native/extract/parameter_features.json", "{}"), ("native/tag/tag.json", "{}")):
        (S / rel).parent.mkdir(parents=True, exist_ok=True)
        (S / rel).write_text(txt)
    return S


def test_prep_state_ready_stale_missing(tmp_path):
    S = _set(tmp_path)
    opts, _ = options.effective_options(None, None)
    kw = dict(step_exts=[".step"], mesh_include_name="inc.inc", renum_csv_name="RENUM.csv")
    assert prep.prep_state(str(S), opts=opts, **kw).status == prep.MISSING
    (S / "native" / "prep.json").write_text(json.dumps(prep.prep_document(
        str(S), opts=opts, engine_version="0.5.0", ocp_version=None, job_id="j", created_at="t", **kw)))
    assert prep.prep_state(str(S), opts=opts, current_engine_version="0.5.3", **kw).status == prep.READY
    st = prep.prep_state(str(S), opts=opts, current_engine_version="0.6.0", **kw)
    assert st.status == prep.STALE and "0.5.0" in st.reason and "0.6.0" in st.reason
    other, _ = options.effective_options(None, {"tag": {"tol_abs_mm": 0.2}})
    assert prep.prep_state(str(S), opts=other, **kw).reason == prep.STALE_MESSAGE_TAG
    (S / "radioss_assem" / "inc.inc").write_text("CHANGED")
    assert prep.prep_state(str(S), opts=opts, **kw).status == prep.STALE
    (S / "native" / "tag" / "tag.json").unlink()
    assert prep.prep_state(str(S), opts=opts, **kw).status == prep.MISSING


def test_prep_parts_inputs(tmp_path):
    S = tmp_path / "P"
    (S / "cad" / "parts").mkdir(parents=True)
    for n in ("b.step", "a.step"):
        (S / "cad" / "parts" / n).write_text(n)
    got = prep.cad_inputs(str(S), [".step"])
    assert [p["rel"] for p in got["parts"]] == ["cad/parts/a.step", "cad/parts/b.step"]


# ---- features_view ----
def test_features_view_summary():
    doc = {"engine_version": "0.5.0", "features": [
        {"name": "A1", "type": "THICKNESS", "body": "A", "nominal": 10, "range": {"min": 9, "max": 11}, "group": "G1"},
        {"name": "A2", "nominal": 10, "range": {"min": 9, "max": 11}, "group": "G1"},
        {"name": "B", "nominal": 2, "range": {"min": 1, "max": 3}, "ref": {"locked": True, "provisional": True}},
        {"name": "bad", "nominal": "x"}, "junk"],
        "groups": [{"id": "G1", "kind": "MIRROR", "parameter": "A1", "members": ["A1", "A2"]}],
        "warnings": [{"code": "W", "message": "m", "feature": "B"}, {"x": 1}]}
    reps = features_view.representative_params(doc)
    assert [r["name"] for r in reps][:2] == ["A1", "B"] and len(reps) == 3 and reps[2]["min"] is None   # 값 없는 피처는 None
    s = features_view.summary(doc, {"B": "art-1"})
    b = next(f for f in s["features"] if f["name"] == "B")
    assert b["ref_locked"] and b["ref_provisional"] and b["png_artifact_id"] == "art-1" and s["groups"][0]["members"] == ["A1", "A2"]
    assert s["warnings"] == [{"code": "W", "message": "m", "feature": "B"}] and s["engine_version"] == "0.5.0"
