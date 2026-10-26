"""DOE 표본 형상 그리드 미리보기 API(doe-preview.md §6.4·§6.6): 생성(캐시 전부 적중 200 / 202 DOE_PREVIEW)·조회·취소.

- 표본 입력 검증은 실제 `TD_DOE_GEN` native와 같은 함수(`native_plan`·`_native_doe_common`·`reuse_samples`)를 쓰고, 표본 행렬 자체는 워커
  DP_MATRIX가 DG_PREP과 같은 함수로 계산한다(API는 lhs_opt 같은 느린 생성을 하지 않는다 — 중복 판정은 `grid_key`).
- 형상 입력 해석(`geometry/doe_preview_src`)은 API·워커 공통이라 같은 digest가 나온다.
- 동시·중복(§6.4): 같은 grid_key QUEUED·RUNNING → 그 행(202) · 셀이 전부 DONE → 작업 없이 200(cache_hit) · 같은 사용자·같은 출처의
  이전 QUEUED는 새 요청이 취소 · 사용자별 QUEUED+RUNNING ≥ max_active_per_user → 429 PREVIEW_BUSY · 보관 Study·정리 중 409.
- 셀 상태는 `doe_preview_cells`(DONE 셀 인덱스) + 작업 result `cell_errors`(ERROR 셀, 캐시 안 함)에서 읽는다. 응답은 청크마다 채워진다.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from physicsai_core.db.repositories import doe_preview as dp_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.db.repositories import workers as workers_repo
from physicsai_core.errors import DomainError
from physicsai_core.features import doe_preview_missing
from physicsai_core.geometry import baselines as bl
from physicsai_core.geometry import doe_preview as dp
from physicsai_core.geometry import doe_preview_src as src_mod
from physicsai_core.geometry.messages import label_of
from physicsai_core.geometry.shell_native import SHELL
from physicsai_core.stage1_train_data import doe_platform

from ..auth import Principal
from ..context import AppContext
from .common import audit, require_power, study_root
from .geometry_gate import native_set_gate, require_native_available, require_shell_available
from .job_params.base import invalid_at
from .job_params.stage1_native import _native_doe_common, _native_params, native_plan, needs_plan
from .job_params.stage1_train_data import TdDoeGenParams, reuse_samples
from .job_params.study_manage import study_gate


def _unsupported(message: str) -> DomainError:
    return DomainError("DOE_PREVIEW_UNSUPPORTED", message, status=409)


def _engine_version(conn: Any) -> str | None:
    hb = workers_repo.latest(conn)
    v = ((hb or {}).get("resources") or {}).get("paicad_version")
    return v if isinstance(v, str) and v else None


def _require_available(ctx: AppContext, shape: str) -> None:
    """`features.doe_preview` 판정 — 쉘이면 `paicad_shell_view_grid`도(409 DOE_PREVIEW_UNAVAILABLE, missing 목록)."""
    tmpl, res = doe_preview_missing(ctx.settings, shape)
    if tmpl or res:
        raise DomainError("DOE_PREVIEW_UNAVAILABLE", "형상 미리보기를 쓸 수 없습니다 — 관리자 설정이 필요합니다", status=409, missing=tmpl + res)


def _select(ctx: AppContext, sel: Any) -> dict[str, Any]:
    """선택 검증·정규화(§5.2): limit 생략 = page_size, 최대 max_page_size, offset은 page_size 배수."""
    cfg = ctx.settings.doe_preview
    limit = int(sel.limit) if sel.limit is not None else int(cfg.page_size)
    if limit > cfg.max_page_size:
        raise invalid_at("select.limit", f"limit은 최대 {cfg.max_page_size}입니다")
    if sel.offset % cfg.page_size:
        raise invalid_at("select.offset", f"offset은 {cfg.page_size}의 배수여야 합니다")
    if sel.order == "var" and not sel.var:
        raise invalid_at("select.var", "정렬 변수(var)가 필요합니다")
    return {"order": sel.order, "var": sel.var if sel.order == "var" else None, "desc": bool(sel.desc) if sel.order == "var" else False,
            "offset": int(sel.offset), "limit": limit}


class _Resolved:
    """요청 해석 결과: 형상 입력 + 작업 params의 표본 부분 + 키."""

    def __init__(self, src: src_mod.Source, extra: dict[str, Any], mkey: str, doe_id: str | None) -> None:
        self.src, self.extra, self.mkey, self.doe_id = src, extra, mkey, doe_id


def _sampling_part(ctx: AppContext, conn: Any, study: dict[str, Any], body: Any, names: list[str], inputs: Any) -> dict[str, Any]:
    """표본 부분(sampling | num_runs+seed) 검증 → 작업 params 조각 {sampling?, num_runs, seed}. 실제 TD_DOE_GEN native와 같은 함수."""
    if body.sampling is None:
        raise invalid_at("sampling", "표본 방식(sampling)이 필요합니다")
    cfg = ctx.settings
    p = TdDoeGenParams(sampling=body.sampling)
    plan = native_plan(cfg, p, multi=False, inputs=inputs) if needs_plan(p) else None
    samples = reuse_samples(ctx, conn, study, p.sampling)
    _label, num_runs, seed, _multi, _fail = _native_doe_common(cfg, p, samples, names, plan)
    return _native_params({"num_runs": num_runs, "seed": seed}, p, plan)


def _resolve_train(ctx: AppContext, conn: Any, study: dict[str, Any], body: Any) -> _Resolved:
    s = ctx.settings
    setup = train_repo.get_setup(conn, study["id"])
    if setup is None or not setup.get("features_rel"):
        raise DomainError("PREREQUISITE_MISSING", "형상 피처와 사용 파라미터가 필요합니다(①-1을 Native로 먼저)", status=409, missing=["GEOM_FEATURES"])
    if setup.get("engine") != "native":
        raise _unsupported(dp.UNSUPPORTED_ENGINE)
    from physicsai_core.geometry.shell_native import kind_of_features_rel

    shape = kind_of_features_rel(setup.get("features_rel"))
    if shape == SHELL:  # paicad `shell view grid`는 --fixed-dir 필수인데 ①-1 기반 쉘은 DOE 실행 때 fixed-scan(고정 정보 없음)
        raise _unsupported("쉘 판금 ①-1 기반 DOE는 고정 정보가 없어 형상 미리보기를 지원하지 않습니다 — 파라미터 세트 기준 DOE에서 쓰세요")
    require_native_available(s)
    _require_available(ctx, shape)
    root = study_root(ctx, study)
    try:
        src = src_mod.from_train(root, setup, s)
    except src_mod.SourceError as exc:
        raise DomainError(exc.code, exc.message, status=409) from None
    from physicsai_core.stage1_train_data import train_params as tp

    used = tp.used(setup.get("parameters") or [])
    part = _sampling_part(ctx, conn, study, body, [q["name"] for q in used], doe_platform.design_inputs_native(setup))
    return _finish(ctx, src, part, None)


def _resolve_set(ctx: AppContext, conn: Any, study: dict[str, Any], body: Any) -> _Resolved:
    s = ctx.settings
    psid = body.source.param_set_id
    if not psid:
        raise invalid_at("source.param_set_id", "param_set 출처에는 param_set_id가 필요합니다")
    ps = ps_repo.get(conn, psid)
    if ps is None or ps["study_id"] != study["id"]:
        raise DomainError("PREREQUISITE_MISSING", "파라미터 세트를 찾을 수 없습니다", status=409, missing=["PARAM_SET"])
    if ps.get("engine") != "native":
        raise _unsupported(dp.UNSUPPORTED_ENGINE)
    from .param_set_native_api import set_kind, set_path

    S = set_path(ctx, ps)
    if bl.is_multi(S):
        raise _unsupported(dp.UNSUPPORTED_MULTI)
    shape = set_kind(ctx, ps)
    native_set_gate(ctx, ps)  # 409 GEOM_NATIVE_UNAVAILABLE · GEOM_PREP_STALE
    _require_available(ctx, shape)
    if shape == SHELL:
        require_shell_available(s)
    from . import native_vars_run  # 지연 import(순환: native_vars_api → param_set_native_api → jobs → job_params)

    res = native_vars_run.resolve(ctx, conn, study, ps, None, None)  # native-vars.md §4.2: 실제 DOE와 같은 변수 스냅숏(범위)
    try:
        src = src_mod.from_param_set(study_root(ctx, study), res.ps, s)
    except src_mod.SourceError as exc:
        raise DomainError(exc.code, exc.message, status=409) from None
    part = _sampling_part(ctx, conn, study, body, [str(r["name"]) for r in ps["parameters"]],
                          doe_platform.design_inputs_from_params(list(res.ps["parameters"])))
    if res.vars is not None:
        part["vars"] = res.vars
    return _finish(ctx, src, part, None)


def _resolve_doe(ctx: AppContext, conn: Any, study: dict[str, Any], body: Any) -> _Resolved:
    s = ctx.settings
    did = body.source.doe_id
    if not did:
        raise invalid_at("source.doe_id", "train_doe 출처에는 doe_id가 필요합니다")
    doe = train_repo.get_doe(conn, did)
    if doe is None or doe["study_id"] != study["id"]:
        raise DomainError("NOT_FOUND", "DOE를 찾을 수 없습니다", status=404)
    if doe.get("engine") != "native":
        raise _unsupported(dp.UNSUPPORTED_ENGINE)
    if doe["status"] != "READY":
        raise DomainError("DOE_NOT_READY", "READY 상태의 DOE가 필요합니다", status=409)
    root = study_root(ctx, study)
    D = os.path.join(root, *str(doe["dir_rel"]).replace("\\", "/").split("/"))
    mpath = os.path.join(D, dp.MATRIX_CSV)
    if not os.path.isfile(mpath):
        raise DomainError("PREREQUISITE_MISSING", "DOE 표본 표(doe_matrix.csv)가 없습니다", status=409, missing=["DOE_MATRIX"])
    with open(mpath, encoding="utf-8", newline="") as fh:
        head = fh.readline()
    if "baseline_id" in head.strip().split(","):
        raise _unsupported(dp.UNSUPPORTED_MULTI)
    try:
        src = src_mod.from_doe(root, doe, s)
    except src_mod.SourceError as exc:
        raise DomainError(exc.code, exc.message, status=409) from None
    _require_available(ctx, src.shape)
    from physicsai_core.geometry.prep import sha256_file

    return _finish(ctx, src, {"sampling": {"kind": "train_doe", "doe_id": did}, "matrix_sha256": sha256_file(mpath)}, did)


def _finish(ctx: AppContext, src: src_mod.Source, part: dict[str, Any], doe_id: str | None) -> _Resolved:
    table = dp.param_table(src.matrix_rows)
    mkey = dp.matrix_key(source_digest=src.digest, sampling=part.get("sampling"), num_runs=part.get("num_runs"), seed=part.get("seed"),
                         params=table) if doe_id is None else dp.sha_of({"source": src.digest, "doe_id": doe_id, "matrix": part.get("matrix_sha256")})
    return _Resolved(src, part, mkey, doe_id)


def _resolve(ctx: AppContext, conn: Any, study: dict[str, Any], body: Any) -> _Resolved:
    kind = body.source.kind
    if kind == "train":
        return _resolve_train(ctx, conn, study, body)
    if kind == "param_set":
        return _resolve_set(ctx, conn, study, body)
    return _resolve_doe(ctx, conn, study, body)


def _source_ref(body: Any, res: _Resolved) -> dict[str, Any]:
    return {k: v for k, v in {"param_set_id": body.source.param_set_id, "doe_id": body.source.doe_id,
                              "train_setup_id": res.src.source_ref.get("train_setup_id")}.items() if v}


def _cells_ready(conn: Any, study_id: str, doc: dict[str, Any]) -> bool:
    keys = [c["key"] for c in (doc or {}).get("cells") or []]
    return bool(keys) and len(dp_repo.done_cells(conn, study_id, keys)) == len(set(keys))


def _files_present(ctx: AppContext, study: dict[str, Any], rows: dict[str, dict[str, Any]]) -> bool:
    root = study_root(ctx, study)
    for k in rows:
        if not os.path.isfile(os.path.join(root, *dp.cell_dir_rel(k).split("/"), dp.THUMB_PNG)):
            return False
    return True


def create(ctx: AppContext, principal: Principal, study_id: str, body: Any, rid: str, ip: str | None) -> tuple[dict[str, Any], int]:
    """`POST /studies/{id}/doe-previews` → (DoePreview, 200|202)."""
    s = ctx.settings
    cfg = s.doe_preview
    with ctx.engine.connect() as conn:
        st0 = studies_repo.require(conn, study_id)
    require_power(principal, st0["project_id"])
    sel = _select(ctx, body.select)
    with ctx.engine.connect() as conn:
        res = _resolve(ctx, conn, st0, body)
    src = res.src
    names = {p["name"] for p in src.geo_params} | {str(r.get("name")) for r in src.matrix_rows}
    if sel["order"] == "var" and sel["var"] not in names:
        raise invalid_at("select.var", "세트·학습 표에 없는 변수 이름입니다")
    thumb_doc = dp.thumb_options_document(cfg, src.geo_params)
    pid = str(uuid.uuid4())
    with ctx.engine.begin() as conn:
        study = studies_repo.require(conn, study_id, for_update=True)  # 같은 Study 생성 직렬화(D3-25)
        study_gate(conn, study, "DOE_PREVIEW")  # 보관·정리 중 409
        ver = _engine_version(conn)
        gkey = dp.grid_key(source_digest=src.digest, mkey=res.mkey, select=sel, thumb=dp.thumb_digest(thumb_doc),
                           engine_version=ver or f"unknown:{pid}", doe_id=res.doe_id)
        if ver is not None:
            row = dp_repo.live_by_grid_key(conn, study["id"], gkey, for_update=True)
            if row is not None and row["status"] in dp_repo.ACTIVE:
                return out(ctx, conn, row), 202
            if row is not None and row["status"] == "DONE" and _cells_ready(conn, study["id"], row.get("cell_keys") or {}):
                keys = [c["key"] for c in row["cell_keys"]["cells"]]
                if _files_present(ctx, study, dp_repo.get_cells(conn, keys)):
                    dp_repo.touch_cells(conn, keys)
                    return out(ctx, conn, row, cache_hit=True), 200
        ref = _source_ref(body, res)
        for old in dp_repo.queued_of_user(conn, principal.user_id, study["id"]):  # §6.4-3 같은 출처의 이전 QUEUED는 취소(최신 우선)
            if old["source_kind"] == body.source.kind and (old.get("source_ref") or {}) == ref and old.get("job_id"):
                j = jobs_repo.get_job(conn, old["job_id"])
                if j is not None and j["state"] == "QUEUED":
                    jobs_repo.request_cancel(conn, old["job_id"], principal.user_id)
        if dp_repo.active_count(conn, principal.user_id) >= cfg.max_active_per_user:
            raise DomainError("PREVIEW_BUSY", label_of("PREVIEW_BUSY"), status=429, limit=cfg.max_active_per_user)
        params = {"preview_id": pid, "source": {"kind": body.source.kind, **ref}, "select": sel, "grid_key": gkey, "matrix_key": res.mkey,
                  "engine_version": ver, **{k: v for k, v in res.extra.items() if k != "matrix_sha256"}}
        job = jobs_repo.insert_job(conn, study=study, job_type="DOE_PREVIEW", params=params, user_id=principal.user_id,
                                   user_name=principal.display_name)
        row = dp_repo.insert(conn, {"id": pid, "study_id": study["id"], "created_by": principal.user_id, "job_id": job["id"], "grid_key": gkey,
                                    "source_kind": body.source.kind, "source_ref": ref, "matrix_key": res.mkey, "select": sel,
                                    "status": "QUEUED"})
        audit(conn, principal, "DOE_PREVIEW_CREATE", "doe_preview", pid,
              {"job_id": job["id"], "source": body.source.kind, "order": sel["order"], "offset": sel["offset"]}, rid, ip)
        return out(ctx, conn, row), 202


def _study_of(ctx: AppContext, preview_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    with ctx.engine.connect() as conn:
        row = dp_repo.get(conn, preview_id)
        if row is None:
            raise DomainError("NOT_FOUND", "형상 미리보기를 찾을 수 없습니다", status=404)
        return row, studies_repo.require(conn, row["study_id"])


def get(ctx: AppContext, preview_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        row = dp_repo.get(conn, preview_id)
        if row is None:
            raise DomainError("NOT_FOUND", "형상 미리보기를 찾을 수 없습니다", status=404)
        return out(ctx, conn, row)


def cancel(ctx: AppContext, principal: Principal, preview_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    """`POST /doe-previews/{id}/cancel`: 요청자(power)·관리자. 대기·실행 중 작업의 취소 플래그(완료 청크 셀은 캐시에 남는다). 끝난 뒤는 409 JOB_TERMINAL."""
    row0, study0 = _study_of(ctx, preview_id)
    require_power(principal, study0["project_id"])
    if row0["created_by"] != principal.user_id and not principal.is_global_admin:
        raise DomainError("PERMISSION_DENIED", "요청자 또는 관리자만 취소할 수 있습니다", status=403, required="requester_or_admin")
    with ctx.engine.begin() as conn:
        studies_repo.require(conn, study0["id"], for_update=True)
        row = dp_repo.get(conn, preview_id, for_update=True)
        if row is None or row["status"] not in dp_repo.ACTIVE or not row.get("job_id"):
            raise DomainError("JOB_TERMINAL", "이미 끝난 형상 미리보기입니다", status=409)
        jobs_repo.request_cancel(conn, row["job_id"], principal.user_id)
        audit(conn, principal, "DOE_PREVIEW_CANCEL", "doe_preview", preview_id, {"job_id": row["job_id"]}, rid, ip)
        return out(ctx, conn, dp_repo.get(conn, preview_id))  # type: ignore[arg-type]


# ---- 응답 ----------------------------------------------------------------------------------------------------


def _gen_of(ctx: AppContext, doe_dir: str, run_key: str | None) -> dict[str, Any]:
    """생성 후 갤러리(train_doe): run 폴더 SKIPPED.json 있음 → SKIPPED(code·step), starter 있음 → OK, 그 밖 PENDING(DB 추가 없음)."""
    if not run_key:
        return {"status": "PENDING", "code": None, "step": None}
    from physicsai_core.geometry.view import read_json

    R = os.path.join(doe_dir, *ctx.settings.train_data.platform_run_root.replace("\\", "/").split("/"), run_key)
    sk = os.path.join(R, "SKIPPED.json")
    if os.path.isfile(sk):
        d = read_json(sk) or {}
        return {"status": "SKIPPED", "code": d.get("code") if isinstance(d.get("code"), str) else "GEOM_INTERNAL",
                "step": d.get("step") if isinstance(d.get("step"), str) else None}
    from .path_inspect import starters_in

    if os.path.isdir(R) and starters_in(R, ctx.settings.predict.starter_glob):
        return {"status": "OK", "code": None, "step": None}
    return {"status": "PENDING", "code": None, "step": None}


def _cell_out(entry: dict[str, Any], row: dict[str, Any] | None, err: str | None, params: list[dict[str, Any]], gen: dict[str, Any] | None
              ) -> dict[str, Any]:
    vals = {k: float(v) for k, v in (entry.get("values") or {}).items()}
    base = {"doe_no": entry.get("doe_no"), "nominal": bool(entry.get("nominal")), "values": vals,
            "top_changes": dp.top_changes(vals, params) if not entry.get("nominal") else [], "gen": gen}
    if row is not None and row["status"] == "DONE":
        code = row.get("code")
        return {**base, "status": row.get("result_status") or "OK", "code": code, "category": row.get("category"),
                "message_ko": label_of(code) if code else None, "max_disp_mm": row.get("max_disp_mm"), "clipped": bool(row.get("clipped")),
                "png_artifact_id": row.get("png_artifact_id"), "glb_artifact_id": row.get("glb_artifact_id"),
                "manifest_artifact_id": row.get("manifest_artifact_id")}
    if err is not None:
        return {**base, "status": "ERROR", "code": err, "message_ko": label_of(err)}
    return {**base, "status": "PENDING"}


def out(ctx: AppContext, conn: Any, row: dict[str, Any], cache_hit: bool = False) -> dict[str, Any]:
    doc = row.get("cell_keys") or {}
    entries = list(doc.get("cells") or [])
    params = list(doc.get("params") or [])
    job = jobs_repo.get_job(conn, row["job_id"]) if row.get("job_id") else None
    errors = ((job or {}).get("result") or {}).get("cell_errors") or {}
    cells_db = dp_repo.get_cells(conn, [e["key"] for e in entries])
    doe_dir = None
    if row["source_kind"] == "train_doe" and entries:
        doe = train_repo.get_doe(conn, (row.get("source_ref") or {}).get("doe_id") or "")
        if doe is not None:
            study = studies_repo.require(conn, row["study_id"])
            doe_dir = os.path.join(study_root(ctx, study), *str(doe["dir_rel"]).replace("\\", "/").split("/"))
    cells = [_cell_out(e, cells_db.get(e["key"]), errors.get(e["key"]), params,
                       _gen_of(ctx, doe_dir, e.get("run_key")) if doe_dir and not e.get("nominal") else None) for e in entries]
    count = lambda st: sum(1 for c in cells if c["status"] == st)  # noqa: E731
    queue = None
    if job is not None and job["state"] == "QUEUED":
        queue = {"lane": job["lane"], "position": jobs_repo.queue_positions(conn, job["lane"]).get(job["id"])}
    code = (job or {}).get("failure_code") if row["status"] == "FAILED" else None
    ref = row.get("source_ref") or {}
    return {"id": row["id"], "job_id": row.get("job_id"), "status": row["status"], "cache_hit": cache_hit,
            "source": {"kind": row["source_kind"], "param_set_id": ref.get("param_set_id"), "doe_id": ref.get("doe_id")},
            "select": row.get("select"), "queue": queue, "n_total": row.get("n_total"),
            "n_ok": count("OK") if entries else row.get("n_ok"), "n_fail": count("FAIL") if entries else row.get("n_fail"),
            "n_error": count("ERROR") if entries else row.get("n_error"),
            "order": list(doc.get("order") or [])[:dp.ORDER_MAX], "tag_state": doc.get("tag_state") or "none",
            "disp_range_mm": doc.get("disp_range_mm"), "colormap": doc.get("colormap") or dp.COLORMAP, "cells": cells, "code": code,
            "message_ko": label_of(code) if code else None, "warnings": list((job or {}).get("warnings") or []),
            "timing": row.get("timing"), "created_at": row.get("created_at"), "finished_at": row.get("finished_at")}
