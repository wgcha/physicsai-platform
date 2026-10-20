"""단계 4B 다중 baseline(geometry-engine.md §4.10·§7.3.8·§11.4) — 순수 함수(파일 쓰기·DB는 호출자).

세트 S에 `S/param_map.json`이 있으면 다중 baseline 세트다(없으면 기존 단일 경로 — 분기 1곳, §16 8).
- baseline 목록 = param_map.json `baselines[{id, rel}]`. 첫 baseline(`base`)은 S 자신(rel ".", 복사·이동 없음),
  추가 baseline은 `S/baselines/<id>/{cad, radioss_assem, native/, baseline.json}`.
- 행마다 `proposed`(paicad 제안, 편집 불가)와 `decision`(사용자 결정, 플랫폼만 씀). 유효 대응은 항상 decision.map.
- 확정(`status: confirmed`) 전에는 DOE·일괄 생성 불가(409 PARAM_MAP_UNCONFIRMED, 단건 예측은 대상 아님).
- 공통 이름 → baseline 원 이름 변환·샘플 배정·층화 LHS·학습 입력 열(N/A 지시 열·원-핫)은 플랫폼이 한다(§18).
300줄 분할(R-B): 상수·`MapError`·`Var`·파일·목록 = `baselines_base`, 결정·확정 = `baselines_decide`, 파라미터 표·샘플 배정·층화 LHS =
`baselines_table`(여기서 재노출 — 호출부는 `from physicsai_core.geometry import baselines as bl` 그대로).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from .baselines_base import (  # noqa: F401 - 300줄 분할(R-B), 기존 경로 재노출
    PARAM_MAP, BASELINES_DIR, BASELINE_JSON, SINGLE_PARAMS, BASE_ID, ID_RE, NAME_RE, RESERVED, NA_SUFFIX,
    ONEHOT_PREFIX, ACTIONS, USAGES, NO_COVER, MapError, Var, map_path, is_multi, load, load_file, shape_problems,
    baseline_ids, baseline_rel, baseline_root, baselines_input,
)
from .baselines_decide import (  # noqa: F401 - 300줄 분할(R-B), 기존 경로 재노출
    _rows, unresolved, undecided_count, accept_decision, _decision_parts, normalize_decision, decision_problems,
    put_decisions, confirm, to_draft, inherit, drop_baseline, variables, display_names,
)
from .baselines_table import (  # noqa: F401 - 300줄 분할(R-B), 기존 경로 재노출
    _range_of, feasible_of, parameter_rows, _per, assign_baseline, original_values, na_names, training_columns,
    training_values, training_snapshot, stratum_counts, _split_intervals, range_gaps, stratified_lhs,
)


# ------------------------------------------------------------------ 세트 폴더 읽기(API·워커 공용)
FEATURES_REL = "native/extract/parameter_features.json"


def features_path(root: str) -> str:
    """준비본 features 파일(솔리드 parameter_features.json | 쉘 shell_features.json — prep.json kind, shell-morph.md §7.2)."""
    from .shell_native import features_name, read_kind

    return os.path.join(root, "native", "extract", features_name(read_kind(root)))


def _read_json(path: str, max_bytes: int) -> dict[str, Any] | None:
    try:
        if os.path.getsize(path) > max_bytes:
            return None
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _rep_features(doc: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not doc:
        return {}
    members: set[str] = set()
    reps: set[str] = set()
    for g in doc.get("groups") or []:
        if isinstance(g, dict) and isinstance(g.get("parameter"), str):
            reps.add(g["parameter"])
            members |= {m for m in g.get("members") or [] if isinstance(m, str)}
    return {f["name"]: f for f in doc.get("features") or []
            if isinstance(f, dict) and isinstance(f.get("name"), str) and (f["name"] in reps or f["name"] not in members)}


def read_baselines(S: str, pm: Mapping[str, Any], max_bytes: int) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, dict[str, dict[str, Any]]]]:
    """({bid: {원 이름: 대표 피처}}, {bid: {원 이름: 파라미터 표 행}}). base 표 = 다중 전환 전 단일 표(single_parameters.json) 우선."""
    feats: dict[str, dict[str, dict[str, Any]]] = {}
    rows: dict[str, dict[str, dict[str, Any]]] = {}
    for b in baseline_ids(pm):
        root = baseline_root(S, pm, b)
        feats[b] = _rep_features(_read_json(features_path(root), max_bytes))
        pj = os.path.join(S, *SINGLE_PARAMS.split("/")) if root == S and os.path.isfile(os.path.join(S, *SINGLE_PARAMS.split("/"))) \
            else os.path.join(root, "parameters.json")
        doc = _read_json(pj, max_bytes) or {}
        rows[b] = {str(r["name"]): r for r in doc.get("parameters") or []
                   if isinstance(r, dict) and isinstance(r.get("name"), str) and r.get("source") != "prop"
                   and all(isinstance(r.get(k), (int, float)) for k in ("nominal", "min", "max"))}
    return feats, rows


def rep_features_at(root: str, max_bytes: int) -> dict[str, dict[str, Any]]:
    return _rep_features(_read_json(features_path(root), max_bytes))


def known_names(feats: Mapping[str, Mapping[str, Any]]) -> dict[str, set[str]]:
    return {b: set(f) for b, f in feats.items()}
