"""④ 일괄 예측 서비스 공용: 상수·표본 정보 요약·배치 확인·재시도 대상·상세 응답·단건 조회 — predict_batches에서 재노출."""

from __future__ import annotations

import math
from typing import Any

from physicsai_core.db.repositories import contour_media as media_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import surrogate_opts as so_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import DomainError
from physicsai_core.geometry import native_vars as nv
from physicsai_core.geometry.messages import MAX_MESSAGE, category_of
from physicsai_core.paths import display_path
from physicsai_core.sampling import designs as sampling_designs
from physicsai_core.sampling import registry as sampling_registry
from physicsai_core.stage4_predict import input_kind as ik
from physicsai_core.stage4_predict.batch_matrix import batch_label
from physicsai_core.state_machine import TERMINAL

from ..auth import Principal
from ..context import AppContext

ESTIMATE_SAMPLES = 5  # 예상 소요 = 최근 성공 PREDICT 5개 소요 중앙값 × N
MAX_CURVE_POINTS = 2000
ACTIVE_BATCH = ("GENERATING", "PREDICTING")
RETRY_CHILD_STATES = ("FAILED", "CANCELED", "INTERRUPTED")


# ---- 공용 --------------------------------------------------------------------------------------


def _active_unit_points(meta: dict[str, Any], rows: list[dict[str, Any]]) -> list[list[float]]:
    """meta.ranges의 활성 변수(lo < hi) 단위 좌표 — 기존 `lhs`의 quality를 meta에 저장하지 않고 계산한다(V3-S9-5 골든 보존)."""
    ranges = meta.get("ranges") if isinstance(meta.get("ranges"), dict) else {}
    act = [(n, r[0], r[1]) for n, r in ranges.items()
           if isinstance(r, list) and len(r) == 2 and all(isinstance(v, (int, float)) for v in r) and r[0] < r[1]]
    pts = []
    for row in rows:
        vals = row.get("values") or {}
        if any(not isinstance(vals.get(n), (int, float)) for n, _lo, _hi in act):
            return []
        pts.append([(float(vals[n]) - lo) / (hi - lo) for n, lo, hi in act])
    return pts if act and len(pts) >= 2 else []


def _sampling_info(conn: Any, source_kind: str, meta: dict[str, Any] | None, owned_kind: str | None,
                   rows: list[dict[str, Any]], recommended: int | None) -> dict[str, Any] | None:
    """배치·미리보기 `sampling`(S15 §20.6): 방식·라벨·desc_id·등급(§20.7)·meta. 알 수 없는 source_kind면 None."""
    kind = sampling_registry.kind_of_source(source_kind)
    if kind is None:
        return None
    meta = {k: v for k, v in (meta or {}).items() if k != "vars"}  # native-vars.md §4.2: 변수 스냅숏은 `vars`로 따로 내보낸다
    doe_type = doe_opts = None
    if source_kind == "TRAIN_DOE":
        d = train_repo.get_doe(conn, str(meta.get("doe_id") or ""))
        if d is not None:
            doe_type, doe_opts = d["doe_type"], d.get("options") if isinstance(d.get("options"), dict) else {}
    cls, note = sampling_registry.batch_influence(source_kind, meta, owned_kind, doe_type, doe_opts)
    if source_kind == "LHS" and "quality" not in meta:
        pts = _active_unit_points(meta, rows)
        if pts:
            meta["quality"] = sampling_designs.quality(pts)
    _method, label, desc_id = sampling_registry.method_info(kind)
    return {"kind": kind, "method": source_kind, "desc_id": desc_id, "label": label, "influence_class": cls,
            "influence_note": note, "recommended_count": recommended, "meta": meta}


def _sampling_summary(b: dict[str, Any]) -> dict[str, Any] | None:
    kind = sampling_registry.kind_of_source(b["source_kind"])
    if kind is None:
        return None
    meta = b.get("source_meta") or {}
    seed, offset = meta.get("seed"), meta.get("offset")
    return {"kind": kind, "method": b["source_kind"], "label": sampling_registry.method_info(kind)[1], "count": b["run_count"],
            "seed": seed if isinstance(seed, int) and not isinstance(seed, bool) else None,
            "offset": offset if isinstance(offset, int) and not isinstance(offset, bool) else None}


def _require_batch(conn: Any, batch_id: str, *, for_update: bool = False) -> dict[str, Any]:
    b = pb_repo.get(conn, batch_id, for_update=for_update)
    if b is None:
        raise DomainError("BATCH_NOT_FOUND", "일괄 예측을 찾을 수 없습니다", status=404)
    return b


def _require_not_opt_owned(conn: Any, batch_id: str) -> None:
    """내장 최적화 소유 배치(phase3 §18.6)의 배치 단위 취소·실패만 다시 → 409 BATCH_OWNED_BY_OPT(⑤에서 조작)."""
    it = so_repo.owned_iter_of_batch(conn, batch_id)
    if it is not None:
        label = so_repo.opt_label(it["opt_no"])
        raise DomainError("BATCH_OWNED_BY_OPT", f"내장 최적화 {label}의 배치입니다 — ⑤에서 취소·이어서 실행하세요", status=409,
                          surrogate_opt_id=it["opt_id"])


def _can_cancel(b: dict[str, Any], principal: Principal, project_id: str) -> bool:
    return (b["status"] in ACTIVE_BATCH and principal.can_execute(project_id)
            and (principal.is_global_admin or b["created_by"] == principal.user_id))


def _retry_targets(rows: list[dict[str, Any]]) -> tuple[bool, list[dict[str, Any]]]:
    """(생성 다시 필요, 다시 실행할 하위 run 행)."""
    regen = any(r["gen_state"] != "DONE" for r in rows)
    kids = [r for r in rows if r["gen_state"] == "DONE" and r["predict_job_id"] and r["job_state"] in RETRY_CHILD_STATES]
    return regen, kids


def _detail(ctx: AppContext, conn: Any, b: dict[str, Any], principal: Principal) -> dict[str, Any]:
    s = studies_repo.require(conn, b["study_id"])
    ps = ps_repo.get(conn, b["param_set_id"]) or {}
    m = models_repo.get(conn, b["model_id"]) or {}
    parent = jobs_repo.get_job(conn, b["job_id"])
    rows = pb_repo.runs_with_jobs(conn, b["id"])
    media = media_repo.media_views_for_jobs(conn, [r["predict_job_id"] for r in rows])  # phase3 §15 S10
    root = ctx.settings.storage.ai_root
    out_rows = []
    for r in rows:
        st = pb_repo.row_state(r, r["job_state"])
        gen_fail = r["gen_state"] == "FAILED"
        out_rows.append({
            "doe_no": r["doe_no"], "run_key": r["run_key"],
            "folder": display_path(root, s["folder_name"], f"{b['dir_rel']}/{r['run_key']}"),
            "values": r["values"], "applied_values": r["applied_values"], "out_of_range": r["out_of_range"] or [],
            "state": st, "gen_category": category_of(r["gen_code"]) if gen_fail else None,  # §6.5 category(GEOM_*만)
            "code": r["gen_code"] if gen_fail else (r["job_failure_code"] if st in ("FAILED", "CANCELED") else None),
            "message": (r["gen_message"] or "")[:MAX_MESSAGE] if gen_fail else (r["job_failure_message"] if st in ("FAILED", "CANCELED") else None),
            "job_id": r["predict_job_id"], "responses": r["responses"],
            "media_views": media.get(r["predict_job_id"] or "", []),
        })
    regen, kids = _retry_targets(rows)
    owned_it = so_repo.owned_iter_of_batch(conn, b["id"])
    owned = owned_it is not None  # phase3 §18.6: ⑤에서만 취소·이어서 실행
    parent_active = parent is not None and parent["state"] not in TERMINAL
    return {
        "id": b["id"], "label": batch_label(b["batch_no"]), "status": b["status"],
        "dir": display_path(root, s["folder_name"], b["dir_rel"]), "input_kind": b["input_kind"],
        "input": ik.to_public(b["input_kind"]), "warnings": _cushion_warnings(b, ps, rows),
        "source_kind": b["source_kind"],
        "sampling": _sampling_info(conn, b["source_kind"], b.get("source_meta"), owned_it["kind"] if owned_it else None,
                                   rows, None),
        "param_set": {"id": b["param_set_id"], "label": ps.get("label")},
        "model": {"id": b["model_id"], "name": f"{m['name']} v{m['version']}" if m else b["model_id"]},
        "job_id": b["job_id"], "multi_execution": b["multi_execution"], **pb_repo.counts(conn, b["id"]),
        "parameters": [p["name"] for p in nv.apply(ps, nv.vars_of(b.get("source_meta")))["parameters"] or []],  # 스냅숏 우선(native-vars §4.2)
        "vars": nv.vars_of(b.get("source_meta")),
        "responses": [{"name": x["name"], "unit": x.get("unit") or ""} for x in ps.get("responses") or []],
        "rows": out_rows, "created_at": b["created_at"], "created_by_name": b["created_by_name"],
        "finished_at": b["finished_at"], "can_cancel": not owned and _can_cancel(b, principal, s["project_id"]),
        "can_retry_failed": not owned and principal.can_execute(s["project_id"]) and not parent_active and (regen or bool(kids)),
    }


def _cushion_warnings(b: dict[str, Any], ps: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """쿠션 입력 배치에서 성공한 run이 있는데 값이 하나도 없는 응답만 경고(INPUT_CUSHION_RESPONSES, 차단 없음 — 사용자 확정 Q2)."""
    if ik.to_public(b["input_kind"]) != ik.CUSHION:
        return []
    done = [r for r in rows if r["job_state"] == "SUCCEEDED"]
    if not done:
        return []
    names = [str(x["name"]) for x in ps.get("responses") or [] if isinstance(x, dict) and x.get("name")
             and not any(_num((r["responses"] or {}).get(x["name"])) for r in done)]
    w = ik.cushion_missing_warning(names)
    return [w] if w else []


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _response_summary(conn: Any, batch_id: str, ps: dict[str, Any]) -> dict[str, Any] | None:
    """첫 응답의 완료 run 값 최소~최대(실행 목록 1줄). 응답 정의·값이 없으면 None."""
    first = next((r for r in ps.get("responses") or [] if isinstance(r, dict) and r.get("name")), None)
    if first is None:
        return None
    vals = [float(v) for r in pb_repo.runs_with_jobs(conn, batch_id) if r["job_state"] == "SUCCEEDED"
            for v in [(r["responses"] or {}).get(first["name"])]
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)]
    if not vals:
        return None
    return {"name": first["name"], "unit": first.get("unit") or "", "min": min(vals), "max": max(vals), "count": len(vals)}


def get_batch(ctx: AppContext, principal: Principal, batch_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        return _detail(ctx, conn, _require_batch(conn, batch_id), principal)
