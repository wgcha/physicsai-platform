"""DOE 표본 형상 그리드 미리보기의 플랫폼 쪽 순수 함수(doe-preview.md §3·§5·§6). 표준 라이브러리만(+ 같은 패키지 모듈), paicad import 없음.

- 셀 캐시: 서버측 AI 루트 `<study>/_cache/doe_preview/cells/<key[0:2]>/<key>/`(플랫폼 임시 산출물, geometry-view.md §6.6 — 브라우저 캐시 아님).
  행렬 캐시 `matrix/<mkey>/doe_matrix.csv`, 작업 폴더 `jobs/<job_id>/`. 셀 폴더 = paicad `view grid`의 `cells/<id>/` 그대로(preview_manifest.json·
  preview.glb?·thumb.png).
- 셀 키 = sha256(정규 JSON): {kind, study_id, shape_digest, values(사용 파라미터 전부, 빠진 값 공칭), view_tess, thumb_digest, engine_version}.
  `study_id`는 계약 §6.3의 키 구성에 더한 값이다 — 셀 인덱스 PK가 `cache_key`라서 같은 입력의 다른 Study가 충돌하지 않게 한다.
- grid_key = sha256{source digest, mkey, select, thumb_digest, engine_version}, mkey = sha256{source digest, 정규화 sampling, 사용 이름·범위}.
"""

from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .view import THUMB_KIND, cache_rel, canonical

CACHE_ROOT = "_cache/doe_preview"
CELLS_CACHE = f"{CACHE_ROOT}/cells"
MATRIX_CACHE = f"{CACHE_ROOT}/matrix"
JOBS_CACHE = f"{CACHE_ROOT}/jobs"
GRID_MANIFEST, THUMB_PNG, CELLS_JSON, THUMB_OPTIONS_JSON, VIEW_OPTIONS_JSON, OPTIONS_JSON = (
    "grid_manifest.json", "thumb.png", "cells.json", "thumb_options.json", "view_options.json", "options.json")
CELL_MANIFEST, CELL_GLB = "preview_manifest.json", "preview.glb"
MATRIX_CSV = "doe_matrix.csv"
THUMB_CONTENT_TYPE = "image/png"
CELL_ARTIFACT_KINDS = (THUMB_KIND, "GEOM_PREVIEW_GLB", "GEOM_PREVIEW_MANIFEST")
SOURCE_KINDS = ("train", "param_set", "train_doe")
ORDERS = ("change", "doe", "var")
COLORMAP = "turbo16"
NOMINAL_ID = "nominal"
ORDER_MAX = 2000  # 응답 `order`에 싣는 doe_no 최대 개수(§6.6)
LENGTH_UNITS = frozenset({"mm"})  # 색 범위 계산(§3.3)에 쓰는 길이 단위. 각도·무차원은 제외
CELL_STATUS_CACHEABLE = ("OK", "FAIL")  # 그 밖(ERROR)은 캐시하지 않는다
UNSUPPORTED_MULTI = "다중 baseline DOE는 형상 미리보기를 지원하지 않습니다"
UNSUPPORTED_ENGINE = "형상 미리보기는 Native 형상 엔진에서만 쓸 수 있습니다"


def grid_command_key(kind: str) -> str:
    return "paicad_shell_view_grid" if kind == "shell" else "paicad_view_grid"


def sha_of(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


# ---- 파라미터 표(사용 파라미터 요약) ---------------------------------------------------------------------------


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def param_table(rows: Iterable[Mapping[str, Any]], units: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """파라미터 행(①-2 사용 행·세트 행) → [{name, nominal, min, max, unit}](표 순서 유지, 공칭·범위가 숫자가 아닌 행은 뺀다).
    단위 = `units`(features JSON의 피처 단위)가 있으면 그것, 없으면 행의 `unit`, 비어 있으면 mm(Native 엔진 기본 길이 단위)."""
    out: list[dict[str, Any]] = []
    for r in rows:
        nom, lo, hi = _num(r.get("nominal")), _num(r.get("min")), _num(r.get("max"))
        if nom is None or lo is None or hi is None or not isinstance(r.get("name"), str):
            continue
        u = (units or {}).get(r["name"]) or r.get("unit") or "mm"
        out.append({"name": r["name"], "nominal": nom, "min": lo, "max": hi, "unit": str(u)})
    return out


def disp_ref_mm(params: Sequence[Mapping[str, Any]]) -> float:
    """`disp_ref_mm = max over 사용 파라미터 of max(|max−nominal|, |nominal−min|)`(길이 단위만, 각도·무차원 제외, 0이면 1.0) — §3.3."""
    best = 0.0
    for p in params:
        if str(p.get("unit", "mm")).lower() not in LENGTH_UNITS:
            continue
        best = max(best, abs(p["max"] - p["nominal"]), abs(p["nominal"] - p["min"]))
    return float(best) if best > 0 else 1.0


def thumb_options_document(cfg: Any, params: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """`thumb_options.json`(§3.3) = 설정 `doe_preview.thumb` 사용값 + 계산값(`disp_range_mm = [0, disp_ref_mm]`)."""
    t = cfg.thumb
    return {"schema_version": 1, "w": int(t.w), "h": int(t.h), "view_dir": [float(x) for x in t.view_dir], "margin": float(t.margin),
            "disp_range_mm": [0.0, disp_ref_mm(params)], "colormap": str(t.colormap), "nominal_ghost": bool(t.nominal_ghost),
            "edges": False}


def thumb_digest(doc: Mapping[str, Any]) -> str:
    return sha_of(doc)


# ---- 행·선택 ---------------------------------------------------------------------------------------------------

Row = tuple[int, str, dict[str, float]]  # (doe_no, run_key, 값) — `doe_matrix_csv` 행과 같은 모양


def change_score(values: Mapping[str, float], params: Sequence[Mapping[str, Any]]) -> float:
    """사용 파라미터마다 `(v − nominal)/(max−min)`의 L2 노름(§5.2). 범위 폭 0인 파라미터와 값이 없는 파라미터는 0."""
    s = 0.0
    for p in params:
        span = p["max"] - p["min"]
        v = values.get(p["name"])
        if span <= 0 or v is None:
            continue
        s += ((float(v) - p["nominal"]) / span) ** 2
    return math.sqrt(s)


def order_rows(rows: Sequence[Row], params: Sequence[Mapping[str, Any]], order: str, var: str | None = None, desc: bool = False) -> list[int]:
    """정렬된 doe_no 목록(전체 표본 표 기준, §5.2). change = 변화 큰 순(같으면 doe_no 오름차순) · doe = doe_no 오름차순 ·
    var = `var` 값 오름(desc면 내림, 같으면 doe_no 오름차순)."""
    if order == "doe":
        return sorted(r[0] for r in rows)
    if order == "var":
        vals = {r[0]: float(r[2].get(var or "", math.nan)) for r in rows}
        key = (lambda n: (-vals[n], n)) if desc else (lambda n: (vals[n], n))
        return sorted(vals, key=key)
    if order != "change":
        raise ValueError(f"알 수 없는 정렬: {order}")
    sc = {r[0]: change_score(r[2], params) for r in rows}
    return sorted(sc, key=lambda n: (-sc[n], n))


def page_slice(order: Sequence[int], offset: int, limit: int) -> tuple[bool, list[int]]:
    """페이지의 (공칭 셀 포함 여부, 표본 doe_no 목록)(§5.2). offset 0 = 공칭 + 표본 `limit−1`개, 이후 = 표본 `limit`개
    (앞 페이지가 이미 보인 `offset` 셀 가운데 공칭 1개를 뺀 만큼 건너뜀)."""
    if offset == 0:
        return True, list(order[: max(0, limit - 1)])
    start = offset - 1
    return False, list(order[start: start + limit])


def top_changes(values: Mapping[str, float], params: Sequence[Mapping[str, Any]], n: int = 3) -> list[dict[str, Any]]:
    """`|rel|` 큰 순 n개 `{name, value, rel}`(rel = (v−nom)/(max−min), 같으면 표 순서). 변화 0인 항목은 뺀다."""
    items = []
    for i, p in enumerate(params):
        v = values.get(p["name"])
        span = p["max"] - p["min"]
        if v is None or span <= 0:
            continue
        rel = (float(v) - p["nominal"]) / span
        if rel != 0.0:
            items.append((-abs(rel), i, {"name": p["name"], "value": float(v), "rel": rel}))
    items.sort(key=lambda x: (x[0], x[1]))
    return [x[2] for x in items[:n]]


def full_values(values: Mapping[str, float], params: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """사용 파라미터 전부(빠진 값은 공칭) — 셀 키 입력."""
    return {p["name"]: float(values.get(p["name"], p["nominal"])) for p in params}


# ---- 키 -------------------------------------------------------------------------------------------------------


def folder_digest(path: str | None) -> str | None:
    """폴더 직계 파일(이름·sha256) 정렬 목록의 sha256. 폴더가 없거나 파일이 없으면 None(tag·fixed 폴더 digest용)."""
    from .prep import sha256_file

    if not path or not os.path.isdir(path):
        return None
    items = sorted((n, sha256_file(os.path.join(path, n))) for n in os.listdir(path) if os.path.isfile(os.path.join(path, n))
                   and not os.path.islink(os.path.join(path, n)))
    return sha_of(items) if items else None


def shape_digest(*, cad_files: Sequence[str], body_map: str | None, features: str, tag_dir: str | None, opts_sha: str,
                 fixed_digest: str | None) -> str:
    """형상 입력 digest(§6.3): CAD sha256들 + body_map sha + `features` sha + tag 폴더 digest(없으면 null) + 유효 geom options sha + (쉘) `fixed_digest`.
    파일 sha256은 `prep.sha256_file`(경로·크기·수정시각 캐시)을 쓴다. 파일이 없으면 None으로 기록한다."""
    from .prep import sha256_file

    def sha(p: str | None) -> str | None:
        return sha256_file(p) if p and os.path.isfile(p) else None

    doc = {"cad": [sha(p) for p in cad_files], "body_map": sha(body_map), "features": sha(features), "tag": folder_digest(tag_dir),
           "options": opts_sha, "fixed": fixed_digest}
    return sha_of(doc)


def cell_key(*, kind: str, study_id: str, shape: str, values: Mapping[str, float], view_tess: Mapping[str, Any] | None, thumb: str,
             engine_version: str) -> str:
    doc = {"kind": kind, "study_id": study_id, "shape_digest": shape, "values": {k: float(v) for k, v in values.items()},
           "view_tess": {k: float(v) for k, v in (view_tess or {}).items() if v is not None}, "thumb_digest": thumb,
           "engine_version": engine_version}
    return sha_of(doc)


def matrix_key(*, source_digest: str, sampling: Mapping[str, Any] | None, num_runs: int | None, seed: int | None,
               params: Sequence[Mapping[str, Any]]) -> str:
    """행렬 캐시 키(§6.1 DP_MATRIX): 형상 입력 digest + 정규화 sampling(+ lhs의 num_runs·seed) + 사용 이름·범위."""
    doc = {"source": source_digest, "sampling": dict(sampling) if sampling else None, "num_runs": num_runs, "seed": seed,
           "params": [[p["name"], p["nominal"], p["min"], p["max"]] for p in params]}
    return sha_of(doc)


def grid_key(*, source_digest: str, mkey: str | None, select: Mapping[str, Any], thumb: str, engine_version: str,
             doe_id: str | None = None) -> str:
    """같은 요청(출처·표본·선택·썸네일 옵션·버전)의 중복 판정 키(§6.4). `train_doe`는 mkey 대신 doe_id."""
    sel = {k: select.get(k) for k in ("order", "var", "desc", "offset", "limit")}
    return sha_of({"source": source_digest, "mkey": mkey, "doe_id": doe_id, "select": sel, "thumb": thumb, "engine_version": engine_version})


def cell_dir_rel(key: str) -> str:
    return cache_rel(CELLS_CACHE, key)


def matrix_dir_rel(mkey: str) -> str:
    return cache_rel(MATRIX_CACHE, mkey)


def job_dir_rel(job_id: str) -> str:
    return f"{JOBS_CACHE}/{job_id}"


# ---- paicad 입력·결과 ------------------------------------------------------------------------------------------


def cells_document(cells: Sequence[tuple[str, Mapping[str, float]]]) -> dict[str, Any]:
    """`cells.json`(§3.2): `{schema_version, cells:[{id, values}]}` — 공칭 셀은 `{id:"nominal", values:{}}`."""
    return {"schema_version": 1, "cells": [{"id": i, "values": {k: float(v) for k, v in vals.items()}} for i, vals in cells]}


def chunked(items: Sequence[Any], size: int) -> list[list[Any]]:
    n = max(1, int(size))
    return [list(items[i: i + n]) for i in range(0, len(items), n)]


def judge_cell(entry: Mapping[str, Any] | None) -> dict[str, Any]:
    """`grid_manifest.cells[]` 1개 → {cacheable, status, code, category, max_disp_mm}. status ∈ OK|FAIL|ERROR.
    GV-10 규칙 준용: FAIL이라도 category가 VIEW·INPUT·INTERNAL이거나 code가 `VIEW_`로 시작하면 인프라 문제 → ERROR(캐시 안 함)."""
    if not isinstance(entry, Mapping) or entry.get("status") not in ("OK", "FAIL", "ERROR"):
        return {"cacheable": False, "status": "ERROR", "code": "OUTPUT_MISSING", "category": None, "max_disp_mm": None}
    st = str(entry["status"])
    code = entry.get("code") if isinstance(entry.get("code"), str) else None
    cat = entry.get("category") if isinstance(entry.get("category"), str) else None
    disp = _num(entry.get("max_disp_mm"))
    if st == "FAIL" and (cat in ("VIEW", "INPUT", "INTERNAL") or (code or "").startswith("VIEW_")):
        st = "ERROR"
    return {"cacheable": st in CELL_STATUS_CACHEABLE, "status": st, "code": code, "category": cat, "max_disp_mm": disp}
