"""MCP API `/mcp/*`(mcp.md §5.2·§6.2·§7·§9·§10). 세션·토큰 모두 허용, mcp.enabled=false면 404 MCP_DISABLED.

operationId = 도구 이름(명시). `x-mcp`가 도구 스펙 생성기(scripts/gen_tool_specs.py)의 단일 출처.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request

from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, request_id
from ..schemas import mcp as M
from ..services import mcp as svc

router = APIRouter(tags=["mcp"])
DISABLED = "MCP_DISABLED(mcp.enabled: false)"
JOB_ID = "작업 id(run_job·list_jobs의 job_id)"
TOP_N = "표 행 수[행](1~500, 기본 10, 최대 mcp.summary.top_n_max)"


@router.get("/mcp/ping", operation_id="ping", response_model=M.Ping, summary="연결 점검", responses=M.errors(e404=DISABLED),
            openapi_extra=M.xmcp_tool("ping", "read", "Connection check: server version, token prefix, scope, days left",
                                      "연결 점검: 서버 버전·토큰 접두·범위·남은 일수"))
def ping(request: Request, _p: Principal = Depends(get_principal)) -> dict:
    """연결 점검. 서버 버전·토큰 접두(pai_xxxxxxxx)·범위·남은 일수·도구 수를 돌려주고, 만료 5일 이하면 warnings에 안내한다. 세션 요청이면 token은 null. 부작용 없음."""
    return svc.ping(get_ctx(request), request.state)


@router.get("/mcp/job-kinds", operation_id="list_job_kinds", response_model=list[M.JobKindItem],
            summary="작업 종류 목록", responses=M.errors(e404=DISABLED),
            openapi_extra=M.xmcp_tool("list_job_kinds", "read", "List job kinds with cost and confirm requirement",
                                      "작업 종류 목록(비용·확인 필요 여부)"))
def list_job_kinds(request: Request, _p: Principal = Depends(get_principal)) -> list:
    """API로 만들 수 있는 작업 종류(①-3 DOE 생성·④ 예측·⑥ 최적화 등)와 비용(heavy·light)·확인 필요 여부를 본다.
    작업을 만들기 전에 먼저 호출해 kind 이름을 고른다. 부작용 없음."""
    return svc.list_kinds(get_ctx(request))


@router.get("/mcp/job-kinds/{kind}", operation_id="describe_job_kind", response_model=M.JobKindDetail,
            summary="작업 종류 설명(params 스키마)", responses=M.errors(e404=DISABLED, e422="JOB_KIND_UNKNOWN"),
            openapi_extra=M.xmcp_tool("describe_job_kind", "read", "Describe a job kind: params JSON Schema, example, limits",
                                      "작업 종류의 params 스키마·예시·한도"))
def describe_job_kind(request: Request, kind: str = Path(max_length=64, description="작업 종류(list_job_kinds의 kind)"),
                      _p: Principal = Depends(get_principal)) -> dict:
    """작업 종류 하나의 params JSON Schema(필드 설명·단위·범위)·예시·한도를 본다. plan_job·run_job의 params를 만들 때 쓴다. 부작용 없음."""
    return svc.describe_kind(get_ctx(request), kind)


@router.post("/mcp/jobs/plan", operation_id="plan_job", response_model=M.JobPlan, summary="작업 계획(dry-run)",
             responses=M.errors(e404=f"{DISABLED} · NOT_FOUND", e422="JOB_KIND_UNKNOWN · INVALID_PARAMS", e403="JOB_KIND_DENIED"),
             openapi_extra=M.xmcp_tool("plan_job", "read", "Dry-run a job: runs, time estimate, queue, problems; issues confirm_token",
                                       "작업을 만들지 않고 계획 계산, 확인 토큰 발급"))
def plan_job(body: M.JobPlanRequest, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """작업을 만들지 않고(저장 없음) run 수·동시 수·레인·예상 시간[분]·대기열 앞 작업 수·문제(problems)를 계산한다.
    비용 큰 종류를 run 범위 토큰으로 부르면 1회용 confirm_token(기본 600초)을 함께 준다 — 사용자에게 계획을 보여 준 뒤 run_job에 넣는다.
    problems가 있으면 valid=false, confirm_token=null."""
    return svc.plan(get_ctx(request), principal, request.state, body)


@router.post("/mcp/jobs", operation_id="run_job", response_model=M.JobStatus, status_code=201, summary="작업 생성",
             responses=M.errors(e404=f"{DISABLED} · NOT_FOUND", e403="JOB_KIND_DENIED",
                                e409="CONFIRM_INVALID(reason: mismatch·expired·used·unknown) · STUDY_JOB_BUSY 등 기존 생성 오류",
                                e422="JOB_KIND_UNKNOWN · INVALID_PARAMS", e428="CONFIRM_REQUIRED(plan_with: plan_job)"),
             openapi_extra=M.xmcp_tool("run_job", "run", "Create a job; heavy kinds need the confirm_token from plan_job",
                                       "작업 생성(비용 큰 종류는 plan_job의 confirm_token 필요)", confirm="by_kind"))
def run_job(body: M.JobRunRequest, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """작업을 만든다(부작용: 대기열에 작업 등록·슬롯·HPC 자원 사용). 기존 웹 생성 API와 같은 서비스·검증을 거친다.
    토큰 요청에서 비용 큰 종류(cost heavy)는 plan_job이 준 confirm_token이 필요하다 — 없으면 428, params가 바뀌었거나 만료·재사용이면 409."""
    return svc.run(get_ctx(request), principal, request.state, body, request_id(request), client_ip(request))


@router.get("/mcp/jobs", operation_id="list_jobs", response_model=list[M.JobStatus], summary="작업 목록(짧은 형태)",
            responses=M.errors(e404=DISABLED, e422="JOB_KIND_UNKNOWN"),
            openapi_extra=M.xmcp_tool("list_jobs", "read", "List jobs by study, state, kind (newest first)",
                                      "Study·상태·종류로 작업 목록(최신순)"))
def list_jobs(request: Request,
              study_id: str | None = Query(default=None, max_length=64, description="Study id로 거르기"),
              state: str | None = Query(default=None, max_length=200, description="작업 상태(쉼표 구분, 예 QUEUED,RUNNING)"),
              kind: str | None = Query(default=None, max_length=64, description="작업 종류(list_job_kinds의 kind)"),
              mine: bool = Query(default=False, description="내가 만든 작업만"),
              limit: int = Query(default=20, ge=1, le=50, description="최대 개수[개](1~50)"),
              principal: Principal = Depends(get_principal)) -> list:
    """작업 목록(최신순, 종류 무관 공통 JobStatus 짧은 형태). 진행 상황 확인용. 부작용 없음."""
    return svc.list_jobs(get_ctx(request), principal, study_id=study_id, state=state, kind=kind, mine=mine, limit=limit)


@router.get("/mcp/jobs/{job_id}", operation_id="job_status", response_model=M.JobStatus, summary="작업 상태",
            responses=M.errors(e404=f"{DISABLED} · NOT_FOUND"),
            openapi_extra=M.xmcp_tool("job_status", "read", "Status, progress and error of one job", "작업 하나의 상태·진행률·오류"))
def job_status(request: Request, job_id: str = Path(max_length=64, description=JOB_ID),
               principal: Principal = Depends(get_principal)) -> dict:
    """작업 하나의 상태·진행률[%]·대기 순번·엔티티·오류. 폴링은 수십 초 간격으로. 부작용 없음."""
    return svc.job_status(get_ctx(request), principal, job_id)


@router.get("/mcp/jobs/{job_id}/summary", operation_id="job_summary", response_model=M.Summary, summary="작업 결과 요약",
            responses=M.errors(e404=f"{DISABLED} · NOT_FOUND · SUMMARY_ENTITY_UNKNOWN"),
            openapi_extra=M.xmcp_tool("job_summary", "read", "Summary of the result entity a job produced (top-N rows, stats)",
                                      "작업이 만든 결과 엔티티 요약(표 상위 N행·통계)"))
def job_summary(request: Request, job_id: str = Path(max_length=64, description=JOB_ID),
                top_n: int | None = Query(default=None, ge=1, le=500, description=TOP_N),
                principal: Principal = Depends(get_principal)) -> dict:
    """작업이 만든 결과(DOE·배치·최적화·판정 등)의 요약 봉투(사실·표 상위 N행·통계, 8 KiB 이하). 부작용 없음."""
    return svc.job_summary(get_ctx(request), principal, job_id, top_n)


@router.post("/mcp/jobs/{job_id}/cancel", operation_id="cancel_job", response_model=M.JobStatus, status_code=202,
             summary="작업 취소", responses=M.errors(e404=f"{DISABLED} · NOT_FOUND", e409="JOB_TERMINAL"),
             openapi_extra=M.xmcp_tool("cancel_job", "run", "Cancel a job (tokens: only jobs created by the same token; idempotent)",
                                       "작업 취소(토큰은 그 토큰이 만든 작업만, 멱등)"))
def cancel_job(request: Request, job_id: str = Path(max_length=64, description=JOB_ID),
               principal: Principal = Depends(get_principal)) -> dict:
    """작업 취소(부작용: 대기 작업 취소·실행 중 작업 중단 요청). API 토큰은 그 토큰이 만든 작업만 취소할 수 있다. 이미 끝났으면 상태만 돌려준다."""
    return svc.cancel(get_ctx(request), principal, request.state, job_id, request_id(request), client_ip(request))


@router.get("/mcp/summary/{entity}/{id}", operation_id="get_summary", response_model=M.Summary, summary="엔티티 요약",
            responses=M.errors(e404=f"{DISABLED} · NOT_FOUND · SUMMARY_ENTITY_UNKNOWN"),
            openapi_extra=M.xmcp_tool("get_summary", "read", "Summary of a study, param set, DOE, batch, optimization, check ...",
                                      "study·param_set·train_doe·predict_batch 등 엔티티 요약"))
def get_summary(request: Request,
                entity: str = Path(max_length=32, description="엔티티 종류(study·param_set·train_doe·predict_run·predict_batch·surrogate_opt·equiv_check·fem_verify·geom_preview·job)"),
                id: str = Path(max_length=64, description="엔티티 id"),  # noqa: A002 — 경로 이름(계약 §7)
                top_n: int | None = Query(default=None, ge=1, le=500, description=TOP_N),
                principal: Principal = Depends(get_principal)) -> dict:
    """엔티티(study·param_set·train_doe·predict_run·predict_batch·surrogate_opt·equiv_check·fem_verify·geom_preview·job) 요약 봉투.
    절대경로 없이 표시 이름·id만, 8 KiB 이하(넘으면 truncated). 부작용 없음."""
    return svc.summary(get_ctx(request), principal, entity, id, top_n)


@router.get("/mcp/system", operation_id="system_status", response_model=M.SystemStatus, summary="시스템 상태",
            responses=M.errors(e404=DISABLED),
            openapi_extra=M.xmcp_tool("system_status", "read", "Queue head, slot holder, worker online, config, HPC mode, features",
                                      "대기열 앞 5개·슬롯·워커·설정·HPC 모드·기능"))
def system_status(request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """대기열 앞 5개·전역 슬롯 보유 작업·워커 온라인·설정 정상 여부·HPC 모드·기능 사용 가능 여부. 작업 전에 확인. 부작용 없음."""
    return svc.system_status(get_ctx(request), principal)


@router.get("/mcp/audit", operation_id="list_audit", response_model=M.ApiAuditPage, summary="토큰 요청 감사 조회",
            responses=M.errors(e404=DISABLED, e422="INVALID_PARAMS"),
            openapi_extra=M.xmcp_tool("list_audit", "admin", "API token request audit log (admin only)",
                                      "API 토큰 요청 감사 기록(관리자 전용)"))
def list_audit(request: Request,
               user_id: str | None = Query(default=None, max_length=200, description="사용자 id"),
               token_id: str | None = Query(default=None, max_length=64, description="API 토큰 id"),
               operation_id: str | None = Query(default=None, max_length=200, description="operationId"),
               status: int | None = Query(default=None, ge=100, le=599, description="HTTP 상태 코드[-](100~599)"),
               since: datetime | None = Query(default=None, description="이 시각 이후(ISO 8601)"),
               until: datetime | None = Query(default=None, description="이 시각 이전(ISO 8601)"),
               limit: int | None = Query(default=None, ge=1, le=200, description="최대 개수[개](1~200, 기본 50)"),
               cursor: str | None = Query(default=None, max_length=200, description="다음 페이지 커서(next_cursor)"),
               principal: Principal = Depends(get_principal)) -> dict:
    """토큰 요청 감사 기록(최신순, 본문·값 없음). 전역 관리자(세션) 또는 admin 범위 토큰만. 부작용 없음."""
    return svc.list_audit(get_ctx(request), principal, user_id=user_id, token_id=token_id, operation_id=operation_id,
                          status=status, since=since, until=until, limit=limit, cursor=cursor)


@router.get("/mcp/glossary", operation_id="get_glossary", response_model=dict, summary="도메인 용어집",
            responses=M.errors(e404=DISABLED, e422="INVALID_PARAMS"),
            openapi_extra=M.xmcp_tool("get_glossary", "read", "Domain glossary: feature abbreviations, entities, job kinds, stages, error codes",
                                      "피처 약어·엔티티·작업 종류·단계 번호·오류 코드·동의어"))
def get_glossary(request: Request,
                 section: Literal["entities", "job_types", "job_kinds", "stages", "feature_abbr", "enums", "error_codes",
                                  "terms", "error_hints"] | None = Query(default=None, description="부분 조회할 절(생략 = 전체, 64 KiB 상한)"),
                 _p: Principal = Depends(get_principal)) -> dict:
    """도메인 용어집: 피처 약어(THK=두께 등)·엔티티 관계·작업 종류·화면 단계 번호·오류 코드와 사람이 쓴 한국어 이름·동의어.
    사용자 말을 파라미터·엔티티 이름으로 바꿀 때 쓴다. 부작용 없음."""
    return svc.glossary(get_ctx(request), section)


@router.get("/mcp/tools", operation_id="mcp_tool_specs", response_model=dict | list, summary="도구 스펙(MCP 서버 부팅용)",
            responses=M.errors(e404=DISABLED),
            openapi_extra=M.xmcp_exclude("MCP 서버 부팅용", token_risk="read"))
def mcp_tool_specs(request: Request,
                   format: Literal["mcp", "openai"] = Query(default="mcp", description="mcp(tools.mcp.json) | openai(tools.openai.json)"),  # noqa: A002
                   _p: Principal = Depends(get_principal)) -> dict | list:
    """생성된 도구 스펙 파일을 그대로 돌려준다(MCP 서버가 부팅 때 읽어 도구를 동적으로 노출)."""
    return svc.tools(get_ctx(request), format)
