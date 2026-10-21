"""설정 스키마 — MCP 기능 절 `mcp`(mcp.md §13). 기본값은 이 파일 한 곳.

`enabled: false`(기본)면 토큰 인증·`/mcp/*`·토큰 화면·`/physicsai/mcp`가 모두 꺼진다(404 MCP_DISABLED, 기존 동작 불변 — V-MCP-1).
토큰 기한은 esl과 같은 30일 계약(MR-13): 기본·최대·역할 스냅숏 경과 모두 상한 30일(설정으로도 30을 넘길 수 없다).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field

from ._model import _M

if TYPE_CHECKING:
    from .schema import ConfigIssue, Settings

TOKEN_MAX_DAYS = 30  # MR-13: 설정 상한도 30(무기한·연장 없음)


class McpTokenCfg(_M):
    default_expiry_days: int = 30
    max_expiry_days: int = 30
    max_per_user: int = 5
    snapshot_max_age_days: int = 30  # 역할 스냅숏 최대 경과일 — 넘으면 401 API_TOKEN_STALE
    last_used_update_s: int = 60


class McpServerCfg(_M):
    http_enabled: bool = True  # false면 /physicsai/mcp 404(stdio는 API만 쓰므로 영향 없음)
    call_timeout_s: int = 60
    max_result_bytes: int = 65536


class McpRateLimitCfg(_M):
    requests_per_min: int = 60
    plans_per_min: int = 10
    max_active_jobs_per_token: int = 3


class McpAuditCfg(_M):
    retention_days: int = 180
    record_reads: bool = False


class McpSummaryCfg(_M):
    max_bytes: int = 8192
    top_n_default: int = 10
    top_n_max: int = 50


class McpSimilarCfg(_M):
    max_rows: int = 20000


class McpCfg(_M):
    enabled: bool = False
    require_confirm_for_token: bool = True
    confirm_ttl_s: int = 600
    allowed_job_kinds: list[str] | None = None  # null = 레지스트리 전체
    denied_job_kinds: list[str] = Field(default_factory=lambda: ["solve_pbs"])  # 미결 Q3 기본(PBS 자원은 웹에서만)
    token: McpTokenCfg = Field(default_factory=McpTokenCfg)
    server: McpServerCfg = Field(default_factory=McpServerCfg)
    rate_limit: McpRateLimitCfg = Field(default_factory=McpRateLimitCfg)
    audit: McpAuditCfg = Field(default_factory=McpAuditCfg)
    summary: McpSummaryCfg = Field(default_factory=McpSummaryCfg)
    similar: McpSimilarCfg = Field(default_factory=McpSimilarCfg)


RANGES: dict[str, tuple[int, int]] = {
    "confirm_ttl_s": (60, 3600),
    "token.default_expiry_days": (1, TOKEN_MAX_DAYS),
    "token.max_expiry_days": (1, TOKEN_MAX_DAYS),
    "token.max_per_user": (1, 100),
    "token.snapshot_max_age_days": (1, TOKEN_MAX_DAYS),
    "token.last_used_update_s": (0, 3600),
    "server.call_timeout_s": (1, 600),
    "server.max_result_bytes": (1024, 4194304),
    "rate_limit.requests_per_min": (1, 10000),
    "rate_limit.plans_per_min": (1, 1000),
    "rate_limit.max_active_jobs_per_token": (1, 100),
    "audit.retention_days": (30, 3650),
    "summary.max_bytes": (1024, 1048576),
    "summary.top_n_default": (1, 500),
    "summary.top_n_max": (1, 500),
    "similar.max_rows": (100, 1000000),
}


def _get(cfg: McpCfg, dotted: str) -> int:
    v: object = cfg
    for part in dotted.split("."):
        v = getattr(v, part)
    return int(v)  # type: ignore[call-overload]


def validate_mcp(s: Settings, issues: list[ConfigIssue]) -> None:
    from .schema import ConfigIssue as issue

    m = s.mcp
    for k, (lo, hi) in RANGES.items():
        if not lo <= _get(m, k) <= hi:
            issues.append(issue(f"mcp.{k}", f"{lo}~{hi}"))
    if m.token.default_expiry_days > m.token.max_expiry_days:
        issues.append(issue("mcp.token.default_expiry_days", "max_expiry_days 이하"))
    if m.summary.top_n_default > m.summary.top_n_max:
        issues.append(issue("mcp.summary.top_n_default", "top_n_max 이하"))
    for key in ("allowed_job_kinds", "denied_job_kinds"):
        vals = getattr(m, key) or []
        if any(not isinstance(v, str) or not v.strip() for v in vals):
            issues.append(issue(f"mcp.{key}", "작업 종류 이름 목록"))
