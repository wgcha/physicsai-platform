"""MCP 스키마(mcp.md §4.4·§5.2·§6.2·§7·§9·§10)와 `x-mcp` 표시 도우미.

도구 operation 필수 항목(V-MCP-6): summary·description(한국어), 요청 필드·쿼리 description, 수치는 단위(`x-unit` 또는 설명 안 `[단위]`)와
범위(minimum/maximum 또는 enum), 요청 본문 examples, 응답 모델, 오류 code 목록(responses 설명).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from .common import ErrorResponse, Req, Resp

# ---- x-mcp 표시 ---------------------------------------------------------------------------------------

TOKEN_401 = "AUTHENTICATION_REQUIRED · API_TOKEN_INVALID · API_TOKEN_REVOKED · API_TOKEN_EXPIRED · API_TOKEN_STALE"
TOKEN_403 = "API_TOKEN_SCOPE · API_TOKEN_OPERATION_NOT_ALLOWED · SESSION_REQUIRED · PERMISSION_DENIED · CSRF_HEADER_REQUIRED"


def xmcp_tool(tool: str, risk: Literal["read", "run", "admin"], summary_en: str, summary_ko: str, *,
              confirm: Literal["never", "by_kind", "always"] = "never", version: int = 1,
              deprecated: bool = False) -> dict[str, Any]:
    """openapi_extra용 `x-mcp` 도구 표시(도구 이름 단일 출처). 도구 설명 = "<summary_en> / <summary_ko>"(≤ 300자, MR-16)."""
    return {"x-mcp": {"tool": tool, "risk": risk, "confirm": confirm, "version": version, "summary_en": summary_en,
                      "summary_ko": summary_ko, "deprecated": deprecated}}


def xmcp_exclude(reason: str, *, session_only: bool = False, token_risk: str | None = None) -> dict[str, Any]:
    """openapi_extra용 `x-mcp` 제외 표시(사유 필수). session_only = 토큰 요청 403 SESSION_REQUIRED, token_risk = 도구는 아니지만 토큰 허용."""
    x: dict[str, Any] = {"exclude": reason}
    if session_only:
        x["session_only"] = True
    if token_risk:
        x["token_risk"] = token_risk
    return {"x-mcp": x}


def errors(**codes: str) -> dict[int | str, dict[str, Any]]:
    """오류 응답 표: 상태 → code 목록 설명. 토큰 401·403·429는 항상 포함."""
    out: dict[int | str, dict[str, Any]] = {
        401: {"model": ErrorResponse, "description": TOKEN_401},
        403: {"model": ErrorResponse, "description": TOKEN_403},
        429: {"model": ErrorResponse, "description": "RATE_LIMITED(Retry-After 헤더) · TOKEN_ACTIVE_JOB_LIMIT"},
    }
    for k, v in codes.items():
        st = int(k.removeprefix("e"))
        base = out.get(st, {}).get("description")
        out[st] = {"model": ErrorResponse, "description": f"{base} · {v}" if base else v}
    return out


# ---- API 토큰(§4.4) ----------------------------------------------------------------------------------

TokenScope = Literal["read", "run", "admin"]


class ApiTokenCreate(Req):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[0-9A-Za-z가-힣 _.\-]+$",
                      description="토큰 이름(1~64자, 영숫자·한글·공백·_.-) — 사용자 안에서 유효 토큰끼리 유일")
    scope: TokenScope = Field(description="범위 read < run < admin(run은 어느 프로젝트든 power 이상, admin은 전역 관리자)")
    expires_in_days: int | None = Field(default=None, ge=1, le=3650,
                                        description="만료까지 일수[일] — 생략 = mcp.token.default_expiry_days(30), 최대 max_expiry_days(30)")


class ApiToken(Resp):
    id: str
    name: str
    scope: TokenScope
    token_prefix: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None
    snapshot_at: datetime
    status: Literal["active", "expired", "revoked", "stale"]


class ApiTokenAdmin(ApiToken):
    user_id: str
    username: str


class ApiTokenCreated(Resp):
    token: str = Field(description="평문 토큰 — 이 응답에서 한 번만 돌려준다(다시 볼 수 없음)")
    api_token: ApiToken


# ---- 작업 종류·공통 작업 계약(§5) -----------------------------------------------------------------------


class JobKindItem(Resp):
    kind: str
    version: int
    label_ko: str
    stage: str
    cost: Literal["heavy", "light"]
    confirm_required: bool
    summary_entity: str
    allowed: bool = Field(description="mcp.allowed_job_kinds·denied_job_kinds 기준 생성 가능 여부")


class JobKindDetail(JobKindItem):
    job_types: list[str]
    params_schema: dict[str, Any]
    example: dict[str, Any]
    limits: dict[str, Any]


_PLAN_EXAMPLE = {"kind": "predict_batch", "study_id": "3f2b0c1e-0000-4000-8000-000000000001",
                 "params": {"multi_execution": 4, "source": {"kind": "lhs", "count": 20, "seed": 1}}}


class JobPlanRequest(Req):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [_PLAN_EXAMPLE]})

    kind: str = Field(min_length=1, max_length=64, description="작업 종류(list_job_kinds의 kind)")
    study_id: str = Field(min_length=1, max_length=64, description="대상 Study id")
    params: dict[str, Any] = Field(default_factory=dict,
                                   description="종류별 파라미터 — describe_job_kind로 스키마 확인")


class JobRunRequest(JobPlanRequest):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{**_PLAN_EXAMPLE, "confirm_token": "pcf_…"}]})

    confirm_token: str | None = Field(default=None, max_length=128,
                                      description="plan_job이 준 1회용 확인 토큰(토큰 요청 + 비용 큰 종류에서 필수)")


class PlanProblem(Resp):
    code: str
    message: str
    field: str | None = None


class JobPlan(Resp):
    kind: str
    kind_version: int
    study_id: str
    valid: bool
    runs: int | None = None
    parallel: int | None = None
    lane: str | None = None
    uses_global_slot: bool = False
    hpc_jobs: int = 0
    estimate_min: float | None = None
    estimate_basis: Literal["recent_median", "none"] = "none"
    disk_bytes_est: int | None = None
    targets: dict[str, str] = Field(default_factory=dict)
    queue_ahead: int = 0
    warnings: list[PlanProblem] = Field(default_factory=list)
    problems: list[PlanProblem] = Field(default_factory=list)
    confirm_required: bool
    confirm_token: str | None = None
    expires_at: datetime | None = None
    plan_id: str | None = None


class EntityRef(Resp):
    type: str
    id: str | None = None


class JobError(Resp):
    code: str | None = None
    message: str | None = None


class JobStatus(Resp):
    job_id: str | None = None
    kind: str | None = None
    job_type: str | None = None
    study_id: str
    state: str
    progress_pct: float | None = None
    progress_label: str | None = None
    queue_position: int | None = None
    entity: EntityRef | None = None
    created_by_name: str | None = None
    via_token: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: JobError | None = None


# ---- 요약(§7) ----------------------------------------------------------------------------------------


class SummaryTable(Resp):
    name: str
    columns: list[str]
    rows: list[list[Any]]
    total_rows: int
    stats: dict[str, dict[str, float]] = Field(default_factory=dict)


class SummaryLink(Resp):
    entity: str
    id: str
    rel: str


class Summary(Resp):
    entity: str
    id: str
    title: str
    state: str | None = None
    as_of: datetime
    facts: dict[str, Any] = Field(default_factory=dict)
    tables: list[SummaryTable] = Field(default_factory=list)
    links: list[SummaryLink] = Field(default_factory=list)
    truncated: bool = False
    bytes: int = 0


class SystemStatus(Resp):
    queue_head: list[dict[str, Any]]
    slot_holder_job_id: str | None = None
    worker_online: bool
    config_ok: bool
    hpc_mode: str | None = None
    features: dict[str, Any]


class PingToken(Resp):
    prefix: str
    scope: TokenScope
    expires_at: datetime
    days_left: int
    snapshot_age_days: int


class Ping(Resp):
    ok: bool
    server_version: str
    mcp_enabled: bool
    token: PingToken | None = Field(default=None, description="세션 요청이면 null")
    tools_count: int
    warnings: list[str] = Field(default_factory=list)


class StdioHint(Resp):
    command: str = Field(description="stdio 실행기 이름(physicsai-mcp)")
    command_path: str | None = Field(default=None, description="서버 venv의 실행기 경로(없으면 null) — 경로만, 비밀 없음")
    install: str = Field(description="내 PC 설치 안내 한 줄(오프라인 wheels)")


class McpConnection(Resp):
    """웹 "AI 연결(MCP)" 페이지용 연결 안내(mcp.md §23.4, MR-C3). enabled=false면 404 MCP_DISABLED라 200이면 항상 true."""

    enabled: bool
    http_enabled: bool = Field(description="false면 /physicsai/mcp(HTTP)가 꺼져 stdio만 쓸 수 있다")
    url: str = Field(description="HTTP MCP 주소(설정 mcp.public_url 또는 요청 origin + /physicsai/mcp 짐작)")
    url_source: Literal["config", "guess"]
    api_base: str = Field(description="stdio PHYSICSAI_MCP_URL용 = url에서 끝의 /mcp를 뗀 값")
    stdio_hint: StdioHint


# ---- 감사(§6.2) --------------------------------------------------------------------------------------


class ApiAudit(Resp):
    id: str
    occurred_at: datetime
    user_id: str | None = None
    username: str | None = None
    api_token_id: str | None = None
    token_prefix: str | None = None
    operation_id: str | None = None
    tool: str | None = None
    method: str
    route: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    study_id: str | None = None
    kind: str | None = None
    job_id: str | None = None
    plan_id: str | None = None
    status_code: int
    result_code: str | None = None
    duration_ms: int | None = None
    request_id: str | None = None
    client_ip: str | None = None
    params_sha256: str | None = None


class ApiAuditPage(Resp):
    items: list[ApiAudit]
    next_cursor: str | None = None
