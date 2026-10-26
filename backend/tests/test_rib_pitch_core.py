"""rib-gap.md V-RG-9(플랫폼, DB 없는 부분): 추출 조건 그룹 `rib_pitch` 정규화·paicad 변환·요약 문구, openapi 열거값, 변수 풀의 열 정보·공동 범위 경고(순수 함수),
features 뷰(`row`·`rib_rows`), 용어집 ko, fake_paicad 합성 열."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from physicsai_api.schemas.extract_filter import ExtractFilter
from physicsai_core.geometry import extract_filter as ef
from physicsai_core.geometry import features_view as fv
from physicsai_core.geometry import native_vars as nv

FAKE = Path(__file__).parent / "fake_tools" / "fake_paicad"


def _raw(groups, **over):
    return {"groups": groups, "conditions": {}, "draft_max_deg": None, **over}


def test_group_normalize_order_and_types():
    n, probs = ef.normalize(_raw(["rib_pitch", "thickness", "position"]))
    assert probs == [] and n["groups"] == ["thickness", "position", "rib_pitch"]  # 표 순서(position 바로 뒤)
    flt, _ = ef.to_paicad(n)
    assert flt["types"] == ["THICKNESS", "RIB_THICKNESS", "POCKET_WIDTH", "HOLE_POS_U", "HOLE_POS_V", "RIB_POS_U", "RIB_POS_V",
                            "RIB_PITCH_U", "RIB_PITCH_V"]
    n2, _ = ef.normalize(_raw(["rib_pitch"], conditions={"thickness_mm": {"min": 1, "max": 5}, "position_min_size_mm": 3}))
    assert n2["conditions"] == {}  # 조건 없는 그룹 — 선택 안 한 그룹의 조건은 제거
    assert ef.to_paicad(n2)[0] == {"types": ["RIB_PITCH_U", "RIB_PITCH_V"]}
    assert ef.from_paicad({"types": ["RIB_PITCH_U", "RIB_PITCH_V", "RIB_POS_U"], "draft_max_deg": 3.0}) == \
        {"groups": ["position", "rib_pitch"], "conditions": {}, "draft_max_deg": 3.0}
    assert ef.from_paicad({"types": ["RIB_PITCH_V"]})["groups"] == ["rib_pitch"]
    assert ef.types_of(n2) == ["RIB_PITCH_U", "RIB_PITCH_V"]
    _, bad = ef.normalize(_raw(["rib_gap"]))
    assert bad and bad[0]["key"] == "groups" and "rib_gap" in bad[0]["message"]  # 모르는 그룹은 거부
    _, dup = ef.normalize(_raw(["rib_pitch", "rib_pitch"]))
    assert dup and "중복" in dup[0]["message"]


def test_labels_and_summary_lines():
    assert ef.GROUP_LABELS["rib_pitch"] == "리브 간격(피치)" and ef.TYPE_LABELS["RIB_PITCH_U"] == "리브 피치 U"
    assert {k: ef.EXCLUDED_LABELS[k] for k in ("not_slender", "row_branch", "row_single", "row_member")} == \
        {"not_slender": "기둥형", "row_branch": "열 분기", "row_single": "이웃 없음", "row_member": "간격 열 소속"}
    doc = {"filter_applied": True, "bodies": [{"body": "A", "types": {
        "RIB_PITCH_U": {"selected": True, "candidates": 6, "kept": 3, "excluded": {"not_slender": 1, "row_branch": 1, "row_single": 1}, "elapsed_s": 0.1},
        "RIB_PITCH_V": {"selected": False},
        "RIB_POS_U": {"selected": True, "candidates": 4, "kept": 1, "excluded": {"row_member": 3}, "elapsed_s": 0.0}}, "rib_rejects": {}}]}
    lines = ef.summary_lines(ef.summarize_stats(doc))
    assert "리브 피치 U: 후보 6 · 채택 3 · 제외 3(기둥형 1, 열 분기 1, 이웃 없음 1) · 0.1초" in lines
    assert "리브 위치 U: 후보 4 · 채택 1 · 제외 3(간격 열 소속 3) · 0.0초" in lines
    assert not any("리브 피치 V" in x for x in lines)  # 선택 안 한 종류는 같은 그룹 중 하나라도 골랐으면 줄 없음


def test_api_schema_enum_and_openapi():
    f = ExtractFilter.model_validate({"groups": ["position", "rib_pitch"]})
    assert f.groups == ["position", "rib_pitch"]
    try:
        ExtractFilter.model_validate({"groups": ["rib_gap"]})
    except ValueError:
        pass
    else:
        raise AssertionError("알 수 없는 그룹이 통과함")
    spec = json.loads((Path(__file__).parents[1] / "openapi.json").read_text(encoding="utf-8"))
    items = spec["components"]["schemas"]["ExtractFilter"]["properties"]["groups"]["items"]["enum"]
    assert items == ["thickness", "height", "position", "rib_pitch", "hole_radius", "fillet"]
    sch = spec["components"]["schemas"]
    assert "rib_rows" in sch["NativeFeatures"]["properties"] and "row" in sch["NativeFeature"]["properties"]
    assert "rib" in sch["NativeVarPoolRow"]["properties"] and "rib" in sch["VarRow"]["properties"]
    assert {"row", "k", "n", "anchor", "gap_mm", "end_room_mm"} <= set(sch["VarRib"]["properties"])


# ---- 변수 풀·경고(순수) ------------------------------------------------------------------------------------------


def _pf(name, typ, nominal, lo, hi, **extra):
    return {"name": name, "type": typ, "body": "B", "nominal": nominal, "unit": "mm", "range": {"min": lo, "max": hi, "ratio": None},
            "group": None, "ref": {"rule": "nearest_fixed", "provisional": True, "locked": False}, **extra}


def _doc(anchor="rib:2", n=3, room=(9.0, 9.0), with_rows=True):
    ribs = [{"index": i, "cap": f"F{i}0", "minus": f"F{i}1", "plus": f"F{i}2", "moving": [], "thickness": 6.0, "center": 20.0 * i} for i in range(1, n + 1)]
    feats = [_pf(f"B_RIB_PITCH_U_{k}", "RIB_PITCH_U", 20.0, 15.0, 25.0, feasible={"min": 7.0, "max": 27.0},
                 measure={"faces": [f"F{k}1", f"F{k}2", f"F{k + 1}1", f"F{k + 1}2"]}, row={"id": "U1", "k": k, "n": n}) for k in range(1, n)]
    feats += [_pf("B_RIB_T_1", "RIB_THICKNESS", 6.0, 5.7, 6.3, measure={"faces": ["F11", "F12"]}),
              _pf(f"B_RIB_T_{n}", "RIB_THICKNESS", 6.0, 5.7, 6.3, measure={"faces": [f"F{n}1", f"F{n}2"]})]
    doc = {"features": feats, "groups": []}
    if with_rows:
        doc["rib_rows"] = [{"id": "U1", "body": "B", "axis": "x", "anchor": anchor, "ribs": ribs,
                            "end_room_mm": {"minus": room[0], "plus": room[1]}}]
    return doc


def _vars(doc, ranges):
    pool = nv.pool(doc)
    rows = [{"name": e["name"], "nominal": e["nominal"], "min": ranges.get(e["name"], (e["default_range"]["min"], e["default_range"]["max"]))[0],
             "max": ranges.get(e["name"], (e["default_range"]["min"], e["default_range"]["max"]))[1], "unit": "mm"} for e in pool]
    return nv.effective(rows, pool)[0], pool


def test_pool_rib_info_and_position_flag():
    doc = _doc("mid:1", n=3)
    pool = {e["name"]: e for e in nv.pool(doc)}
    e = pool["B_RIB_PITCH_U_2"]
    assert e["position"] is False and e["type"] == "RIB_PITCH_U" and e["feasible"]["min"] == 7.0
    assert nv.rib_public(e["rib"]) == {"row": "U1", "k": 2, "n": 3, "anchor": "mid:1", "gap_mm": 14.0, "end_room_mm": {"minus": 9.0, "plus": 9.0}}
    assert [(r["index"], r["thk"]) for r in e["rib"]["ribs"]] == [(1, "B_RIB_T_1"), (2, None), (3, "B_RIB_T_3")]
    assert "rib" not in pool["B_RIB_T_1"] and nv.rib_public(None) is None and nv.rib_public({"row": 1}) is None
    # rib_rows가 없으면(수작업 파일 등) 변수는 풀에 남고 열 정보·경고만 생략
    bare = {e["name"]: e for e in nv.pool(_doc(with_rows=False))}
    assert "B_RIB_PITCH_U_1" in bare and "rib" not in bare["B_RIB_PITCH_U_1"]
    vd, _ = _vars(_doc(with_rows=False), {"B_RIB_PITCH_U_1": (15.0, 80.0)})
    assert _joint(vd) == []
    # snapshot 행에 열 정보가 실리고 apply가 표시 키를 뺀다
    vd, _ = _vars(doc, {})
    assert any("rib" in v for v in vd["variables"]) and all("rib" not in r for r in nv.apply({"parameters": []}, vd)["parameters"])
    vr = {r["name"]: r for r in nv.var_rows(vd, nv.pool(doc))}
    assert vr["B_RIB_PITCH_U_1"]["rib"]["row"] == "U1" and "rib" not in vr["B_RIB_T_1"] and vr["B_RIB_PITCH_U_1"]["position"] is False


def _joint(vd, bounds=None):
    return [w for w in nv.warn_rows(vd, bounds) if w["code"] == "RIB_PITCH_JOINT_RANGE"]


def test_joint_range_side_weights_anchor_first_last_and_bounds():
    assert nv._side_weights("rib:2", 1) == (1.0, 0.0) and nv._side_weights("rib:2", 2) == (0.0, 1.0)
    assert nv._side_weights("mid:2", 1) == (1.0, 0.0) and nv._side_weights("mid:2", 2) == (0.5, 0.5) and nv._side_weights("mid:2", 3) == (0.0, 1.0)
    assert nv._side_weights("rib:1", 1) == (0.0, 1.0) and nv._side_weights("rib:4", 3) == (1.0, 0.0) and nv._side_weights("bogus", 1) == (0.0, 0.0)
    # first(rib:1): 모든 피치가 +쪽 — 상한 합 10 > 끝 여유(+) 9
    doc = _doc("rib:1", n=3, room=(1.0, 9.0))
    vd, _ = _vars(doc, {})
    ws = _joint(vd)  # +쪽 5 + 5 + 끝 리브 두께 ½·0.3 = 10.15 > 9 → 경고 1건(−쪽은 쓰는 피치 없음)
    assert len(ws) == 1 and "+쪽" in ws[0]["message"] and "(U1)" in ws[0]["message"] and ws[0]["name"] == "B_RIB_PITCH_U_1"
    # bounds(실행 범위)가 변수 기준 범위를 대신한다: 피치 두 개를 [15, 25] → bounds [15, 22]면 +쪽 합 4 ≤ 9
    assert _joint(vd, {"B_RIB_PITCH_U_1": [15, 22], "B_RIB_PITCH_U_2": [15, 22]}) == []
    # 끝 여유를 모르면(None) 그 쪽은 판정하지 않는다
    doc2 = _doc("rib:1", n=3)
    doc2["rib_rows"][0]["end_room_mm"] = {"minus": None, "plus": None}
    vd2, _ = _vars(doc2, {"B_RIB_PITCH_U_1": (15.0, 60.0)})
    assert _joint(vd2) == []


def test_joint_range_rows_are_per_body_even_with_same_row_id():
    """실제 paicad는 열 id(U1…)를 바디마다 다시 매긴다 — 바디 A·B의 같은 id 열이 서로의 끝 여유·기준을 섞으면 안 된다."""
    a, b = _doc("rib:1", n=3, room=(1.0, 9.0)), _doc("rib:1", n=3, room=(1.0, 99.0))
    for f in b["features"]:
        f["name"] = f["name"].replace("B_", "C_")
        f["body"] = "C"
    b["rib_rows"][0]["body"] = "C"
    doc = {"features": a["features"] + b["features"], "groups": [], "rib_rows": a["rib_rows"] + b["rib_rows"]}
    vd, _ = _vars(doc, {})
    ws = _joint(vd)
    assert [w["name"] for w in ws] == ["B_RIB_PITCH_U_1"]  # A(끝 여유 9)만 넘고 C(끝 여유 99)는 넘지 않는다


def test_features_view_row_and_rib_rows_sanitized():
    doc = _doc("mid:2", n=4)
    doc["rib_rows"][0]["face_signatures"] = {"F11": "sig"}
    doc["rib_rows"][0]["end_limited_by"] = {"minus": "B_RIB_T_1", "plus": None}
    doc["features"].append(_pf("X_THK_1", "THICKNESS", 3.0, 2.0, 4.0, row={"id": 5, "k": "a"}))  # 모양이 틀린 row는 버린다
    rows = {r["name"]: r for r in fv.feature_rows(doc)}
    assert rows["B_RIB_PITCH_U_2"]["row"] == {"id": "U1", "k": 2, "n": 4} and "row" not in rows["B_RIB_T_1"] and "row" not in rows["X_THK_1"]
    s = fv.summary(doc)
    assert s["rib_rows"][0]["anchor"] == "mid:2" and s["rib_rows"][0]["end_limited_by"] == {"minus": "B_RIB_T_1", "plus": None}
    assert "face_signatures" not in s["rib_rows"][0] and s["rib_rows"][0]["ribs"][0] == {"index": 1, "thickness": 6.0, "center": 20.0}
    assert fv.summary({"features": []})["rib_rows"] is None and fv.rib_rows({"rib_rows": "x"}) is None


def test_glossary_terms_have_ko_for_pitch_types():
    terms = yaml.safe_load((Path(__file__).parents[1] / "physicsai_api" / "mcp" / "glossary_terms.yaml").read_text(encoding="utf-8"))["terms"]
    by = {t["key"]: t for t in terms}
    for k in ("feature:RIB_PITCH_U", "feature:RIB_PITCH_V"):
        assert by[k]["ko"] and by[k]["unit"] == "mm" and "리브 간격" in by[k]["ko"]


def _fake_extract(tmp_path, types, env_extra=None):
    cad = tmp_path / "m.step"
    cad.write_text("ISO-10303-21;")
    opts = tmp_path / "options.json"
    opts.write_text(json.dumps({"extract": {"filter": {"types": types}, "draft_max_deg": 3.0}} if types else {"extract": {}}))
    out = tmp_path / "out"
    import os

    env = {**os.environ, **(env_extra or {})}
    if not (env_extra or {}).get("FAKE_PAICAD_FEATURES"):
        env.pop("FAKE_PAICAD_FEATURES", None)
    r = subprocess.run([sys.executable, str(FAKE), "extract", "--cad", str(cad), "--options", str(opts), "--out-dir", str(out)],
                       capture_output=True, text=True, env=env, shell=False, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads((out / "parameter_features.json").read_text()), json.loads((out / "extract_stats.json").read_text())


def test_fake_paicad_synthetic_rib_rows_only_with_pitch_types(tmp_path):
    (tmp_path / "a").mkdir()
    doc, stats = _fake_extract(tmp_path / "a", ["RIB_PITCH_U", "RIB_PITCH_V", "RIB_THICKNESS"])
    names = [f["name"] for f in doc["features"]]
    assert names == ["B_RIB_PITCH_U_1", "B_RIB_PITCH_U_2", "B_RIB_PITCH_U_3", "B_RIB_PITCH_V_1", "B_RIB_PITCH_V_2", "B_RIB_T_1", "B_RIB_T_2"]
    assert [r["id"] for r in doc["rib_rows"]] == ["U1", "V1"] and doc["rib_rows"][0]["anchor"] == "mid:2" and doc["rib_rows"][1]["anchor"] == "rib:2"
    f = {x["name"]: x for x in doc["features"]}
    assert f["B_RIB_PITCH_U_2"]["row"] == {"id": "U1", "k": 2, "n": 4} and f["B_RIB_PITCH_U_2"]["measure"]["method"] == "rib_pitch"
    body_b = next(b for b in stats["bodies"] if b["body"] == "B")["types"]
    assert body_b["RIB_PITCH_U"]["selected"] is True and body_b["RIB_PITCH_U"]["kept"] == 3 and body_b["RIB_PITCH_V"]["kept"] == 2
    # 한 방향만 고르면 그 열만(rib_rows도 사용된 열만)
    (tmp_path / "b").mkdir()
    doc, _ = _fake_extract(tmp_path / "b", ["RIB_PITCH_V"])
    assert [x["name"] for x in doc["features"]] == ["B_RIB_PITCH_V_1", "B_RIB_PITCH_V_2"] and [r["id"] for r in doc["rib_rows"]] == ["V1"]
    # RIB_PITCH 미선택·필터 없음 = 기존 출력(rib_rows·row 없음)
    for i, types in enumerate((["THICKNESS", "RIB_POS_U"], None)):
        (tmp_path / f"c{i}").mkdir()
        doc, stats = _fake_extract(tmp_path / f"c{i}", types)
        assert "rib_rows" not in doc and not any(x["type"].startswith("RIB_PITCH") or "row" in x for x in doc["features"])
        assert stats["bodies"][0]["types"]["RIB_PITCH_U"] == {"selected": False}
