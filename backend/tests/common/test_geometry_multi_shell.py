"""geometry-engine.md §11.1(3S)·§4.10/§7.3.8(4B) 플랫폼 순수 함수: 쉘 두께 선택·값 분리, 매칭표 결정·확정·승계·배정·층화 LHS·
학습 입력 열, paicad_props_*·paicad_map 명령 템플릿(선택 인자 쌍 생략, V-GE-1)."""

from __future__ import annotations

import pytest

from physicsai_core.commands import render_argv, validate_template
from physicsai_core.config.schema_hpc import CommandsCfg
from physicsai_core.geometry import baselines as bl
from physicsai_core.geometry import shell as sh
from physicsai_core.stage4_predict.batch_matrix import lhs_values, run_key_for

PROPS = {"schema_version": 1, "engine_version": "0.7.0", "props": [
    {"id": 1, "parameter": "BRACKET_SHELL_T", "thickness": 1.2, "range": {"min": 1.14, "max": 1.26}, "selectable": True, "supported": True},
    {"id": 3, "parameter": "PANEL_SHELL_T", "thickness": 2.0, "selectable": False, "supported": True, "element_overrides": 2},
    {"id": 5, "parameter": "LID_SHELL_T", "thickness": 1.0, "selectable": False, "supported": True,
     "part_overrides": [{"id": 9, "title": "LID", "thickness": 1.1}]},
    {"id": 4, "parameter": None, "thickness": None, "selectable": False, "supported": False}]}


def test_shell_selection_rules_and_split():
    rows = sh.selection_rows(PROPS, [{"name": "BRACKET_SHELL_T", "max": 1.4}], geometry_names=["A"])
    assert rows == [{"name": "BRACKET_SHELL_T", "nominal": 1.2, "min": 1.14, "max": 1.4, "unit": "mm", "source": "prop", "prop_id": 1}]
    with pytest.raises(sh.ShellError) as e:
        sh.selection_rows(PROPS, [{"name": "PANEL_SHELL_T"}, {"name": "LID_SHELL_T"}, {"name": "NOPE"}, {"name": "BRACKET_SHELL_T", "min": 0}])
    assert [p["code"] for p in e.value.problems] == ["PROP_OVERRIDDEN_BY_ELEMENT", "PROP_OVERRIDDEN_BY_PART", "PROP_NOT_FOUND",
                                                     "PROP_THICKNESS_INVALID"]
    with pytest.raises(sh.ShellError) as e:
        sh.selection_rows(PROPS, [{"name": "BRACKET_SHELL_T"}], geometry_names=["BRACKET_SHELL_T"])
    assert e.value.problems[0]["code"] == "PARAM_NAME_CONFLICT"
    params = [{"name": "A", "nominal": 1, "min": 0, "max": 2}, *rows]
    assert sh.split_values(params, {"A": 1.5, "BRACKET_SHELL_T": 1.3}) == ({"A": 1.5}, {"BRACKET_SHELL_T": 1.3})
    assert sh.has_geometry(params) and not sh.has_geometry(rows)
    summ = sh.summary(PROPS, params)
    assert [p["selected"] for p in summ["props"]] == [True, False, False, False]
    assert [p["reason_code"] for p in summ["props"]] == [None, "PROP_OVERRIDDEN_BY_ELEMENT", "PROP_OVERRIDDEN_BY_PART",
                                                         "PROP_UNSUPPORTED_TYPE"]


def _pm(usage="topology", grades=("recommend", "check", "unmatched")):
    pm = {"schema_version": 1, "status": "draft", "confirmed_by": None, "confirmed_at": None, "usage": usage,
          "baselines": [{"id": "base", "rel": "."}, {"id": "B2", "rel": "baselines/B2"}],
          "discrete": {"name": "baseline", "values": ["base", "B2"]} if usage == "topology" else None,
          "range_split": {"param": "T", "intervals": [{"baseline": "base", "nominal": 10.0}, {"baseline": "B2", "nominal": 15.0}]}
          if usage == "range" else None,
          "common": [
              {"row_id": "r1", "type": "thickness", "unit": "mm", "signature": "s1", "needs_review": False,
               "proposed": {"name": "T", "grade": grades[0], "map": {"base": "T1", "B2": "T2"}, "nominal": {"base": 10.0, "B2": 15.0}},
               "decision": None},
              {"row_id": "r2", "type": "height", "unit": "mm", "signature": "s2", "needs_review": False,
               "proposed": {"name": "H", "grade": grades[1], "map": {"base": "H1", "B2": "H2"}, "nominal": {"base": 20.0, "B2": 20.0}},
               "decision": None},
              {"row_id": "r3", "type": "radius", "unit": "mm", "signature": "s3", "needs_review": False,
               "proposed": {"name": "R", "grade": grades[2], "map": {"base": "R1", "B2": None}, "nominal": {"base": 4.0, "B2": None}},
               "decision": None}]}
    return pm


KNOWN = {"base": {"T1", "H1", "R1"}, "B2": {"T2", "H2"}}


def test_confirm_requires_explicit_check_rows_and_accepts_rest():
    pm = _pm()
    assert bl.unresolved(pm) == ["r2"]
    with pytest.raises(bl.MapError) as e:
        bl.confirm(pm, "u", "t", KNOWN)
    assert e.value.code == "GEOM_INPUT_INVALID" and e.value.problems[0]["row_id"] == "r2"
    pm2 = bl.put_decisions(pm, [{"row_id": "r2", "decision": {"action": "rename", "name": "RIB_H", "map": {"base": "H1", "B2": "H2"}}}], KNOWN)
    c = bl.confirm(pm2, "u-1", "2026-10-19T00:00:00Z", KNOWN)
    assert c["status"] == "confirmed" and c["confirmed_by"] == "u-1"
    assert [v.name for v in bl.variables(c)] == ["T", "RIB_H", "R"]
    assert c["common"][0]["decision"] == {"action": "accept", "name": "T", "map": {"base": "T1", "B2": "T2"}}
    back = bl.put_decisions(c, [{"row_id": "r1", "decision": None}], KNOWN)       # 확정 상태에서 PUT → draft
    assert back["status"] == "draft" and back["confirmed_by"] is None and back["confirmed_at"] is None


@pytest.mark.parametrize("dec,code", [
    ({"row_id": "r3", "decision": {"action": "rename", "name": "T", "map": {"base": "R1"}}}, "PARAM_NAME_CONFLICT"),
    ({"row_id": "r3", "decision": {"action": "rename", "name": "baseline", "map": {"base": "R1"}}}, "PARAM_NAME_CONFLICT"),
    ({"row_id": "r3", "decision": {"action": "rename", "name": "X__na", "map": {"base": "R1"}}}, "PARAM_NAME_CONFLICT"),
    ({"row_id": "r3", "decision": {"action": "change", "name": "R", "map": {"base": "T1"}}}, "PARAM_NAME_CONFLICT"),  # T1을 두 이름이
    ({"row_id": "r3", "decision": {"action": "change", "name": "R", "map": {"base": "ZZ"}}}, "GEOM_INPUT_INVALID"),
    ({"row_id": "r9", "decision": {"action": "accept"}}, "GEOM_INPUT_INVALID"),
])
def test_decision_conflicts(dec, code):
    pm = bl.put_decisions(_pm(), [{"row_id": "r1", "decision": {"action": "accept"}}], KNOWN)
    with pytest.raises(bl.MapError) as e:
        bl.put_decisions(pm, [dec], KNOWN)
    assert e.value.code == code


def test_split_decision_makes_two_variables_and_inherit_by_signature():
    pm = bl.put_decisions(_pm(), [{"row_id": "r2", "decision": {"action": "split", "parts": [
        {"name": "H_BASE", "map": {"base": "H1"}}, {"name": "H_B2", "map": {"B2": "H2"}}]}}], KNOWN)
    c = bl.confirm(pm, "u", "t", KNOWN)
    assert [v.name for v in bl.variables(c)] == ["T", "H_BASE", "H_B2", "R"]
    new = _pm()
    new["common"][0]["signature"] = "s1-changed"
    inh = bl.inherit(new, c)
    assert inh["status"] == "draft" and inh["common"][0]["decision"] is None and inh["common"][0]["needs_review"] is True
    assert inh["common"][1]["decision"]["action"] == "split" and inh["common"][1]["needs_review"] is False
    assert bl.unresolved(inh) == ["r1"]


def _rows_for(pm):
    feats = {"base": {"T1": {"nominal": 10.0, "range": {"min": 9.5, "max": 10.5}, "feasible": {"min": 6.0, "max": 14.0}},
                      "H1": {"nominal": 20.0, "range": {"min": 19.0, "max": 21.0}},
                      "R1": {"nominal": 4.0, "range": {"min": 3.8, "max": 4.2}}},
             "B2": {"T2": {"nominal": 15.0, "range": {"min": 14.25, "max": 15.75}, "feasible": {"min": 14.5, "max": 15.5}},
                    "H2": {"nominal": 20.0, "range": {"min": 19.0, "max": 21.0}, "feasible": {"min": 19.5, "max": 20.5}}}}
    return bl.parameter_rows(pm, feats, {"base": {}, "B2": {}})


def test_parameter_rows_assign_and_training_columns():
    c = bl.confirm(bl.put_decisions(_pm("range"), [{"row_id": "r2", "decision": {"action": "accept"}}], KNOWN), "u", "t", KNOWN)
    rows = _rows_for(c)
    t = rows[0]
    assert (t["min"], t["max"], t["nominal"]) == (9.5, 15.75, 10.0) and t["baselines"]["B2"]["feasible"] == {"min": 14.5, "max": 15.5}
    assert rows[2]["baselines"]["B2"] is None
    assert bl.assign_baseline(c, rows, {"T": 12.0, "H": 20.0, "R": 4.0}) == "base"
    assert bl.assign_baseline(c, rows, {"T": 15.0, "H": 20.0}) == "B2"
    assert bl.assign_baseline(c, rows, {"T": 14.2, "H": 20.0}) is None        # 틈(14~14.5) → BASELINE_NO_COVER
    assert bl.assign_baseline(c, rows, {"T": 15.0, "H": 21.0}) is None        # B2 feasible 밖, base T 밖
    assert bl.range_gaps(c, rows) == ["base–B2"]
    assert bl.original_values(rows, "B2", {"T": 15.1, "H": 20.0, "R": 4.0}) == {"T2": 15.1, "H2": 20.0}
    assert bl.training_columns(c, rows, ["SH"]) == ["T", "H", "R", "SH", "R__na"]
    assert bl.training_values(c, rows, "B2", {"T": 15.1, "H": 20.0, "R": None}, {"SH": 1.2}) == \
        {"T": 15.1, "H": 20.0, "R": 0.0, "SH": 1.2, "R__na": 1.0}
    topo = bl.confirm(bl.put_decisions(_pm(), [{"row_id": "r2", "decision": {"action": "accept"}}], KNOWN), "u", "t", KNOWN)
    trows = _rows_for(topo)
    assert bl.assign_baseline(topo, trows, {"baseline": "B2"}) == "B2" and bl.assign_baseline(topo, trows, {"baseline": "x"}) is None
    tv = bl.training_values(topo, trows, "base", {"T": 10.0, "H": 20.0, "R": 4.0})
    assert tv["baseline__base"] == 1.0 and tv["baseline__B2"] == 0.0 and tv["R__na"] == 0.0


@pytest.mark.parametrize("n,b", [(5, 2), (7, 3), (2, 3), (10, 4)])
def test_stratum_counts_differ_at_most_one(n, b):
    c = bl.stratum_counts(n, b)
    assert sum(c) == n and max(c) - min(c) <= 1 and c == sorted(c, reverse=True)


def test_stratified_lhs_deterministic_and_range_interval():
    c = bl.confirm(bl.put_decisions(_pm("range"), [{"row_id": "r2", "decision": {"action": "accept"}}], KNOWN), "u", "t", KNOWN)
    rows = _rows_for(c)
    a = bl.stratified_lhs(c, rows, 6, 3, lhs_values, run_key_for, {"SH": (1.0, 1.4)})
    assert a == bl.stratified_lhs(c, rows, 6, 3, lhs_values, run_key_for, {"SH": (1.0, 1.4)})
    assert [x[2] for x in a] == ["base"] * 3 + ["B2"] * 3 and [x[0] for x in a] == list(range(1, 7))
    for _no, _rk, b, v in a:
        assert 1.0 <= v["SH"] <= 1.4
        if b == "base":
            assert 6.0 <= v["T"] <= 12.5 and v["R"] is not None                 # 담당 구간 = (feasible 6, 중점 12.5)
        else:
            assert 14.5 <= v["T"] <= 15.5 and v["R"] is None                    # B2 feasible로 자름, R은 N/A


def test_drop_baseline_and_shape_problems(tmp_path):
    pm = _pm()
    pm["baselines"].append({"id": "B3", "rel": "baselines/B3"})
    pm["discrete"]["values"].append("B3")
    pm["common"].append({"row_id": "r4", "type": "depth", "unit": "mm", "signature": "s4", "needs_review": False,
                         "proposed": {"name": "D", "map": {"base": None, "B2": None, "B3": "D3"}}, "decision": None})
    d = bl.drop_baseline(pm, "B3")
    assert bl.baseline_ids(d) == ["base", "B2"] and [r["row_id"] for r in d["common"]] == ["r1", "r2", "r3"]
    assert d["discrete"]["values"] == ["base", "B2"]
    bad = {**_pm(), "range_split": {"param": "T", "intervals": []}}
    assert any("함께" in p["message"] for p in bl.shape_problems(bad))
    with pytest.raises(bl.MapError):
        bl.baseline_root(str(tmp_path), {"baselines": [{"id": "x", "rel": "../evil"}]}, "x")


def test_paicad_map_and_props_templates():
    cmds = CommandsCfg()
    for k in ("paicad_props_scan", "paicad_props_apply", "paicad_map"):
        assert validate_template(k, getattr(cmds, k)) == []
    assert validate_template("paicad_map", ["{hw}", "map"]) != []                # argv[0]은 {paicad}만
    exe = {"paicad_path": "/opt/paicad"}
    base = {"paicad": "", "baselines_json": "/s/b.json", "map_out_dir": "/s/out", "options_json": "/s/o.json", "usage": "topology"}
    argv = render_argv("paicad_map", cmds.paicad_map, {**base, "user_map": "", "split_param": ""}, executables=exe, is_windows=False)
    assert "--user-map" not in argv and "--split-param" not in argv and argv[argv.index("--usage") + 1] == "topology"
    argv = render_argv("paicad_map", cmds.paicad_map, {**base, "usage": "range", "user_map": "/s/param_map.json", "split_param": "T"},
                       executables=exe, is_windows=False)
    assert argv[argv.index("--user-map") + 1] == "/s/param_map.json" and argv[argv.index("--split-param") + 1] == "T"
    argv = render_argv("paicad_props_apply", cmds.paicad_props_apply,
                       {"assem_dir": "/r/INPUT", "values_json": "/r/v.json", "props_json": "/s/props.json", "out_dir": "/r/out"},
                       executables=exe, is_windows=False)
    assert argv[:3] == ["/opt/paicad", "props", "apply"]
