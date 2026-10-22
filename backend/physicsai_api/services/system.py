"""상태·자원·알림·관리 조회(§10.2, §10.7, §10.8)."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.commands import TEMPLATE_SPECS
from physicsai_core.config.schema_capture import effective_video_ext, transcode_enabled
from physicsai_core.config import RESOURCE_DIR_KEYS, RESOURCE_FILE_KEYS, effective_altair, redacted_settings
from physicsai_core.features import feature_status, geometry_status
from physicsai_core.stage5_optimize.surrogate import algo as so_algo
from physicsai_core.db.repositories import notifications as notif_repo
from physicsai_core.db.repositories import workers as workers_repo
from physicsai_core.errors import DomainError

from ..auth import Principal
from ..context import AppContext
from . import uploads as upload_svc
from .common import clamp_limit, decode_cursor, encode_cursor

ALTAIR_KEYS = ("hyperstudy_path", "simlab_path", "edspy_path", "hw_exe_path", "hvtrans_exe_path", "hstpy_path")


def _resource_status(s: Any) -> list[dict[str, Any]]:
    out = []
    for k in RESOURCE_FILE_KEYS + RESOURCE_DIR_KEYS:
        v = getattr(s.resources, k)
        ok = bool(v) and (os.path.isdir(v) if k in RESOURCE_DIR_KEYS else os.path.isfile(v))
        out.append({"key": k, "configured": bool(v), "ok": ok})
    return out


def status(ctx: AppContext, principal: Principal | None = None) -> dict[str, Any]:
    s = ctx.settings
    with ctx.engine.connect() as conn:
        hb = workers_repo.latest(conn)
    online = bool(hb) and float(hb["age_s"]) <= 3 * s.worker.heartbeat_interval_s  # type: ignore[index]
    av = ctx.hpc.availability()
    alt = effective_altair(s)
    eff = (hb or {}).get("effective_limits") or None
    worker_cfg_errors = list(((hb or {}).get("resources") or {}).get("worker_config_errors") or []) if online else []
    return {
        "config": {
            "ok": ctx.config.ok and not worker_cfg_errors,
            "errors": ctx.config.error_keys() + [f"worker:{k}" for k in worker_cfg_errors],
            "warnings": list(dict.fromkeys(w.key for w in ctx.config.warnings)),
        },
        "worker": {
            "online": online,
            "worker_id": hb["worker_id"] if hb else None,
            "last_seen_at": hb["last_seen_at"] if hb else None,
            "limiter": hb["limiter"] if hb else None,
        },
        "hpc": {"mode": av.mode, "configured": av.configured, "message": av.message,
                "collect_mode": s.hpc.transfer.collect_mode,
                "scx_version": (s.hpc.scx.version or None) if av.mode == "scx" else None},
        "altair": [{"key": k, "ok": bool(alt.get(k)) and os.path.isfile(alt.get(k, ""))} for k in ALTAIR_KEYS],
        "templates": [{"key": k, "configured": getattr(s.commands, k) is not None} for k in TEMPLATE_SPECS],
        "limits": {
            "configured": {"cores": s.worker.max_logical_cores, "memory_gb": s.worker.max_memory_gb,
                           "priority": s.worker.priority, "auto_detect": s.worker.auto_detect,
                           "max_multi_execution": s.train_data.max_multi_execution,
                           # S18 §23.4: ①-3 생성 방식 화면 기본·플랫폼 동시 수 기본(실제 = min(값, max_multi_execution))·run 상한
                           "doe_generator_default": s.train_data.doe_generator_default,
                           "doe_platform_parallel_default": min(s.train_data.platform_parallel_default,
                                                                s.train_data.max_multi_execution),
                           "doe_platform_max_runs": s.train_data.platform_max_runs},
            "detected": {"cores": eff.get("detected_cores"), "memory_gb": eff.get("detected_memory_gb")} if eff else None,
            "effective": {k: eff.get(k) for k in ("cores", "cpu_rate", "memory_gb", "priority", "cpu_cap_enforced")} if eff else None,
        },
        "ui": s.ui.model_dump(),
        "auth": {"mode": s.auth.mode, "login_url": s.auth.dashboard_public_login_url},
        "resources": _resource_status(s),
        "features": {**feature_status(s, av.configured),  # mcp.md §13·§20.5 features.mcp·mcp_http
                     "mcp": {"enabled": bool(s.mcp.enabled), "missing": [] if s.mcp.enabled else ["mcp.enabled"]},
                     "mcp_http": {"enabled": bool(s.mcp.enabled and s.mcp.server.http_enabled),
                                  "missing": [] if s.mcp.enabled and s.mcp.server.http_enabled else
                                  ["mcp.enabled" if not s.mcp.enabled else "mcp.server.http_enabled"]}},
        "env_check": env_status(ctx, principal) if principal is not None else None,
        "capture": {"views": list(s.capture.views), "video": bool(s.capture.video), "video_ext": s.capture.video_ext,
                    "default_field": s.capture.default_field, "default_component": s.capture.default_component,
                    "estimate": {"image_mb": s.capture.estimate_image_mb, "video_mb": s.capture.estimate_video_mb,
                                 "sec_per_view": s.capture.estimate_sec_per_view,
                                 "sec_per_video": s.capture.estimate_sec_per_video},
                    "video_target_bytes": s.capture.video_target_bytes, "transcode": transcode_enabled(s),
                    "video_ext_effective": effective_video_ext(s)},
        "surrogate_opt": {"defaults": {"iterations": s.surrogate_opt.default_iterations,
                                       "candidates": s.surrogate_opt.default_candidates,
                                       "tol_rel": s.surrogate_opt.default_tol_rel, "surrogate": s.surrogate_opt.default_surrogate},
                          "max_variables": s.surrogate_opt.max_variables, "max_iterations": s.surrogate_opt.max_iterations,
                          "max_candidates": s.surrogate_opt.max_candidates,
                          "max_objectives": s.surrogate_opt.max_objectives, "max_observe": s.surrogate_opt.max_observe,
                          "max_extra_points": s.surrogate_opt.max_extra_points,
                          # opt-native §4.2·§9: 알고리즘·검증 방식 목록·기본값
                          "algorithms": list(so_algo.ALGORITHMS), "default_algorithm": s.surrogate_opt.default_algorithm,
                          "algo_defaults": so_algo.config_defaults(s.surrogate_opt),
                          "ga_max_evals": s.surrogate_opt.ga_max_evals, "verifications": list(so_algo.VERIFICATIONS),
                          "max_levels": s.surrogate_opt.max_levels},
        "geometry": geometry_status(s),  # geometry-engine.md §7.1
        "demo": bool(s.demo.enabled),
        "upload": upload_svc.status_block(ctx),  # upload-report.md §6.4
    }


def env_status(ctx: AppContext, principal: Principal) -> dict[str, Any] | None:
    from .env_checks import status_block

    return status_block(ctx, principal)


def resources(ctx: AppContext) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        hb = workers_repo.latest(conn)
    if not hb or not hb.get("resources"):
        raise DomainError("NO_SAMPLE", "워커 자원 표본이 아직 없습니다", status=404)
    r = dict(hb["resources"])
    eff = hb.get("effective_limits") or {}
    r["limits"] = {
        "cores": eff.get("cores"), "cpu_rate": eff.get("cpu_rate"), "memory_gb": eff.get("memory_gb"),
        "priority": eff.get("priority"), "cpu_cap_enforced": bool(eff.get("cpu_cap_enforced")),
        "cpu_max_concurrent": eff.get("cpu_max_concurrent"), "total_cap": eff.get("total_cap"),  # job-queues.md §8.1(옛 워커는 null)
    }
    r.setdefault("gpu", [])
    r.setdefault("jobs", [])
    return r


def list_notifications(ctx: AppContext, principal: Principal, after_seq: int | None, limit: int | None,
                       cursor: str | None) -> tuple[dict[str, Any], str | None]:
    """after_seq 없으면 최근 30일 최신순. 다음 페이지 커서(더 오래된 항목)는 X-Next-Cursor 헤더로."""
    lim = clamp_limit(limit)
    before = decode_cursor(cursor) if cursor else None
    with ctx.engine.connect() as conn:
        items = notif_repo.list_for_user(conn, principal.user_id, after_seq=after_seq, limit=lim + 1,
                                         before_seq=before, retention_days=ctx.settings.notifications.retention_days)
        unread, max_seq = notif_repo.unread_count(conn, principal.user_id)
    nxt = None
    if after_seq is None and len(items) > lim:
        items = items[:lim]
        nxt = encode_cursor(items[-1]["seq"])
    return {"items": items[:lim], "max_seq": max_seq, "unread_count": unread}, nxt


def unread(ctx: AppContext, principal: Principal) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        u, m = notif_repo.unread_count(conn, principal.user_id)
    return {"unread_count": u, "max_seq": m}


def mark_read(ctx: AppContext, principal: Principal, seqs: list[int] | None, all_: bool) -> dict[str, Any]:
    if not all_ and not seqs:
        raise DomainError("INVALID_PARAMS", "seqs 또는 all=true가 필요합니다", status=422, errors=[{"loc": ["seqs"], "msg": "required"}])
    with ctx.engine.begin() as conn:
        notif_repo.mark_read(conn, principal.user_id, seqs, all_)
        u, _ = notif_repo.unread_count(conn, principal.user_id)
    return {"unread_count": u}


def admin_config(ctx: AppContext) -> dict[str, Any]:
    s = ctx.settings
    return {
        "path": ctx.config.path,
        "sha256": ctx.config.sha256,
        "ok": ctx.config.ok,
        "issues": [{"key": i.key, "message": i.message} for i in ctx.config.issues],
        "settings": redacted_settings(s),
        "templates": {k: getattr(s.commands, k) for k in TEMPLATE_SPECS},
    }
