"""extract-filter.md ①-1(V-EF-1·6·7·12): native 추출 조건 — params 정규화·options.json·features filter·train_setups.extract_filter·
통계 요약(로그·result)·재추출 백업·422 코드·defaults/geom_options 처리·altair 무변경 경계. 가짜 paicad."""

from __future__ import annotations

import json
from pathlib import Path

from helpers_native import make_project
from helpers_stage1 import job, make_inputs, study, submit
from physicsai_test_support import API, H

P = H("tok-power")

FILTER = {"groups": ["thickness", "position", "fillet"],
          "conditions": {"thickness_mm": {"min": 2, "max": 30}, "face_area_min_mm2": 50, "position_min_size_mm": 3,
                         "fillet_radius_min_mm": 1, "hole_radius_min_mm": 9},  # 선택 안 한 그룹(구멍 반경)의 조건은 제거된다
          "draft_max_deg": None}


def _extract(c, w, sid, ai: Path, name: str, tag: str = "", **params):
    proj = make_project(ai / name / "00_inbox" / tag)
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(proj / "bracket.step"), "engine": "native", **params})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    return j, ai / name / "01_train" / "extract" / j["id"]


def _read(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _train(c, sid):
    """GET /studies/{id}/train. 응답의 extract_filter는 스키마 모양이라 비어 있는 조건 키가 null로 나온다 → null 키를 뺀 정규화 모양으로 돌려준다."""
    ts = c.get(f"{API}/studies/{sid}/train", headers=P).json()
    f = ts.get("extract_filter")
    if f:
        f["conditions"] = {k: v for k, v in f["conditions"].items() if v is not None}
    return ts


def test_no_filter_is_unchanged_and_stats_summarized(p2_native):
    """V-EF-1: extract_filter 생략 → params·options.json·features에 filter 없음, train_setups.extract_filter null. 통계 요약은 항상."""
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "ef0")
    j, X = _extract(c, w, sid, ai, "ef0")
    assert "extract_filter" not in j["params"]
    opts = _read(X / "options.json")
    assert "filter" not in opts["extract"] and opts["extract"]["draft_max_deg"] == 3.0
    assert "filter" not in _read(X / "parameter_features.json")
    ts = _train(c, sid)
    assert ts["extract_filter"] is None and ts["engine"] == "native"
    assert {p["name"] for p in ts["parameters"]} == {"A_THK_1", "B_RIB_H_1", "C_HOLE_R_1"}  # RIB_POS 없음
    assert (X / "extract_stats.json").is_file()
    s = ts["extract_summary"]
    assert s["filter_applied"] is False and s["types"]["THICKNESS"]["kept"] == 2 and s["png_rendered"] == 4
    assert job(c, j["id"])["result"]["extract_summary"] == s


def test_filter_params_options_features_db_and_summary(p2_native):
    """V-EF-7: 정규화(미선택 그룹 조건 제거) 후 params·options.json·features filter·train_setups.extract_filter 일치 + 요약."""
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "ef1")
    j, X = _extract(c, w, sid, ai, "ef1", extract_filter=FILTER)
    norm = j["params"]["extract_filter"]
    assert norm == {"groups": ["thickness", "position", "fillet"],
                    "conditions": {"thickness_mm": {"min": 2.0, "max": 30.0}, "face_area_min_mm2": 50.0, "position_min_size_mm": 3.0,
                                   "fillet_radius_min_mm": 1.0}, "draft_max_deg": None}
    opts = _read(X / "options.json")["extract"]
    assert opts["filter"] == {"types": ["THICKNESS", "RIB_THICKNESS", "POCKET_WIDTH", "HOLE_POS_U", "HOLE_POS_V", "RIB_POS_U", "RIB_POS_V",
                                       "FILLET_RADIUS"],
                              "thickness_mm": {"min": 2.0, "max": 30.0}, "face_area_min_mm2": 50.0, "position_min_size_mm": 3.0,
                              "fillet_radius_min_mm": 1.0}
    assert opts["draft_max_deg"] == 3.0  # null → 설정·paicad 기본
    feats = _read(X / "parameter_features.json")
    assert feats["filter"] == {**opts["filter"], "draft_max_deg": 3.0}
    assert [f["name"] for f in feats["features"]] == ["A_THK_1", "A_THK_2", "B_RIB_U_1", "B_RIB_V_1"]  # types 밖 미출력 + RIB_POS 생성
    assert sorted(p.name for p in (X / "features").iterdir()) == ["A_THK_1.png", "A_THK_2.png", "B_RIB_U_1.png", "B_RIB_V_1.png"]
    ts = _train(c, sid)
    assert ts["extract_filter"] == norm
    assert [p["name"] for p in ts["parameters"]] == ["A_THK_1", "B_RIB_U_1", "B_RIB_V_1"]
    s = ts["extract_summary"]
    assert s["filter_applied"] is True and s["types"]["THICKNESS"]["kept"] == 2 and s["types"]["HOLE_RADIUS"]["selected"] is False
    assert s["types"]["RIB_POS_U"]["kept"] == 1 and s["types"]["RIB_THICKNESS"]["kept"] == 0 and s["png_rendered"] == 4
    assert job(c, j["id"])["result"]["feature_png_count"] == 4
    f = c.get(f"{API}/studies/{sid}/train/features", headers=P).json()  # features 응답 filter = 정규화본(유효 draft 포함)
    assert f["filter"]["groups"] == ["thickness", "position", "fillet"] and f["filter"]["draft_max_deg"] == 3.0
    assert [x["name"] for x in f["features"]] == ["A_THK_1", "A_THK_2", "B_RIB_U_1", "B_RIB_V_1"]
    log = (ai / "ef1" / "logs" / j["id"] / "step_02_SIMLAB_EXTRACT.log").read_text(encoding="utf-8")
    assert "두께: 판정 2 · 채택 2 · 제외 0" in log and "구멍 반경: 건너뜀(선택 안 함)" in log and "하이라이트 PNG 4장" in log


def test_draft_priority_and_defaults_filter_ignored(p2_native):
    """§6.3: draft_max_deg job > geometry.defaults > paicad 기본. geometry.defaults.extract.filter는 무시."""
    c, mk, ai, lc, _d = p2_native
    lc.settings.geometry.defaults["extract"] = {"draft_max_deg": 4.0, "filter": {"types": ["FILLET_RADIUS"]}}
    w = mk()
    sid = study(c, "ef2")
    j, X = _extract(c, w, sid, ai, "ef2")  # 필터 없음 → defaults의 filter는 쓰지 않는다
    o = _read(X / "options.json")["extract"]
    assert "filter" not in o and o["draft_max_deg"] == 4.0
    j2, X2 = _extract(c, w, sid, ai, "ef2", "b", extract_filter={**FILTER, "draft_max_deg": None})
    assert _read(X2 / "options.json")["extract"]["draft_max_deg"] == 4.0  # job null → defaults
    j3, X3 = _extract(c, w, sid, ai, "ef2", "c", extract_filter={**FILTER, "draft_max_deg": 6.5})
    o3 = _read(X3 / "options.json")["extract"]
    assert o3["draft_max_deg"] == 6.5 and _read(X3 / "parameter_features.json")["filter"]["draft_max_deg"] == 6.5
    assert _train(c, sid)["extract_filter"]["draft_max_deg"] == 6.5


def test_reextract_other_filter_backs_up_table_and_overwrites_record(p2_native):
    """U2·§6.5: 다른 조건으로 재추출 → 표를 새로 쓰고 이전 params.json은 백업, 기록은 새 조건(필터 없으면 null)."""
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "ef3")
    _j1, _X1 = _extract(c, w, sid, ai, "ef3", extract_filter=FILTER)
    assert [p["name"] for p in _train(c, sid)["parameters"]] == ["A_THK_1", "B_RIB_U_1", "B_RIB_V_1"]
    f2 = {"groups": ["height"], "conditions": {}, "draft_max_deg": None}
    j2, _X2 = _extract(c, w, sid, ai, "ef3", "b", extract_filter=f2)
    ts = _train(c, sid)
    assert [p["name"] for p in ts["parameters"]] == ["B_RIB_H_1"] and ts["extract_filter"]["groups"] == ["height"]
    assert list((ai / "ef3" / "_backup").glob("*/01_train/params.json"))  # 이전 표 백업
    j3, _X3 = _extract(c, w, sid, ai, "ef3", "c")
    ts = _train(c, sid)
    assert ts["extract_filter"] is None and len(ts["parameters"]) == 3  # 필터 없음 = null로 덮어씀


def test_empty_result_message_and_summary_kept(p2_native):
    """§5.2: 조건 때문에 피처 0개 → GEOM_EXTRACT_EMPTY + 조건 안내 문구, 통계 요약은 남는다."""
    c, mk, ai, lc, _d = p2_native
    w = mk()
    sid = study(c, "ef4")
    proj = make_project(ai / "ef4" / "00_inbox")
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(proj / "bracket.step"), "engine": "native",
                                              "extract_filter": {"groups": ["hole_radius"], "conditions": {"hole_radius_min_mm": 9}}})
    assert w.run_once_slot() == "FAILED"
    jd = job(c, j["id"])
    assert jd["failure_code"] == "GEOM_EXTRACT_EMPTY" and "조건에 맞는 피처가 없습니다 — 찾을 종류·조건을 넓혀 보세요" in jd["failure_message"]
    s = jd["result"]["extract_summary"]
    assert s["types"]["HOLE_RADIUS"]["excluded"] == {"hole_radius_min": 1} and s["types"]["HOLE_RADIUS"]["kept"] == 0
    assert _train(c, sid)["extract_filter"] is None  # 실패 — 설정은 바뀌지 않음


def test_filter_validation_422(p2_native):
    """V-EF-6: 422 EXTRACT_FILTER_INVALID(problems 한국어, 작업 생성 안 됨)."""
    c, mk, ai, lc, _d = p2_native
    sid = study(c, "ef5")
    proj = make_project(ai / "ef5" / "00_inbox")
    base = {"cad_path": str(proj / "bracket.step"), "engine": "native"}
    cases = [({"groups": []}, "groups", "찾을 종류를 하나 이상 고르세요"),
             ({"groups": ["fillet"], "conditions": {"fillet_radius_min_mm": -2}}, "conditions.fillet_radius_min_mm", "0보다 큰 값을 넣으세요"),
             ({"groups": ["thickness"], "conditions": {"thickness_mm": {"min": 9, "max": 3}}}, "conditions.thickness_mm", "최솟값이 최댓값보다 큽니다"),
             ({"groups": ["thickness"], "draft_max_deg": 50}, "draft_max_deg", "구배 허용각은 0°보다 크고 45°보다 작아야 합니다")]
    for flt, key, msg in cases:
        r = submit(c, sid, "TD_EXTRACT_PARAMS", {**base, "extract_filter": flt}, expect=422)
        d = r["detail"]
        assert d["code"] == "EXTRACT_FILTER_INVALID" and {"key": key, "message": msg} in d["problems"], d
    # 모양 오류(모르는 키·그룹)는 스키마가 거부(INVALID_PARAMS)
    for flt in ({"groups": ["x"]}, {"groups": ["fillet"], "conditions": {"zzz": 1}}, {"groups": ["fillet"], "extra": 1}):
        r = submit(c, sid, "TD_EXTRACT_PARAMS", {**base, "extract_filter": flt}, expect=422)
        assert r["detail"]["code"] == "INVALID_PARAMS"
    assert c.get(f"{API}/jobs", params={"study_id": sid}, headers=P).json() == []  # 422는 작업을 만들지 않는다


def test_unsupported_for_shell_native(p2_native):
    """쉘 비드 추출에 extract_filter → 422 EXTRACT_FILTER_UNSUPPORTED."""
    c, mk, ai, lc, _d = p2_native
    sid = study(c, "ef6")
    r = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(ai / "x.step"), "engine": "native", "kind": "shell", "extract_filter": FILTER}, expect=422)
    assert r["detail"]["code"] == "EXTRACT_FILTER_UNSUPPORTED"
    assert "native 솔리드 추출에서만" in r["detail"]["message"]


def test_altair_unchanged_and_filter_rejected(p2_env, fake_record):
    """V-EF-12: altair 요청의 extract_filter는 422 EXTRACT_FILTER_UNSUPPORTED(엔진 명시·생략 모두), altair 추출 자체는 현행 그대로
    (params에 extract_filter 없음, train_setups.extract_filter null, extract_stats 없음)."""
    c, mk, ai, lc, _d = p2_env
    w = mk()
    sid = study(c, "ef7")
    cad, _assem = make_inputs(ai / "ef7")
    for eng in ({}, {"engine": "altair"}):
        r = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(cad), "extract_filter": FILTER, **eng}, expect=422)
        assert r["detail"]["code"] == "EXTRACT_FILTER_UNSUPPORTED"
    j = submit(c, sid, "TD_EXTRACT_PARAMS", {"cad_path": str(cad)})
    assert w.run_once_slot() == "SUCCEEDED", job(c, j["id"])
    assert j["params"] == {"cad_path": str(cad)}
    ts = _train(c, sid)
    assert ts["engine"] == "altair" and ts["extract_filter"] is None and ts["extract_summary"] is None
    X = ai / "ef7" / "01_train" / "extract" / j["id"]
    assert not (X / "extract_stats.json").exists() and not (X / "options.json").exists()
