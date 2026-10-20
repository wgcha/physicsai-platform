"""범주 baseline(다중 baseline 위상 변형)의 대리모델 입력 인코딩(opt-native §7) — 순수 함수, numpy만(워커 전용).

학습 입력 규칙(geometry-engine §7.3.8, `baselines.training_values`)과 같은 열: 공통 변수(그 수준에서 N/A면 0) + `<이름>__na` 지시 열
(N/A면 1) + `baseline__<id>` 원-핫. 대리모델 입력은 공통 변수만 탐색 범위로 [0,1] 정규화한 값(지시·원-핫은 0/1 그대로)이다.

spec(설정에서 만든 사전, FitResult.encoding으로 저장):
  {"cat": "baseline", "levels": [id…], "active": {이름: [수준별 활성 bool]}, "na": [N/A 가능 이름(학습 열 순서)]}
설계 값의 범주는 수준 인덱스(0..L−1, levels 순서)로 둔다. 비활성 변수의 값은 0(배치 values의 N/A 규칙과 같음).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

CAT = "baseline"
NA_SUFFIX = "__na"
ONEHOT_PREFIX = "baseline__"


def make_spec(settings: Mapping[str, Any]) -> dict[str, Any] | None:
    """저장 settings의 범주 spec(위상 변형 세트만, 없으면 None) — dataset.cat_spec과 같음."""
    from .dataset import cat_spec

    return cat_spec(settings)


def columns(spec: Mapping[str, Any], free: Sequence[str]) -> list[str]:
    """대리모델 입력 열 이름: 자유 공통 변수(범주 제외) + 지시 열 + 원-핫."""
    return ([n for n in free if n != spec["cat"]] + [n + NA_SUFFIX for n in spec["na"]]
            + [ONEHOT_PREFIX + b for b in spec["levels"]])


def level_index(X: np.ndarray, free: Sequence[str], spec: Mapping[str, Any], fixed_level: int = 0) -> np.ndarray:
    L = len(spec["levels"])
    if spec["cat"] in free:
        j = list(free).index(spec["cat"])
        return np.clip(np.round(np.asarray(X, dtype=float)[:, j]), 0, L - 1).astype(int)
    return np.full(len(X), int(fixed_level), dtype=int)


def active_matrix(spec: Mapping[str, Any], names: Sequence[str]) -> np.ndarray:
    """(L, len(names)) 활성 표(spec.active에 없는 이름 = 모든 수준 활성)."""
    L = len(spec["levels"])
    return np.array([[spec["active"].get(n, [True] * L)[lv] for n in names] for lv in range(L)], dtype=bool).reshape(L, len(names))


def transform(X: np.ndarray, free: Sequence[str], lo: np.ndarray, hi: np.ndarray, spec: Mapping[str, Any],
              fixed_level: int = 0) -> np.ndarray:
    """원 단위 자유 변수 행렬(범주 = 수준 인덱스) → 대리모델 입력(columns 순서)."""
    X = np.atleast_2d(np.asarray(X, dtype=float))
    lvl = level_index(X, free, spec, fixed_level)
    span = np.where(np.asarray(hi) - np.asarray(lo) > 0, np.asarray(hi) - np.asarray(lo), 1.0)
    Xn = (X - lo) / span
    keep = [j for j, n in enumerate(free) if n != spec["cat"]]
    names = [free[j] for j in keep]
    A = active_matrix(spec, names)
    vals = Xn[:, keep] * A[lvl] if keep else np.zeros((len(X), 0))
    Na = active_matrix(spec, spec["na"])
    ind = 1.0 - Na[lvl].astype(float) if spec["na"] else np.zeros((len(X), 0))
    onehot = np.eye(len(spec["levels"]))[lvl]
    return np.hstack([vals, ind, onehot])


def effective(X: np.ndarray, free: Sequence[str], spec: Mapping[str, Any], fixed_level: int = 0) -> np.ndarray:
    """유효값(중복·거리): 그 수준에서 비활성인 공통 변수는 NaN."""
    X = np.array(np.atleast_2d(X), dtype=float, copy=True)
    lvl = level_index(X, free, spec, fixed_level)
    for j, n in enumerate(free):
        if n == spec["cat"] or n not in spec["active"]:
            continue
        act = np.asarray(spec["active"][n], dtype=bool)[lvl]
        X[~act, j] = np.nan
    return X


def canonical(values: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    """설계 값의 N/A 정리: 배정 수준에서 비활성인 공통 변수 = 0.0(배치 values 규칙)."""
    out = dict(values)
    lv = out.get(spec["cat"])
    if lv is None:
        return out
    li = int(round(float(lv)))
    for n, act in spec["active"].items():
        if n in out and 0 <= li < len(act) and not act[li]:
            out[n] = 0.0
    return out


def training_view(row: Mapping[str, Any], spec: Mapping[str, Any], common: Sequence[str]) -> dict[str, float]:
    """한 행의 학습 입력 값(원 단위 — `baselines.training_values`와 같은 규칙) — 시험·미리보기 비교용."""
    li = int(round(float(row[spec["cat"]])))
    out: dict[str, float] = {}
    for n in common:
        act = spec["active"].get(n, [True] * len(spec["levels"]))[li]
        out[n] = float(row[n]) if act and row.get(n) is not None else 0.0
    for n in spec["na"]:
        out[n + NA_SUFFIX] = 0.0 if spec["active"].get(n, [True] * len(spec["levels"]))[li] and row.get(n) is not None else 1.0
    for k, b in enumerate(spec["levels"]):
        out[ONEHOT_PREFIX + b] = 1.0 if k == li else 0.0
    return out
