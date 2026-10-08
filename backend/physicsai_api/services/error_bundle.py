"""오류 묶음 다운로드(phase2 §10): 권한·조건 확인 후 zip 스트리밍(B16 헬퍼 재사용)."""

from __future__ import annotations

import os
import platform
import sys
import zipfile
from datetime import datetime, timezone
from typing import Any

from physicsai_core import __version__
from physicsai_core.config import effective_altair, redacted_settings
from physicsai_core.db import MIGRATION_HEAD
from physicsai_core.db.repositories import env_checks as env_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import workers as workers_repo
from physicsai_core.error_bundle import BundleMasker, iter_items
from physicsai_core.errors import DomainError

from ..auth import Principal
from ..context import AppContext
from .common import audit, error_bundle_available, job_detail, study_root
from .jobs import ZIP_CHUNK, _ZipSink, list_hpc_jobs

EXE_KEYS = ("hyperstudy_path", "simlab_path", "edspy_path", "hw_exe_path", "hvtrans_exe_path", "hstpy_path")


def _exe_info(path: str) -> dict[str, Any]:
    if not path or not os.path.isfile(path):
        return {"exists": False, "size": None, "mtime": None}
    st = os.stat(path)
    return {"exists": True, "size": st.st_size, "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()}


def build(ctx: AppContext, principal: Principal, job_id: str, rid: str, ip: str | None) -> tuple[Any, str]:
    s = ctx.settings
    with ctx.engine.begin() as conn:
        j = jobs_repo.get_job(conn, job_id)
        if j is None:
            raise DomainError("NOT_FOUND", "작업을 찾을 수 없습니다", status=404)
        if not (principal.is_global_admin or j["created_by"] == principal.user_id):
            raise DomainError("PERMISSION_DENIED", "작업 등록자 본인 또는 전역 관리자만 받을 수 있습니다", status=403,
                              required="owner_or_global_admin")
        if not error_bundle_available(j):
            raise DomainError("ERROR_BUNDLE_NOT_AVAILABLE", "실패·취소·중단되었거나 주의가 필요한 작업만 받을 수 있습니다", status=409)
        st = studies_repo.require(conn, j["study_id"])
        detail = job_detail(conn, j, principal, include_commands=False, ai_root=s.storage.ai_root)
        detail["env_snapshot"] = j["env_snapshot"]
        detail["retry_of"] = j["retry_of_job_id"]
        steps = jobs_repo.get_steps(conn, job_id)
        hb = workers_repo.latest(conn)
        latest = env_repo.latest(conn, "DONE")
        audit(conn, principal, "ERROR_BUNDLE_DOWNLOAD", "job", job_id, None, rid, ip)
    hpc = list_hpc_jobs(ctx, job_id)
    alt = effective_altair(s)
    environment = {
        "app_version": __version__, "python": sys.version.split()[0], "os": platform.platform(),
        "migration_head": MIGRATION_HEAD, "altair_version_label": s.altair.version_label,
        "executables": {k: _exe_info(alt.get(k, "")) for k in EXE_KEYS},
        "worker": ({"worker_id": hb["worker_id"], "limiter": hb["limiter"], "effective_limits": hb["effective_limits"],
                    "gpu": (hb.get("resources") or {}).get("gpu")} if hb else None),
    }
    env_latest = ({"id": latest["id"], "finished_at": latest["finished_at"], "summary": latest["summary"],
                   "items": list(latest["api_items"] or []) + list(latest["worker_items"] or [])} if latest else None)
    masker = BundleMasker(s.logging.mask_patterns, s.auth.cookie_name, s.database.url_env)
    root = study_root(ctx, st)
    log_dir = os.path.join(root, "logs", job_id)
    items = iter_items(
        job=detail, steps=steps, log_dir=log_dir, study_root=root, hpc_jobs=hpc or None,
        config_summary=redacted_settings(s), environment=environment, env_check_latest=env_latest,
        tail_bytes=s.error_bundle.log_tail_bytes, max_total=s.error_bundle.max_total_bytes, masker=masker,
        created=datetime.now(timezone.utc).isoformat(),
    )

    def gen() -> Any:
        sink = _ZipSink()
        with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for name, data in items:
                with zf.open(name, "w", force_zip64=True) as dst:
                    for i in range(0, len(data), ZIP_CHUNK):
                        dst.write(data[i: i + ZIP_CHUNK])
                        chunk = sink.take()
                        if chunk:
                            yield chunk
                chunk = sink.take()
                if chunk:
                    yield chunk
        tail = sink.take()
        if tail:
            yield tail

    return gen(), f"{st['folder_name']}_{job_id[:8]}_error_bundle.zip"
