"""①-3 다른 DOE의 표본표 재사용(equiv-check.md Q1 확정, 2026-10-20): 같은 Study의 READY DOE samples.csv를 그대로 표본으로 쓴다.

run 이름(run_key)을 유지해 등가성 판정 쌍 매칭 키(by_name)로 쓰고, 파라미터 이름 집합이 같을 때만 허용한다(native·altair 모두).
읽기만 한다(API 사전조건·워커 DG_PREP 공용)."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

from ..db.repositories import train as train_repo
from ..stage4_predict.run_metrics import safe_study_path
from .doe_samples import read_samples_csv

Samples = tuple[list[str], list[dict[str, Any]]]


def load_reuse_samples(conn: Any, study_id: str, study_root: str, doe_id: str) -> tuple[Samples | None, dict[str, str] | None]:
    """(samples, None) 또는 (None, problem{code, message}). problem: SOURCE_DOE_NOT_FOUND | SOURCE_DOE_NOT_READY | SOURCE_SAMPLES_MISSING."""
    d = train_repo.get_doe(conn, doe_id)
    if d is None or d["study_id"] != study_id:
        return None, {"code": "SOURCE_DOE_NOT_FOUND", "message": "표본표를 재사용할 DOE를 이 Study에서 찾을 수 없습니다"}
    if d["status"] != "READY" or d["sample_status"] not in ("PARSED", "PARTIAL"):
        return None, {"code": "SOURCE_DOE_NOT_READY", "message": f"DOE {d['doe_label']}의 표본표가 준비되지 않았습니다(READY·PARSED/PARTIAL 필요)"}
    p = safe_study_path(study_root, d.get("samples_rel")) if d.get("samples_rel") else None
    if not p or not os.path.isfile(p):
        return None, {"code": "SOURCE_SAMPLES_MISSING", "message": f"DOE {d['doe_label']}의 samples.csv가 없습니다"}
    header, rows = read_samples_csv(p)
    if not rows:
        return None, {"code": "SOURCE_SAMPLES_MISSING", "message": f"DOE {d['doe_label']}의 samples.csv에 행이 없습니다"}
    return (header, rows), None


def name_mismatch(samples: Samples, names: Sequence[str]) -> dict[str, Any] | None:
    """표본표 파라미터 이름 집합 ≠ 대상 이름 집합이면 problem(DOE_PARAM_MISMATCH + 차이 이름)."""
    cols = [h for h in samples[0][1:] if not h.startswith("resp:")]
    if set(cols) == set(names):
        return None
    extra, miss = sorted(set(cols) - set(names)), sorted(set(names) - set(cols))
    detail = "; ".join(x for x in (f"원본 DOE에만: {', '.join(extra)}" if extra else "", f"원본 DOE에 없음: {', '.join(miss)}" if miss else "") if x)
    return {"code": "DOE_PARAM_MISMATCH", "message": f"파라미터 이름 집합이 다릅니다({detail})", "only_source": extra, "missing": miss}


def matrix_rows(samples: Samples, names: Sequence[str]) -> tuple[list[tuple[int, str, dict[str, float]]], list[str]]:
    """samples → ([(doe_no, run_key, values)] run 이름 유지·번호 순, 건너뛴 run 이름). run 이름이 `run__N` 형식이 아니거나 중복이거나
    값이 비면 건너뛴다(run 폴더 이름·DG_SCAN 규칙과 맞추기 위해 — ④ 일괄 `train_doe` 원천과 같은 규칙)."""
    from ..sampling.matrix_rows import doe_no_of

    out: list[tuple[int, str, dict[str, float]]] = []
    used: set[int] = set()
    skipped: list[str] = []
    for r in samples[1]:
        rk = str(r.get("run_key") or "")
        vals = r.get("values") or {}
        no = doe_no_of(rk)
        if no is None or no in used or any(vals.get(n) is None for n in names):
            skipped.append(rk)
            continue
        used.add(no)
        out.append((no, rk, {n: float(vals[n]) for n in names}))
    out.sort(key=lambda r: r[0])
    return out, skipped


def sampling_record(doe_id: str, source_label: str | None = None) -> dict[str, Any]:
    return {"kind": "train_doe", "input": {"doe_id": doe_id}, "meta": {"source_label": source_label} if source_label else None}


def is_reuse(sampling: Mapping[str, Any] | None) -> bool:
    return isinstance(sampling, Mapping) and sampling.get("kind") == "train_doe"
