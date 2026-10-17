"""SCX 제출 결과 모름 조치 요청(phase3 §16.5): `POST /jobs/{id}/hpc-jobs/{hid}/resolve`.

API는 게이트웨이를 부르지 않는다(platform.md §12.2 — availability()만). 요청을 `hpc_jobs.resolve_request`에 적고(감사 HPC_RESOLVE)
워커 폴러가 다음 주기에 처리한다(recheck = 같은 request_id replay, attach = relay에 잡 ID 연결, mark_not_submitted = 행 FAILED).
권한: 작업 등록자는 power 이상, 그 밖은 전역 관리자(재시도와 같은 소유자·관리자 규칙).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.errors import DomainError

from ..auth import Principal
from ..context import AppContext
from .common import audit, require_global_admin, require_job, require_power
from .job_files import hpc_row_out
from .job_params.base import invalid_errors

WARNING = "SCX에 잡이 실제로 있는데 '제출 안 됨'으로 표시하면 같은 해석이 두 번 돌 수 있습니다(폴더는 따로)."


def request_resolve(ctx: AppContext, principal: Principal, job_id: str, hid: str, action: str, external_job_id: str | None,
                    version: int, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        job = require_job(conn, job_id)
        if job["created_by"] == principal.user_id:
            require_power(principal, job["project_id"])
        else:
            require_global_admin(principal)
        row = hpc_repo.get(conn, hid, for_update=True)
        if row is None or row["job_id"] != job_id:
            raise DomainError("NOT_FOUND", "HPC 행을 찾을 수 없습니다", status=404)
        if action == "attach" and not external_job_id:
            raise invalid_errors([{"loc": ["body", "external_job_id"], "msg": "attach에는 SCX 잡 ID가 필요합니다"}])
        if action != "attach" and external_job_id is not None:
            raise invalid_errors([{"loc": ["body", "external_job_id"], "msg": "external_job_id는 attach에서만 씁니다"}])
        if not (row["state"] == "UNKNOWN" and row["submission_unknown"]):
            raise DomainError("HPC_NOT_UNKNOWN", "SCX 제출 결과 모름 상태인 행이 아닙니다", status=409)
        if job["state"] != "WAITING_HPC" and action != "mark_not_submitted":
            # 끝난(중단·실패·취소) 작업의 결과 모름 행은 기록 정리(제출 안 됨)만 — 다시 확인·연결은 작업을 되살리지 않는다
            raise DomainError("HPC_RESOLVE_NOT_ALLOWED", "대기 중(WAITING_HPC)이 아닌 작업은 '제출 안 됨' 조치만 할 수 있습니다",
                              status=409)
        if row["resolve_request"] is not None:
            raise DomainError("HPC_RESOLVE_PENDING", "이미 요청한 조치를 워커가 처리하는 중입니다", status=409)
        req = {"action": action, "by": principal.user_id, "by_name": principal.display_name,
               "requested_at": datetime.now(timezone.utc).isoformat()}
        if external_job_id is not None:
            req["external_job_id"] = external_job_id
        if row["version"] != version or not hpc_repo.request_resolve(conn, hid, version, req):
            raise DomainError("VERSION_CONFLICT", "행이 그 사이 바뀌었습니다. 새로 고친 뒤 다시 시도하세요", status=409)
        audit(conn, principal, "HPC_RESOLVE", "hpc_job", hid,
              {"job_id": job_id, "action": action, "external_job_id": external_job_id, "request_id": row["request_id"]}, rid, ip)
        out = hpc_repo.get(conn, hid)
    return hpc_row_out(ctx, out or row)
