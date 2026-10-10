"""설정 값 검증 — 2차 단계(①②⑤·환경 점검·오류 묶음) 규칙(phase2 §8)."""

from __future__ import annotations

import re

from .rules import _compile
from .schema import ENV_PROBE_TOOLS, ConfigIssue, Settings


def _validate_phase2(s: Settings, issues: list[ConfigIssue]) -> None:
    """2차 키 검증(phase2 §8.2 끝)."""
    add = lambda k, m: issues.append(ConfigIssue(k, m))  # noqa: E731
    td = s.train_data
    for i, p in enumerate(td.hst_log_error_patterns):
        _compile(f"train_data.hst_log_error_patterns[{i}]", p, issues)
    _compile("train_data.hst_progress_regex", td.hst_progress_regex, issues, ("run",))
    _compile("train_data.paramitem_regex", td.paramitem_regex, issues, ("name", "value"))
    _compile("train_data.result_run_dir_regex", td.result_run_dir_regex, issues, ("run_key",))
    for k in ("tpl_prt_regex", "tpl_parameter_line_regex", "tpl_paramitem_line_regex"):
        _compile(f"train_data.{k}", getattr(td, k), issues)
    _compile("optimize.progress_regex", s.optimize.progress_regex, issues, ("run",))
    if not 1 <= td.max_multi_execution <= 64:
        add("train_data.max_multi_execution", "1~64")
    if not 2 <= td.max_runs <= 100000:
        add("train_data.max_runs", "2~100000")
    if not 0 < td.param_default_range_ratio < 1:
        add("train_data.param_default_range_ratio", "0~1 사이")
    if not re.fullmatch(r"%[-0-9.]*[idfeEgG]", td.param_default_format):
        add("train_data.param_default_format", "%[-0-9.]*[idfeEgG]")
    if td.samples_extractor not in ("paramitem", "csv", "none"):
        add("train_data.samples_extractor", "paramitem | csv | none")
    if td.extract_progress_total < 1:
        add("train_data.extract_progress_total", "1 이상")
    if not td.tpl_marker:
        add("train_data.tpl_marker", "비어 있을 수 없습니다")
    for e in td.cad_extensions:
        if not re.fullmatch(r"\.[A-Za-z0-9_]{1,16}", e):
            add("train_data.cad_extensions", f"확장자 형식 오류: {e}")
    if td.result_match_depth < 1:
        add("train_data.result_match_depth", "1 이상")
    if td.max_runs_per_submit < 1:
        add("train_data.max_runs_per_submit", "1 이상")
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", s.optimize.default_study_folder):
        add("optimize.default_study_folder", "^[A-Za-z0-9_-]{1,64}$")
    for i, sp in enumerate(s.optimize.summary_parsers):
        if sp.kind not in ("csv_table", "json_passthrough"):
            add(f"optimize.summary_parsers[{i}].kind", "csv_table | json_passthrough")
    for name in s.optimize.env:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            add("optimize.env", f"환경변수 이름 형식 오류: {name}")
    if s.env_check.probe_timeout_s <= 0 or s.env_check.expire_s <= 0:
        add("env_check", "probe_timeout_s·expire_s는 양수")
    from ..commands import EXECUTABLE_PLACEHOLDERS, parse_placeholders

    for tool in ENV_PROBE_TOOLS:
        argv = getattr(s.env_check.probes, tool)
        if argv is None:
            continue
        key = f"env_check.probes.{tool}"
        if not argv or not all(isinstance(x, str) for x in argv) or argv[0] != "{" + tool + "}":
            add(key, f"argv[0]은 {{{tool}}}이어야 합니다")
            continue
        for el in argv[1:]:
            try:
                names = parse_placeholders(el)
            except ValueError as exc:
                add(key, str(exc))
                continue
            if names:
                add(key, "도구 placeholder 외 다른 placeholder는 쓸 수 없습니다")
        if tool not in EXECUTABLE_PLACEHOLDERS:
            add(key, "알 수 없는 도구")
    if s.error_bundle.log_tail_bytes < 1024 or s.error_bundle.max_total_bytes < s.error_bundle.log_tail_bytes:
        add("error_bundle", "log_tail_bytes ≥ 1024, max_total_bytes ≥ log_tail_bytes")
    if s.spdm_import.max_files < 1 or s.curation.max_files < 1:
        add("spdm_import.max_files", "1 이상")
