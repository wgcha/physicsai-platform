"""phase3 §16.3·§16.12-2: 드라이브 이름·경로 규칙(정규화·예약어·번호·접미·길이·SPDM 금지)."""

from __future__ import annotations

import pytest

from simdash_adapters.hpc import scx_naming as n


@pytest.mark.parametrize("raw, want", [
    ("cushion", "cushion"),
    ("쿠션 시험", "study"),
    ("TV 55 쿠션", "TV_55"),
    ("a  b__c", "a_b_c"),
    ("__-x-__", "x"),
    ("", "study"),
    ("con", "s_con"),
    ("LPT9", "s_LPT9"),
    ("COM10", "COM10"),
    ("x" * 80, "x" * 64),
    ("Ａ", "study"),  # 전각 → 밖 문자
    ("éclair", "_clair".strip("_")),  # NFC 후 é는 밖 문자 → '_' → 앞 '_' 제거
])
def test_sanitize_project(raw, want):
    assert n.sanitize_project(raw) == want


def test_numbers_and_job_names():
    assert n.fmt_no(3) == "003" and n.fmt_no(1000) == "1000"
    with pytest.raises(ValueError):
        n.fmt_no(0)
    ts = "20261017T105700"
    assert n.train_job_name(3, "run__00012", ts) == "01_D-003_run__00012_20261017T105700"
    assert n.verify_job_name(7, ts) == "04_V-007_20261017T105700"
    with pytest.raises(ValueError):
        n.train_job_name(1, "run/../x", ts)
    with pytest.raises(ValueError):
        n.verify_job_name(1, "2026-10-17")
    assert n.with_suffix("a", 1) == "a" and n.with_suffix("a", 2) == "a_2" and n.with_suffix("a", 9) == "a_9"
    with pytest.raises(ValueError):
        n.with_suffix("a", 10)


def test_drive_base_and_rel_rules():
    assert n.drive_base_rel("~") == ""
    assert n.drive_base_rel("~/physicsai") == "physicsai"
    assert n.drive_base_rel("~/a/b/") == "a/b"
    for bad in ("/Users/vd.dashboard", "physicsai", "~/../x", "~/a//b", "~/.hidden", "~\\a", "~/a\x01"):
        with pytest.raises(ValueError):
            n.drive_base_rel(bad)
    assert n.join_rel("", "cushion", "01_x") == "cushion/01_x"
    assert n.rel_problem("cushion/01_D-001_run__1_20261017T000000") is None
    assert n.rel_problem("cushion/../x") is not None
    assert n.rel_problem("/abs/x") is not None
    assert n.rel_problem("~/x") is not None
    assert n.rel_problem(".hidden/x") is not None
    assert n.rel_problem("a/" + "b" * 1100) is not None
    assert n.rel_problem("cushion/_bad", segment_check_from=1) is not None
    assert n.file_name_problem("a.rad") is None
    for bad in ("", ".", "..", "a/b", "a\\b", "a:b", "a\x00", "x" * 256):
        assert n.file_name_problem(bad) is not None


def test_forbidden_prefixes():
    fp = ["SPDM"]
    assert n.forbidden_reason("SPDM", fp)
    assert n.forbidden_reason("spdm/01_x", fp)  # 대소문자 무시
    assert n.forbidden_reason("SPDM/proj/01_x", fp)
    assert n.forbidden_reason("SPDMX/01_x", fp) is None
    assert n.forbidden_reason("cushion/01_x", fp) is None
    # 프로젝트 폴더가 SPDM 루트의 상위 폴더(Projects/SPDM 옆에 만들지 않음)
    assert n.forbidden_reason("Projects/01_x", ["Projects/SPDM"])
    assert n.forbidden_reason("physicsai/cushion/01_x", ["physicsai/SPDM"], base="physicsai") is None
    assert n.forbidden_reason("physicsai/SPDM/01_x", ["physicsai/SPDM"], base="physicsai")
    assert n.forbidden_reason("cushion/01_x", ["~"]) is not None  # 홈 전체가 SPDM이면 모두 거부
    assert n.display_path("/Users/vd.dashboard", "cushion/01_x") == "/Users/vd.dashboard/cushion/01_x"


def test_forbidden_prefix_forms():
    """금지 접두는 상대·`~/`·절대(home_display 기준) 표기를 모두 같은 것으로 본다(대소문자 무시)."""
    hd = "/Users/vd.dashboard"
    for raw in ("SPDM", "~/SPDM", "/Users/vd.dashboard/SPDM", "/users/VD.dashboard/spdm/"):
        assert n.forbidden_reason("SPDM/x/01_a", [raw], home_display=hd), raw
        assert n.forbidden_reason("cushion/01_a", [raw], home_display=hd) is None, raw
    assert n.forbidden_reason("cushion/01_a", ["/Users/vd.dashboard"], home_display=hd)  # 홈 전체 = 모두 거부


def test_v3_s16_9_fem_verify_job_name():
    """phase3 §21.3.7 S16: ④ 조립 FEM 검증 잡 폴더 `04_FV-<NNN>_<ts>`(검사·접미 규칙은 V와 같다)."""
    ts = "20261019T101500"
    assert n.fem_verify_job_name(3, ts) == "04_FV-003_20261019T101500"
    assert n.fem_verify_job_name(1234, ts) == "04_FV-1234_20261019T101500"
    assert n.with_suffix(n.fem_verify_job_name(3, ts), 2) == "04_FV-003_20261019T101500_2"
    assert n.SEGMENT_RE.match(n.fem_verify_job_name(3, ts))
    with pytest.raises(ValueError):
        n.fem_verify_job_name(1, "2026-10-19")
    with pytest.raises(ValueError):
        n.fem_verify_job_name(0, ts)
