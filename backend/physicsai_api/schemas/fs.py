"""API 스키마 — 서버 경로 탐색(phase3 §12 S7, D3-46). 이름·종류·크기·mtime만(파일 내용 없음)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from .common import Resp

__all__ = ["FsRoot", "FsRoots", "FsEntry", "FsList"]


class FsRoot(Resp):
    key: str
    label: str
    path: str


class FsRoots(Resp):
    roots: list[FsRoot]
    inbox_share_hint: str | None = None


class FsEntry(Resp):
    name: str
    type: Literal["dir", "file"]
    size: int | None = None
    mtime: datetime


class FsList(Resp):
    path: str
    parent: str | None
    entries: list[FsEntry]
    truncated: bool
