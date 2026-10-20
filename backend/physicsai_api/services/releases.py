"""플랫폼 버전·버전 게시판 조회(읽기 전용 — 배포 RELEASES.md로만 기록). 파일 위치: 프런트 배치 폴더(설치) → 저장소(소스 실행)."""

from __future__ import annotations

from physicsai_core import __version__
from physicsai_core import releases as R

from ..context import AppContext
from ..frontend_static import effective_root


def version_info(ctx: AppContext) -> dict:
    root = effective_root(ctx.settings)
    info = R.load_build_info(root)
    build = {"source_hash": info.get("source_hash"), "built_at": info.get("built_at")} if info else None
    commit = (info or {}).get("git_commit") or R.git_commit_of(R.source_repo_root())
    return {"platform_version": __version__, "paicad_version": R.installed_version("paicad"), "build": build, "git_commit": commit}


def releases(ctx: AppContext) -> dict:
    rels = R.load_releases(effective_root(ctx.settings))
    return {"current_version": __version__, "releases": [{"version": r.version, "date": r.date, "items": list(r.items)} for r in rels]}
