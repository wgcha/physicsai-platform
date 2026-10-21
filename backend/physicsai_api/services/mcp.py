"""공통 작업 계약 `/mcp/*`(mcp.md §5·§6.2·§7·§9·§10·§17). 라우터는 이 모듈만 부른다(레이어 규칙 3).

- plan_job(read) → JobPlan(+ run 범위 토큰·heavy면 1회용 confirm_token, TTL mcp.confirm_ttl_s, (토큰·종류·Study·params 해시) 결합)
- run_job(run) → 토큰 + heavy + require_confirm_for_token이면 confirm 필수(428/409), 기존 생성 서비스 호출(웹 흐름 불변)
- cancel_job(run) → 토큰 요청은 그 토큰이 만든 작업만(§2.1 예외), 세션은 기존 권한
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError

from physicsai_core import __version__
from physicsai_core.db.repositories import api_audit as audit_repo
from physicsai_core.db.repositories import api_tokens as tokens_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import mcp_plans as plans_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.request_context import token_job_context
from physicsai_core.state_machine import TERMINAL

from ..auth import Principal
from ..auth_tokens import scope_allows
from ..context import AppContext
from ..mcp import clock
from ..mcp import glossary as glossary_mod
from ..mcp import job_kinds as jk
from ..mcp import summaries as summaries_mod
from .api_tokens import require_enabled
from .common import clamp_limit, require_global_admin, require_power

CONFIRM_PREFIX = "pcf_"
EXPIRY_WARN_DAYS = 5  # ping: 만료 임박 경고(mcp.md §9.1)


def params_sha256(params: dict[str, Any]) -> str:
    canon = json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _note(request_state: Any, **kw: Any) -> None:
    """감사 미들웨어가 읽는 요청 메모(키 이름·해시·id만 — 값·본문 금지)."""
    cur = dict(getattr(request_state, "mcp_audit", None) or {})
    cur.update({k: v for k, v in kw.items() if v is not None})
    request_state.mcp_audit = cur


def require_kind(name: str) -> jk.JobKind:
    k = jk.JOB_KINDS.get(name)
    if k is None:
        raise DomainError("JOB_KIND_UNKNOWN", f"알 수 없는 작업 종류: {name}", status=422, kinds=sorted(jk.JOB_KINDS))
    return k


def require_allowed(ctx: AppContext, k: jk.JobKind) -> None:
    if not jk.kind_allowed(k.kind, ctx.settings):
        raise DomainError("JOB_KIND_DENIED", f"이 작업 종류는 API로 만들 수 없습니다({k.kind}) — 웹 화면에서 실행하세요", status=403,
                          kind=k.kind)


def _validate(k: jk.JobKind, params: dict[str, Any]) -> Any:
    try:
        return k.params_model.model_validate(params)
    except ValidationError as exc:
        raise DomainError("INVALID_PARAMS", "요청 값이 올바르지 않습니다", status=422,
                          errors=[{"loc": ["body", "params", *e["loc"]], "msg": e["msg"]} for e in exc.errors()]) from None


# ---- 작업 종류 ---------------------------------------------------------------------------------------


def _kind_item(ctx: AppContext, k: jk.JobKind) -> dict[str, Any]:
    return {"kind": k.kind, "version": k.version, "label_ko": k.label_ko, "stage": k.stage, "cost": k.cost,
            "confirm_required": jk.confirm_required(k, ctx.settings), "summary_entity": k.summary_entity,
            "allowed": jk.kind_allowed(k.kind, ctx.settings)}


def list_kinds(ctx: AppContext) -> list[dict[str, Any]]:
    require_enabled(ctx)
    return [_kind_item(ctx, k) for k in sorted(jk.JOB_KINDS.values(), key=lambda x: x.kind)]


def describe_kind(ctx: AppContext, name: str) -> dict[str, Any]:
    require_enabled(ctx)
    k = require_kind(name)
    return {**_kind_item(ctx, k), "job_types": list(k.job_types), "params_schema": k.params_model.model_json_schema(),
            "example": k.example, "limits": k.limits(ctx.settings)}


# ---- plan → confirm → run --------------------------------------------------------------------------


def plan(ctx: AppContext, principal: Principal, state: Any, body: Any) -> dict[str, Any]:
    require_enabled(ctx)
    k = require_kind(body.kind)
    psha = params_sha256(body.params)
    _note(state, kind=k.kind, study_id=body.study_id, params_sha256=psha)
    require_allowed(ctx, k)
    with ctx.engine.connect() as conn:
        studies_repo.require(conn, body.study_id)
    base: dict[str, Any] = {"kind": k.kind, "kind_version": k.version, "study_id": body.study_id,
                            "confirm_required": jk.confirm_required(k, ctx.settings)}
    try:
        p = k.params_model.model_validate(body.params)
    except ValidationError as exc:
        probs = [jk.problem("INVALID_PARAMS", e["msg"], ".".join(str(x) for x in e["loc"])) for e in exc.errors()]
        return {**base, "valid": False, "problems": probs}
    frag = k.plan_fn(ctx, principal, body.study_id, p)
    out = {**base, **frag}
    out["valid"] = not out.get("problems")
    lane = out.get("lane")
    if lane:
        with ctx.engine.connect() as conn:
            out["queue_ahead"] = len(jobs_repo.queue_positions(conn, lane))
    tok = getattr(state, "api_token", None) or {}
    token_id = getattr(state, "api_token_id", None)
    # run 범위 이상 토큰만 confirm_token을 받는다(read 토큰·세션 요청은 계획만 — §5.2 규칙)
    if out["valid"] and out["confirm_required"] and token_id and scope_allows(tok.get("scope", "read"), "run"):
        plain = CONFIRM_PREFIX + secrets.token_urlsafe(32)
        now = clock.now()
        exp = now + timedelta(seconds=ctx.settings.mcp.confirm_ttl_s)
        pid = str(uuid.uuid4())
        nums = {key: out.get(key) for key in ("runs", "parallel", "lane", "hpc_jobs", "estimate_min", "disk_bytes_est")}
        with ctx.engine.begin() as conn:
            plans_repo.insert(conn, id=pid, api_token_id=token_id, user_id=principal.user_id, kind=k.kind, kind_version=k.version,
                              study_id=body.study_id, params_sha256=psha, confirm_hash=_hash(plain), summary=nums,
                              created_at=now, expires_at=exp)
        out.update(confirm_token=plain, expires_at=exp, plan_id=pid)
        _note(state, plan_id=pid)
    return out


def _check_confirm(ctx: AppContext, token_id: str | None, k: jk.JobKind, study_id: str, psha: str, confirm: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        row = plans_repo.get_by_confirm_hash(conn, _hash(confirm))

    def bad(reason: str, msg: str) -> DomainError:
        return DomainError("CONFIRM_INVALID", msg, status=409, reason=reason, plan_with="plan_job")

    if row is None or row["api_token_id"] != token_id:
        raise bad("unknown", "확인 토큰을 찾을 수 없습니다 — plan_job을 다시 호출하세요")
    if row["kind"] != k.kind or row["kind_version"] != k.version or row["study_id"] != study_id or row["params_sha256"] != psha:
        raise bad("mismatch", "확인 토큰이 이 요청(종류·Study·params)과 맞지 않습니다 — 바뀐 값으로 plan_job을 다시 호출하세요")
    if row["used_at"] is not None:
        raise bad("used", "이미 사용한 확인 토큰입니다(1회용) — plan_job을 다시 호출하세요")
    if row["expires_at"] <= clock.now():
        raise bad("expired", "확인 토큰이 만료되었습니다 — plan_job을 다시 호출하세요")
    return row


def run(ctx: AppContext, principal: Principal, state: Any, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    require_enabled(ctx)
    k = require_kind(body.kind)
    psha = params_sha256(body.params)
    _note(state, kind=k.kind, study_id=body.study_id, params_sha256=psha)
    require_allowed(ctx, k)
    token_id = getattr(state, "api_token_id", None)
    if token_id:
        with ctx.engine.connect() as conn:
            active = tokens_repo.active_job_ids(conn, token_id)
        lim = ctx.settings.mcp.rate_limit.max_active_jobs_per_token
        if len(active) >= lim:
            raise DomainError("TOKEN_ACTIVE_JOB_LIMIT", f"이 토큰이 만든 진행 중 작업이 상한({lim})입니다 — 끝나거나 취소한 뒤 다시 시도하세요",
                              status=429, active_job_ids=active)
    p = _validate(k, body.params)
    plan_row = None
    need = bool(token_id) and jk.confirm_required(k, ctx.settings)
    if need and not body.confirm_token:
        raise DomainError("CONFIRM_REQUIRED", "비용 큰 작업은 확인이 필요합니다 — plan_job으로 계획을 보고 confirm_token을 받아 다시 보내세요",
                          status=428, plan_with="plan_job")
    if body.confirm_token:
        plan_row = _check_confirm(ctx, token_id, k, body.study_id, psha, body.confirm_token)
        with ctx.engine.begin() as conn:
            if not plans_repo.claim(conn, plan_row["id"], clock.now()):
                raise DomainError("CONFIRM_INVALID", "이미 사용한 확인 토큰입니다(1회용) — plan_job을 다시 호출하세요", status=409,
                                  reason="used", plan_with="plan_job")
        _note(state, plan_id=plan_row["id"])
    try:
        with token_job_context(token_id) as created:
            out, job_id, ent = k.create_fn(ctx, principal, body.study_id, p, rid, ip)
    except Exception:
        if plan_row is not None:  # 작업이 만들어지지 않았으니 확인 토큰은 다시 쓸 수 있다
            with ctx.engine.begin() as conn:
                plans_repo.release(conn, plan_row["id"])
        raise
    job_id = job_id or (created[0] if created else None)
    if plan_row is not None:
        with ctx.engine.begin() as conn:
            plans_repo.set_job(conn, plan_row["id"], job_id)
    _note(state, job_id=job_id)
    if job_id is None:  # 형상 미리보기 캐시 적중 등 — 작업 없이 결과
        return {"job_id": None, "kind": k.kind, "job_type": None, "study_id": body.study_id,
                "state": "SUCCEEDED" if out.get("status") == "DONE" else str(out.get("status") or "SUCCEEDED"),
                "entity": {"type": k.summary_entity, "id": ent}}
    st = job_status(ctx, principal, job_id)
    if ent and st.get("entity") and not st["entity"].get("id"):
        st["entity"]["id"] = ent
    return st


# ---- 조회·취소 ---------------------------------------------------------------------------------------


def _status_of(j: dict[str, Any], pos: int | None, prefix: str | None) -> dict[str, Any]:
    ent = jk.entity_of_job(j)
    return {"job_id": j["id"], "kind": jk.kind_of_job(j), "job_type": j["job_type"], "study_id": j["study_id"], "state": j["state"],
            "progress_pct": j.get("progress_pct"), "progress_label": j.get("progress_label"),
            "queue_position": pos if j["state"] == "QUEUED" else None,
            "entity": {"type": ent[0], "id": ent[1]} if ent else None, "created_by_name": j.get("created_by_name"),
            "via_token": prefix, "created_at": j.get("created_at"), "started_at": j.get("started_at"),
            "finished_at": j.get("finished_at"),
            "error": {"code": j.get("failure_code"), "message": j.get("failure_message")} if j.get("failure_code") else None}


def job_status(ctx: AppContext, principal: Principal, job_id: str) -> dict[str, Any]:
    require_enabled(ctx)
    with ctx.engine.connect() as conn:
        j = jobs_repo.get_job(conn, job_id)
        if j is None:
            raise DomainError("NOT_FOUND", "작업을 찾을 수 없습니다", status=404)
        pos = jobs_repo.queue_positions(conn, j["lane"]).get(j["id"]) if j["state"] == "QUEUED" else None
        pre = tokens_repo.prefixes(conn, [j["api_token_id"]]) if j.get("api_token_id") else {}
    return _status_of(j, pos, pre.get(j.get("api_token_id") or ""))


def list_jobs(ctx: AppContext, principal: Principal, *, study_id: str | None, state: str | None, kind: str | None,
              mine: bool, limit: int | None) -> list[dict[str, Any]]:
    require_enabled(ctx)
    jt = require_kind(kind).job_types[0] if kind else None
    lim = max(1, min(50, int(limit or 20)))
    with ctx.engine.connect() as conn:
        rows = jobs_repo.list_with_study_title(conn, study_id=study_id or None, states=state.split(",") if state else None,
                                               created_by=principal.user_id if mine else None, job_type=jt, limit=lim, offset=0)
        pos = {lane: jobs_repo.queue_positions(conn, lane) for lane in ("SLOT", "LIGHT", "PREVIEW")}
        pre = tokens_repo.prefixes(conn, [r["api_token_id"] for r in rows if r.get("api_token_id")])
    return [_status_of(r, pos[r["lane"]].get(r["id"]), pre.get(r.get("api_token_id") or "")) for r in rows]


def job_summary(ctx: AppContext, principal: Principal, job_id: str, top_n: int | None) -> dict[str, Any]:
    require_enabled(ctx)
    with ctx.engine.connect() as conn:
        j = jobs_repo.get_job(conn, job_id)
    if j is None:
        raise DomainError("NOT_FOUND", "작업을 찾을 수 없습니다", status=404)
    ent = jk.entity_of_job(j)
    if ent and ent[1] and ent[0] in summaries_mod.SUMMARIES:
        return summaries_mod.summarize(ctx, principal, ent[0], ent[1], top_n)
    return summaries_mod.summarize(ctx, principal, "job", job_id, top_n)


def cancel(ctx: AppContext, principal: Principal, state: Any, job_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    require_enabled(ctx)
    token_id = getattr(state, "api_token_id", None)
    with ctx.engine.connect() as conn:
        j = jobs_repo.get_job(conn, job_id)
    if j is None:
        raise DomainError("NOT_FOUND", "작업을 찾을 수 없습니다", status=404)
    _note(state, job_id=job_id, study_id=j["study_id"])
    if token_id and j.get("api_token_id") != token_id:  # §2.1: 토큰은 그 토큰이 만든 작업만
        raise DomainError("PERMISSION_DENIED", "API 토큰은 그 토큰이 만든 작업만 취소할 수 있습니다", status=403, required="same_token")
    if token_id:  # 권한 = min(토큰 범위, 역할 스냅숏): 스냅숏에서 power를 잃었으면 자기 토큰 작업도 취소 불가
        require_power(principal, j["project_id"])
    if j["state"] in TERMINAL or j.get("cancel_requested_at") is not None:  # 멱등
        return job_status(ctx, principal, job_id)
    kname = jk.kind_of_job(j)
    k = jk.JOB_KINDS.get(kname) if kname else None
    ent = jk.entity_of_job(j)
    with token_job_context(token_id):  # 취소 경로의 audit_events에도 detail.api_token_id
        if k is not None and k.cancel_fn is not None and ent and ent[1]:
            k.cancel_fn(ctx, principal, ent[1], rid, ip)
        else:
            from . import jobs as jobs_svc

            jobs_svc.cancel_job(ctx, principal, job_id, rid, ip, token_owner_ok=bool(token_id))
    return job_status(ctx, principal, job_id)


# ---- 요약·시스템·감사·용어집·도구·ping ---------------------------------------------------------------


def summary(ctx: AppContext, principal: Principal, entity: str, eid: str, top_n: int | None) -> dict[str, Any]:
    require_enabled(ctx)
    return summaries_mod.summarize(ctx, principal, entity, eid, top_n)


def system_status(ctx: AppContext, principal: Principal) -> dict[str, Any]:
    require_enabled(ctx)
    from . import jobs as jobs_svc
    from . import system

    st = system.status(ctx)
    q = jobs_svc.queue_view(ctx)
    head = ([q["running"]] if q["running"] else []) + q["queued"][:5]
    keep = ("id", "job_type", "stage_label", "state", "study_title", "queue_position", "progress_pct", "created_by_name")
    return {"queue_head": [{k: x.get(k) for k in keep} for x in head[:5]], "slot_holder_job_id": q["slot"]["holder_job_id"],
            "worker_online": bool(st["worker"]["online"]), "config_ok": bool(st["config"]["ok"]), "hpc_mode": st["hpc"]["mode"],
            "features": {k: (v.get("enabled") if isinstance(v, dict) else v) for k, v in st["features"].items()}}


def _enc_cursor(ts: datetime, rid: str) -> str:
    return base64.urlsafe_b64encode(f"{ts.isoformat()}|{rid}".encode()).decode().rstrip("=")


def _dec_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        ts, _, rid = base64.urlsafe_b64decode(cursor.encode() + b"==").decode().partition("|")
        return datetime.fromisoformat(ts), rid
    except (ValueError, UnicodeDecodeError):
        raise DomainError("INVALID_PARAMS", "cursor 형식이 올바르지 않습니다", status=422,
                          errors=[{"loc": ["query", "cursor"], "msg": "invalid"}]) from None


def list_audit(ctx: AppContext, principal: Principal, *, user_id: str | None, token_id: str | None, operation_id: str | None,
               status: int | None, since: Any, until: Any, limit: int | None, cursor: str | None) -> dict[str, Any]:
    require_enabled(ctx)
    require_global_admin(principal)  # admin 토큰은 범위 판정에서 스냅숏 전역 관리자까지 확인됨
    lim = clamp_limit(limit)
    with ctx.engine.connect() as conn:
        rows = audit_repo.list_(conn, user_id=user_id, token_id=token_id, operation_id=operation_id, status=status, since=since,
                                until=until, limit=lim + 1, after=_dec_cursor(cursor))
    page = rows[:lim]
    nxt = _enc_cursor(page[-1]["occurred_at"], page[-1]["id"]) if len(rows) > lim and page else None
    return {"items": page, "next_cursor": nxt}


def glossary(ctx: AppContext, section: str | None) -> dict[str, Any]:
    require_enabled(ctx)
    if section is not None and section not in glossary_mod.SECTIONS:
        raise DomainError("INVALID_PARAMS", "요청 값이 올바르지 않습니다", status=422,
                          errors=[{"loc": ["query", "section"], "msg": " | ".join(glossary_mod.SECTIONS)}])
    return glossary_mod.merged(section)


def tools(ctx: AppContext, fmt: str, *, with_visible: bool = False, scope: str | None = None) -> Any:
    """생성 도구 스펙 파일 그대로. `with_visible`(mcp 형식만)이면 최상위 `visible` = 이 범위(`scope`, None=세션=전체)의 호출자가 부를 수 있는 도구 이름 —
    MCP 서버의 `tools/list` 표시 필터 판정을 백엔드가 한다(MCP 계층에는 권한 판단 없음, mcp.md §20.1)."""
    require_enabled(ctx)
    return tool_specs(fmt, with_visible=with_visible, scope=scope)


def tool_specs(fmt: str, *, with_visible: bool = False, scope: str | None = None) -> Any:
    name = "tools.openai.json" if fmt == "openai" else "tools.mcp.json"
    doc = json.loads((glossary_mod.GENERATED_DIR / name).read_text(encoding="utf-8"))
    if with_visible and fmt != "openai":
        doc["visible"] = [t["name"] for t in doc["tools"]
                          if scope is None or scope_allows(scope, (t.get("annotations") or {}).get("x-risk", "read"))]
    return doc


def ping(ctx: AppContext, state: Any) -> dict[str, Any]:
    """연결 점검(MR-17): 서버 버전·MCP 사용 여부·토큰 접두·범위·남은 일수·도구 수. 세션 요청이면 token=null."""
    require_enabled(ctx)
    now = clock.now()
    warnings: list[str] = []
    token: dict[str, Any] | None = None
    tid = getattr(state, "api_token_id", None)
    if tid:
        with ctx.engine.connect() as conn:
            row = tokens_repo.get(conn, tid)
        if row is not None:
            days_left = max(0, int((row["expires_at"] - now).total_seconds() // 86400))
            token = {"prefix": row["token_prefix"], "scope": row["scope"], "expires_at": row["expires_at"], "days_left": days_left,
                     "snapshot_age_days": max(0, (now - row["snapshot_at"]).days)}
            if days_left <= EXPIRY_WARN_DAYS:
                warnings.append(f"토큰 만료 임박(남은 {days_left}일) — 웹에서 새 토큰을 발급해 교체하세요")
    return {"ok": True, "server_version": __version__, "mcp_enabled": True, "token": token,
            "tools_count": len(tools(ctx, "mcp").get("tools") or []), "warnings": warnings}
