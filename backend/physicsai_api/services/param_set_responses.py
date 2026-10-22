"""④ 템플릿(파라미터 세트) 응답 정의(phase3 §14.6 S9): `PUT /param-sets/{id}/responses`."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import surrogate_opts as so_repo
from physicsai_core.errors import DomainError
from physicsai_core.fileutil import write_json_atomic
from physicsai_core.paths import resolve_in_study
from physicsai_core.stage4_predict import param_sets as ps_mod
from physicsai_core.stage4_predict.response_defs import validate_response_defs

from ..auth import Principal
from ..context import AppContext
from .common import audit, param_set_out, require_power, study_root
from .input_kind_gate import with_capability


def put_responses(ctx: AppContext, principal: Principal, ps_id: str, rows: list[dict[str, Any]], rid: str,
                  ip: str | None) -> dict[str, Any]:
    """phase3 §14.6 템플릿 응답 정의: 검증(⑤ H3D 형식) → DB `param_sets.responses` + 정규화본 `responses.json`(원자적,
    `original/` 불변) 같은 트랜잭션. 실측 `resp:` 열 이름을 빼면 422 RESPONSE_IN_USE."""
    with ctx.engine.begin() as conn:
        p = ps_repo.get(conn, ps_id)
        if p is None:
            raise DomainError("NOT_FOUND", "파라미터 세트를 찾을 수 없습니다", status=404)
        s = studies_repo.require(conn, p["study_id"])
        require_power(principal, s["project_id"])
        stored = resolve_in_study(study_root(ctx, s), p["stored_rel"])
        if not os.path.isdir(stored):
            raise DomainError("PARAM_SET_FILES_MISSING", "파라미터 세트 폴더(04_params)가 없습니다", status=409)
        header, _rows = ps_mod.read_samples(stored)
        measured = [h[5:] for h in header if h.startswith("resp:")]
        out, problems = validate_response_defs(rows, measured=measured)
        if problems:
            in_use = all(x["code"] == "RESPONSE_IN_USE" for x in problems)
            raise DomainError("RESPONSE_IN_USE" if in_use else "RESPONSE_INVALID",
                              "실측 응답 열은 지울 수 없습니다" if in_use else "응답 정의가 올바르지 않습니다",
                              status=422, problems=problems)
        _require_perf_unchanged(conn, p, out)
        ps_repo.set_responses(conn, ps_id, out)
        write_json_atomic(os.path.join(stored, "responses.json"), {"responses": out})
        audit(conn, principal, "PARAM_SET_UPDATE", "param_set", ps_id, {"responses": [r["name"] for r in out]}, rid, ip)
        p = ps_repo.get(conn, ps_id)
    return with_capability(ctx, p, param_set_out(p))  # type: ignore[arg-type]


def _require_perf_unchanged(conn: Any, ps: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    """S17 §22.3.1: 진행 중 내장 최적화가 `settings.performances`에 스냅샷한 성능의 spec 변경·삭제 → 409 PERF_IN_USE_BY_OPT
    (단위만 바뀌는 것은 허용)."""
    opt = so_repo.active_for_study(conn, ps["study_id"])
    if opt is None or opt["param_set_id"] != ps["id"]:
        return
    snap = (opt.get("settings") or {}).get("performances") or {}
    new = {r["name"]: r.get("spec") for r in rows}
    for name, d in snap.items():
        if name not in new or new[name] != (d or {}).get("spec"):
            label = so_repo.opt_label(opt["opt_no"])
            raise DomainError("PERF_IN_USE_BY_OPT",
                              f"내장 최적화 {label}이 이 성능을 쓰고 있어 정의를 바꿀 수 없습니다 — 끝난 뒤 바꾸세요",
                              status=409, surrogate_opt_id=opt["id"], performance=name)
