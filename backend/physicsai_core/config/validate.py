"""설정 값 검증(계약 §14, §17): 1차 규칙 표. 2차 규칙은 validate_stages."""

from __future__ import annotations

import os
import re

from ..commands import TEMPLATE_SPECS, validate_template
from .rules import _compile, has_unsafe_chars, is_abs_path_str, paths_overlap
from .schema import (
    LAUNCHER_KEYS,
    RESOURCE_DIR_KEYS,
    RESOURCE_FILE_KEYS,
    ConfigIssue,
    Settings,
)
from .validate_stages import _validate_phase2, _validate_phase3


def validate_settings(s: Settings, absent: frozenset[str] = frozenset()) -> list[ConfigIssue]:  # noqa: C901 - 표 기반 규칙 나열
    issues: list[ConfigIssue] = []
    add = lambda k, m: issues.append(ConfigIssue(k, m))  # noqa: E731

    if s.schema_version != 1:
        add("schema_version", "schema_version은 1이어야 합니다")
    if s.profile not in ("dev", "prod"):
        add("profile", "profile은 dev 또는 prod입니다")
    prod = s.profile == "prod"

    # storage
    spdm = [r for r in s.storage.spdm_roots]
    ai_root = s.storage.ai_root
    if not ai_root or not is_abs_path_str(ai_root):
        add("storage.ai_root", "ai_root는 절대경로여야 합니다")
    elif has_unsafe_chars(ai_root):
        add("storage.ai_root", "ai_root에 공백·제어문자·cmd 메타문자를 쓸 수 없습니다")
    elif not os.path.isdir(ai_root):
        add("storage.ai_root", f"ai_root 폴더가 없습니다: {ai_root}")
    elif not os.access(ai_root, os.W_OK):
        add("storage.ai_root", "ai_root에 쓸 수 없습니다")
    if ai_root:
        for r in spdm:
            if paths_overlap(ai_root, r):
                add("storage.ai_root", f"ai_root가 SPDM 루트와 겹칩니다: {r}")
    inbox = s.storage.inbox_dir
    inbox_parts = inbox.replace("\\", "/").split("/")
    if (not inbox or is_abs_path_str(inbox) or inbox.startswith(("/", "\\")) or has_unsafe_chars(inbox)
            or any(x in ("", ".", "..") for x in inbox_parts)
            # D3-50: ':'(대체 데이터 스트림·드라이브 상대)·끝 마침표/공백(Windows가 `_backup.`을 `_backup`으로 연다) 거부
            or any(":" in x or x[-1:] in (".", " ") for x in inbox_parts)
            or any(x.rstrip(" .").casefold() in ("_backup", "_platform") for x in inbox_parts)):
        add("storage.inbox_dir", "inbox_dir는 AI 루트 기준 상대 폴더 이름이어야 합니다"
            "(공백·':'·끝 마침표·'..'·_backup·_platform 불가)")
    if s.storage.inbox_share_hint is not None and len(s.storage.inbox_share_hint) > 260:
        add("storage.inbox_share_hint", "inbox_share_hint는 260자 이하여야 합니다")
    for i, r in enumerate(s.storage.allowed_import_roots):
        k = f"storage.allowed_import_roots[{i}]"
        if not is_abs_path_str(r):
            add(k, "절대경로여야 합니다")
        elif has_unsafe_chars(r):
            add(k, "공백·제어문자·cmd 메타문자를 쓸 수 없습니다")
        elif not os.path.isdir(r):
            add(k, f"폴더가 없습니다: {r}")
        elif not os.access(r, os.R_OK):
            add(k, "읽을 수 없습니다")
        for sp in spdm:
            if paths_overlap(r, sp):
                add(k, f"SPDM 루트와 겹칩니다: {sp}")

    # altair
    for k in ("hyperstudy_path", "simlab_path", "edspy_path", "hw_exe_path", "hvtrans_exe_path", "hstpy_path"):
        v = getattr(s.altair, k)
        if v:
            if not is_abs_path_str(v):
                add(f"altair.{k}", "절대경로여야 합니다")
            elif prod and not os.path.isfile(v):
                add(f"altair.{k}", f"실행 파일이 없습니다: {v}")
    if s.altair.altair_home and not is_abs_path_str(s.altair.altair_home):
        add("altair.altair_home", "절대경로여야 합니다")

    # resources (phase2 §8.2: 비었거나 절대경로·공백/메타 없음·prod면 존재)
    for k in RESOURCE_FILE_KEYS + RESOURCE_DIR_KEYS:
        v = getattr(s.resources, k)
        key = f"resources.{k}"
        if v:
            if not is_abs_path_str(v):
                add(key, "절대경로여야 합니다")
            elif has_unsafe_chars(v):
                add(key, "공백·제어문자·cmd 메타문자를 쓸 수 없습니다")
            elif prod and k in RESOURCE_DIR_KEYS and not os.path.isdir(v):
                add(key, f"폴더가 없습니다: {v}")
            elif prod and k in RESOURCE_FILE_KEYS and not os.path.isfile(v):
                add(key, f"파일이 없습니다: {v}")
            for sp in spdm:
                if paths_overlap(v, sp):
                    add(key, f"SPDM 루트와 겹칩니다: {sp}")
        elif prod and k == "preview_pred_h3d_tcl":
            add(key, "prod에서는 필수입니다")
    for name, lc in s.resources.launchers.items():
        key = f"resources.launchers.{name}"
        if name not in LAUNCHER_KEYS:
            add(key, "알 수 없는 런처 키입니다(extract_params | gen_radioss | optimization)")
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+\.py", lc.script) or has_unsafe_chars(lc.script):
            add(key + ".script", "파일 이름만(경로 구분자 없이) .py 로 끝나야 합니다")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", lc.core):
            add(key + ".core", "^[A-Za-z_][A-Za-z0-9_]*$")

    # worker
    w = s.worker
    if not 1 <= w.max_logical_cores <= 1024:
        add("worker.max_logical_cores", "1~1024")
    if not 1 <= w.max_memory_gb <= 4096:
        add("worker.max_memory_gb", "1~4096")
    if not 0.1 <= w.auto_detect_ratio <= 1.0:
        add("worker.auto_detect_ratio", "0.1~1.0")
    for k in ("heartbeat_interval_s", "lease_ttl_s", "claim_interval_s", "cancel_check_interval_s", "resource_sample_interval_s"):
        if getattr(w, k) <= 0:
            add(f"worker.{k}", "양수여야 합니다")
    if w.lease_ttl_s < 3 * w.heartbeat_interval_s:
        add("worker.lease_ttl_s", "lease_ttl_s ≥ 3 × heartbeat_interval_s 이어야 합니다")
    if w.limiter not in ("auto", "windows_job", "posix", "null"):
        add("worker.limiter", "auto | windows_job | posix | null")
    elif w.limiter == "null" and prod:
        add("worker.limiter", "null 제한기는 dev에서만 허용됩니다")
    if w.priority not in ("idle", "below_normal", "normal"):
        add("worker.priority", "idle | below_normal | normal")
    if w.gpu_query is not None and (not w.gpu_query or not all(isinstance(x, str) for x in w.gpu_query)):
        add("worker.gpu_query", "문자열 배열이어야 합니다")
    if not all(isinstance(x, str) and x.strip() for x in s.resources.gpu_query_candidates):
        add("resources.gpu_query_candidates", "빈 문자열이 아닌 실행 파일 이름·경로 배열이어야 합니다")

    # auth
    a = s.auth
    if a.mode not in ("dashboard", "dev_static", "demo"):
        add("auth.mode", "dashboard | dev_static | demo")
    if a.mode == "dev_static" and (s.profile != "dev" or s.server.host != "127.0.0.1"):
        add("auth.mode", "dev_static은 profile=dev이고 127.0.0.1 바인딩일 때만 허용됩니다")
    if a.mode == "demo" and not s.demo.enabled:
        add("auth.mode", "demo 인증은 demo.enabled=true(시연 모드)일 때만 허용됩니다")
    # 시연 모드: 운영 설정에서는 켤 수 없다
    if s.demo.enabled and (s.profile != "dev" or s.server.host != "127.0.0.1"):
        add("demo.enabled", "시연 모드는 profile=dev이고 server.host=127.0.0.1일 때만 허용됩니다")
    if s.demo.frontend_root and not s.demo.enabled:
        add("demo.frontend_root", "demo.enabled=false이면 비워 두어야 합니다")
    elif s.demo.frontend_root and not os.path.isfile(os.path.join(s.demo.frontend_root, "index.html")):
        add("demo.frontend_root", f"프런트 빌드 폴더에 index.html이 없습니다: {s.demo.frontend_root}")
    # 폴더·index.html이 없는 것은 오류가 아니다(기동 후 배치될 수 있음) — 환경 점검 server.frontend_root가 WARN으로 알린다
    if s.server.frontend_root and not is_abs_path_str(s.server.frontend_root):
        add("server.frontend_root", "절대경로여야 합니다(빈 값 = 서빙 안 함)")
    if not re.match(r"^https?://[^\s/]+(:\d+)?/?$", a.dashboard_internal_url):
        add("auth.dashboard_internal_url", "URL 형식이 아닙니다(예: http://127.0.0.1:8000)")
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", a.cookie_name):
        add("auth.cookie_name", "^[A-Za-z0-9_\\-]+$")
    for k in ("introspection_path", "projects_path"):
        if not getattr(a, k).startswith("/"):
            add(f"auth.{k}", "'/'로 시작해야 합니다")
    for m in a.dev_static_principal.memberships:
        if m.role not in ("general", "power", "admin"):
            add("auth.dev_static_principal.memberships", "role은 general|power|admin")

    # dataset
    d = s.dataset
    if not 0.05 <= d.holdout_ratio <= 0.5:
        add("dataset.holdout_ratio", "0.05~0.5")
    if d.min_h3d_files < 2:
        add("dataset.min_h3d_files", "2 이상")
    if d.min_psdata_bytes < 0:
        add("dataset.min_psdata_bytes", "0 이상")
    if d.split_group not in ("file", "parent_dir"):
        add("dataset.split_group", "file | parent_dir")
    if s.package.link_mode not in ("hardlink_or_copy", "copy"):
        add("package.link_mode", "hardlink_or_copy | copy")

    # parsers
    for i, p in enumerate(s.training_log.parsers):
        _compile(f"training_log.parsers[{i}]", p.pattern, issues, ("epoch", "loss"))
    if s.training_log.max_curve_points < 3:
        add("training_log.max_curve_points", "3 이상")
    for i, p in enumerate(s.score.parsers):
        _compile(f"score.parsers[{i}]", p.pattern, issues, ("value",))
    for i, p in enumerate(s.commands_log_error_patterns):
        _compile(f"commands_log_error_patterns[{i}]", p, issues)
    lg = s.logging
    if lg.max_mb <= 0 or lg.max_mb > 1024:
        add("logging.max_mb", "0 초과 1024 이하")
    if not 1 <= lg.backups <= 100:
        add("logging.backups", "1~100")
    if lg.level.upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        add("logging.level", "DEBUG | INFO | WARNING | ERROR | CRITICAL")
    if lg.dir:
        if has_unsafe_chars(lg.dir) and not os.path.isdir(lg.dir):
            add("logging.dir", "공백·메타문자 없는 경로를 권장합니다(폴더도 없음)")
        if ai_root and paths_overlap(os.path.abspath(lg.dir), ai_root):
            add("logging.dir", "AI 루트와 겹칠 수 없습니다(운영 로그는 설치 폴더 쪽)")
        for sp in spdm:
            if paths_overlap(os.path.abspath(lg.dir), sp):
                add("logging.dir", f"SPDM 루트와 겹칩니다: {sp}")
    for i, p in enumerate(s.logging.mask_patterns):
        _compile(f"logging.mask_patterns[{i}]", p, issues)

    if s.predict.integer_rounding not in ("half_up", "truncate"):
        add("predict.integer_rounding", "half_up | truncate")
    pr = s.predict
    for k in ("rendered_script_name", "simlab_mesh_name", "mesh_include_name", "renum_csv_name"):
        v = getattr(pr, k)
        if not v or has_unsafe_chars(v) or "/" in v or "\\" in v or v in (".", ".."):
            add(f"predict.{k}", "파일 이름만, 공백·메타문자 금지")
    for i, ext in enumerate(pr.prepared_input_exts):
        if not re.fullmatch(r"\.[A-Za-z0-9_]{1,16}", ext):
            add(f"predict.prepared_input_exts[{i}]", "'.'으로 시작하는 확장자(예: .rad)")
    if not pr.prepared_input_exts:
        add("predict.prepared_input_exts", "1개 이상")
    if not 1 <= pr.prepared_max_files <= 100000:
        add("predict.prepared_max_files", "1~100000")
    if pr.prepared_max_total_bytes <= 0:
        add("predict.prepared_max_total_bytes", "양수")

    # commands
    for key in TEMPLATE_SPECS:
        if f"commands.{key}" in absent:
            continue  # 파일에 없음 → 해당 기능 비활성(경고, features·작업 생성 409)
        for msg in validate_template(key, getattr(s.commands, key)):
            add(f"commands.{key}", msg)

    # hpc
    if s.hpc.gateway not in ("none", "command", "adapter", "scx"):
        add("hpc.gateway", "none | command | adapter | scx")
    t = s.hpc.transfer
    if t.collect_mode not in ("in_place", "shared_folder", "drive"):
        add("hpc.transfer.collect_mode", "in_place | shared_folder | drive")
    elif t.collect_mode in ("shared_folder", "drive"):
        for k in ("collect_root_local", "collect_root_remote"):
            if not getattr(t, k):
                add(f"hpc.transfer.{k}", "shared_folder·drive 모드에서는 필수입니다")
    if t.collect_root_local:
        k = "hpc.transfer.collect_root_local"
        v = t.collect_root_local
        if not is_abs_path_str(v):
            add(k, "절대경로여야 합니다")
        elif has_unsafe_chars(v):
            add(k, "공백·제어문자·cmd 메타문자를 쓸 수 없습니다")
        elif not os.path.isdir(v):
            add(k, f"폴더가 없습니다: {v}")
        if ai_root and paths_overlap(v, ai_root):
            add(k, "AI 루트와 겹칠 수 없습니다")
        for sp in spdm:
            if paths_overlap(v, sp):
                add(k, f"SPDM 루트와 겹칩니다: {sp}")
    if t.collect_root_remote and (has_unsafe_chars(t.collect_root_remote) or not is_abs_path_str(t.collect_root_remote)):
        add("hpc.transfer.collect_root_remote", "절대경로여야 하며 공백·메타문자를 쓸 수 없습니다")
    if s.hpc.gateway == "command" and "hpc.command" not in absent:  # 없으면 게이트웨이 미구성(train_solve 비활성)
        from ..hpc.command import validate_command_config

        for msg in validate_command_config(s.hpc):
            add("hpc.command", msg)
    if s.hpc.gateway == "scx":  # phase3 §16.8 — 비밀 파일 유무는 설정 오류가 아니라 availability(configured=false)
        from simdash_adapters.hpc.scx import validate_scx_config

        for msg in validate_scx_config(s.hpc.scx):
            add("hpc.scx", msg)
        sf = s.hpc.scx.secret_file
        if sf and not is_abs_path_str(sf):
            add("hpc.scx.secret_file", "절대경로여야 합니다(빈 값 = <런타임>/secrets/scx_relay_key)")

    _validate_phase2(s, issues)
    _validate_phase3(s, issues)

    if s.notifications.retention_days < 1:
        add("notifications.retention_days", "1 이상")
    if s.ui.max_artifact_bytes <= 0:
        add("ui.max_artifact_bytes", "양수")
    return issues
