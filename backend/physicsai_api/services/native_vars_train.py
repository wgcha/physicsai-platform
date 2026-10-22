"""변수 정의의 학습 범위 출처 해석(native-vars.md NV-8·§5.2, v0.2.8 Altair 확장 altair-vars.md §5.2): 모델 → 데이터셋 → 데이터셋 입력의 ① DOE →
`train_does.parameters_snapshot`. 세트와 같은 엔진의 DOE만 쓴다(Native = 피처 파일, Altair = 스냅숏 + 그 DOE tpl 선언의 공칭).

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
from physicsai_core.naming import TPL_FULL_NAME, TPL_NAME
from physicsai_core.paths import resolve_in_study
from physicsai_core.stage1_train_data import train_tpl
from physicsai_core.tpl_render import parse_declarations

from ..context import AppContext
from .common import study_root
from .job_params.dataset_engine import _doe_ids


def _altair_decl(D: str) -> dict[str, float]:
    """Altair DOE 폴더 tpl의 선언 공칭 {이름: 공칭} — 전체 tpl(표지 줄)만. 옛 부분 tpl DOE의 미사용 행은 기록이 없다(= {})."""
    for name in (TPL_FULL_NAME, TPL_NAME):
        path = os.path.join(D, name)
        if not os.path.isfile(path):
            continue
        if train_tpl.scope_of_file(path) != "full":
            return {}
        try:
            with open(path, encoding="utf-8-sig") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            return {}
        return {d["name"]: d["nominal"] for d in parse_declarations(text) if d["nominal"] is not None}
    return {}


def _doe_inputs(ctx: AppContext, conn: Any, study: dict[str, Any], model: dict[str, Any], engine: str = "native"
                ) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    """학습에 쓴 READY DOE(세트와 같은 엔진) [{id, snapshot, features | altair·decl}]와 train_source. 모름이면 None."""
    ds_id = model.get("dataset_id")
    ds = datasets_repo.get(conn, ds_id) if ds_id else None
    if ds is None:
        return None
    root = study_root(ctx, study)
    ids = _doe_ids(root, ds["source_path"])
    if ids is None:
        return None
    does = [d for d in train_repo.list_does(conn, study["id"])
            if d["status"] == "READY" and (d.get("engine") or "altair") == engine and (not ids or d["id"] in ids)]
    out: list[dict[str, Any]] = []
    for d in sorted(does, key=lambda x: x["id"]):
        if engine == "altair":
            D = resolve_in_study(root, d["dir_rel"])
            out.append({"id": d["id"], "snapshot": d.get("parameters_snapshot") or [], "altair": True, "decl": _altair_decl(D)})
            continue
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
              identities: list[dict[str, Any]], engine: str = "native"
              ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, str]]]:
    """(이름 → 학습 범위|None, train_source, 안내 notes). 모델이 없으면 (None, None, [])(세트 상세 — 학습 범위를 보이지 않음)."""
    if model is None:
        return None, None, []
    found = _doe_inputs(ctx, conn, study, model, engine)
    if found is None:
        return None, None, [{"code": nv.NOTE_UNKNOWN, "message": nv.UNKNOWN_MESSAGE}]
    does, src = found
    ranges, notes = nv.train_ranges(identities, does)
    return ranges, src, notes


def identities_of(pool: list[dict[str, Any]], set_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 피처 확인용 식별 정보: 풀 항목(이름·type·body·공칭, Altair는 type·body 없음) + 세트의 쉘 두께 PROP 행(이름·공칭만)."""
    out = [{"name": e["name"], "type": e.get("type"), "body": e.get("body"), "nominal": e["nominal"]} for e in pool]
    names = {e["name"] for e in pool}
    out += [{"name": str(r["name"]), "nominal": r.get("nominal"), "prop": True} for r in set_rows
            if nv.is_prop_row(r) and str(r["name"]) not in names]
    return out
