"""형상 3D 보기·미리보기 API(geometry-view.md §6.5·§6.9): 공칭 뷰 조회, 미리보기 생성(캐시 200 / 202 GEOM_PREVIEW)·조회.

- 미리보기 캐시 = 서버측 AI 루트 `<study>/_cache/geom_preview/`(플랫폼 임시 산출물, 브라우저 캐시 아님). 키 = 세트·준비본·값·fe·paicad 버전.
- 동시·중복(§6.4): 같은 키 DONE → 즉시(cache_hit) · QUEUED/RUNNING → 그 행 · 같은 사용자·같은 세트 QUEUED는 새 요청이 취소 ·
  사용자별 QUEUED+RUNNING ≥ max_queued_per_user → 429 PREVIEW_BUSY · 보관 Study·정리 중 409.
- paicad 버전은 워커 하트비트(resources.paicad_version)에서 읽는다. 모르면 캐시 조회 없이 항상 새 작업(키에 미리보기 id를 섞음).
"""

from __future__ import annotations

import math
import os
import uuid
from typing import Any

from physicsai_core.db.repositories import artifacts as art_repo
from physicsai_core.db.repositories import geom_view as gv_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import workers as workers_repo
from physicsai_core.errors import DomainError
from physicsai_core.features import geometry_view_missing, geometry_view_shell_missing
from physicsai_core.geometry import baselines as bl
from physicsai_core.geometry.messages import label_of
from physicsai_core.geometry.shell import is_prop_row
from physicsai_core.geometry.shell_native import read_kind
from physicsai_core.geometry.view import (
    PREVIEW_CACHE,
    VIEW_DIR,
    cache_rel,
    prep_digest,
    prep_view,
    preview_cache_key,
    read_json,
)
from physicsai_core.paths import resolve_in_study

from ..auth import Principal
from ..context import AppContext
from .common import audit, require_power, study_root
from .job_params.study_manage import study_gate


def view_available(ctx: AppContext, kind: str) -> bool:
    t, r = (geometry_view_shell_missing if kind == "shell" else geometry_view_missing)(ctx.settings)
    return not t and not r


def _ps_native(conn: Any, ps_id: str) -> dict[str, Any]:
    ps = ps_repo.get(conn, ps_id)
    if ps is None:
        raise DomainError("NOT_FOUND", "파라미터 세트를 찾을 수 없습니다", status=404)
    if (ps.get("engine") or "altair") != "native":
        raise DomainError("VIEW_NATIVE_ONLY", label_of("VIEW_NATIVE_ONLY"), status=409)
    return ps


def _latest_art(conn: Any, study_id: str, kind: str, prefix: str) -> str | None:
    rows = art_repo.list_by_prefix(conn, study_id, kind, prefix)
    return rows[0]["id"] if rows else None


def get_view(ctx: AppContext, ps_id: str) -> dict[str, Any]:
    """`GET /param-sets/{id}/view` → GeomView."""
    with ctx.engine.connect() as conn:
        ps = _ps_native(conn, ps_id)
        st = studies_repo.require(conn, ps["study_id"])
        S = resolve_in_study(study_root(ctx, st), ps["stored_rel"])
        prefix = ps["stored_rel"].rstrip("/") + "/" + VIEW_DIR + "/"
        glb = _latest_art(conn, ps["study_id"], "GEOM_VIEW_GLB", prefix)
        man = _latest_art(conn, ps["study_id"], "GEOM_VIEW_MANIFEST", prefix)
    kind = read_kind(S)
    v = prep_view(S)
    status = v.get("status") or "MISSING"
    if status == "READY" and not (glb and man):
        status = "MISSING"
    avail = view_available(ctx, kind)
    from .param_set_native_api import prep_state_of

    pst = prep_state_of(ctx, ps)
    return {"param_set_id": ps_id, "train_setup_id": None, "kind": kind, "status": status,
            "reason": None if status == "READY" else _view_reason(v, status), "glb_artifact_id": glb if status == "READY" else None,
            "manifest_artifact_id": man if status == "READY" else None, "tess": v.get("tess"), "engine_version": v.get("engine_version"),
            "available": avail, "preview_available": avail and pst is not None and pst.status == "READY"}


def _view_reason(v: dict[str, Any], status: str) -> str:
    if status == "FAILED":
        return f"3D 보기를 만들지 못했습니다({v.get('reason') or '사유 모름'}) — 그림으로 표시합니다"
    return "공칭 3D 보기가 없습니다 — 형상 준비를 다시 하거나 [3D 보기 만들기](공칭 미리보기)를 쓰세요"


def train_view(ctx: AppContext, study_id: str) -> dict[str, Any]:
    """`GET /studies/{id}/train/view`(§6.9): ①-1 TX_VIEW 결과. 미리보기 없음(preview_available=false)."""
    from physicsai_core.db.repositories import train as train_repo
    from physicsai_core.geometry.shell_native import kind_of_features_rel
    from physicsai_core.geometry.view import view_result

    with ctx.engine.connect() as conn:
        st = studies_repo.require(conn, study_id)
        setup = train_repo.get_setup(conn, study_id)
        rel = (setup or {}).get("features_rel")
        if not setup or setup.get("engine") != "native" or not rel:
            raise DomainError("NOT_FOUND", "① Native 학습 설정이 없습니다 — 파라미터 추출을 Native로 먼저 하세요", status=404)
        prefix = os.path.dirname(rel).rstrip("/") + "/view/"
        glb = _latest_art(conn, study_id, "GEOM_VIEW_GLB", prefix)
        man = _latest_art(conn, study_id, "GEOM_VIEW_MANIFEST", prefix)
    kind = kind_of_features_rel(rel)
    vdir = os.path.join(os.path.dirname(resolve_in_study(study_root(ctx, st), rel)), "view")
    v = view_result(vdir, None) if os.path.isdir(vdir) else None
    m = read_json(os.path.join(vdir, "view_manifest.json")) if os.path.isdir(vdir) else None
    status = "READY" if v and glb and man else ("FAILED" if m is not None else "MISSING")
    return {"param_set_id": None, "train_setup_id": setup.get("id") if setup else None, "kind": kind, "status": status,
            "reason": None if status == "READY" else _view_reason({"reason": (m or {}).get("code")}, status),
            "glb_artifact_id": glb if status == "READY" else None, "manifest_artifact_id": man if status == "READY" else None,
            "tess": (v or {}).get("tess"), "engine_version": (v or {}).get("engine_version"),
            "available": view_available(ctx, kind), "preview_available": False}


# ---- 미리보기 -----------------------------------------------------------------------------------------------------


def preview_out(row: dict[str, Any], cache_hit: bool = False) -> dict[str, Any]:
    code = row.get("code") or row.get("fe_code")
    return {"id": row["id"], "param_set_id": row["param_set_id"], "job_id": row.get("job_id"), "status": row["status"],
            "cache_hit": cache_hit, "values": row.get("values") or {}, "fe": row.get("fe") or "off",
            "result_status": row.get("result_status"), "code": row.get("code"), "category": row.get("category"),
            "message_ko": label_of(code) if code else None, "fe_status": row.get("fe_status"), "fe_code": row.get("fe_code"),
            "glb_artifact_id": row.get("glb_artifact_id"), "fe_glb_artifact_id": row.get("fe_glb_artifact_id"),
            "manifest_artifact_id": row.get("manifest_artifact_id"), "timing": row.get("timing"),
            "created_at": row.get("created_at"), "finished_at": row.get("finished_at")}


def _engine_version(conn: Any) -> str | None:
    hb = workers_repo.latest(conn)
    v = ((hb or {}).get("resources") or {}).get("paicad_version")
    return v if isinstance(v, str) and v else None


def _values(ctx: AppContext, ps: dict[str, Any], S: str, given: dict[str, float]) -> dict[str, float]:
    """형상 대표 행 이름 집합으로 검사(모르는 이름·비유한 값 422) → 빠진 값 공칭. 3S 두께 행은 3D 대응 없음이라 뺀다.
    확정 다중 baseline 세트는 공통 이름 → 기본 baseline 원 이름(§1.3: 기본 baseline만 표시)."""
    geo = [r for r in ps["parameters"] if not is_prop_row(r)]
    props = {str(r["name"]) for r in ps["parameters"] if is_prop_row(r)}
    names = {str(r["name"]) for r in geo}
    errs = []
    for k, v in given.items():
        if k not in names and k not in props:
            errs.append({"loc": ["values", k], "msg": "세트에 없는 파라미터 이름입니다"})
        elif not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(float(v)):
            errs.append({"loc": ["values", k], "msg": "유한한 숫자여야 합니다"})
    if errs:
        raise DomainError("INPUT_INVALID", "미리보기 값이 올바르지 않습니다", status=422, errors=errs)
    full = {str(r["name"]): float(given.get(str(r["name"]), r["nominal"])) for r in geo}
    try:
        pm = bl.load(S, ctx.settings.geometry.max_report_bytes)
    except bl.MapError:
        pm = None
    if pm is not None and pm.get("status") == "confirmed":
        full = bl.original_values(ps["parameters"], bl.baseline_ids(pm)[0], full)
    return full


def create_preview(ctx: AppContext, principal: Principal, ps_id: str, body: Any, rid: str, ip: str | None) -> tuple[dict[str, Any], int]:
    """`POST /param-sets/{id}/previews` → (GeomPreview, 200|202)."""
    from .geometry_gate import require_native_available, require_shell_available
    from .param_set_native_api import kind_options, prep_state_of

    s = ctx.settings
    with ctx.engine.connect() as conn:
        ps = _ps_native(conn, ps_id)
        st0 = studies_repo.require(conn, ps["study_id"])
    require_power(principal, st0["project_id"])
    S = resolve_in_study(study_root(ctx, st0), ps["stored_rel"])
    kind = read_kind(S)
    require_native_available(s)
    if kind == "shell":
        require_shell_available(s)
    if not view_available(ctx, kind):
        missing = (geometry_view_shell_missing if kind == "shell" else geometry_view_missing)(s)
        raise DomainError("VIEW_UNAVAILABLE", label_of("VIEW_UNAVAILABLE"), status=409, missing=missing[0] + missing[1])
    pst = prep_state_of(ctx, ps)
    if pst is None or pst.status != "READY":
        raise DomainError("GEOM_PREP_STALE", (pst.reason if pst else None) or "형상 준비본이 유효하지 않습니다 — 형상 준비를 다시 하세요",
                          status=409, prep_status=pst.status if pst else "MISSING", param_set_id=ps_id)
    values = _values(ctx, ps, S, dict(body.values or {}))
    opts = kind_options(ctx, S, ps.get("geom_options"))
    prep = read_json(os.path.join(S, "native", "prep.json"))
    nom = read_json(os.path.join(S, *VIEW_DIR.split("/"), "view_manifest.json"))
    tess = (nom or {}).get("tess") if (nom or {}).get("status") == "OK" else None
    vt = tess if isinstance(tess, dict) else {"linear_mm": s.geometry.view.tess.linear_mm, "angular_deg": s.geometry.view.tess.angular_deg}
    pid = str(uuid.uuid4())
    with ctx.engine.begin() as conn:
        study = studies_repo.require(conn, ps["study_id"], for_update=True)  # 같은 Study 생성 직렬화(D3-25)
        study_gate(conn, study, "GEOM_PREVIEW")  # 보관·정리 중 409(R3-4)
        ver = _engine_version(conn)
        key = preview_cache_key(param_set_id=ps_id, kind=kind, prep_digest=prep_digest(prep, opts), view_tess=vt, values=values,
                                fe=body.fe, engine_version=ver or f"unknown:{pid}")
        if ver is not None:
            row = gv_repo.live_by_key(conn, gv_repo.PREVIEWS, key, for_update=True)
            if row is not None and row["status"] == "DONE" and _files_present(ctx, study, key):
                gv_repo.touch(conn, gv_repo.PREVIEWS, row["id"])
                return preview_out(row, cache_hit=True), 200
            if row is not None and row["status"] in ("QUEUED", "RUNNING"):
                return preview_out(row), 202
            if row is not None:  # DONE인데 캐시 파일이 사라짐 → 만료로 두고 새로
                gv_repo.set_values(conn, gv_repo.PREVIEWS, row["id"], status="EXPIRED")
        for old in gv_repo.queued_previews(conn, principal.user_id, ps_id):  # §6.4-3 최신 값 우선
            if old.get("job_id"):
                j = jobs_repo.get_job(conn, old["job_id"])
                if j is not None and j["state"] == "QUEUED":
                    jobs_repo.request_cancel(conn, old["job_id"], principal.user_id)
        if gv_repo.active_count(conn, gv_repo.PREVIEWS, principal.user_id) >= s.geometry.view.max_queued_per_user:
            raise DomainError("PREVIEW_BUSY", label_of("PREVIEW_BUSY"), status=429, limit=s.geometry.view.max_queued_per_user)
        params = {"param_set_id": ps_id, "preview_id": pid, "values": values, "fe": body.fe, "cache_key": key, "engine_version": ver}
        job = jobs_repo.insert_job(conn, study=study, job_type="GEOM_PREVIEW", params=params, user_id=principal.user_id,
                                   user_name=principal.display_name)
        row = gv_repo.insert(conn, gv_repo.PREVIEWS, {"id": pid, "study_id": study["id"], "param_set_id": ps_id, "cache_key": key,
                                                    "job_id": job["id"], "created_by": principal.user_id, "status": "QUEUED", "fe": body.fe,
                                                    "values": values, "engine_version": ver})
        audit(conn, principal, "GEOM_PREVIEW_CREATE", "param_set", ps_id, {"preview_id": pid, "job_id": job["id"], "fe": body.fe}, rid, ip)
    return preview_out(row), 202


def _files_present(ctx: AppContext, study: dict[str, Any], key: str) -> bool:
    d = os.path.join(study_root(ctx, study), *cache_rel(PREVIEW_CACHE, key).split("/"), "out")
    return os.path.isfile(os.path.join(d, "preview_manifest.json"))


def get_preview(ctx: AppContext, preview_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        row = gv_repo.get(conn, gv_repo.PREVIEWS, preview_id)
    if row is None:
        raise DomainError("NOT_FOUND", "미리보기를 찾을 수 없습니다", status=404)
    return preview_out(row)
