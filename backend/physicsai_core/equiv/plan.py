"""레시피 binding 해석·run별 값 읽기·추출 계획(equiv-check.md §4.3·§4.5) — API 미리보기·워커 공용.

- `bind(defn, bindings)`: 레시피의 빈 원천(null)에 실행 요청 bindings를 채운다(필수 미연결 → METRIC_UNBOUND).
- `resolve(defn, side_a, side_b)`: `perf` 원천을 양쪽 템플릿 성능 정의로 해석(spec·단위 비교 경고), 지표마다 쪽별 응답 정의.
- `run_values(...)`: run 1개의 지표 값 읽기(기존 RESPONSES.txt·curve.json 또는 판정 폴더 추출본 overlay) + 추출 필요 판단.
- `extraction_plan(...)`: 쌍 전체에서 추출이 필요한 (side, run) 목록·사본 바이트.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..stage4_predict import performance
from ..stage4_predict.run_metrics import RunFiles, RunMetrics, load_run_metrics
from .recipes import unbound_required
from .sides import Run, Side

CURVE_JSON = "curve.json"
RESPONSE_SPEC_KEYS = ("subcase", "datatype", "component", "layer", "stat", "series", "source")


def bind(defn: Mapping[str, Any], bindings: Mapping[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """빈 원천에 bindings[metric_id]를 채운 정의 사본 + problems(METRIC_UNBOUND). bindings 값은 §3.1 source 모양."""
    out = json.loads(json.dumps(defn))
    for m in out["metrics"]:
        b = (bindings or {}).get(m["id"])
        if m.get("source") is None and isinstance(b, Mapping):
            m["source"] = dict(b)
    probs = [{"code": "METRIC_UNBOUND", "metric_id": mid,
              "message": f"필수 지표 '{next((x['label'] for x in out['metrics'] if x['id'] == mid), mid)}'의 원천이 연결되지 않았습니다 — 성능 정의를 연결하거나 참고로 바꾸세요"}
             for mid in unbound_required(out)]
    return out, probs


def _perf_def(side: Side, name: str) -> dict[str, Any] | None:
    for r in side.responses:
        if str(r.get("name")) == name and isinstance(r.get("spec"), Mapping):
            return {"name": name, "unit": str(r.get("unit") or ""), "spec": dict(r["spec"])}
    return None


def response_def_for(metric: Mapping[str, Any], side: Side) -> dict[str, Any] | None:
    """지표 원천 → 그 쪽의 응답 정의 `{name, unit, spec}`(perf_value 입력). mesh_volume·미연결은 None."""
    src = metric.get("source")
    if not isinstance(src, Mapping):
        return None
    t = src.get("type")
    if t == "perf":
        return _perf_def(side, str(src.get("perf")))
    if t == "h3d":
        return {"name": str(src.get("name") or metric["id"]), "unit": "",
                "spec": {"source": "H3D", "subcase": int(src.get("subcase", 1)), "datatype": src["datatype"],
                         "component": str(src.get("component") or ""), "layer": str(src.get("layer") or ""),
                         "stat": str(src.get("stat") or "MAX").upper()}}
    if t == "curve":
        return {"name": str(metric["id"]), "unit": "",
                "spec": {"source": "CURVE", "series": src.get("series"), "stat": str(src.get("stat") or "MAX").upper()}}
    return None


def _spec_key(d: Mapping[str, Any] | None) -> tuple[Any, ...] | None:
    if d is None:
        return None
    sp = d.get("spec") or {}
    return tuple(str(sp.get(k) or "").upper() if k != "series" else sp.get(k) for k in RESPONSE_SPEC_KEYS)


def resolve(defn: Mapping[str, Any], a: Side, b: Side) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """지표마다 {"a": 응답 정의|None, "b": …, "na": 사유|None} + 경고(EQ_SPEC_DIFFERS·EQ_UNIT_DIFFERS)."""
    resolved: dict[str, dict[str, Any]] = {}
    warnings: list[dict[str, Any]] = []
    for m in defn["metrics"]:
        kind = m["kind"]
        if kind == "mesh_volume" or m.get("source") is None:
            resolved[m["id"]] = {"a": None, "b": None, "na": None if kind == "mesh_volume" else "UNBOUND"}
            continue
        da, db = response_def_for(m, a), response_def_for(m, b)
        na = None
        if m["source"].get("type") == "perf" and (da is None or db is None):
            na = "PERF_UNDEFINED"
            missing = [s for s, d in (("A", da), ("B", db)) if d is None]
            warnings.append({"code": "EQ_PERF_UNDEFINED", "metric_id": m["id"],
                             "message": f"{m['label']}: 성능 정의 '{m['source'].get('perf')}'가 {'·'.join(missing)} 쪽 템플릿에 없습니다"})
        elif da and db:
            if _spec_key(da) != _spec_key(db):
                warnings.append({"code": "EQ_SPEC_DIFFERS", "metric_id": m["id"], "message": f"{m['label']}: 두 쪽 성능 정의 spec이 다릅니다(비차단)"})
            if (da.get("unit") or "") != (db.get("unit") or ""):
                warnings.append({"code": "EQ_UNIT_DIFFERS", "metric_id": m["id"],
                                 "message": f"{m['label']}: 단위가 다릅니다(A {da.get('unit') or '-'}, B {db.get('unit') or '-'}) — 환산하지 않습니다"})
        resolved[m["id"]] = {"a": da, "b": db, "na": na}
    return resolved, warnings


# ---- run별 값 ------------------------------------------------------------------------------------------


@dataclass
class RunRead:
    """run 1개에서 읽은 지표 입력: 값·사유·추출 필요 여부."""

    metrics: RunMetrics
    curve_json: str | None
    result_dir: str | None
    need_h3d: list[dict[str, Any]] = field(default_factory=list)   # 추출할 응답 정의(name·spec)
    need_t01: bool = False


def extract_dir(extract_root: str | None, side_key: str, run_name: str) -> str | None:
    return os.path.join(extract_root, side_key, run_name) if extract_root else None


def _curve_file(run: Run, ex_dir: str | None) -> str | None:
    if ex_dir:
        p = os.path.join(ex_dir, CURVE_JSON)
        if os.path.isfile(p):
            return p
    return run.curve_json


def read_run(run: Run, side: Side, side_key: str, defn: Mapping[str, Any], resolved: Mapping[str, Mapping[str, Any]],
             *, extract_root: str | None, max_bytes: int) -> RunRead:
    """run의 RunMetrics(추출본 overlay) + 지표별 추출 필요 판단."""
    ex = extract_dir(extract_root, side_key, run.name)
    result_dir = run.result_dir
    if ex and os.path.isfile(os.path.join(ex, "RESPONSES.txt")):
        result_dir = ex
    curve = _curve_file(run, ex)
    m = load_run_metrics(RunFiles(curve_json=curve, result_dir=result_dir), max_bytes=max_bytes)
    rr = RunRead(m, curve, result_dir)
    for met in defn["metrics"]:
        d = (resolved.get(met["id"]) or {}).get(side_key)
        if met["kind"] == "mesh_volume":
            continue
        uses_curve = met["kind"] in ("curve_corr", "curve_nrmse") or (d and str((d.get("spec") or {}).get("source") or "H3D").upper() == "CURVE")
        if uses_curve:
            if curve is None and run.t01:
                rr.need_t01 = True
            continue
        if d is None:
            continue
        pd = performance.perf_defs([d]).get(d["name"])
        if pd is None:
            continue
        v, why = performance.perf_value(pd, m)
        if v is None and run.h3d and why in ("NOT_EXTRACTED", "SPEC_CHANGED", "NO_VALUE"):
            if why == "NO_VALUE" and m.requests is not None and d["name"] in m.requests:
                continue  # 같은 요청으로 이미 추출했는데 값이 없음 → 다시 추출해도 같다
            if not any(x["name"] == d["name"] for x in rr.need_h3d):
                rr.need_h3d.append(d)
    return rr


@dataclass
class ExtractPlan:
    h3d: list[dict[str, Any]] = field(default_factory=list)   # {side, run, h3d, bytes, responses:[정의]}
    t01: list[dict[str, Any]] = field(default_factory=list)   # {side, run, t01}
    copy_bytes: int = 0

    @property
    def count(self) -> int:
        return len(self.h3d) + len(self.t01)


def extraction_plan(defn: Mapping[str, Any], resolved: Mapping[str, Mapping[str, Any]], a: Side, b: Side,
                    pairs: Sequence[tuple[str, str]], *, extract_root: str | None, max_bytes: int) -> ExtractPlan:
    plan = ExtractPlan()
    runs_a = {r.name: r for r in a.runs}
    runs_b = {r.name: r for r in b.runs}
    for side_key, side, runs, idx in (("a", a, runs_a, 0), ("b", b, runs_b, 1)):
        done: set[str] = set()
        for pair in pairs:
            name = pair[idx]
            run = runs.get(name)
            if run is None or not run.ok or name in done:
                continue
            done.add(name)
            rr = read_run(run, side, side_key, defn, resolved, extract_root=extract_root, max_bytes=max_bytes)
            if rr.need_h3d and run.h3d:
                try:
                    size = os.path.getsize(run.h3d)
                except OSError:
                    size = 0
                plan.h3d.append({"side": side_key, "run": name, "h3d": run.h3d, "bytes": size, "responses": rr.need_h3d})
                plan.copy_bytes += size
            if rr.need_t01 and run.t01:
                plan.t01.append({"side": side_key, "run": name, "t01": run.t01})
    return plan


def curve_definitions(conn: Any, study_id: str, model_id: str | None) -> list[dict[str, str]] | None:
    """FV_CURVE 규칙(phase3 §21.3.6) ① 모델 데이터셋 → 큐레이션 작업(CU_T01_CURVES) params.curves ② Study 최신 성공 CU_T01_CURVES."""
    from ..db.repositories import curations as cur_repo
    from ..db.repositories import datasets as ds_repo
    from ..db.repositories import jobs as jobs_repo
    from ..db.repositories import models as models_repo

    m = models_repo.get(conn, model_id) if model_id else None
    if m and m.get("dataset_id"):
        d = ds_repo.get(conn, m["dataset_id"])
        dj = jobs_repo.get_job(conn, d["job_id"]) if d and d.get("job_id") else None
        cid = ((dj or {}).get("params") or {}).get("curation_id")
        cur = cur_repo.get_curation(conn, cid) if cid else None
        cj = jobs_repo.get_job(conn, cur["job_id"]) if cur else None
        curves = ((cj or {}).get("params") or {}).get("curves") if cj and cj["job_type"] == "CU_T01_CURVES" else None
        if curves:
            return [dict(c) for c in curves]
    rows = jobs_repo.list_with_study_title(conn, study_id=study_id, states=["SUCCEEDED"], created_by=None,
                                           job_type="CU_T01_CURVES", limit=1, offset=0)
    if rows and (rows[0].get("params") or {}).get("curves"):
        return [dict(c) for c in rows[0]["params"]["curves"]]
    return None


def t01_requests(defn: Mapping[str, Any], fallback: Sequence[Mapping[str, str]] | None) -> list[dict[str, str]]:
    """레시피 곡선 원천의 t01 요청(중복 제거) + 없으면 fallback(FV_CURVE 규칙)."""
    out: list[dict[str, str]] = []
    for m in defn["metrics"]:
        src = m.get("source")
        t01 = src.get("t01") if isinstance(src, Mapping) else None
        if isinstance(t01, Mapping):
            item = {"type": str(t01.get("type")), "request": str(t01.get("request")), "component": str(t01.get("component"))}
            if item not in out:
                out.append(item)
    for c in fallback or []:
        item = {"type": str(c.get("type")), "request": str(c.get("request")), "component": str(c.get("component"))}
        if item not in out:
            out.append(item)
    return out
