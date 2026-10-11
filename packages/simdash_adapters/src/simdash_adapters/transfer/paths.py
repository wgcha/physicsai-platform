"""PBS 경로 변환·회수 경로 해석(순수 함수, 파일 시스템을 건드리지 않는다)."""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

from ..pathstr import fwd

SHARED_COLLECT_MODES = ("shared_folder", "drive")


def map_path(path: str, path_map: Iterable[Any]) -> str:
    """로컬 경로 → PBS 원격 경로(path_map 첫 일치 접두, 대소문자 무시). 항목은 `.local`·`.remote` 속성을 가진다."""
    p = fwd(path)
    for m in path_map:
        local = fwd(m.local).rstrip("/")
        if p.lower().startswith(local.lower() + "/") or p.lower() == local.lower():
            return fwd(m.remote).rstrip("/") + p[len(local):]
    return p


def resolve_collect_dirs(transfer: Any, *, study_folder: str, doe_id: str, run_key: str,
                         local_result_dir: str) -> tuple[str, str | None]:
    """(PBS result_dir, 회수할 로컬 경로 | None=in_place).

    shared_folder·drive: 원격 = `collect_root_remote/<study>/<doe>/<run>`, 로컬 = `collect_root_local/<study>/<doe>/<run>`.
    그 밖(in_place): 원격 = `map_path(local_result_dir)`, 회수 없음.
    """
    if transfer.collect_mode in SHARED_COLLECT_MODES:
        sub = f"{study_folder}/{doe_id}/{run_key}"
        remote = fwd(transfer.collect_root_remote).rstrip("/") + "/" + sub
        local = os.path.join(os.path.normpath(transfer.collect_root_local), study_folder, doe_id, run_key)
        return remote, local
    return map_path(local_result_dir, transfer.path_map), None
