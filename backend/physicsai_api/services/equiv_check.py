"""⑤ 해석 등가성 판정 API 서비스(equiv-check.md §4·§6): 미리보기(DB 무쓰기)·생성(202, EQ_CHECK 작업)·이력 목록·상세·곡선·표·메모.

생성 = Study 행 FOR UPDATE 안에서 eq_no 채번 → 활성 수 검사 → 이력 행 + EQ_CHECK 작업을 한 트랜잭션으로.
DB에는 레시피 스냅숏·대상·쌍 요약·집계 수치만(쌍별 값·곡선은 판정 폴더 파일 — 상세는 파일을 읽어 돌려준다, LRU·no-store)."""

from __future__ import annotations

import base64
import binascii
import json
import os
import uuid
from datetime import datetime
from typing import Any

from physicsai_core.db.repositories import equiv_check as eq_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.equiv import compute as cmp_mod
from physicsai_core.equiv import pairing as pairing_mod
from physicsai_core.equiv import plan as plan_mod
from physicsai_core.equiv.metrics import VERDICT_TEXT, reason_text
from physicsai_core.equiv.recipes import normalize_definition, tol_text, validate_definition
from physicsai_core.equiv.sides import Side, resolve_side, runs_for_pairing
from physicsai_core.errors import DomainError
from physicsai_core.paths import display_path, resolve_in_study
from physicsai_core.stage4_predict.run_metrics import _Lru
from physicsai_core.state_machine import TERMINAL

from ..auth import Principal
from ..context import AppContext
from . import equiv_recipes as rec_svc
from .common import audit, can_retry, clamp_limit, job_summary, require_config_ok, require_power, study_root
from .job_params.study_manage import study_gate

SYSTEM_RUN_MESSAGE = ("시스템 기본 레시피는 제안값입니다 — 복제(다른 이름으로 저장)해 지표·허용오차·필수/참고를 확인한 "
                      "레시피로 실행하세요")
STATUS_TEXT = {"RUNNING": "실행 중", "DONE": "완료", "FAILED": "실패", "CANCELED": "취소"}
_CACHE = _Lru(128)
MAX_CURVE_POINTS = 5000


# ---- 계획(미리보기·생성 공용) ------------------------------------------------------------------------


def _recipe_for(ctx: AppContext, conn: Any, body: Any) -> dict[str, Any]:
    """요청의 recipe | recipe_inline → {definition, source, key, version, modified}."""
    if (body.recipe is None) == (body.recipe_inline is None):
        raise DomainError("EQ_CHECK_INVALID", "레시피를 선택하세요(recipe 또는 recipe_inline 중 하나)", status=422,
                          problems=[{"code": "RECIPE_REQUIRED", "message": "판정에는 사용자가 선택·확인한 레시피가 필요합니다"}])
    if body.recipe is not None:
        defn, source, key, version = rec_svc.load_for_check(ctx, conn, body.recipe)
        return {"definition": defn, "source": source, "key": key, "version": version, "modified": False,
                "name": _recipe_name(ctx, conn, source, key, version)}
    probs = validate_definition(body.recipe_inline.definition, max_metrics=ctx.settings.equiv_check.max_metrics)
    if probs:
        raise DomainError("EQ_RECIPE_INVALID", "레시피 정의가 올바르지 않습니다", status=422, problems=probs)
    defn = normalize_definition(body.recipe_inline.definition)
    base = body.recipe_inline.base
    key, version = (base.key, base.version) if base else (None, None)
    source = "adhoc"
    if base is not None:
        try:
            _bd, bsrc, key, version = rec_svc.load_for_check(ctx, conn, base)
            source = bsrc
        except DomainError:
            key, version = None, None
    return {"definition": defn, "source": source, "key": key, "version": version, "modified": True,
            "name": _recipe_name(ctx, conn, source, key, version)}


def _recipe_name(ctx: AppContext, conn: Any, source: str, key: str | None, version: int | None) -> str | None:
    if source == "system":
        return rec_svc.SYSTEM_RECIPE_NAME
    row = eq_repo.get_version(conn, key, version) if key else None
    return row["name"] if row else None


def plan(ctx: AppContext, conn: Any, study: dict[str, Any], body: Any) -> dict[str, Any]:
    s = ctx.settings
    root = study_root(ctx, study)
    a = resolve_side(conn, s, study, root, body.side_a.model_dump())
    b = resolve_side(conn, s, study, root, body.side_b.model_dump())
    problems = [{**p, "side": "a"} for p in a.problems] + [{**p, "side": "b"} for p in b.problems]
    warnings = list(a.warnings) + list(b.warnings)
    rec = _recipe_for(ctx, conn, body)
    if rec["source"] == "system":  # EQ-C1: 시스템 기본은 제안값(읽기 전용) — 복제·확인한 레시피만 실행
        problems.append({"code": "RECIPE_NOT_CONFIRMED", "message": SYSTEM_RUN_MESSAGE})
    bound, probs = plan_mod.bind(rec["definition"], body.bindings)
    problems += probs
    pairs: list[tuple[str, str]] = []
    pr = pairing_mod.PairResult()
    if not a.problems and not b.problems:
        ra, rb = runs_for_pairing(a), runs_for_pairing(b)
        pr = pairing_mod.match(body.pairing.mode, ra, rb, rel_tol=s.equiv_check.param_match_rel_tol,
                               integer_names=list(set(a.integer_names) | set(b.integer_names)),
                               manual=[p.model_dump() for p in body.pairing.pairs] if body.pairing.pairs else None,
                               max_pairs=s.equiv_check.max_pairs)
        # EQ-C1: 양쪽 run이 1개씩이면(fem_verify·단일 폴더 등) 이름이 달라도 by_name이 그 둘을 쌍으로 본다
        if body.pairing.mode == "by_name" and not pr.pairs and len(ra) == 1 and len(rb) == 1:
            pr = pairing_mod.PairResult(pairs=[(ra[0]["name"], rb[0]["name"])])
        problems += pr.problems
        pairs = list(pr.pairs)
    resolved, rw = plan_mod.resolve(bound, a, b) if pairs else ({}, [])
    warnings += rw
    ex = plan_mod.extraction_plan(bound, resolved, a, b, pairs, extract_root=None, max_bytes=s.ui.max_artifact_bytes) if pairs \
        else plan_mod.ExtractPlan()
    if ex.copy_bytes > s.equiv_check.max_extract_copy_bytes:
        problems.append({"code": "EQ_EXTRACT_TOO_LARGE",
                         "message": f"추출용 h3d 사본 합계 {ex.copy_bytes} B가 상한(equiv_check.max_extract_copy_bytes)을 넘습니다 — "
                                    "①-6 run 응답 추출 또는 ④ 성능 다시 추출을 먼저 실행하면 사본 없이 재사용합니다"})
    if ex.count and not ctx_feature(ctx, "equiv_check_extract"):
        warnings.append({"code": "EQ_EXTRACT_UNAVAILABLE", "message": "추출 도구(hw·응답 TCL·T01 곡선)가 없어 추출이 필요한 지표는 NA가 됩니다"})
    return {"a": a, "b": b, "recipe": rec, "definition": bound, "pairs": pairs, "pair_result": pr, "resolved": resolved,
            "extract": ex, "problems": problems, "warnings": warnings}


def ctx_feature(ctx: AppContext, name: str) -> bool:
    from physicsai_core.features import feature_status

    return bool(feature_status(ctx.settings, ctx.hpc.availability().configured).get(name, {}).get("enabled"))


def _side_out(side: Side) -> dict[str, Any]:
    return {**side.ref_dict(), "run_count": len(side.runs), "ok_count": sum(1 for r in side.runs if r.ok),
            "responses": [str(r.get("name")) for r in side.responses if isinstance(r.get("spec"), dict)],
            "runs": [{"name": r.name, "no": r.no, "ok": r.ok, "state": r.state, "has_h3d": r.h3d is not None,
                      "has_t01": r.t01 is not None, "has_curve": r.curve_json is not None, "has_mesh": r.mesh_inc is not None}
                     for r in side.runs[:500]]}


def _metric_rows(pl: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for m in pl["definition"]["metrics"]:
        r = pl["resolved"].get(m["id"]) or {}
        out.append({"id": m["id"], "label": m["label"], "kind": m["kind"], "required": m.get("required", True), "source": m.get("source"),
                    "tol": m.get("tol"), "tol_text": tol_text(m), "bound": m.get("source") is not None or m["kind"] == "mesh_volume",
                    "a": r.get("a"), "b": r.get("b"), "na": r.get("na")})
    return out


def preview(ctx: AppContext, principal: Principal, study_id: str, body: Any) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        study = studies_repo.require(conn, study_id)
        pl = plan(ctx, conn, study, body)
    pr = pl["pair_result"]
    return {"side_a": _side_out(pl["a"]), "side_b": _side_out(pl["b"]),
            "pairing": {"mode": body.pairing.mode, "n_pairs": len(pl["pairs"]), "n_unmatched_a": len(pr.unmatched_a), "n_unmatched_b": len(pr.unmatched_b)},
            "pairs": [{"no": i, "a": x, "b": y} for i, (x, y) in enumerate(pl["pairs"], 1)],
            "unmatched_a": pr.unmatched_a, "unmatched_b": pr.unmatched_b, "metrics": _metric_rows(pl),
            "extract": {"h3d_runs": len(pl["extract"].h3d), "t01_runs": len(pl["extract"].t01), "copy_bytes": pl["extract"].copy_bytes},
            "problems": pl["problems"], "warnings": pl["warnings"], "can_run": not pl["problems"]}


def _snapshot(ctx: AppContext, pl: dict[str, Any]) -> dict[str, Any]:
    snap = dict(pl["definition"])
    snap["resolved"] = pl["resolved"]
    snap["recipe"] = {"source": pl["recipe"]["source"], "key": pl["recipe"]["key"], "version": pl["recipe"]["version"],
                      "modified": pl["recipe"]["modified"], "name": pl["recipe"].get("name")}
    if pl["recipe"]["source"] == "system":
        snap["system_version"] = int(ctx.settings.equiv_check.system_version)
    snap["warnings"] = pl["warnings"]
    raw = json.dumps(snap, ensure_ascii=False).encode("utf-8")
    if len(raw) > ctx.settings.equiv_check.snapshot_max_bytes:
        raise DomainError("EQ_CHECK_INVALID", "레시피 스냅숏이 너무 큽니다", status=422,
                          problems=[{"code": "SNAPSHOT_TOO_LARGE", "message": f"{len(raw)} B > {ctx.settings.equiv_check.snapshot_max_bytes} B"}])
    return snap


def check_retry_reactivate(settings: Any, conn: Any, old: dict[str, Any]) -> None:
    """재시도(services.jobs.retry_locked)로 이력 행이 다시 RUNNING이 될 때 Study당 활성 수 상한 재검사(409 EQ_CHECK_LIMIT)."""
    p = old.get("params") or {}
    row = eq_repo.get_check(conn, p.get("eq_id")) if isinstance(p.get("eq_id"), str) else None
    if row is None or row["status"] == "RUNNING":
        return
    if eq_repo.count_active(conn, row["study_id"]) >= settings.equiv_check.max_active:
        raise DomainError("EQ_CHECK_LIMIT", f"이 Study에서 동시에 실행할 수 있는 판정은 {settings.equiv_check.max_active}개입니다", status=409)


def create(ctx: AppContext, principal: Principal, study_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    s = ctx.settings
    if not s.equiv_check.enabled:
        raise DomainError("FEATURE_NOT_AVAILABLE", "등가성 판정 기능이 꺼져 있습니다(equiv_check.enabled)", status=409)
    with ctx.engine.begin() as conn:
        study = studies_repo.require(conn, study_id, for_update=True)
        require_power(principal, study["project_id"])
        require_config_ok(ctx)
        study_gate(conn, study, "EQ_CHECK")
        pl = plan(ctx, conn, study, body)
        if pl["problems"]:
            raise DomainError("EQ_CHECK_INVALID", "판정을 실행할 수 없습니다", status=422, problems=pl["problems"])
        if eq_repo.count_active(conn, study["id"]) >= s.equiv_check.max_active:
            raise DomainError("EQ_CHECK_LIMIT", f"이 Study에서 동시에 실행할 수 있는 판정은 {s.equiv_check.max_active}개입니다", status=409)
        no = eq_repo.next_eq_no(conn, study["id"])
        pr = pl["pair_result"]
        rec = pl["recipe"]
        row = eq_repo.insert_check(
            conn, id=str(uuid.uuid4()), study_id=study["id"], eq_no=no, recipe_key=rec["key"] if rec["source"] != "system" else None,
            recipe_version=rec["version"] if rec["source"] != "system" else None, recipe_source=rec["source"], modified=rec["modified"],
            recipe_snapshot=_snapshot(ctx, pl), side_a={**pl["a"].ref_dict(), "request": body.side_a.model_dump()},
            side_b={**pl["b"].ref_dict(), "request": body.side_b.model_dump()},
            pairing={"mode": body.pairing.mode, "n_pairs": len(pl["pairs"]), "n_unmatched_a": len(pr.unmatched_a),
                     "n_unmatched_b": len(pr.unmatched_b), "manual": [p.model_dump() for p in body.pairing.pairs] if body.pairing.pairs else None},
            status="RUNNING", note=body.note, dir_rel=f"{s.equiv_check.dir_name}/{eq_repo.label(no)}",
            created_by=principal.user_id, created_by_name=principal.display_name)
        job = eq_repo.enqueue(conn, row)
        audit(conn, principal, "EQ_CHECK_CREATE", "eq_check", row["id"],
              {"eq_no": no, "recipe": rec["key"], "version": rec["version"], "source": rec["source"], "pairs": len(pl["pairs"])}, rid, ip)
        return {"eq_id": row["id"], "eq_no": no, "label": eq_repo.label(no), "job_id": job["id"]}


# ---- 이력·상세 --------------------------------------------------------------------------------------


def _encode_cursor(row: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(f"{row['created_at'].isoformat()}|{row['id']}".encode()).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        at, _, eid = base64.urlsafe_b64decode(cursor.encode() + b"==").decode().partition("|")
        if not eid:
            raise ValueError(at)
        return datetime.fromisoformat(at), eid
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise DomainError("INVALID_PARAMS", "cursor 형식이 올바르지 않습니다", status=422,
                          errors=[{"loc": ["query", "cursor"], "msg": "invalid"}]) from None


def _summary_line(row: dict[str, Any]) -> str | None:
    sm = row.get("summary") or {}
    v = sm.get("verdict") or {}
    if not v:
        return None
    snap = row.get("recipe_snapshot") or {}
    rec = snap.get("recipe") or {}
    name = rec.get("name") or ("시스템 기본" if row["recipe_source"] == "system" else "레시피")
    ver = f" v{row['recipe_version']}" if row.get("recipe_version") else (f" v{snap.get('system_version')}" if row["recipe_source"] == "system" else "")
    return (f"필수 {v.get('required_pass', 0)}/{v.get('required_total', 0)} · 참고 미달 {v.get('reference_fail', 0)} · 쌍 {sm.get('n_pairs', 0)}"
            f" · {name}{ver}{'(수정됨)' if row.get('modified') else ''}")


def _recipe_ref(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    out = {"source": row["recipe_source"], "key": row.get("recipe_key"), "version": row.get("recipe_version"), "modified": bool(row.get("modified")),
           "name": None, "deleted": False, "current_version": None}
    if row["recipe_source"] == "system":
        out["name"] = rec_svc.SYSTEM_RECIPE_NAME
        out["version"] = (row.get("recipe_snapshot") or {}).get("system_version")
    elif row.get("recipe_key"):
        cur = eq_repo.get_version(conn, row["recipe_key"], None)
        if cur is not None:
            out["name"], out["deleted"], out["current_version"] = cur["name"], cur.get("deleted_at") is not None, int(cur["version"])
    return out


def _item(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "label": eq_repo.label(row["eq_no"]), "eq_no": int(row["eq_no"]), "status": row["status"],
            "status_text": STATUS_TEXT.get(row["status"], row["status"]), "verdict": row.get("verdict"),
            "verdict_text": VERDICT_TEXT.get(row.get("verdict") or "", None), "side_a": row["side_a"], "side_b": row["side_b"],
            "pairing": {k: v for k, v in (row.get("pairing") or {}).items() if k != "manual"}, "recipe": _recipe_ref(conn, row),
            "summary_line": _summary_line(row), "note": row.get("note"), "created_at": row["created_at"], "created_by": row["created_by"],
            "created_by_name": row["created_by_name"], "finished_at": row.get("finished_at"), "job_id": row.get("job_id")}


def list_(ctx: AppContext, principal: Principal, study_id: str, *, side_kind: str | None, side_ref: str | None, verdict: str | None,
          recipe_key: str | None, limit: int | None, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    after = _decode_cursor(cursor)
    lim = clamp_limit(limit)
    with ctx.engine.connect() as conn:
        studies_repo.require(conn, study_id)
        rows = eq_repo.list_for_study(conn, study_id, side_kind=side_kind, side_ref=side_ref, verdict=verdict, recipe_key=recipe_key,
                                      limit=lim + 1, after=after)
        items = [_item(conn, r) for r in rows[:lim]]
    return items, (_encode_cursor(rows[lim - 1]) if len(rows) > lim else None)


def _require(conn: Any, eid: str, *, for_update: bool = False) -> dict[str, Any]:
    row = eq_repo.get_check(conn, eid, for_update=for_update)
    if row is None:
        raise DomainError("EQ_CHECK_NOT_FOUND", "판정 이력을 찾을 수 없습니다", status=404)
    return row


def _read_json(path: str, max_bytes: int) -> Any:
    try:
        st = os.stat(path)
        if st.st_size > max_bytes:
            return None
        key = ("eq_json", path, st.st_mtime_ns, st.st_size)
    except OSError:
        return None

    def load() -> Any:
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh)
    try:
        return _CACHE.get_or_load(key, load)
    except (OSError, ValueError):
        return None


def _read_rows(path: str, max_bytes: int) -> list[dict[str, Any]]:
    try:
        st = os.stat(path)
        if st.st_size > max_bytes:
            return []
        key = ("eq_csv", path, st.st_mtime_ns, st.st_size)
    except OSError:
        return []

    def load() -> list[dict[str, Any]]:
        with open(path, encoding="utf-8-sig") as fh:
            return cmp_mod.parse_csv_text(fh.read())
    try:
        return _CACHE.get_or_load(key, load)
    except (OSError, ValueError):
        return []


def _eq_dir(ctx: AppContext, study: dict[str, Any], row: dict[str, Any]) -> str:
    return resolve_in_study(study_root(ctx, study), row["dir_rel"])


def detail(ctx: AppContext, principal: Principal, eid: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        row = _require(conn, eid)
        study = studies_repo.require(conn, row["study_id"])
        out = _item(conn, row)
        job = jobs_repo.get_job(conn, row["job_id"]) if row.get("job_id") else None
        out["job"] = job_summary(job, study["title"], None) if job else None
        out["can_retry"] = bool(job) and can_retry(job, principal)
        out["can_cancel"] = bool(job) and job["state"] not in TERMINAL and principal.is_global_admin  # 취소는 기존 /jobs 규칙
        warnings = list((job or {}).get("warnings") or [])
    snap = row["recipe_snapshot"]
    E = _eq_dir(ctx, study, row)
    mb = ctx.settings.ui.max_artifact_bytes
    rows = _read_rows(os.path.join(E, "metrics.csv"), mb) if row["status"] == "DONE" else []
    pairs_doc = _read_json(os.path.join(E, "pairs.json"), mb) or {}
    sm = row.get("summary") or {}
    aggs = sm.get("metrics") or {}
    metrics = []
    for m in snap.get("metrics", []):
        ag = dict(aggs.get(m["id"]) or {})
        res = (snap.get("resolved") or {}).get(m["id"]) or {}
        metrics.append({"id": m["id"], "label": m["label"], "kind": m["kind"], "required": m.get("required", True), "tol": m.get("tol"),
                        "tol_text": tol_text(m), "source": m.get("source"), "a_def": res.get("a"), "b_def": res.get("b"), **ag,
                        "status": ag.get("status", "NA")})
    for r in rows:
        r["reason_text"] = reason_text(r.get("reason"))
    out.update({"recipe_snapshot": snap, "summary": row.get("summary"), "metrics": metrics, "rows": rows,
                "pairs": pairs_doc.get("pairs") or [], "unmatched_a": pairs_doc.get("unmatched_a") or [], "unmatched_b": pairs_doc.get("unmatched_b") or [],
                "warnings": [{"code": w.get("code", ""), "message": w.get("message", "")} for w in warnings + list(snap.get("warnings") or [])],
                "failure": ({"code": row["failure_code"], "message": row.get("failure_message") or ""} if row.get("failure_code") else None),
                "dir": display_path(ctx.settings.storage.ai_root, study["folder_name"], row["dir_rel"]),
                "can_edit_note": principal.is_global_admin or row["created_by"] == principal.user_id})
    return out


def curves(ctx: AppContext, principal: Principal, eid: str, pair: int, metric: str, max_points: int) -> dict[str, Any]:
    from .predict_batches_curves import downsample

    with ctx.engine.connect() as conn:
        row = _require(conn, eid)
        study = studies_repo.require(conn, row["study_id"])
    if not metric.replace("_", "").isalnum() or pair < 1:
        raise DomainError("EQ_CHECK_NOT_FOUND", "곡선을 찾을 수 없습니다", status=404)
    p = os.path.join(_eq_dir(ctx, study, row), "curves", str(pair), f"{metric}.json")
    data = _read_json(p, ctx.settings.ui.max_artifact_bytes)
    if not isinstance(data, dict):
        raise DomainError("EQ_CHECK_NOT_FOUND", "곡선을 찾을 수 없습니다(곡선 지표가 아니거나 계산되지 않음)", status=404)
    mp = max(2, min(int(max_points), MAX_CURVE_POINTS))
    t, a, da = downsample(list(data["t"]), list(data["a"]), mp)
    _t, b, db = downsample(list(data["t"]), list(data["b"]), mp)
    if len(b) != len(t):  # 두 계열을 같은 격자로 — 보수적으로 균일 간격 추출
        step = max(1, len(data["t"]) // mp)
        t, a, b = data["t"][::step], data["a"][::step], data["b"][::step]
        da = True
    return {"pair_no": data["pair_no"], "metric_id": data["metric_id"], "a_run": data["a_run"], "b_run": data["b_run"], "t": t, "a": a, "b": b,
            "corr": data.get("corr"), "nrmse_pct": data.get("nrmse_pct"), "overlap_ratio": data.get("overlap_ratio"), "downsampled": da or db}


def table_csv(ctx: AppContext, principal: Principal, eid: str) -> tuple[bytes, str]:
    with ctx.engine.connect() as conn:
        row = _require(conn, eid)
        study = studies_repo.require(conn, row["study_id"])
    p = os.path.join(_eq_dir(ctx, study, row), "metrics.csv")
    try:
        with open(p, encoding="utf-8-sig") as fh:
            text = fh.read()
    except OSError:
        text = ",".join(cmp_mod.CSV_HEADER) + "\n"
    return ("﻿" + text).encode("utf-8"), f"{eq_repo.label(row['eq_no'])}_metrics.csv"


def patch_note(ctx: AppContext, principal: Principal, eid: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        row = _require(conn, eid, for_update=True)
        if not (principal.is_global_admin or row["created_by"] == principal.user_id):
            raise DomainError("PERMISSION_DENIED", "작성자 또는 관리자만 메모를 고칠 수 있습니다", status=403, required="owner")
        eq_repo.set_check(conn, eid, note=(body.note or None))
        audit(conn, principal, "EQ_CHECK_NOTE", "eq_check", eid, {"len": len(body.note or "")}, rid, ip)
        return _item(conn, _require(conn, eid))
