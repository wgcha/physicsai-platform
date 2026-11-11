"""SM-C3~C8(shell-morph.md §14, 플랫폼 0.2.17) 쉘 옵션 새 키: 통과·범위 검증·기본값 생략·정책 skip 고정·hold 자격(V-SM-13 확장, V-SM-19·20 플랫폼 측)."""

from __future__ import annotations

import copy

from physicsai_core.geometry import messages
from physicsai_core.geometry.shell_options import (
    DEFAULT_SHELL_OPTIONS,
    NEW_KEY_DEFAULTS,
    effective_shell_options,
    force_skip,
    hold_problems,
    paicad_document,
    policy_of,
    prep_options_sha256,
)

NEW = {"fixed": {"policy": "warn"}, "quality": {"fail_policy": "warn", "distort_min_mm": 0.2, "distort_rel": 0.3},
       "extract": {"islands": False, "island_max_mm": 30, "island_ring_frac": 0.8}, "tag": {"label_angle_deg": 20},
       "bead": {"hold": {"beads": ["CHASSIS_REAR_B5"], "ring_mm": 4.0, "blend_mm": 9.0}}}


def test_new_keys_pass_through_and_validate():
    opts, probs = effective_shell_options(None, NEW)
    assert probs == []
    assert opts["fixed"]["policy"] == "warn" and opts["quality"]["fail_policy"] == "warn" and opts["extract"]["islands"] is False
    assert opts["bead"]["hold"] == {"beads": ["CHASSIS_REAR_B5"], "ring_mm": 4.0, "blend_mm": 9.0}
    assert policy_of(opts) == {"fixed": "warn", "quality": "warn"}
    doc = paicad_document(opts)
    assert doc["kind"] == "shell" and doc["fixed"]["policy"] == "warn" and doc["tag"]["label_angle_deg"] == 20


def test_defaults_equal_new_keys_are_not_written():
    base, _ = effective_shell_options(None, None)
    explicit = {sec: dict(keys) for sec, keys in NEW_KEY_DEFAULTS.items()}
    explicit["extract"] = {"islands": True, "island_max_mm": 40, "island_ring_frac": 0.9}  # 정수 40도 기본값과 같다
    opts, probs = effective_shell_options(None, explicit)
    assert probs == [] and opts == base  # 기본값과 같은 새 키는 유효 옵션(= options.json)에 없다
    assert paicad_document(opts) == paicad_document(base)
    assert set(base) == set(DEFAULT_SHELL_OPTIONS) and all(k not in base["fixed"] for k in ("policy",))
    assert "hold" not in base["bead"] and "fail_policy" not in base["quality"] and "islands" not in base["extract"]
    assert "label_angle_deg" not in base["tag"]
    # 부분 hold: beads만 주면 ρ·b는 기본값으로 채워진다. beads가 비면 hold 전체가 기본값 = 생략
    o2, p2 = effective_shell_options(None, {"bead": {"hold": {"beads": ["B1"]}}})
    assert p2 == [] and o2["bead"]["hold"] == {"beads": ["B1"], "ring_mm": 3.0, "blend_mm": 8.0}
    o3, _ = effective_shell_options(None, {"bead": {"hold": {"beads": []}}})
    assert o3 == base


def test_new_keys_do_not_change_prep_sha():
    base, _ = effective_shell_options(None, None)
    opts, _ = effective_shell_options(None, NEW)
    assert prep_options_sha256(opts) == prep_options_sha256(base)  # 정책·label_angle은 준비본(STALE) 무관
    tagged, _ = effective_shell_options(None, {"tag": {"tol_abs_mm": 0.07}})
    assert prep_options_sha256(tagged) != prep_options_sha256(base)


def test_new_key_ranges_rejected():
    bad = {"fixed": {"policy": "ignore"}, "quality": {"fail_policy": "x", "distort_min_mm": 0, "distort_rel": -1},
           "extract": {"islands": "yes", "island_max_mm": 0, "island_ring_frac": 1.5}, "tag": {"label_angle_deg": 91},
           "bead": {"hold": {"beads": ["a", "a"], "ring_mm": 0, "blend_mm": -2, "x": 1}}}
    _o, probs = effective_shell_options(None, bad)
    keys = {p["key"] for p in probs}
    assert keys == {"fixed.policy", "quality.fail_policy", "quality.distort_min_mm", "quality.distort_rel", "extract.islands",
                    "extract.island_max_mm", "extract.island_ring_frac", "tag.label_angle_deg", "bead.hold.beads", "bead.hold.ring_mm",
                    "bead.hold.blend_mm", "bead.hold.x"}
    _o, probs = effective_shell_options(None, {"bead": {"hold": ["B1"]}})
    assert [p["key"] for p in probs] == ["bead.hold"]
    _o, probs = effective_shell_options(None, {"fixed": {"nope": 1}})  # 모르는 키 거부는 그대로
    assert [p["key"] for p in probs] == ["fixed.nope"]


def test_predict_optimize_policy_forced_skip():
    opts, _ = effective_shell_options(None, NEW)
    snap = copy.deepcopy(opts)
    f = force_skip(opts)
    assert opts == snap  # 원본 불변
    assert policy_of(f) == {"fixed": "skip", "quality": "skip"} and "policy" not in f["fixed"] and "fail_policy" not in f["quality"]
    assert f["bead"]["hold"]["beads"] == ["CHASSIS_REAR_B5"] and f["extract"]["islands"] is False  # 정책만 고정, 나머지 유지


def test_hold_must_be_hold_eligible():
    opts, _ = effective_shell_options(None, NEW)
    feats = {"beads": [{"id": "CHASSIS_REAR_B5", "hold_eligible": True}, {"id": "CHASSIS_REAR_B1"}]}
    assert hold_problems(opts, feats) == []
    probs = hold_problems(opts, {"beads": [{"id": "CHASSIS_REAR_B5", "hold_eligible": False}]})
    assert probs[0]["key"] == "bead.hold.beads" and probs[0]["code"] == "GEOM_OPTIONS_INVALID" and "CHASSIS_REAR_B5" in probs[0]["message"]
    assert hold_problems(opts, None) and hold_problems(effective_shell_options(None, None)[0], None) == []  # beads 없으면 문제 없음


def test_new_message_codes_korean():
    t = messages.CODE_TABLE
    assert t["SHELL_FEATURE_DISTORTED"][0] == "DEVIATION" and "피처" in t["SHELL_FEATURE_DISTORTED"][1]
    assert t["SHELL_FIXED_MOVED"][0] == "FIXED" and t["SHELL_QUALITY_WARN"][0] == "QUALITY" and t["BEAD_ISLAND_TOO_LARGE"][0] == "PREP"
    assert messages.korean_message("SHELL_FEATURE_DISTORTED", "B1 island B1_I1: dev 0.4 mm").startswith("비드 안 피처가 바닥을 따라가지 않음")
    assert messages.category_of("SHELL_FEATURE_DISTORTED") == "DEVIATION"


def test_config_warns_shell_defaults_warn_policy():
    from physicsai_core.config.loader import config_warnings
    from physicsai_core.config.schema import Settings

    s = Settings.model_validate({"geometry": {"shell_defaults": {"fixed": {"policy": "warn"}, "quality": {"fail_policy": "skip"}}}}) \
        if hasattr(Settings, "model_validate") else None
    assert s is not None
    keys = [w.key for w in config_warnings({}, s, frozenset())]
    assert "geometry.shell_defaults.fixed.policy" in keys and "geometry.shell_defaults.quality.fail_policy" not in keys
