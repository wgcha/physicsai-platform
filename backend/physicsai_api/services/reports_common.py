"""보고서 원천 읽기 공용(upload-report.md §9.3 ② 입력 요약): 엔진 정보·모델·출처("내 PC에서 올림") 문구."""

from __future__ import annotations

import logging
import os
from typing import Any

from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo

from ..context import AppContext

log = logging.getLogger(__name__)


def study_info(study: dict[str, Any]) -> dict[str, Any]:
    return {"id": study["id"], "title": study["title"], "folder_name": study["folder_name"], "project_id": study["project_id"]}


def engine_info(ctx: AppContext, ps: dict[str, Any] | None) -> dict[str, Any]:
    """형상 엔진 표시(Native: paicad 버전·솔리드/쉘, Altair: SimLab)."""
    if not ps:
        return {}
    eng = ps.get("engine") or "altair"
    out: dict[str, Any] = {"engine": eng, "version": ps.get("engine_version"), "kind": None}
    if eng == "native":
        try:
            from physicsai_core.geometry.shell_native import read_kind

            from .param_set_native_api import set_path

            out["kind"] = read_kind(set_path(ctx, ps))
        except Exception:  # noqa: BLE001 - 표시용 부가 정보, 실패해도 보고서는 계속
            log.debug("보고서 형상 종류 확인 실패", exc_info=True)
    return out


def param_set_info(ps: dict[str, Any] | None) -> dict[str, Any]:
    p = ps or {}
    return {"id": p.get("id"), "label": p.get("label"), "input_kind": p.get("input_kind") or "assembly", "source_path": p.get("source_path")}


def model_info(conn: Any, study: dict[str, Any], model_id: str | None) -> dict[str, Any]:
    m = models_repo.get(conn, model_id) if model_id else None
    if not m:
        return {}
    return {"id": m["id"], "name": m["name"], "version": m["version"], "label": m.get("label"), "is_final": study.get("final_model_id") == m["id"],
            "eval_score": m.get("eval_score"), "source_path": m.get("source_path")}


def load_param_set(conn: Any, ps_id: str | None) -> dict[str, Any] | None:
    return ps_repo.get(conn, ps_id) if ps_id else None


def require_study(conn: Any, study_id: str) -> dict[str, Any]:
    return studies_repo.require(conn, study_id)


# ---- 입력 출처(업로드) ------------------------------------------------------------------------------------


def uploads_lookup(ctx: AppContext, conn: Any, study_id: str) -> list[dict[str, Any]]:
    """완료된 업로드 세션 행(`uploads` — 업로드 브랜치 migration 0021 이후에만 존재). 테이블이 없거나 열이 다르면 빈 목록(보고서는 계속)."""
    try:
        from sqlalchemy import inspect, text

        if not inspect(conn).has_table("uploads"):
            return []
        rows = conn.execute(text("select dir_rel, username, created_at from uploads where study_id = :s and state = 'COMPLETED'"), {"s": study_id}).all()
        return [{"dir_rel": r[0], "username": r[1], "at": r[2]} for r in rows]
    except Exception:  # noqa: BLE001
        log.debug("업로드 출처 조회 실패(무시)", exc_info=True)
        return []


def origin_text(ctx: AppContext, rows: list[dict[str, Any]], path: str | None) -> str | None:
    """경로가 업로드 폴더(`<ai_root>/<dir_rel>`) 아래면 "내 PC에서 올림 · 10-21 14:02 · 홍길동"(표시용)."""
    if not path or not rows:
        return None
    root = os.path.normpath(ctx.settings.storage.ai_root)
    p = os.path.normcase(os.path.normpath(path))
    for r in rows:
        base = os.path.normcase(os.path.normpath(os.path.join(root, str(r["dir_rel"]))))
        if p == base or p.startswith(base + os.sep):
            at = r.get("at")
            when = at.strftime("%m-%d %H:%M") if hasattr(at, "strftime") else ""
            return f"내 PC에서 올림 · {when} · {r.get('username') or ''}".replace("  ", " ").strip(" ·")
    return None


def origins(ctx: AppContext, conn: Any, study_id: str, items: list[tuple[str, str | None]]) -> list[tuple[str, str]]:
    """[(라벨, 경로)] → 입력 경로 표시값(+업로드 출처 문구) 줄. 경로가 없으면 뺀다."""
    rows = uploads_lookup(ctx, conn, study_id)
    out = []
    for label, path in items:
        if not path:
            continue
        tag = origin_text(ctx, rows, path)
        out.append((label, f"{path}" + (f"  ({tag})" if tag else "")))
    return out
