"""업로드 청크 쓰기(upload-report.md §4·§5): offset 순서 검증 → `.part`에 이어 쓰기 → 마지막 청크에서 전체 sha256 확인 후 최종 이름.

세션 행 `SELECT … FOR UPDATE` 아래에서만 쓴다(같은 파일 동시 쓰기 없음). 누적 sha256 상태는 프로세스 메모리 —
재시작·불일치 시 받은 부분을 한 번 다시 읽어 복원한다. 쓰기 오류 ENOSPC는 507(받은 데까지 유지 — 공간 확보 후 이어 올리기).
"""

from __future__ import annotations

import errno
import hashlib
import os
import threading
from typing import Any

from physicsai_core import uploads as U
from physicsai_core.db.repositories import uploads as repo
from physicsai_core.errors import DomainError

from ..auth import Principal
from ..context import AppContext
from . import uploads as base
from .common import require_config_ok
from .upload_checks import INSUFFICIENT, segs_of

_HASHES: dict[tuple[str, int], tuple[Any, int]] = {}
_LOCK = threading.Lock()
_NO_SPACE = (errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC))


def _hash_state(key: tuple[str, int], part: str, received: int) -> Any:
    with _LOCK:
        st = _HASHES.get(key)
    if st is not None and st[1] == received:
        return st[0]
    h = hashlib.sha256()
    if received:
        with open(part, "rb") as fh:
            left = received
            while left:
                b = fh.read(min(left, 1 << 20))
                if not b:
                    break
                h.update(b)
                left -= len(b)
    return h


def _hash_put(key: tuple[str, int], h: Any, received: int | None) -> None:
    with _LOCK:
        if received is None:
            _HASHES.pop(key, None)
        else:
            _HASHES[key] = (h, received)


def put_chunk(ctx: AppContext, principal: Principal, upload_id: str, index: int, offset: int, data: bytes,
              chunk_sha256: str | None = None) -> dict[str, Any]:
    root = base.require_root(ctx)
    require_config_ok(ctx)
    chunk = ctx.settings.upload.chunk_bytes
    with ctx.engine.begin() as conn:
        up = base.owned(principal, base.get_row(conn, upload_id, for_update=True))
        base.require_open(up)
        if index < 0 or index >= len(up["files"]):
            raise DomainError("UPLOAD_FILE_NOT_FOUND", "업로드 파일 번호가 없습니다", status=404)
        files = [dict(f) for f in up["files"]]
        f = files[index]
        if f.get("done"):
            raise DomainError("UPLOAD_FILE_DONE", f"이미 다 받은 파일입니다: {f['rel']}", status=409, received=int(f["size"]))
        up_dir = U.abs_dir_of(ctx.settings, up["dir_rel"])
        p = U.target_path(up_dir, segs_of(f), create_parents=True)
        part = p + U.PART_SUFFIX
        received = U.part_size(part) if os.path.isfile(part) else 0
        if offset != received:
            raise DomainError("UPLOAD_OFFSET_MISMATCH", f"offset {offset}이 받은 크기 {received}와 다릅니다(이어 올리기는 received부터)",
                              status=409, received=received)
        if len(data) > chunk:
            raise DomainError("CHUNK_TOO_LARGE", f"청크가 chunk_size({chunk} B)보다 큽니다", status=413, limit=chunk)
        if offset + len(data) > f["size"]:
            raise DomainError("CHUNK_OVERFLOW", "선언한 파일 크기를 넘는 청크입니다", status=422, size=int(f["size"]),
                              received=received)
        if os.path.lexists(p):
            raise DomainError("UPLOAD_FILE_EXISTS", f"이미 있는 파일입니다(덮어쓰지 않음): {f['rel']}", status=409, rel=f["rel"])
        if chunk_sha256 is not None and hashlib.sha256(data).hexdigest() != chunk_sha256.lower():
            raise DomainError("CHUNK_SHA256_MISMATCH", "청크 sha256이 다릅니다(쓰지 않음) — 같은 offset으로 다시 보내세요", status=422,
                              received=received)
        key = (upload_id, index)
        h = _hash_state(key, part, received)
        if data:
            try:
                U.append_chunk(part, data, up_dir)  # 사전할당·fsync 없이 append(재시작 시 received = .part 크기)
            except OSError as exc:
                if exc.errno in _NO_SPACE:
                    _hash_put(key, None, None)
                    raise DomainError(INSUFFICIENT, "디스크 공간이 부족합니다 — 공간을 확보한 뒤 같은 파일을 이어 올리세요(받은 부분은 유지)",
                                      status=507, received=U.part_size(part)) from exc
                raise
            h.update(data)
        received += len(data)
        _hash_put(key, h, received)
        if received == f["size"]:
            sha = h.hexdigest()
            _hash_put(key, None, None)
            if f.get("sha256_expected") and sha != f["sha256_expected"]:
                U.move_to_backup(root, U.user_segment(up["username"], up["user_id"]), part,
                                         f"{os.path.basename(up_dir)}__{'_'.join(segs_of(f))}.mismatch")
                raise DomainError("SHA256_MISMATCH", f"sha256이 다릅니다 — 처음부터 다시 올리세요: {f['rel']}", status=422, rel=f["rel"],
                                  expected=f["sha256_expected"], actual=sha, received=0)
            if os.path.lexists(p):
                raise DomainError("UPLOAD_FILE_EXISTS", f"이미 있는 파일입니다(덮어쓰지 않음): {f['rel']}", status=409, rel=f["rel"])
            os.rename(part, p)
            f.update(done=True, sha256=sha)
        repo.update_row(conn, upload_id, files=files)
    return {"index": index, "received": received, "done": bool(f.get("done")), "sha256": f.get("sha256")}
