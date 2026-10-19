"""DATASET_CREATE의 형상 엔진 판별(geometry-engine.md §7.7·§17.4): input_path가 `01_train/results/<doe_id>`(또는 doe) 아래면 그 DOE의 engine."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import DomainError
from physicsai_core.geometry.reports import same_major_minor

from ...context import AppContext
from ..common import study_root

# 계약 §7.7은 `01_train/doe/<doe_id>`라 쓰지만 ③-1은 그 폴더를 입력으로 받지 않는다(check_dataset_input) — 실제 입력은 결과 회수 폴더
DOE_PREFIXES = (("01_train", "results"), ("01_train", "doe"))


def _doe_ids(root: str, input_path: str) -> list[str] | None:
    """input_path의 DOE 소속: DOE 폴더 아래면 [id], `01_train/doe` 자체면 [](전체), 그 밖은 None(판별 불가)."""
    try:
        rel = os.path.relpath(os.path.realpath(input_path), os.path.realpath(root))
    except ValueError:
        return None
    parts = [x for x in rel.replace("\\", "/").split("/") if x and x != "."]
    if tuple(parts[:2]) not in DOE_PREFIXES:
        return None
    return parts[2:3]


def detect(ctx: AppContext, conn: Any, study: dict[str, Any], input_path: str
           ) -> tuple[str | None, str | None, list[dict[str, str]]]:
    """(engine, engine_version, 경고). altair·native가 섞이면 422 ENGINE_MIXED. 판별 불가는 (None, None, [])."""
    ids = _doe_ids(study_root(ctx, study), input_path)
    if ids is None:
        return None, None, []
    does = [d for d in train_repo.list_does(conn, study["id"]) if d["status"] == "READY" and (not ids or d["id"] in ids)]
    engines = {d["engine"] for d in does}
    if len(engines) > 1:
        raise DomainError("ENGINE_MIXED", "altair·native 학습데이터를 한 데이터셋에 섞을 수 없습니다", status=422)
    if not engines:
        return None, None, []
    engine = engines.pop()
    if engine != "native":
        return engine, None, []
    vers = sorted({d["engine_version"] for d in does if d.get("engine_version")})
    if len(vers) <= 1:
        return engine, vers[0] if vers else None, []
    warn = []
    if any(not same_major_minor(vers[0], v) for v in vers[1:]):
        warn = [{"code": "ENGINE_VERSION_MIXED",
                 "message": f"형상 엔진 버전이 다른 학습데이터가 섞였습니다({', '.join(vers)}) — 형상 결과가 다를 수 있습니다"}]
    return engine, None, warn
