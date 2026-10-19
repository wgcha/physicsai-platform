"""Committed SM1 shell envelope report (shell-morph section 7.1): regenerated with default options/steps, byte
identical after blanking the engine_version / sweep_id lines (same rule as the G1 report)."""

from __future__ import annotations


def test_committed_sm1_report_exists():
    from data.make_shell_envelope_report import GOLDEN_DIR, REPORT_FILES

    for name in REPORT_FILES:
        assert (GOLDEN_DIR / name).is_file(), name
    md = (GOLDEN_DIR / "report_envelope.md").read_text(encoding="utf-8")
    assert "SHELL_FIXED_REGION_VIOLATION" in md and "| % |" in md and "| mm |" in md


def test_sm1_report_regenerates_byte_identical(shell_golden, tmp_path):
    from data.make_envelope_report import normalize_report
    from data.make_shell_envelope_report import GOLDEN_DIR, REPORT_FILES, generate

    rep = generate(tmp_path, shell_golden)
    for name in REPORT_FILES:
        assert normalize_report(rep[name]) == normalize_report((GOLDEN_DIR / name).read_bytes()), name
