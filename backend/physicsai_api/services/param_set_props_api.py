"""단계 3S 쉘 두께 API 서비스(geometry-engine.md §11.1): PROP 스캔 작업(202)·결과 조회·선택 저장.

- 스캔은 외부 명령이라 워커가 한다(PARAM_SET_NATIVE mode props_scan → `S/native/props/props.json`).
- 선택 = 파라미터 표의 `source: "prop"` 행(형상 행 뒤). `include_geometry=false`면 형상 행을 빼 두께만 있는 세트로
  (빼낸 형상 행은 `S/native/props/geometry_parameters.json`에 두고 다시 켤 때 되살린다). 다중 baseline 세트는 형상 행을 뺄 수 없다.
"""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.fileutil import write_json_atomic
from physicsai_core.geometry import baselines as bl
from physicsai_core.geometry import shell as sh
from physicsai_core.geometry.prep import is_shell_only
from physicsai_core.geometry.reports import ReportError, read_report
from physicsai_core.paths import resolve_in_study

from ..auth import Principal
from ..context import AppContext
from . import jobs as jobs_svc
from .common import audit, param_set_out, study_root
from .param_set_baselines_api import require_writable

GEOMETRY_BACKUP = "native/props/geometry_parameters.json"


def _native(conn: Any, ps_id: str) -> dict[str, Any]:
    p = ps_repo.get(conn, ps_id)
    if p is None:
        raise DomainError("NOT_FOUND", "파라미터 세트를 찾을 수 없습니다", status=404)
    if (p.get("engine") or "altair") != "native":
        raise DomainError("ENGINE_MISMATCH", "쉘 두께 파라미터는 Native 형상 엔진 세트에서만 씁니다(Altair 경로 미적용, §15 Q13)", status=409)
    return p


def _S(ctx: AppContext, conn: Any, p: dict[str, Any]) -> str:
    return resolve_in_study(study_root(ctx, studies_repo.require(conn, p["study_id"])), p["stored_rel"])


def _props_doc(ctx: AppContext, S: str) -> dict[str, Any] | None:
    path = os.path.join(S, *sh.PROPS_JSON.split("/"))
    if not os.path.isfile(path):
        return None
    try:
        return read_report(path, ctx.settings.geometry.max_report_bytes)
    except ReportError as exc:
        raise DomainError("INPUT_INVALID", exc.message, status=409) from None


def start_scan(ctx: AppContext, principal: Principal, ps_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    """POST /param-sets/{id}/props/scan → 202 {job_id}."""
    with ctx.engine.connect() as conn:
        p = _native(conn, ps_id)
    job = jobs_svc.create_job(ctx, principal, p["study_id"], "PARAM_SET_NATIVE", {"mode": "props_scan", "param_set_id": ps_id}, rid, ip)
    return {"job_id": job["id"]}


def get_props(ctx: AppContext, ps_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        p = _native(conn, ps_id)
        S = _S(ctx, conn, p)
    doc = _props_doc(ctx, S)
    base = {"scanned": doc is not None, "shell_only": is_shell_only(S), "include_geometry": sh.has_geometry(p["parameters"])}
    if doc is None:
        return {**base, "engine_version": None, "props": [], "warnings": []}
    return {**base, **sh.summary(doc, p["parameters"])}


def put_props(ctx: AppContext, principal: Principal, ps_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    """PUT /param-sets/{id}/props: 선택 전체 교체 → 갱신된 ParamSet. 검증 실패 422 PROP_SELECTION_INVALID(problems)."""
    from .param_set_native_api import enrich

    with ctx.engine.begin() as conn:
        p = _native(conn, ps_id)
        require_writable(conn, principal, p)
        S = _S(ctx, conn, p)
        doc = _props_doc(ctx, S)
        if doc is None:
            raise DomainError("PROPS_NOT_SCANNED", "쉘 두께 PROP 스캔을 먼저 하세요", status=409)
        geo = sh.geometry_rows(p["parameters"])
        include = bool(body.include_geometry)
        if is_shell_only(S):
            include = False
        elif not include and bl.is_multi(S):
            raise DomainError("PROP_SELECTION_INVALID", "다중 baseline 세트는 형상 파라미터를 뺄 수 없습니다", status=422,
                              problems=[{"code": "MULTI_BASELINE", "message": "다중 baseline 세트는 형상 파라미터를 뺄 수 없습니다"}])
        gbak = os.path.join(S, *GEOMETRY_BACKUP.split("/"))
        if include and not geo and not is_shell_only(S):
            geo = _restore_geometry(ctx, gbak)
        try:
            props = sh.selection_rows(doc, [x.model_dump() for x in body.selected], geometry_names=[r["name"] for r in geo])
        except sh.ShellError as exc:
            raise DomainError("PROP_SELECTION_INVALID", "쉘 두께 선택이 올바르지 않습니다", status=422, problems=exc.problems) from None
        if not include and geo:
            write_json_atomic(gbak, {"schema_version": 1, "parameters": geo})  # 다시 켤 때 되살릴 형상 행(삭제 없음)
        rows = sh.merge_rows(geo if include else [], props)
        if not rows:
            raise DomainError("PROP_SELECTION_INVALID", "파라미터가 1개 이상 필요합니다", status=422,
                              problems=[{"code": "PARAMETERS_EMPTY", "message": "형상 또는 쉘 두께 파라미터를 하나 이상 고르세요"}])
        write_json_atomic(os.path.join(S, "parameters.json"), {"schema_version": 1, "unit_system": p.get("unit_system") or "mm-ton-s",
                                                                "parameters": rows})
        ps_repo.set_values(conn, ps_id, parameters=rows)
        audit(conn, principal, "PARAM_SET_UPDATE", "param_set", ps_id,
              {"shell_params": [r["name"] for r in props], "include_geometry": include}, rid, ip)
        row = ps_repo.get(conn, ps_id)
    return enrich(ctx, row, param_set_out(row))  # type: ignore[arg-type]


def _restore_geometry(ctx: AppContext, gbak: str) -> list[dict[str, Any]]:
    try:
        doc = read_report(gbak, ctx.settings.geometry.max_report_bytes)
    except ReportError:
        raise DomainError("PROP_SELECTION_INVALID", "되살릴 형상 파라미터가 없습니다 — 형상 준비를 다시 하세요", status=422,
                          problems=[{"code": "GEOMETRY_ROWS_MISSING", "message": "형상 파라미터 백업이 없습니다"}]) from None
    return [r for r in doc.get("parameters") or [] if isinstance(r, dict) and not sh.is_prop_row(r)]
