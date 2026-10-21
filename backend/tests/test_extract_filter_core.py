"""extract-filter.md V-EF-6·V-EF-7(core 부분): 그룹↔종류 매핑·정규화·검증·paicad 변환·통계 요약·옵션(geom_options 거부·defaults 경고)."""

from __future__ import annotations

import copy

import pytest

from physicsai_core.geometry import extract_filter as ef
from physicsai_core.geometry.options import DEFAULT_OPTIONS, effective_options, normalize_override


def _norm(**over):
    raw = {"groups": ["thickness", "position", "fillet"],
           "conditions": {"thickness_mm": {"min": 2, "max": 30}, "face_area_min_mm2": 50, "position_min_size_mm": 3,
                          "fillet_radius_min_mm": 1, "height_mm": {"min": 1, "max": None}, "hole_radius_min_mm": 0.5},
           "draft_max_deg": None, **over}
    n, probs = ef.normalize(raw)
    assert probs == [], probs
    return n


def test_group_types_single_definition():
    assert list(ef.GROUP_TYPES) == ["thickness", "height", "position", "hole_radius", "fillet"]
    assert ef.GROUP_TYPES["position"] == ("HOLE_POS_U", "HOLE_POS_V", "RIB_POS_U", "RIB_POS_V")
    assert ef.GROUP_TYPES["thickness"] == ("THICKNESS", "RIB_THICKNESS", "POCKET_WIDTH")
    all_types = [t for g in ef.GROUP_TYPES.values() for t in g]
    assert len(all_types) == len(set(all_types)) == 11
    # 모든 조건 키는 정확히 한 그룹에 속한다
    owned = [k for ks in ef.GROUP_CONDITIONS.values() for k in ks]
    assert sorted(owned) == sorted(ef.CONDITION_KEYS)


def test_normalize_drops_unselected_group_conditions_and_orders_groups():
    n = _norm(groups=["fillet", "thickness", "position"])
    assert n["groups"] == ["thickness", "position", "fillet"]  # 표 순서로 고정
    assert set(n["conditions"]) == {"thickness_mm", "face_area_min_mm2", "position_min_size_mm", "fillet_radius_min_mm"}
    assert n["conditions"]["thickness_mm"] == {"min": 2.0, "max": 30.0}
    assert n["draft_max_deg"] is None
    flt, draft = ef.to_paicad(n)
    assert flt["types"] == ["THICKNESS", "RIB_THICKNESS", "POCKET_WIDTH", "HOLE_POS_U", "HOLE_POS_V", "RIB_POS_U", "RIB_POS_V", "FILLET_RADIUS"]
    assert "height_mm" not in flt and "hole_radius_min_mm" not in flt and draft is None


def test_normalize_nulls_and_one_sided_range():
    n = ef.normalize({"groups": ["height"], "conditions": {"height_mm": {"min": None, "max": 8}, "face_area_min_mm2": None}})[0]
    assert n["conditions"] == {"height_mm": {"min": None, "max": 8.0}}
    n = ef.normalize({"groups": ["height"], "conditions": {"height_mm": {"min": None, "max": None}}, "draft_max_deg": 5})[0]
    assert n["conditions"] == {} and n["draft_max_deg"] == 5.0
    assert ef.normalize(None) == (None, [])
    assert ef.normalize({"groups": ["fillet"]})[0]["conditions"] == {}


@pytest.mark.parametrize("raw, key, text", [
    ({"groups": []}, "groups", "찾을 종류를 하나 이상 고르세요"),
    ({"groups": ["thickness", "thickness"]}, "groups", "중복"),
    ({"groups": ["nope"]}, "groups", "알 수 없는"),
    ({"groups": ["fillet"], "conditions": {"fillet_radius_min_mm": 0}}, "conditions.fillet_radius_min_mm", "0보다 큰 값을 넣으세요"),
    ({"groups": ["fillet"], "conditions": {"fillet_radius_min_mm": -1}}, "conditions.fillet_radius_min_mm", "0보다 큰 값을 넣으세요"),
    ({"groups": ["thickness"], "conditions": {"thickness_mm": {"min": 5, "max": 2}}}, "conditions.thickness_mm", "최솟값이 최댓값보다 큽니다"),
    ({"groups": ["thickness"], "conditions": {"thickness_mm": {"min": 1, "max": 0}}}, "conditions.thickness_mm.max", "0보다 큰 값을 넣으세요"),
    ({"groups": ["thickness"], "conditions": {"thickness_mm": {"min": -1}}}, "conditions.thickness_mm.min", "0 이상"),
    ({"groups": ["thickness"], "draft_max_deg": 0}, "draft_max_deg", "구배 허용각은 0°보다 크고 45°보다 작아야 합니다"),
    ({"groups": ["thickness"], "draft_max_deg": 45}, "draft_max_deg", "구배 허용각은 0°보다 크고 45°보다 작아야 합니다"),
    ({"groups": ["thickness"], "conditions": {"zzz": 1}}, "conditions.zzz", "알 수 없는 조건"),
    # 선택하지 않은 그룹의 조건도 값 검사는 한다(숨은 오류 방지)
    ({"groups": ["fillet"], "conditions": {"thickness_mm": {"min": 9, "max": 1}}}, "conditions.thickness_mm", "최솟값"),
])
def test_normalize_problems_korean(raw, key, text):
    n, probs = ef.normalize(raw)
    assert n is None
    assert any(p["key"] == key and text in p["message"] for p in probs), probs


def test_paicad_roundtrip_and_features_filter():
    n = _norm(draft_max_deg=5)
    flt, draft = ef.to_paicad(n)
    assert draft == 5.0
    back = ef.from_paicad(dict(flt, draft_max_deg=5.0))
    assert back == n
    # features `filter`는 유효 draft를 항상 가진다(기본 3.0), 모르는 모양은 None
    assert ef.from_paicad({"types": ["FILLET_RADIUS"], "draft_max_deg": 3.0}) == {"groups": ["fillet"], "conditions": {}, "draft_max_deg": 3.0}
    assert ef.from_paicad(None) is None and ef.from_paicad({"types": []}) is None and ef.from_paicad({"types": "x"}) is None


def test_apply_to_options_priority_and_no_filter_unchanged():
    base = effective_options({"extract": {"draft_max_deg": 4.0}})[0]
    assert ef.apply_to_options(base, None) == base and "filter" not in base["extract"]  # 필터 없음 = 현행 문서와 같음
    n = _norm()
    out = ef.apply_to_options(base, n)
    assert out["extract"]["draft_max_deg"] == 4.0 and out["extract"]["filter"]["types"][0] == "THICKNESS"  # defaults 유지
    assert ef.apply_to_options(base, _norm(draft_max_deg=7))["extract"]["draft_max_deg"] == 7.0  # job > defaults
    assert "filter" not in base["extract"]  # 입력 불변
    d2 = ef.apply_to_options(DEFAULT_OPTIONS, n)
    assert d2["extract"]["draft_max_deg"] == 3.0  # paicad 기본


def test_inherit_features_filter_moves_draft():
    feats = {"types": ["THICKNESS", "RIB_THICKNESS", "POCKET_WIDTH"], "face_area_min_mm2": 50, "draft_max_deg": 4.5}
    out = ef.options_inherit_features_filter(DEFAULT_OPTIONS, feats)
    assert out["extract"]["filter"] == {"types": feats["types"], "face_area_min_mm2": 50}
    assert out["extract"]["draft_max_deg"] == 4.5
    assert ef.options_inherit_features_filter(DEFAULT_OPTIONS, None) == DEFAULT_OPTIONS


def test_geom_options_extract_filter_rejected_and_defaults_ignored():
    over, probs = normalize_override({"extract": {"filter": {"types": ["THICKNESS"]}}})
    assert [p["key"] for p in probs] == ["extract.filter"] and "geom_options가 아니라 등록 요청의 extract_filter" in probs[0]["message"]
    # 설정 defaults의 extract.filter는 무시(문제 아님) — 유효 옵션에도 남지 않는다
    opts, probs = effective_options({"extract": {"filter": {"types": ["THICKNESS"]}, "draft_max_deg": 4.0}})
    assert probs == [] and "filter" not in opts["extract"] and opts["extract"]["draft_max_deg"] == 4.0
    d = {"extract": {"filter": {"x": 1}}}
    snap = copy.deepcopy(d)
    ef.strip_defaults_filter(d)
    assert d == snap and ef.has_defaults_filter(d) and not ef.has_defaults_filter({"extract": {}})


def test_config_warning_for_defaults_filter():
    from physicsai_core.config import load_config_dict

    lc = load_config_dict({"storage": {"ai_root": "/tmp"}, "geometry": {"defaults": {"extract": {"filter": {"types": ["THICKNESS"]}}}}},
                          environ={})
    assert not any(i.key.startswith("geometry.defaults") for i in lc.issues)  # 오류 아님
    w = [x for x in lc.warnings if x.key == "geometry.defaults.extract.filter"]
    assert len(w) == 1 and "쓰지 않습니다 — 추출 조건은 추출·세트 등록 때 사용자가 정합니다" in w[0].message
    lc2 = load_config_dict({"storage": {"ai_root": "/tmp"}}, environ={})
    assert not any(x.key == "geometry.defaults.extract.filter" for x in lc2.warnings)


STATS = {
    "schema_version": 1, "engine": "native", "filter_applied": True,
    "bodies": [
        {"body": "A", "types": {
            "THICKNESS": {"selected": True, "initiators": 120, "pair_tests": 180, "kept": 12,
                          "excluded": {"face_area": 180, "thickness_range": 9, "not_mutual": 21}, "elapsed_s": 41.3},
            "HOLE_RADIUS": {"selected": False}, "HOLE_POS_U": {"selected": False}, "HOLE_POS_V": {"selected": False},
            "FILLET_RADIUS": {"selected": True, "candidates": 30, "kept": 4, "excluded": {"fillet_radius_min": 26}, "elapsed_s": 0.01},
            "RIB_POS_U": {"selected": True, "candidates": 3, "kept": 1, "excluded": {"base_axis": 2, "weird_new": 1}, "elapsed_s": 0.0}},
         "rib_rejects": {"cap_not_convex": 14, "lateral_not_plane": 6, "lateral_draft": 3, "base_mismatch": 2}},
        {"body": "B", "types": {"THICKNESS": {"selected": True, "initiators": 1, "pair_tests": 2, "kept": 1, "excluded": {}, "elapsed_s": 1.0}},
         "rib_rejects": {"height_not_positive": 1, "mystery": 2}},
    ],
    "png": {"rendered": 20, "elapsed_s": 8.2}, "elapsed_s": {"total": 72.5},
}


def test_summarize_stats_sums_bodies_and_lines_korean():
    s = ef.summarize_stats(STATS)
    t = s["types"]
    assert t["THICKNESS"]["kept"] == 13 and t["THICKNESS"]["pair_tests"] == 182 and t["THICKNESS"]["excluded"]["face_area"] == 180
    assert t["THICKNESS"]["elapsed_s"] == 42.3 and t["HOLE_RADIUS"] == {"selected": False, "kept": 0, "excluded": {}}
    assert s["png_rendered"] == 20 and s["elapsed_s"] == 72.5 and s["filter_applied"] is True
    assert s["rib_rejects"]["cap_not_convex"] == 14
    lines = ef.summary_lines(s)
    assert lines[0] == "두께: 판정 182 · 채택 13 · 제외 210(면적 180, 범위 9, 비상호 21) · 42.3초"
    assert "필렛 반경: 후보 30 · 채택 4 · 제외 26(반경 26) · 0.0초" in lines
    assert any(l.startswith("리브 위치 U: 후보 3") and "축 비정렬 2" in l and "weird_new 1" in l for l in lines)  # 모르는 키는 원문
    assert "구멍 반경: 건너뜀(선택 안 함)" in lines and "위치(구멍·리브)" not in " ".join(x for x in lines if "건너뜀" in x)
    assert "하이라이트 PNG 20장 · 8.2초 · 전체 72.5초" in lines
    assert lines[-1] == ("리브 후보 탈락 28(윗면 볼록 아님 14, 측면 곡면 6, 측면 구배 3, 밑면 불일치 2, 높이 0 이하 1, mystery 2)")


def test_summary_without_filter_hides_unselected_and_bad_input_is_none():
    st = copy.deepcopy(STATS)
    st["filter_applied"] = False
    st["bodies"] = [{"body": "A", "types": {"THICKNESS": {"selected": True, "kept": 1, "excluded": {}, "initiators": 1, "pair_tests": 1},
                                           "RIB_POS_U": {"selected": False}}}]
    lines = ef.summary_lines(ef.summarize_stats(st))
    assert not any("건너뜀" in l for l in lines) and lines[0].startswith("두께: 판정 1 · 채택 1 · 제외 0")
    assert ef.summarize_stats(None) is None and ef.summarize_stats({"bodies": "x"}) is None and ef.summarize_stats([]) is None


def test_judge_extract_empty_code_from_result_line(tmp_path):
    """보고에 코드가 없어도(피처 0개 보고) stdout `PAICAD RESULT FAIL GEOM_EXTRACT_EMPTY`의 코드를 쓴다 — 필터 안내 문구의 전제."""
    from physicsai_core.geometry.judge import judge_paicad

    rep = tmp_path / "parameter_features.json"
    rep.write_text('{"schema_version": 1, "engine": "native", "features": []}', encoding="utf-8")
    v = judge_paicad(13, str(rep), [], max_bytes=10_000, result_line=("FAIL", "GEOM_EXTRACT_EMPTY"))
    assert not v.ok and v.code == "GEOM_EXTRACT_EMPTY" and "인식된 피처 없음" in (v.message or "")
    v = judge_paicad(20, str(rep), [], max_bytes=10_000, result_line=("FAIL", None))
    assert v.code == "GEOM_INTERNAL"  # 코드가 어디에도 없으면 현행


# V-EF-12(altair 무변경 경계): extract_filter를 다루는 코드 위치의 닫힌 목록. altair(SimLab·NX) 전용 모듈은 이 문자열을 갖지 않는다.
# 요청 검증 분기는 job_params/__init__.py(①-1)·services/stage4_predict.py(④ 등록) 두 곳뿐이다.
EF_FILES = {
    "backend/physicsai_api/routers/param_sets.py", "backend/physicsai_api/schemas/__init__.py", "backend/physicsai_api/schemas/extract_filter.py",
    "backend/physicsai_api/schemas/geometry.py", "backend/physicsai_api/schemas/stage1_train_data.py", "backend/physicsai_api/schemas/stage4_predict.py",
    "backend/physicsai_api/services/job_params/__init__.py", "backend/physicsai_api/services/job_params/stage1_native.py",
    "backend/physicsai_api/services/job_params/stage1_train_data.py", "backend/physicsai_api/services/job_params/stage4_native.py",
    "backend/physicsai_api/services/param_set_baselines_api.py", "backend/physicsai_api/services/param_set_native_api.py",
    "backend/physicsai_api/services/stage1_train_data.py", "backend/physicsai_api/services/stage4_predict.py",
    "backend/physicsai_core/config/loader.py", "backend/physicsai_core/db/tables/stage1_train_data.py",
    "backend/physicsai_core/geometry/extract_filter.py", "backend/physicsai_core/geometry/features_view.py", "backend/physicsai_core/geometry/native_vars.py",
    "backend/physicsai_core/geometry/options.py",
    "backend/physicsai_core/stage4_predict/param_discover_native.py", "worker/physicsai_worker/steps/geometry_native.py",
    "worker/physicsai_worker/steps/stage1_train_data/extract.py", "worker/physicsai_worker/steps/stage1_train_data/extract_native.py",
    "worker/physicsai_worker/steps/stage4_predict/param_set_native.py",
}


def test_v_ef_12_altair_boundary_static():
    from physicsai_test_support import REPO

    found = set()
    for root in ("backend/physicsai_core", "backend/physicsai_api", "worker/physicsai_worker"):
        for p in (REPO / root).rglob("*.py"):
            t = p.read_text(encoding="utf-8")
            if "extract_filter" in t or "extract-filter" in t:
                found.add(p.relative_to(REPO).as_posix())
    assert found == EF_FILES, (found ^ EF_FILES)
    # 공유 파일 두 곳(①-1 TX_PARSE·TX_PREP 분기)은 native 가지 안에서만 필터를 다룬다
    ex = (REPO / "worker/physicsai_worker/steps/stage1_train_data/extract.py").read_text(encoding="utf-8")
    assert ex.count("extract_filter") == 2 and '"extract_filter": ctx.params.get("extract_filter")} if native' in ex
    for altair_only in ("worker/physicsai_worker/steps/launcher.py", "backend/physicsai_core/stage4_predict/param_discover.py",
                        "backend/physicsai_core/stage4_predict/param_sets.py", "backend/physicsai_core/stage1_train_data/train_tpl.py",
                        "backend/physicsai_core/stage1_train_data/train_params.py", "backend/physicsai_core/commands.py"):
        assert "extract_filter" not in (REPO / altair_only).read_text(encoding="utf-8"), altair_only
