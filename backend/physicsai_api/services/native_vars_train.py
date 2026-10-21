"""Native 변수 정의의 학습 범위 출처 해석(native-vars.md NV-8·§5.2): 모델 → 데이터셋 → 데이터셋 입력의 ① DOE → `train_does.parameters_snapshot`.

모델·데이터셋에는 파라미터 범위 메타가 없다. 추적할 수 없으면 `(None, None)` — 호출부가 `TRAIN_RANGE_UNKNOWN` 안내 1줄을 낸다.
순수 계산(구간 합집합·같은 피처 확인)은 `physicsai_core.geometry.native_vars.train_ranges`.
"""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.db.repositories import datasets as datasets_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.geometry import native_vars as nv
from physicsai_core.geometry.reports import ReportError, read_report
from physicsai_core.geometry.shell_native import features_name, read_kind
from physicsai_core.paths import resolve_in_study

from ..context import AppContext
from .common import study_root
from .job_params.dataset_engine import _doe_ids


def _doe_inputs(ctx: AppContext, conn: Any, study: dict[str, Any], model: dict[str, Any]
                ) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    """학습에 쓴 READY·native DOE [{id, snapshot, features}]와 train_source. 모름이면 None."""
    ds_id = model.get("dataset_id")
    ds = datasets_repo.get(conn, ds_id) if ds_id else None
    if ds is None:
        return None
    root = study_root(ctx, study)
    ids = _doe_ids(root, ds["source_path"])
    if ids is None:
        return None
    does = [d for d in train_repo.list_does(conn, study["id"])
            if d["status"] == "READY" and d.get("engine") == "native" and (not ids or d["id"] in ids)]
    out: list[dict[str, Any]] = []
    for d in sorted(does, key=lambda x: x["id"]):
        try:
            D = resolve_in_study(root, d["dir_rel"])
            doc = read_report(os.path.join(D, "native", "extract", features_name(read_kind(D))), ctx.settings.geometry.max_report_bytes)
        except (ReportError, ValueError, OSError):
            continue  # 피처 파일을 읽을 수 없는 DOE(Study 정리 등)는 건너뜀 — 같은 피처 확인이 불가능
        out.append({"id": d["id"], "snapshot": d.get("parameters_snapshot") or [], "features": doc})
    if not out:
        return None
    return out, {"model_id": model["id"], "dataset_id": ds["id"], "doe_ids": [d["id"] for d in out]}


def train_for(ctx: AppContext, conn: Any, study: dict[str, Any], model: dict[str, Any] | None,
              identities: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, str]]]:
    """(이름 → 학습 범위|None, train_source, 안내 notes). 모델이 없으면 (None, None, [])(세트 상세 — 학습 범위를 보이지 않음)."""
    if model is None:
        return None, None, []
    found = _doe_inputs(ctx, conn, study, model)
    if found is None:
        return None, None, [{"code": nv.NOTE_UNKNOWN, "message": nv.UNKNOWN_MESSAGE}]
    does, src = found
    ranges, notes = nv.train_ranges(identities, does)
    return ranges, src, notes


def identities_of(pool: list[dict[str, Any]], set_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 피처 확인용 식별 정보: 풀 항목(이름·type·body·공칭) + 세트의 쉘 두께 PROP 행(이름·공칭만)."""
    out = [{"name": e["name"], "type": e["type"], "body": e["body"], "nominal": e["nominal"]} for e in pool]
    names = {e["name"] for e in pool}
    out += [{"name": str(r["name"]), "nominal": r.get("nominal"), "prop": True} for r in set_rows
            if nv.is_prop_row(r) and str(r["name"]) not in names]
    return out
