"""⑤ 결과분석 입력 — 해석 DOE 결과 표(s14_analysis.md §19.5, D3-62).

samples.csv(+responses.csv)와 train_runs 상태를 합쳐 읽기 전용 표를 만든다. DB에는 아무것도 쓰지 않고 파일 본문도 저장하지 않는다.
파일 파싱 결과는 프로세스 LRU(키 = 종류·경로·mtime_ns·크기)에 둔다 — 같은 파일은 두 번째 호출부터 다시 읽지 않는다.
"""

from __future__ import annotations

import math
import os
import re
from typing import Any

from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import DomainError
from physicsai_core.path_links import is_link_or_reparse
from physicsai_core.paths import resolve_in_study
from physicsai_core.sampling import registry as sampling_registry
from physicsai_core.stage1_train_data import doe_samples
from physicsai_core.stage1_train_data import doe_types as dt_mod
from physicsai_core.stage4_predict.nearest import integer_vars
from physicsai_core.stage4_predict.run_metrics import _Lru

from ..context import AppContext
from .common import study_root

FAILED_STATES = ("SOLVE_FAILED", "COLLECT_FAILED")
_CACHE = _Lru(64)
_NO_RE = re.compile(r"(\d+)$")


def cache_info() -> dict[str, int]:
    """시험·진단용: {hits, misses, size}."""
    with _CACHE.lock:
        return {"hits": _CACHE.hits, "misses": _CACHE.misses, "size": len(_CACHE.data)}


def cache_clear() -> None:
    _CACHE.clear()


def _safe_path(root: str, rel: str) -> str | None:
    """Study 안의 일반 파일이면 절대경로, 밖·링크·없음이면 None."""
    try:
        lexical = os.path.join(root, rel.replace("\\", "/"))
        if is_link_or_reparse(lexical):
            return None
        p = resolve_in_study(root, rel)
    except DomainError:
        return None
    return p if os.path.isfile(p) else None


def _read_cached(kind: str, path: str) -> tuple[list[str], list[dict[str, Any]]]:
    st = os.stat(path)
    key = (kind, path, st.st_mtime_ns, st.st_size)
    return _CACHE.get_or_load(key, lambda: doe_samples.read_samples_csv(path))


def _finite(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _run_no(run_key: str, idx: int) -> int:
    m = _NO_RE.search(run_key)
    return int(m.group(1)) if m else idx + 1


def _type_label(ctx: AppContext, value: str) -> str:
    """정의 파일의 유형 라벨(없거나 파일 오류면 value 그대로)."""
    try:
        types = dt_mod.load_doe_types(ctx.settings.resources.doe_design_type_json, ctx.settings.ui.max_artifact_bytes)
    except DomainError:
        return value
    return next((t["label"] for t in types if t["value"] == value), value)


def _sampling(ctx: AppContext, d: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    """S15 §20.6 표본 방식. 플랫폼 DOE(§23.4)는 {method: doe_type, label: §20.4 이름, desc_id: td_<kind>, options}."""
    if d.get("generator") == "PLATFORM" and d["doe_type"] != sampling_registry.DOE_TYPE_NATIVE_LHS:  # native LHS는 NATIVE_LHS 그대로(아래)
        kind = str((d.get("sampling") or {}).get("kind") or sampling_registry.kind_of_source(d["doe_type"]) or "")
        label = sampling_registry.METHODS[kind][1] if kind in sampling_registry.METHODS else d["doe_label"]
        return {"method": d["doe_type"], "label": label, "desc_id": sampling_registry.platform_desc_id(kind),
                "options": options}
    return {"method": d["doe_type"], "label": _type_label(ctx, d["doe_type"]),
            "desc_id": sampling_registry.DOE_DESC_IDS.get(d["doe_type"]), "options": options}


def result_table(ctx: AppContext, doe_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        d = train_repo.get_doe(conn, doe_id)
        if d is None:
            raise DomainError("DOE_NOT_FOUND", "DOE를 찾을 수 없습니다", status=404)
        st = studies_repo.require(conn, d["study_id"])
        states = {r["run_key"]: r["state"] for r in train_repo.runs_for_doe(conn, doe_id)}
    if d["sample_status"] not in ("PARSED", "PARTIAL"):
        raise DomainError("DOE_NOT_READY", "아직 샘플 표가 준비되지 않았습니다", status=409)
    root = study_root(ctx, st)
    sp = _safe_path(root, d["samples_rel"]) if d["samples_rel"] else None
    if sp is None:
        raise DomainError("SAMPLES_MISSING", "DOE 샘플 표가 없습니다", status=404)
    header, rows = _read_cached("samples", sp)
    notes: list[str] = []

    snap = {p["name"]: p for p in (d["parameters_snapshot"] or []) if isinstance(p, dict) and "name" in p}
    ints = integer_vars(list(snap.values()))
    names = [h for h in header[1:] if not h.startswith("resp:")]

    resp_names: list[str] = []
    resp: dict[str, dict[str, Any]] = {}
    if d["responses_rel"]:
        rp = _safe_path(root, d["responses_rel"])
        if rp is None:
            notes.append("응답 파일을 읽을 수 없습니다")
        else:
            rh, rrows = _read_cached("responses", rp)
            resp_names = [h[5:] if h.startswith("resp:") else h for h in rh[1:]]
            for r in rrows:
                resp[r["run_key"]] = {**r["values"], **r["measured"]}
    if not resp_names and not notes:
        notes.append("응답 파일이 없습니다")

    cap = ctx.settings.train_data.max_runs
    if len(rows) > cap:
        notes.append(f"앞 {cap}행만 표시합니다")
        rows = rows[:cap]

    out_rows: list[dict[str, Any]] = []
    cols: dict[str, list[float]] = {n: [] for n in names}
    usable = 0
    for i, r in enumerate(rows):
        state = states.get(r["run_key"], "UNKNOWN")
        failed = state in FAILED_STATES
        rv = resp.get(r["run_key"], {})
        responses = {n: (None if failed else _finite(rv.get(n))) for n in resp_names}
        if any(v is not None for v in responses.values()):
            usable += 1
        for n in names:
            v = _finite(r["values"].get(n))
            if v is not None:
                cols[n].append(v)
        out_rows.append({"run_id": r["run_key"], "no": _run_no(r["run_key"], i), "state": state,
                         "params": {n: _finite(r["values"].get(n)) for n in names}, "responses": responses})

    params = []
    for n in names:
        s, vs = snap.get(n), cols[n]
        lo = _finite(s.get("min")) if s else None
        hi = _finite(s.get("max")) if s else None
        params.append({"name": n, "integer": n in ints,
                       "min": lo if lo is not None else (min(vs) if vs else None),
                       "max": hi if hi is not None else (max(vs) if vs else None),
                       "unit": (s.get("unit") or None) if s else None})
    total = len(out_rows)
    need = max(5, len(names) + 2)
    options = d["options"] if isinstance(d.get("options"), dict) else {}
    if not resp_names:  # off: s14 조건(§20.7) — 사유는 influence_note
        cls, note = sampling_registry.OFF, sampling_registry.NOTE_NO_RESPONSE
    elif usable < need:
        cls, note = sampling_registry.OFF, sampling_registry.note_too_few_usable(need, usable)
    else:
        cls, note = sampling_registry.doe_influence(d["doe_type"], options)
    return {"doe_id": d["id"], "label": d["doe_label"], "study_id": d["study_id"], "type": d["doe_type"],
            "parameters": params, "responses": [{"name": n, "unit": None} for n in resp_names],
            "meta": {"engine_version": None, "baseline_id": None, "scene": None}, "rows": out_rows,
            "counts": {"total": total, "usable": usable, "no_response": total - usable},
            "sampling": _sampling(ctx, d, options),
            "influence_class": cls, "influence_note": note, "influence_ok": cls != sampling_registry.OFF, "notes": notes}
