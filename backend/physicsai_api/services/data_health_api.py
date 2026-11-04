"""③-1 데이터 점검 결과 조회(data-health.md §8): `GET /jobs/{job_id}/data-health` — `report.json` 내용."""

from __future__ import annotations

import json
import os
from typing import Any

from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.paths import resolve_in_study

from ..context import AppContext
from .common import require_job, study_root


def get_report(ctx: AppContext, job_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        j = require_job(conn, job_id)
        if j["job_type"] != "DATA_HEALTH":
            raise DomainError("NOT_FOUND", "데이터 점검 작업이 아닙니다", status=404)
        if j["state"] != "SUCCEEDED":
            raise DomainError("REPORT_NOT_READY", "데이터 점검이 아직 끝나지 않았습니다 — 끝난 뒤 받으세요", status=409)
        study = studies_repo.require(conn, j["study_id"])
    rel = (j.get("result") or {}).get("report_rel")
    path = resolve_in_study(study_root(ctx, study), rel) if rel else None
    if not path or not os.path.isfile(path):
        raise DomainError("REPORT_MISSING", "점검 결과 파일(report.json)이 없습니다 — 점검을 다시 실행하세요", status=404)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
