"""API 스키마 — 플랫폼 버전·버전 게시판(읽기 전용, RELEASES.md — 배포로만 기록)."""

from __future__ import annotations

from .common import Resp

__all__ = ["BuildInfo", "VersionInfo", "ReleaseEntry", "ReleasesResponse"]


class BuildInfo(Resp):
    source_hash: str | None = None
    built_at: str | None = None


class VersionInfo(Resp):
    platform_version: str
    paicad_version: str | None = None
    build: BuildInfo | None = None
    git_commit: str | None = None


class ReleaseEntry(Resp):
    version: str
    date: str
    items: list[str]


class ReleasesResponse(Resp):
    current_version: str
    releases: list[ReleaseEntry]
