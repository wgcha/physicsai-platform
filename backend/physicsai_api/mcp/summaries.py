"""요약 레지스트리 `SUMMARIES`(mcp.md §7). 새 결과 엔티티는 여기 한 줄 등록(V-MCP-8).

각 summary_fn은 **기존 서비스 조회 함수**를 불러(SQL·파일 파서 복제 금지) 공통 봉투로 줄인다.
봉투 = {entity, id, title, state, as_of, facts(스칼라 ≤ 30키), tables, links, truncated, bytes}, 직렬화 ≤ mcp.summary.max_bytes.
절대경로는 넣지 않는다(경로 성격 키 제외 + 절대경로 모양 문자열 제외). 수치 열 이름에 `[단위]` 접미(세트·결과 표 단위가 있을 때).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from physicsai_core.errors import DomainError

from . import clock

MAX_FACTS = 30
_ABS = re.compile(r"^(?:/|[A-Za-z]:[\\/]|\\\\)")
_PATHY_KEYS = ("path", "_rel", "dir", "root", "folder", "stored")


def _svc(name: str) -> Any:
    """기존 서비스 모듈(job_kinds.SERVICES + 조회 전용 모듈)."""
    from ..services import doe_result_table, predict_runs, stage1_train_data, studies
    from .job_kinds import SERVICES

    return {**SERVICES, "doe_result_table": doe_result_table, "predict_runs": predict_runs,
            "stage1_train_data": stage1_train_data, "studies": studies}[name]


def is_pathy(key: str, value: Any) -> bool:
    k = key.lower()
    if any(p in k for p in _PATHY_KEYS) and k not in ("folder_name",):
        return True
    return isinstance(value, str) and bool(_ABS.match(value))


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def facts_of(d: dict[str, Any], keys: tuple[str, ...] | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in keys or tuple(d.keys()):
        v = d.get(k)
        if (v is None and keys is None) or isinstance(v, (dict, list)) or is_pathy(k, v):
            continue
        if isinstance(v, (str, int, float, bool, datetime)) or v is None:
            out[k] = _jsonable(v)
    for k, v in extra.items():
        if not is_pathy(k, v) and (isinstance(v, (str, int, float, bool)) or v is None):
            out[k] = _jsonable(v)
    return dict(list(out.items())[:MAX_FACTS])


def _flat(row: dict[str, Any], expand: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if k in expand and isinstance(v, dict):
            for kk, vv in v.items():
                if not isinstance(vv, (dict, list)):
                    out[str(kk)] = vv
        elif not isinstance(v, (dict, list)) and not is_pathy(k, v):
            out[k] = v
    return out


def table(name: str, rows: list[dict[str, Any]], top_n: int, *, columns: list[str] | None = None,
          expand: tuple[str, ...] = (), units: dict[str, str] | None = None) -> dict[str, Any]:
    """dict 행 → 표(상위 top_n행) + 수치 열 통계(전체 행 기준). 열 이름에 단위 접미."""
    flat = [_flat(r, expand) for r in rows]
    cols = list(columns or [])
    if not cols:
        for r in flat:
            for k in r:
                if k not in cols:
                    cols.append(k)
    units = units or {}
    stats: dict[str, dict[str, float]] = {}
    for c in cols:
        nums = [float(r[c]) for r in flat if isinstance(r.get(c), (int, float)) and not isinstance(r.get(c), bool)
                and math.isfinite(float(r[c]))]
        if nums and len(nums) == sum(1 for r in flat if r.get(c) is not None):
            label = f"{c}[{units[c]}]" if units.get(c) else c
            stats[label] = {"min": min(nums), "max": max(nums), "mean": round(sum(nums) / len(nums), 6)}
    labels = [f"{c}[{units[c]}]" if units.get(c) else c for c in cols]
    body = [[_jsonable(r.get(c)) for c in cols] for r in flat[:top_n]]
    return {"name": name, "columns": labels, "rows": body, "total_rows": len(rows), "stats": stats}


def envelope(entity: str, eid: str, title: str, state: str | None, facts: dict[str, Any],
             tables: list[dict[str, Any]] | None = None, links: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"entity": entity, "id": eid, "title": title, "state": state, "as_of": clock.now().isoformat(), "facts": facts,
            "tables": tables or [], "links": links or [], "truncated": False, "bytes": 0}


def fit(env: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """직렬화 크기가 max_bytes를 넘으면 가장 큰 표의 행을 반씩 줄이고, 그래도 넘으면 표·링크·사실을 덜어낸다(truncated)."""
    def size() -> int:
        env["bytes"] = 0
        n = len(json.dumps(env, ensure_ascii=False, default=str).encode("utf-8"))
        env["bytes"] = n + len(str(n))
        return env["bytes"]

    while size() > max_bytes:
        env["truncated"] = True
        tabs = [t for t in env["tables"] if t["rows"]]
        if tabs:
            big = max(tabs, key=lambda t: len(json.dumps(t["rows"], default=str)))
            big["rows"] = big["rows"][: len(big["rows"]) // 2]
            continue
        if any(t.get("stats") for t in env["tables"]):
            for t in env["tables"]:
                t["stats"] = {}
            continue
        if env["tables"]:
            env["tables"].pop()
            continue
        if env["links"]:
            env["links"] = env["links"][: len(env["links"]) // 2]
            continue
        if env["facts"]:
            keys = list(env["facts"])
            env["facts"] = {k: env["facts"][k] for k in keys[: len(keys) // 2]}
            continue
        break
    return env


# ---- 엔티티별(기존 서비스 호출) ------------------------------------------------------------------------


def _study(ctx: Any, principal: Any, sid: str, top_n: int) -> dict[str, Any]:
    s = _svc("studies").get_study(ctx, principal, sid)
    stages = [{"stage": k, **v} for k, v in (s.get("stage_status") or {}).items()]
    jobs, _ = _svc("jobs").list_jobs(ctx, principal, study_id=sid, state=None, mine=False, job_type=None, limit=5, cursor=None)
    links: list[dict[str, Any]] = []
    counts: dict[str, Any] = {}
    for ent, fn in (("param_set", lambda: _svc("stage4_predict").list_param_sets(ctx, sid, 200, None)[0]),
                    ("train_doe", lambda: _svc("stage1_train_data").list_does(ctx, sid)),
                    ("predict_batch", lambda: _svc("predict_batches").list_batches(ctx, sid)),
                    ("surrogate_opt", lambda: _svc("surrogate_opts").list_opts(ctx, sid))):
        try:
            rows = fn()
        except DomainError:
            rows = []
        counts[f"{ent}_count"] = len(rows)
        if rows:
            links.append({"entity": ent, "id": str(rows[0]["id"]), "rel": "latest"})
    fm = s.get("final_model") or {}
    facts = facts_of(s, ("title", "project_id", "status", "folder_name", "current_param_set_id", "final_model_id", "created_by_name",
                         "created_at"), final_model=f"{fm.get('name')} v{fm.get('version')}" if fm else None, **counts)
    tabs = [table("stages", stages, top_n), table("recent_jobs", jobs, 5, columns=["id", "job_type", "stage_label", "state",
                                                                                     "progress_pct", "created_at"])]
    return envelope("study", sid, s["title"], s["status"], facts, tabs, links)


def _param_set(ctx: Any, principal: Any, pid: str, top_n: int) -> dict[str, Any]:
    p = _svc("stage4_predict").get_param_set(ctx, pid)
    params = [{"name": x.get("name"), "type": x.get("type") or x.get("kind") or x.get("source"), "unit": x.get("unit"),
               "nominal": x.get("nominal"), "min": x.get("min"), "max": x.get("max"), "integer": x.get("integer")}
              for x in p.get("parameters") or []]
    resp = [{"name": r.get("name"), "unit": r.get("unit")} for r in p.get("responses") or []]
    native = p.get("native") or {}
    facts = facts_of(p, ("label", "engine", "input_kind", "unit_system", "sample_count", "is_current", "origin", "train_doe_id",
                         "registered_by_name", "registered_at"), kind=native.get("kind") if isinstance(native, dict) else None,
                     prep_status=native.get("status") if isinstance(native, dict) else None,
                     baseline_count=len(p.get("baselines") or []), parameter_count=len(params), response_count=len(resp),
                     vars_scope=p.get("vars_scope"),  # altair-vars.md §6: Altair 세트 tpl 범위(full | partial), Native는 없음
                     vars_revision=p.get("vars_revision"),  # native-vars.md §6.6: 변수 정의 리비전(0 = 등록 정의) — Altair·Native 공통 최상위 키
                     vars_count=p.get("vars_count"),
                     input_capability=",".join(p.get("input_capability") or []) or None,  # input-kind.md §6.3: 이 템플릿이 받는 입력 종류(assembly·cushion)
                     input_capability_reason=p.get("input_capability_reason"))
    tabs = [table("parameters", params, top_n), table("responses", resp, top_n)]
    links = [{"entity": "study", "id": p["study_id"], "rel": "study"}]
    return envelope("param_set", pid, p.get("label") or pid, None, facts, tabs, links)


def _train_doe(ctx: Any, principal: Any, did: str, top_n: int) -> dict[str, Any]:
    d = _svc("stage1_train_data").get_doe(ctx, did)
    facts = facts_of(d, ("doe_label", "doe_type", "generator", "engine", "status", "sample_status", "run_count", "multi_execution",
                         "collected_count", "solve_failed_count", "has_run_responses", "created_by_name", "created_at"),
                     **{f"runs_{k}": v for k, v in (d.get("run_state_counts") or {}).items() if isinstance(v, int)})
    tabs: list[dict[str, Any]] = []
    try:
        rt = _svc("doe_result_table").result_table(ctx, did)
        units = {x["name"]: x.get("unit") for x in [*rt.get("parameters", []), *rt.get("responses", [])] if x.get("unit")}
        tabs.append(table("results", rt.get("rows") or [], top_n, expand=("params", "responses"), units=units))
    except DomainError:
        pass
    links = [{"entity": "study", "id": d["study_id"], "rel": "study"}]
    return envelope("train_doe", did, d.get("doe_label") or did, d.get("status"), facts, tabs, links)


def _predict_run(ctx: Any, principal: Any, jid: str, top_n: int) -> dict[str, Any]:
    r = _svc("predict_runs").get_run(ctx, principal, jid)
    tpl = r.get("template") or {}
    mdl = r.get("model") or {}
    facts = facts_of(r, ("state", "origin", "input_mode", "input", "attempts", "duration_s", "created_by_name", "created_at", "finished_at"),
                     template=tpl.get("label") if isinstance(tpl, dict) else None, model=mdl.get("name") if isinstance(mdl, dict) else None)
    vals = [{"name": k, "value": v} for k, v in (r.get("values") or {}).items()] if isinstance(r.get("values"), dict) else []
    rows = r.get("response_table") or []
    units = {x["name"]: x["unit"] for x in rows if x.get("name") and x.get("unit")}
    resp = [{"name": f"{x.get('name')}[{units[x['name']]}]" if x.get("name") in units else x.get("name"),
             "predicted": x.get("predicted"), "nearest_measured": x.get("nearest_measured"), "diff_pct": x.get("diff_pct")} for x in rows]
    tabs = [t for t in (table("inputs", vals, top_n) if vals else None, table("responses", resp, top_n)) if t]
    return envelope("predict_run", jid, f"예측 {jid[:8]}", r.get("state"), facts, tabs)


def _predict_batch(ctx: Any, principal: Any, bid: str, top_n: int) -> dict[str, Any]:
    b = _svc("predict_batches").get_batch(ctx, principal, bid)
    gen, pred = b.get("gen") or {}, b.get("predict") or {}
    facts = facts_of(b, ("label", "status", "input", "input_kind", "source_kind", "multi_execution", "created_by_name", "created_at", "finished_at"),
                     **{f"gen_{k}": v for k, v in gen.items()}, **{f"predict_{k}": v for k, v in pred.items()},
                     out_of_range_runs=sum(1 for r in b.get("rows") or [] if r.get("out_of_range")))
    rows = [{"run_key": r.get("run_key"), "state": r.get("state"), "values": r.get("values"), "responses": r.get("responses") or {}}
            for r in b.get("rows") or []]
    links = [{"entity": "param_set", "id": str((b.get("param_set") or {}).get("id")), "rel": "param_set"}]
    return envelope("predict_batch", bid, b.get("label") or bid, b.get("status"), facts,
                    [table("runs", rows, top_n, expand=("values", "responses"))], links)


def _surrogate_opt(ctx: Any, principal: Any, oid: str, top_n: int) -> dict[str, Any]:
    o = _svc("surrogate_opts").get_opt(ctx, principal, oid)
    best = o.get("best") or {}
    facts = facts_of(o, ("label", "status", "input", "mode", "iter_no", "progress_text", "stop_reason", "created_by_name", "created_at",
                         "finished_at"), algorithm=(o.get("settings") or {}).get("algorithm"),
                     verification=(o.get("settings") or {}).get("verification"), evaluated=len(o.get("runs") or []),
                     best_objective=best.get("objective"), best_feasible=best.get("feasible"),
                     best_run_key=best.get("run_key"), objectives=", ".join(str(x.get("metric")) for x in o.get("objectives") or []))
    tabs = [table("iterations", o.get("iterations") or [], top_n,
                  columns=["iter_no", "kind", "best_value", "best_feasible", "improvement_rel", "hv", "front_size"])]
    pareto = o.get("pareto") or {}
    if pareto.get("front"):
        tabs.append(table("pareto_top", pareto["front"], top_n, expand=("values", "objectives")))
    if best:
        tabs.append(table("best", [best], 1, expand=("values", "objectives", "constraints")))
    links = [{"entity": "predict_batch", "id": str(it["batch"]["id"]), "rel": "verification"}
             for it in o.get("iterations") or [] if isinstance(it.get("batch"), dict) and it["batch"].get("id")][:20]
    return envelope("surrogate_opt", oid, o.get("label") or oid, o.get("status"), facts, tabs, links)


def _equiv_check(ctx: Any, principal: Any, eid: str, top_n: int) -> dict[str, Any]:
    e = _svc("equiv_check").detail(ctx, principal, eid)
    rec = e.get("recipe") or {}
    facts = facts_of(e, ("label", "status", "verdict", "verdict_text", "summary_line", "created_by_name", "created_at", "finished_at"),
                     recipe=rec.get("name"), recipe_version=rec.get("version"), pairs=len(e.get("pairs") or []))
    tabs = [table("metrics", e.get("metrics") or [], top_n)]
    if e.get("rows"):
        tabs.append(table("pairs", e["rows"], top_n))
    return envelope("equiv_check", eid, e.get("label") or eid, e.get("status"), facts, tabs)


def _fem_verify(ctx: Any, principal: Any, fid: str, top_n: int) -> dict[str, Any]:
    f = _svc("fem_verify").detail(ctx, principal, fid)
    cmp_ = f.get("compare") or {}
    facts = facts_of(f, ("label", "status", "status_text", "input_mode", "attempt_no", "created_by_name", "created_at", "finished_at"),
                     max_abs_diff_pct=cmp_.get("max_abs_diff_pct"), worst=cmp_.get("worst"),
                     source=(f.get("source") or {}).get("label") if isinstance(f.get("source"), dict) else None)
    return envelope("fem_verify", fid, f.get("label") or fid, f.get("status"), facts,
                    [table("responses", cmp_.get("responses") or [], top_n)])


def _geom_preview(ctx: Any, principal: Any, pid: str, top_n: int) -> dict[str, Any]:
    g = _svc("geom_view_api").get_preview(ctx, pid)
    facts = facts_of(g, ("status", "cache_hit", "fe", "result_status", "code", "category", "message_ko", "fe_status", "fe_code",
                         "param_set_id"), total_s=(g.get("timing") or {}).get("total_s"))
    vals = [{"name": k, "value": v} for k, v in (g.get("values") or {}).items()]
    return envelope("geom_preview", pid, f"형상 미리보기 {pid[:8]}", g.get("status"), facts, [table("values", vals, top_n)],
                    [{"entity": "param_set", "id": g["param_set_id"], "rel": "param_set"}])


def _job(ctx: Any, principal: Any, jid: str, top_n: int) -> dict[str, Any]:
    from .job_kinds import entity_of_job, kind_of_job

    d, _etag = _svc("jobs").get_job(ctx, principal, jid, False)
    facts = facts_of(d, ("job_type", "stage_label", "state", "progress_pct", "progress_label", "current_step_label", "attention_code",
                         "created_by_name", "created_at", "started_at", "finished_at", "failure_code", "failure_message"),
                     kind=kind_of_job(d))
    links = []
    ent = entity_of_job(d) if d.get("params") is not None else None
    if ent and ent[1]:
        links.append({"entity": ent[0], "id": ent[1], "rel": "entity"})
    steps = [{"step_no": s.get("step_no"), "step_key": s.get("step_key"), "state": s.get("state"),
              "progress_pct": s.get("progress_pct"), "failure_code": s.get("failure_code")} for s in d.get("steps") or []]
    return envelope("job", jid, f"{d.get('job_type')} {jid[:8]}", d.get("state"), facts, [table("steps", steps, top_n)], links)


@dataclass(frozen=True)
class SummaryDef:
    summary_fn: Callable[[Any, Any, str, int], dict[str, Any]]
    id_label: str
    label_ko: str


SUMMARIES: dict[str, SummaryDef] = {
    "study": SummaryDef(_study, "study_id", "Study"),
    "param_set": SummaryDef(_param_set, "param_set_id", "파라미터 세트"),
    "train_doe": SummaryDef(_train_doe, "doe_id", "학습 데이터 DOE"),
    "predict_run": SummaryDef(_predict_run, "job_id", "단일 예측"),
    "predict_batch": SummaryDef(_predict_batch, "batch_id", "일괄 예측"),
    "surrogate_opt": SummaryDef(_surrogate_opt, "opt_id", "내장 최적화"),
    "equiv_check": SummaryDef(_equiv_check, "eq_id", "해석 등가성 판정"),
    "fem_verify": SummaryDef(_fem_verify, "fem_verify_id", "조립 FEM 검증"),
    "geom_preview": SummaryDef(_geom_preview, "preview_id", "형상 미리보기"),
    "job": SummaryDef(_job, "job_id", "작업"),
}

# 엔티티 관계(용어집 entities.relations — §10)
RELATIONS: list[dict[str, str]] = [
    {"from": "study", "to": "param_set", "card": "1-N"}, {"from": "study", "to": "train_doe", "card": "1-N"},
    {"from": "study", "to": "predict_batch", "card": "1-N"}, {"from": "study", "to": "surrogate_opt", "card": "1-N"},
    {"from": "study", "to": "equiv_check", "card": "1-N"}, {"from": "study", "to": "model", "card": "1-N"},
    {"from": "param_set", "to": "baseline", "card": "1-N"}, {"from": "param_set", "to": "parameter", "card": "1-N"},
    {"from": "train_doe", "to": "run", "card": "1-N"}, {"from": "run", "to": "response", "card": "N-N"},
    {"from": "perf_def", "to": "response", "card": "1-N"}, {"from": "equiv_check", "to": "recipe", "card": "N-1"},
    {"from": "predict_batch", "to": "predict_run", "card": "1-N"}, {"from": "fem_verify", "to": "predict_run", "card": "N-1"},
]


def summarize(ctx: Any, principal: Any, entity: str, eid: str, top_n: int | None) -> dict[str, Any]:
    d = SUMMARIES.get(entity)
    if d is None:
        raise DomainError("SUMMARY_ENTITY_UNKNOWN", f"알 수 없는 요약 엔티티: {entity}", status=404, entities=sorted(SUMMARIES))
    sc = ctx.settings.mcp.summary
    n = sc.top_n_default if top_n is None else max(1, min(int(top_n), sc.top_n_max))
    return fit(d.summary_fn(ctx, principal, eid, n), sc.max_bytes)
