"""⑤ 등가성 판정 보고서 원천(upload-report.md §9.3.2): `GET /equiv-checks/{id}` 상세(레시피 스냅숏·metrics.csv 표) + 대표 곡선(`/curves` 서비스)."""

from __future__ import annotations

from typing import Any

from physicsai_core.db.repositories import equiv_check as eq_repo
from physicsai_core.errors import DomainError
from physicsai_core.report_html.equiv import pick_curve_pairs

from ..auth import Principal
from ..context import AppContext
from . import equiv_check as eq_svc
from . import reports_common as rc

CURVE_POINTS = 300


def equiv_input(ctx: AppContext, principal: Principal, eq_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        row = eq_svc._require(conn, eq_id)  # 404 EQ_CHECK_NOT_FOUND
        if row["status"] == "RUNNING":
            raise DomainError("REPORT_NOT_READY", f"등가성 판정 {eq_repo.label(row['eq_no'])}이(가) 아직 끝나지 않았습니다 — 끝난 뒤 받으세요", status=409)
        study = rc.require_study(conn, row["study_id"])
    d = eq_svc.detail(ctx, principal, eq_id)
    curves = []
    for pair, metric in pick_curve_pairs(d.get("rows") or [], d.get("metrics") or []):
        try:
            curves.append(eq_svc.curves(ctx, principal, eq_id, pair, metric, CURVE_POINTS))
        except DomainError:
            continue  # 곡선 파일이 없는 쌍은 건너뜀
    return {"study": rc.study_info(study), "generated_by": principal.display_name, "detail": d, "curves": curves, "engine": {}}
