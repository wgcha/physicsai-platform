"""⑤ 플랫폼 내장 최적화 저장소 조회(라벨·폴더·번호·행·반복·배치 소유) — surrogate_opts에서 재노출."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.engine import Connection

from ..tables import surrogate_opt_iters, surrogate_opts
from .jobs import row_dict

ACTIVE = ("EXPLORING", "FITTING", "VERIFYING", "FINALIZING")
TERMINAL_OPT = ("DONE", "FAILED", "CANCELED")
ROUND_JOB_TYPE = "SURROGATE_OPT"
# 반복 작업 실패 코드 중 정지 사유로 그대로 쓰는 것(그 밖은 ROUND_FAILED)
ROUND_FAIL_REASONS = ("VERIFY_ALL_FAILED", "TOO_FEW_POINTS", "SURROGATE_TIMEOUT", "SURROGATE_FIT_FAILED", "NO_FREE_VARIABLE")


def opt_label(opt_no: int) -> str:
    """opt_no → `SO-001`."""
    return f"SO-{int(opt_no):03d}"


def opt_dir_rel(dir_name: str, opt_no: int) -> str:
    return f"{dir_name.rstrip('/')}/{opt_label(opt_no)}"


def new_opt_id() -> str:
    return str(uuid.uuid4())


# ---- 조회 --------------------------------------------------------------------------------------


def next_opt_no(conn: Connection, study_id: str) -> int:
    """Study별 다음 opt_no(1부터). 호출부가 Study 행을 FOR UPDATE로 잠근 트랜잭션에서 부른다(D3-25)."""
    cur = conn.execute(select(func.max(surrogate_opts.c.opt_no)).where(surrogate_opts.c.study_id == study_id)).scalar()
    return int(cur or 0) + 1


def get(conn: Connection, opt_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(surrogate_opts).where(surrogate_opts.c.id == opt_id)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def list_for_study(conn: Connection, study_id: str, limit: int = 200) -> list[dict[str, Any]]:
    q = (select(surrogate_opts).where(surrogate_opts.c.study_id == study_id)
         .order_by(surrogate_opts.c.opt_no.desc()).limit(limit))
    return [row_dict(r) for r in conn.execute(q)]


def active_for_study(conn: Connection, study_id: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(surrogate_opts).where(and_(
        surrogate_opts.c.study_id == study_id, surrogate_opts.c.status.in_(ACTIVE)))).first())


def iters(conn: Connection, opt_id: str) -> list[dict[str, Any]]:
    q = select(surrogate_opt_iters).where(surrogate_opt_iters.c.opt_id == opt_id).order_by(surrogate_opt_iters.c.iter_no)
    return [row_dict(r) for r in conn.execute(q)]


def get_iter(conn: Connection, opt_id: str, iter_no: int) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(surrogate_opt_iters).where(and_(
        surrogate_opt_iters.c.opt_id == opt_id, surrogate_opt_iters.c.iter_no == iter_no))).first())


def owned_iter_of_batch(conn: Connection, batch_id: str) -> dict[str, Any] | None:
    """배치를 소유한(EXPLORE·VERIFY·FINAL) 반복 행 + opt 열(opt_status·opt_iter_no). 재사용(REUSE) 배치와 추가 검증(EXTRA,
    S17 §22.7 — 끝난 최적화의 일반 배치처럼 ④에서 취소·실패만 다시, 종료 훅은 반복 작업 없이 PREDICT_BATCH_DONE)은 소유가 아니다."""
    q = (select(surrogate_opt_iters, surrogate_opts.c.status.label("opt_status"), surrogate_opts.c.iter_no.label("opt_iter_no"),
                surrogate_opts.c.opt_no.label("opt_no"))
         .select_from(surrogate_opt_iters.join(surrogate_opts, surrogate_opts.c.id == surrogate_opt_iters.c.opt_id))
         .where(and_(surrogate_opt_iters.c.batch_id == batch_id, surrogate_opt_iters.c.kind.notin_(("REUSE", "EXTRA")))))
    return row_dict(conn.execute(q).first())


def batch_owner(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """PREDICT_BATCH params.surrogate_opt `{id, opt_no, iter_no}`(최적화 소유 배치) 또는 None."""
    so = (params or {}).get("surrogate_opt") if isinstance(params, Mapping) else None
    return dict(so) if isinstance(so, Mapping) and isinstance(so.get("id"), str) else None
