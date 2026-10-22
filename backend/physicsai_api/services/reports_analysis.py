"""⑤ 결과분석 보고서 원천(upload-report.md §9.3.1): 출처 batch = `GET /predict-batches/{id}`·`design-map`·`curves` 서비스, doe = `result-table` 서비스.

프런트 어댑터(`analysis/adapters/fromBatch.ts`·`fromDoe.ts`)와 같은 규칙으로 결과 표 dict를 만든다(영향도 사용 조건 포함).
"""

from __future__ import annotations

import re
from typing import Any

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import DomainError
from physicsai_core.report_html.analysis import (MAX_VARS, NO_RESP_HINT, OFF_FALLBACK_TEXT, is_ok, min_influence_runs)
from physicsai_core.sampling import registry as sampling_registry
from physicsai_core.stage4_predict.performance import perf_defs

from ..auth import Principal
from ..context import AppContext
from . import design_map as dm_svc
from . import doe_result_table as doe_svc
from . import predict_batches as pb_svc
from . import reports_common as rc

SOURCES = ("batch", "doe")
MAX_CURVE_SERIES = 12  # 프런트 perfColumns.MAX_CURVE_SERIES와 같은 값
CURVE_STATS = (("max", "최대"), ("min", "최소"), ("absmax", "|최대|"))
CURVE_COL = re.compile(r"^curve:(max|min|absmax)\|(.*)$", re.S)
UNKNOWN_METHOD_TEXT = "표본 방식을 알 수 없어 영향도는 참고용입니다"
CURVE_POINTS = 300
CURVE_RUNS = 200


def _fin(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf") else None


def _not_ready(what: str) -> DomainError:
    return DomainError("REPORT_NOT_READY", f"{what}이(가) 아직 끝나지 않았습니다 — 끝난 뒤 받으세요", status=409)


def _bad_source(s: str) -> DomainError:
    return DomainError("INVALID_PARAMS", f"source는 batch 또는 doe여야 합니다: {s}", status=422, errors=[{"loc": ["query", "source"], "msg": "invalid"}])


# ---- 어댑터(fromBatch) ----------------------------------------------------------------------------------


def table_from_batch(b: dict[str, Any], dm: dict[str, Any] | None, ps_responses: list[dict[str, Any]] | None) -> dict[str, Any]:
    dm_params = {p["name"]: p for p in (dm or {}).get("parameters") or []}
    dm_run = {r["doe_no"]: r for r in (dm or {}).get("runs") or []}
    ints = {n for n, p in dm_params.items() if p.get("integer")}
    defs = list(perf_defs(ps_responses))
    base_names = {x["name"] for x in b["responses"]}
    dm_perf = [(m["id"][5:], m.get("unit")) for m in (dm or {}).get("metrics") or [] if str(m.get("id", "")).startswith("perf:")]
    perf_names = {*defs, *(n for n, _ in dm_perf)}
    extra_perf = [{"name": n, "unit": u, "kind": "perf"} for n, u in dm_perf if n not in base_names]
    curve_cols = [{"name": f"curve:{k}|{s}", "unit": None, "label": f"{s} {lb}(커브)", "kind": "curve"}
                  for s in ((dm or {}).get("series") or [])[:MAX_CURVE_SERIES] for k, lb in CURVE_STATS]

    def perf_of(name: str, table_v: Any, run: dict[str, Any] | None) -> float | None:
        return _fin(run["perf"][name]) if run and run.get("perf") and name in run["perf"] else _fin(table_v)

    def curve_value(name: str, run: dict[str, Any] | None) -> float | None:
        m = CURVE_COL.match(name)
        if not m or not run or not run.get("curve"):
            return None
        return _fin((run["curve"].get(m.group(2)) or {}).get(m.group(1)))

    rows = []
    for r in b["rows"]:
        ok = r["state"] == "SUCCEEDED"
        run = dm_run.get(r["doe_no"])
        resp: dict[str, float | None] = {}
        for x in b["responses"]:
            n = x["name"]
            resp[n] = None if not ok else perf_of(n, (r.get("responses") or {}).get(n), run) if n in perf_names else _fin((r.get("responses") or {}).get(n))
        for x in extra_perf:
            resp[x["name"]] = perf_of(x["name"], (r.get("responses") or {}).get(x["name"]), run) if ok else None
        for x in curve_cols:
            resp[x["name"]] = curve_value(x["name"], run) if ok else None
        applied = r.get("applied_values") or {}
        vals = r.get("values") or {}
        rows.append({"run_id": r["run_key"], "no": r["doe_no"], "state": r["state"],
                     "params": {n: _fin(applied.get(n, vals.get(n))) for n in b["parameters"]}, "responses": resp,
                     "curve": (run or {}).get("curve") if ok else None})
    any_ = lambda x: any(r["responses"].get(x["name"]) is not None for r in rows)  # noqa: E731
    resp_cols = [({"name": x["name"], "unit": x.get("unit") or None, "kind": "perf"} if x["name"] in perf_names else {"name": x["name"], "unit": x.get("unit") or None})
                 for x in b["responses"]]
    resp_cols += [x for x in extra_perf if any_(x)] + [x for x in curve_cols if any_(x)]
    sm = b.get("sampling")
    cls = (sm or {}).get("influence_class") or "reference"
    note = (None if cls != "reference" else ((sm or {}).get("influence_note") if sm else UNKNOWN_METHOD_TEXT))
    first = resp_cols[0]["name"] if resp_cols else None
    names = b["parameters"]
    usable = sum(1 for r in rows if first and is_ok(r["state"]) and r["responses"].get(first) is not None
                 and all(r["params"].get(n) is not None for n in names)) if first else 0
    need = min_influence_runs(len(names))
    data_any = any(any_(x) for x in resp_cols)
    hint = "" if data_any else f" — {NO_RESP_HINT}"
    inf_ok = bool(first) and usable >= need
    reason = (f"응답 정의가 없어 영향도를 계산할 수 없습니다{hint}" if not first
              else f"영향도에는 유효 run이 {need}개 이상 필요합니다(현재 {usable}개){hint}" if usable < need else None)
    notes = []
    stale = ((dm or {}).get("counts") or {}).get("spec_changed") or 0
    if stale > 0:
        notes.append(f"성능 정의가 바뀐 뒤 다시 추출하지 않은 run {stale}개는 성능 값이 비어 있습니다 — ⑥ 최적화 설정의 성능 표에서 '다시 추출'")
    return {"source": "predict", "origin": {"kind": "predict_batch", "id": b["id"], "label": b["label"]},
            "parameters": [{"name": n, "integer": n in ints, "min": _fin((dm_params.get(n) or {}).get("min")),
                            "max": _fin((dm_params.get(n) or {}).get("max")), "unit": None} for n in names],
            "responses": resp_cols, "meta": {"engine_version": None, "baseline_id": None, "scene": None}, "rows": rows,
            "counts": {"total": len(rows), "usable": usable, "no_response": len(rows) - usable},
            "influence": {"ok": inf_ok, "cls": cls, "note": note, "reason": reason}, "notes": notes,
            "sampling": {"label": (sm or {}).get("label"), "lhs": (sm or {}).get("kind") == "lhs", "kind": (sm or {}).get("kind")}}


def table_from_doe(t: dict[str, Any]) -> dict[str, Any]:
    cls = t["influence_class"]
    ok = cls != "off"
    note = t.get("influence_note")
    sm = t.get("sampling") or {}
    kind = sampling_registry.kind_of_source(str(sm.get("method") or ""))
    return {"source": "solver", "origin": {"kind": "train_doe", "id": t["doe_id"], "label": t["label"]},
            "parameters": [{"name": x["name"], "integer": x["integer"], "min": _fin(x.get("min")), "max": _fin(x.get("max")), "unit": x.get("unit")}
                           for x in t["parameters"]],
            "responses": [{"name": x["name"], "unit": x.get("unit")} for x in t["responses"]],
            "meta": {k: (t.get("meta") or {}).get(k) for k in ("engine_version", "baseline_id", "scene")},
            "rows": [{"run_id": r["run_id"], "no": r["no"], "state": r["state"], "params": {k: _fin(v) for k, v in r["params"].items()},
                      "responses": {k: _fin(v) for k, v in r["responses"].items()}, "curve": None} for r in t["rows"]],
            "counts": dict(t["counts"]),
            "influence": {"ok": ok, "cls": cls, "note": note if cls == "reference" else None, "reason": None if ok else (note or OFF_FALLBACK_TEXT)},
            "notes": list(t["notes"]), "sampling": {"label": sm.get("label"), "lhs": kind == "lhs", "kind": kind}}


# ---- 출처 읽기 -------------------------------------------------------------------------------------------


def load_table(ctx: AppContext, principal: Principal, source: str, sid: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(결과 표, 부가 정보{study, param_set, model, engine, curves…})."""
    if source == "batch":
        with ctx.engine.connect() as conn:
            b0 = pb_svc._require_batch(conn, sid)  # 404 BATCH_NOT_FOUND
            if b0["status"] in pb_svc.ACTIVE_BATCH:
                raise _not_ready(f"일괄 예측 {b0.get('batch_no') and 'B-%03d' % b0['batch_no']}")
        b = pb_svc.get_batch(ctx, principal, sid)
        try:
            dm = dm_svc.design_map(ctx, sid)
        except DomainError:
            dm = None
        with ctx.engine.connect() as conn:
            study = studies_repo.require(conn, b0["study_id"])
            ps = ps_repo.get(conn, b0["param_set_id"])
            model = rc.model_info(conn, study, b0["model_id"])
            origins = rc.origins(ctx, conn, study["id"], [("파라미터 세트 입력 경로", (ps or {}).get("source_path")), ("모델 경로", model.get("source_path"))])
        rt = table_from_batch(b, dm, (ps or {}).get("responses"))
        try:
            curves = pb_svc.curves(ctx, sid, None, CURVE_POINTS)
        except DomainError:
            curves = None
        return rt, {"study": rc.study_info(study), "param_set": rc.param_set_info(ps, b0["input_kind"]), "engine": rc.engine_info(ctx, ps),
                    "model": model or None, "origins": origins, "curves": curves}
    if source == "doe":
        with ctx.engine.connect() as conn:
            d = train_repo.get_doe(conn, sid)
            if d is None:
                raise DomainError("DOE_NOT_FOUND", "DOE를 찾을 수 없습니다", status=404)
            study = studies_repo.require(conn, d["study_id"])
        if d["status"] == "BUILDING":
            raise _not_ready(f"해석 DOE {d['doe_label']}")
        try:
            t = doe_svc.result_table(ctx, sid)
        except DomainError as exc:
            if exc.code == "DOE_NOT_READY":
                raise _not_ready(f"해석 DOE {d['doe_label']}") from None
            raise
        return table_from_doe(t), {"study": rc.study_info(study), "param_set": None, "engine": {}, "model": None, "origins": [], "curves": None}
    raise _bad_source(source)


def analysis_input(ctx: AppContext, principal: Principal, source: str, sid: str, compare_source: str | None, compare_id: str | None,
                   vars_: list[str] | None, resp: str | None) -> dict[str, Any]:
    rt, extra = load_table(ctx, principal, source, sid)
    other = None
    warnings: list[str] = []
    if compare_source or compare_id:
        if not (compare_source and compare_id):
            raise DomainError("INVALID_PARAMS", "비교 출처는 compare_source와 compare_id를 함께 보내야 합니다", status=422,
                              errors=[{"loc": ["query", "compare_id"], "msg": "required"}])
        other, oextra = load_table(ctx, principal, compare_source, compare_id)
        if oextra["study"]["id"] != extra["study"]["id"]:
            raise DomainError("INVALID_PARAMS", "비교 출처는 같은 Study여야 합니다", status=422, errors=[{"loc": ["query", "compare_id"], "msg": "other study"}])
    names: list[str] = []
    for v in vars_ or []:  # 반복 쿼리 + 쉼표 구분 모두 허용
        names += [x for x in (s.strip() for s in v.split(",")) if x]
    return {**extra, "generated_by": principal.display_name, "table": rt, "other": other, "vars": names[: MAX_VARS * 4] if names else None,
            "resp": resp, "warnings": warnings}
