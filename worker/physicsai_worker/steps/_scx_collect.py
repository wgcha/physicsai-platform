"""scx 모드 COLLECT: 원격 목록·대상 경로 검사·relay 다운로드(sha256 확인 후 os.replace) — _scx에서 재노출."""

from __future__ import annotations

import fnmatch
import os
import tempfile
import unicodedata
from typing import Any

from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.errors import StepFailure
from physicsai_core.hpc.gateway import HpcGatewayError
from physicsai_core.paths import (
    PathError,
    allowed_roots,
    assert_writable,
    check_user_path,
    is_under,
    windows_reserved_name,
)
from simdash_adapters.hpc.scx_naming import file_name_problem, rel_problem

from ._scx_common import MAX_LIST_ENTRIES, mask

# ---------------------------------------------------------------------------
# COLLECT
# ---------------------------------------------------------------------------

class CollectFail(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _walk(gw: Any, root: str, max_depth: int) -> list[tuple[str, int]]:
    """output_rel 아래 파일 (root 기준 상대 경로, 크기). 깊이 0 = 직속만, 항목 합계 ≤ 20000."""
    out: list[tuple[str, int]] = []
    count = 0
    stack: list[tuple[str, str, int]] = [(root, "", 0)]
    while stack:
        rel, sub, depth = stack.pop()
        for e in gw.list(rel, MAX_LIST_ENTRIES):
            count += 1
            if count > MAX_LIST_ENTRIES:
                raise CollectFail("COLLECT_FAILED", f"결과 폴더 항목이 {MAX_LIST_ENTRIES}개를 넘습니다")
            name = str(e.get("name") or "")
            if file_name_problem(name):
                continue
            child_sub = f"{sub}/{name}" if sub else name
            if e.get("kind") == "dir":
                if depth < max_depth:
                    stack.append((f"{rel}/{name}", child_sub, depth + 1))
            elif e.get("kind") == "file":
                out.append((child_sub, int(e.get("size") or 0)))
    return sorted(out)


WINDOWS_BAD_CHARS = frozenset('?*<>"|:')


def _safe_target(ctx: Any, result_dir: str, rel: str) -> str:
    """원격 상대 경로 → 결과 폴더 안 로컬 경로. Windows에서 쓸 수 없는 이름(예약어 CON·NUL…, `?*<>"|:`, 끝 마침표·공백)·`..`·
    링크·AI 루트 밖·이미 있는 폴더 이름이면 PATH_UNSAFE."""
    parts = rel.split("/")
    for p in parts:
        if p in ("", ".", "..") or file_name_problem(p) or windows_reserved_name(p) or WINDOWS_BAD_CHARS.intersection(p):
            raise CollectFail("PATH_UNSAFE", f"결과 파일 경로를 쓸 수 없습니다(Windows 예약 이름·금지 문자 포함): {rel[:200]}")
    dst = os.path.join(result_dir, *parts)
    try:
        check_user_path(dst, allowed_roots(ctx.settings, imports=False), expect="file", must_exist=False)
        assert_writable(dst)
    except PathError as exc:
        raise CollectFail("PATH_UNSAFE", f"결과 파일을 AI 루트에 쓸 수 없습니다({exc.message}): {rel[:200]}") from None
    except StepFailure as exc:
        raise CollectFail("PATH_UNSAFE", f"{exc.message}: {rel[:200]}") from None
    if not is_under(os.path.realpath(dst), os.path.realpath(result_dir)):
        raise CollectFail("PATH_UNSAFE", f"결과 폴더 밖 경로입니다: {rel[:200]}")
    if os.path.isdir(dst):
        raise CollectFail("PATH_UNSAFE", f"같은 이름의 폴더가 이미 있습니다: {rel[:200]}")
    return dst


def _collisions(rels: list[str]) -> str | None:
    """대소문자만 다른 경로(A.h3d·a.h3d) 또는 파일 이름이 다른 파일의 상위 폴더 이름과 같은 경우(Windows에서 덮어씀·충돌)."""
    seen: dict[str, str] = {}
    for r in rels:
        k = unicodedata.normalize("NFC", r).casefold()
        if k in seen:
            return f"{seen[k]} · {r}"
        seen[k] = r
    for r in rels:
        parts = unicodedata.normalize("NFC", r).casefold().split("/")
        for i in range(1, len(parts)):
            d = "/".join(parts[:i])
            if d in seen:
                return f"{seen[d]} · {r}"
    return None


def collect_run(ctx: Any, gw: Any, row: dict[str, Any], result_dir: str, health_max: int | None) -> list[str]:
    """SUCCEEDED 행 1개 회수. 받은 상대 경로 목록. 실패면 CollectFail(그 run만 회수 실패)."""
    s = ctx.settings
    out_rel = row.get("output_rel")
    if not out_rel and row.get("external_job_id"):
        try:
            st = gw.status(row["external_job_id"])
            out_rel = st.output_rel
            if out_rel:
                ctx.ex.db(lambda c: hpc_repo.set_fields(c, row["id"], output_rel=out_rel, output_path=st.output_path))
        except HpcGatewayError as exc:
            raise CollectFail("COLLECT_FAILED", mask(ctx, f"SCX 잡 상태를 다시 받지 못했습니다: {exc}")) from None
    if not out_rel:
        raise CollectFail("SCX_OUTPUT_MISSING", "SCX 결과 위치 없음")
    if rel_problem(out_rel):
        raise CollectFail("SCX_OUTPUT_MISSING", f"SCX 결과 위치 형식 오류: {out_rel[:200]}")
    pats = s.hpc.transfer.collect_patterns
    limit = min(int(gw.cfg.max_download_bytes), int(s.hpc.transfer.max_collect_bytes),
                int(health_max) if health_max else int(gw.cfg.max_download_bytes))
    try:
        files = [(r, sz) for r, sz in _walk(gw, out_rel, int(gw.cfg.collect_max_depth))
                 if any(fnmatch.fnmatch(r.rsplit("/", 1)[-1], pat) for pat in pats)]
    except HpcGatewayError as exc:
        raise CollectFail("COLLECT_FAILED", mask(ctx, f"SCX 결과 목록 실패: {exc}")) from None
    if not files:
        raise CollectFail("COLLECT_FAILED", "결과 파일 없음")
    big = [r for r, sz in files if sz > limit]
    if big:
        raise CollectFail("COLLECT_FAILED", f"회수 파일이 상한을 넘습니다: {big[0]}")
    clash = _collisions([r for r, _sz in files])
    if clash:
        raise CollectFail("PATH_UNSAFE", f"대소문자·폴더 이름만 다른 결과 파일이 겹칩니다: {clash[:200]}")
    targets = [(r, _safe_target(ctx, result_dir, r)) for r, _sz in files]  # 하나라도 안 되면 내려받기 전에 그 run 실패
    got: list[str] = []
    for r, dst in targets:
        try:
            got.append(_download_one(ctx, gw, f"{out_rel}/{r}", r, dst, limit))
        except OSError as exc:
            raise CollectFail("COLLECT_FAILED", f"결과 파일을 쓸 수 없습니다({type(exc).__name__}): {r[:200]}") from None
    return got


def _download_one(ctx: Any, gw: Any, remote: str, r: str, dst: str, limit: int) -> str:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    for attempt in (1, 2):
        ctx.checkpoint()
        # `<이름>.<임의>.part`(같은 폴더) — 성공하면 os.replace, 실패·취소면 tempfile이 지운다(.part를 남기지 않음, §16.4 9)
        with tempfile.NamedTemporaryFile(dir=os.path.dirname(dst), prefix=os.path.basename(dst) + ".", suffix=".part",
                                         delete=True, delete_on_close=False) as tf:
            tf.close()
            try:
                gw.download(remote, tf.name, limit, on_chunk=lambda _n: ctx.checkpoint())
            except HpcGatewayError as exc:
                if exc.relay_code == "HASH_MISMATCH" and attempt == 1:
                    ctx.log(f"SCX 다운로드 해시 불일치 — 1회 다시 받습니다: {r}")
                    continue
                raise CollectFail("COLLECT_FAILED", f"SCX 다운로드 실패({r}): {mask(ctx, str(exc))}") from None
            os.replace(tf.name, dst)
        return r
    raise CollectFail("COLLECT_FAILED", f"SCX 다운로드 실패({r})")
