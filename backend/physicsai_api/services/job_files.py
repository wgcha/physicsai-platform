"""작업에 딸린 파일·행 조회: 산출물 목록·내려받기, HPC 행, ④ 입력 파일 zip 스트리밍(§10.2, §8.2, B16).

`services/jobs.py`에서 분리(300줄 규칙, 동작 불변). 라우터 함수 이름(operationId)은 그대로다.
"""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.db.repositories import artifacts as artifacts_repo
from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.paths import resolve_in_study

from ..context import AppContext
from .common import MOVED_HINT, input_zip_ready, require_job, study_root


# ---- 산출물·HPC ----------------------------------------------------------------


def list_artifacts(ctx: AppContext, job_id: str) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        require_job(conn, job_id)
        rows = artifacts_repo.list_for_job(conn, job_id)
    return [
        {"id": a["id"], "study_id": a["study_id"], "job_id": a["job_id"], "kind": a["kind"],
         "file_name": os.path.basename(a["rel_path"]), "size": a["size"], "sha256": a["sha256"],
         "content_type": a["content_type"], "created_at": a["created_at"]}
        for a in rows
    ]


def artifact_file(ctx: AppContext, artifact_id: str) -> tuple[str, str, str]:
    with ctx.engine.connect() as conn:
        a = artifacts_repo.get(conn, artifact_id)
        if a is None:
            raise DomainError("NOT_FOUND", "산출물을 찾을 수 없습니다", status=404)
        s = studies_repo.require(conn, a["study_id"])
    if a["content_type"] not in artifacts_repo.ALLOWED_CONTENT_TYPES:
        raise DomainError("NOT_FOUND", "내려받을 수 없는 형식입니다", status=404)
    path = resolve_in_study(study_root(ctx, s), a["rel_path"])
    if not os.path.isfile(path):
        raise DomainError("NOT_FOUND", "산출물 파일이 없습니다", status=404)
    if os.path.getsize(path) > ctx.settings.ui.max_artifact_bytes:
        raise DomainError("NOT_FOUND", "산출물이 크기 상한을 넘습니다", status=404)
    return path, a["content_type"], os.path.basename(a["rel_path"])


def list_hpc_jobs(ctx: AppContext, job_id: str) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        require_job(conn, job_id)
        rows = hpc_repo.list_for_job_with_elapsed(conn, job_id)
    return [
        {"id": r["id"], "run_key": r["run_key"], "attempt_no": r["attempt_no"], "external_job_id": r["external_job_id"],
         "state": r["state"], "external_state_raw": r["external_state_raw"], "submitted_at": r["submitted_at"],
         "elapsed_s": float(r["elapsed"]) if r["elapsed"] is not None else None, "collect_state": r["collect_state"]}
        for r in rows
    ]


# ---- ④ 입력 파일 zip(스트리밍) ------------------------------------------------------

ZIP_CHUNK = 1024 * 1024


class _ZipSink:
    """zipfile이 쓰는 비탐색(non-seekable) 출력. 쓴 바이트를 모았다가 생성기가 꺼내 간다."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.pos = 0

    def write(self, b: bytes) -> int:
        self.buf += b
        self.pos += len(b)
        return len(b)

    def tell(self) -> int:
        return self.pos

    def seek(self, *_a: Any) -> int:
        raise OSError("not seekable")

    def flush(self) -> None:
        return None

    def take(self) -> bytes:
        out = bytes(self.buf)
        self.buf.clear()
        return out


def input_zip(ctx: AppContext, job_id: str) -> tuple[Any, str]:
    """PREDICT 작업의 `P/INPUT/` 직계 파일(.rad·.inc 등)을 zip으로 스트리밍. (생성기, 파일 이름)."""
    import zipfile

    with ctx.engine.connect() as conn:
        j = require_job(conn, job_id)
        if not input_zip_ready(conn, j):
            raise DomainError("INPUT_NOT_READY", "입력 파일이 아직 준비되지 않았습니다(예측 작업의 .rad 조립 완료 후 가능)", status=409)
        s = studies_repo.require(conn, j["study_id"])
        root_id = jobs_repo.root_job_id(conn, j)
    root = study_root(ctx, s)
    inp = resolve_in_study(root, f"04_predict/{root_id}/INPUT")
    if not os.path.isdir(inp):
        raise DomainError("INPUT_NOT_READY", f"입력 파일 폴더가 없습니다. {MOVED_HINT}", status=409)
    names = []
    for n in sorted(os.listdir(inp)):
        p = os.path.join(inp, n)
        if os.path.islink(p) or not os.path.isfile(p):
            continue  # 링크·하위 폴더 제외(경로 탈출 방지)
        if os.path.dirname(os.path.realpath(p)) != os.path.realpath(inp):
            continue
        names.append(n)

    def gen() -> Any:
        sink = _ZipSink()
        with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for n in names:
                with open(os.path.join(inp, n), "rb") as src, zf.open(n, "w", force_zip64=True) as dst:
                    while True:
                        b = src.read(ZIP_CHUNK)
                        if not b:
                            break
                        dst.write(b)
                        chunk = sink.take()
                        if chunk:
                            yield chunk
                chunk = sink.take()
                if chunk:
                    yield chunk
        tail = sink.take()
        if tail:
            yield tail

    return gen(), f"{s['folder_name']}_{job_id[:8]}_INPUT.zip"
