"""설정 값 검증 — 2차 단계(①②⑤·환경 점검·오류 묶음) 규칙(phase2 §8)."""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable
from typing import Any

from .rules import _compile
from .schema import ConfigIssue, Settings
from .schema_capture import validate_capture
from .schema_ops import ENV_PROBE_TOOLS


def _glob_parts_match(parts: list[str], pattern: list[str]) -> bool:
    """폴더 단위 glob 일치(glob.glob과 같게 `*`가 '/'를 넘지 않음, `**` 미지원)."""
    return len(parts) == len(pattern) and all(fnmatch.fnmatchcase(p, q) for p, q in zip(parts, pattern))


def _validate_doe_platform(td: Any, add: Callable[[str, str], None]) -> None:
    """S18 ① 플랫폼 DOE 생성 설정(phase3 §23.8): 방식 이름, 동시 수·run 상한 범위, run 폴더 상위가 run_dir_glob과 맞는지."""
    if td.doe_generator_default not in ("platform", "hyperstudy"):
        add("train_data.doe_generator_default", "platform | hyperstudy")
    if not 1 <= td.platform_parallel_default <= 64:
        add("train_data.platform_parallel_default", "1~64")
    if not 2 <= td.platform_max_runs <= td.max_runs:
        add("train_data.platform_max_runs", f"2~train_data.max_runs({td.max_runs})")
    root = str(td.platform_run_root)
    parts = root.replace("\\", "/").split("/")
    if (not root or root.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", root)
            or not all(re.fullmatch(r"[A-Za-z0-9_\-.]{1,64}", x) and x not in (".", "..") and not x.endswith(".")
                       for x in parts)):
        add("train_data.platform_run_root", "DOE 폴더 기준 상대 폴더여야 합니다(절대경로·'..'·공백 불가)")
    elif not any(_glob_parts_match(parts + ["run__00001"], g.replace("\\", "/").split("/")) for g in td.run_dir_globs()):
        add("train_data.platform_run_root",
            f"'{root}/run__00001'이 train_data.run_dir_glob({', '.join(td.run_dir_globs())}) 중 어느 것과도 맞지 않습니다")


def _validate_run_dir_globs(td: Any, add: Callable[[str, str], None]) -> None:
    """run_dir_glob(문자열 또는 목록, 이슈 #7): 1개 이상, 각 패턴은 D 기준 상대(절대·'..'·빈 조각 불가)."""
    globs = td.run_dir_globs()
    if not globs:
        add("train_data.run_dir_glob", "패턴이 1개 이상 필요합니다")
    for g in globs:
        parts = g.replace("\\", "/").split("/")
        if not g or g.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", g) or any(x in ("", ".", "..") for x in parts):
            add("train_data.run_dir_glob", f"DOE 폴더 기준 상대 패턴이어야 합니다: {g!r}")


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
    _compile("param_set.tpl_export_regex", s.param_set.tpl_export_regex, issues)
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
    _validate_run_dir_globs(td, add)
    _validate_doe_platform(td, add)
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


# phase3 §5.9: study_storage 키 범위
STUDY_STORAGE_RANGES: dict[str, tuple[int, int]] = {
    "max_entries": (1000, 50000000),
    "top_files": (1, 200),
    "max_items_per_category": (10, 5000),
    "log_min_age_days": (0, 3650),
    "keep_failed_logs": (0, 1000),
    "stale_after_hours": (1, 720),
}


# phase3 §14.7: predict_batch 키 범위
PREDICT_BATCH_RANGES: dict[str, tuple[int, int]] = {
    "max_runs": (2, 2000),
    "table_max_bytes": (1024, 67108864),
    "curve_max_runs": (1, 2000),
}
_BATCH_DIR_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{0,63}")  # fullmatch 전용(끝 줄바꿈 거부, D3-53)


def _validate_phase3(s: Settings, issues: list[ConfigIssue]) -> None:
    """3차 키 검증(phase3 §5.9, §14.7, §15)."""
    validate_capture(s, issues)
    from .schema_fem_verify import validate_fem_verify

    validate_fem_verify(s, issues)
    from .schema_equiv import validate_equiv_check

    validate_equiv_check(s, issues)
    for k, (lo, hi) in STUDY_STORAGE_RANGES.items():
        if not lo <= getattr(s.study_storage, k) <= hi:
            issues.append(ConfigIssue(f"study_storage.{k}", f"{lo}~{hi}"))
    pb = s.predict_batch
    for k, (lo, hi) in PREDICT_BATCH_RANGES.items():
        if not lo <= getattr(pb, k) <= hi:
            issues.append(ConfigIssue(f"predict_batch.{k}", f"{lo}~{hi}"))
    from ..paths import ALL_OUTPUT_DIRS

    if not _BATCH_DIR_RE.fullmatch(pb.dir_name) or pb.dir_name.casefold() in {d.casefold() for d in ALL_OUTPUT_DIRS} | {
            "_platform", "01_train", "02_import", "02_curated"}:
        issues.append(ConfigIssue("predict_batch.dir_name",
                                  "dir_name은 Study 직계 폴더 이름(영숫자·_·-, 64자 이내)이며 다른 산출 폴더와 같을 수 없습니다"))
