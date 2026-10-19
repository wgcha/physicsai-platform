"""템플릿 성능 값 계산(phase3 §22.3.3 S17, P4) — 순수 함수(파일 I/O 없음, `run_metrics.RunMetrics` 재사용).

API(미리보기·상세·runs.csv)와 워커(SO_COLLECT·RESPONSE_EXTRACT의 CURVE 값·PB_RESP_EXTRACT)가 같은 함수를 써서 화면·CSV·
대리모델 학습 값이 어긋나지 않게 한다. 성능 = 템플릿 응답 정의(`param_sets.responses`)의 spec 있는 행.

- H3D: run 폴더 `H3D_REQUESTS.txt` 줄과 정의 비교(다르면 SPEC_CHANGED, 요청 파일 없으면 비교 생략) → `responses.apply_stat` 규칙.
- CURVE: curve.json 계열(null = 첫 계열)의 max·min·absmax.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .responses import ParsedResponses, apply_stat, h3d_request, request_key
from .run_metrics import RunMetrics

SOURCES = ("H3D", "CURVE")
CURVE_STAT_KEY = {"MAX": "max", "MIN": "min", "ABSMAX": "absmax"}
CURVE_STAT_LABEL = {"MAX": "커브 최대", "MIN": "커브 최소", "ABSMAX": "커브 |최대|"}


@dataclass(frozen=True)
class PerfDef:
    name: str
    unit: str
    source: str  # "H3D" | "CURVE"
    spec: Mapping[str, Any]

    @property
    def stat(self) -> str:
        return str(self.spec.get("stat") or "MAX").upper()


def perf_defs(ps_responses: Sequence[Mapping[str, Any]] | None) -> dict[str, PerfDef]:
    """템플릿 응답 정의 → {이름: PerfDef}(spec 있는 행만, 순서 유지). source 없는 spec은 H3D(기존 형식)."""
    out: dict[str, PerfDef] = {}
    for r in ps_responses or []:
        if not isinstance(r, Mapping):
            continue
        name, spec = r.get("name"), r.get("spec")
        if not isinstance(name, str) or not name or not isinstance(spec, Mapping) or name in out:
            continue
        src = str(spec.get("source") or "H3D").upper()
        if src not in SOURCES:
            continue
        out[name] = PerfDef(name, str(r.get("unit") or ""), src, dict(spec))
    return out


def _finite(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def perf_value(d: PerfDef, m: RunMetrics) -> tuple[float | None, str | None]:
    """(값, 사유). 사유: SPEC_CHANGED | NOT_EXTRACTED | NO_VALUE | NO_CURVE | SERIES_MISSING | SPEC_INVALID."""
    if d.source == "CURVE":
        if m.curve is None:
            return None, "NO_CURVE"
        series = d.spec.get("series")
        if series is None:
            if not m.curve:
                return None, "SERIES_MISSING"
            series = next(iter(m.curve))
        stats = m.curve.get(series)
        if not stats:
            return None, "SERIES_MISSING"
        key = CURVE_STAT_KEY.get(d.stat)
        v = _finite(stats.get(key)) if key else None
        return (v, None) if v is not None else (None, "NO_VALUE")
    req, why = h3d_request({"name": d.name, "spec": {**dict(d.spec), "source": "H3D"}})
    if req is None:
        return None, why or "SPEC_INVALID"
    if m.requests is not None and d.name in m.requests and tuple(m.requests[d.name]) != request_key(req):
        return None, "SPEC_CHANGED"
    if m.resp is None:
        return None, "NOT_EXTRACTED"
    v, reason = apply_stat(req, ParsedResponses(values=dict(m.resp)))
    v = _finite(v)
    if v is None:
        return None, "NO_VALUE" if reason in (None, "MISSING") else reason
    return v, None


def perf_label(d: PerfDef) -> str:
    """"CornerStress (MAX)" · "AccelPeak (커브 |최대|, Node 100 / X)" · 계열 null이면 "AccelPeak (커브 |최대|)"."""
    if d.source == "CURVE":
        base = CURVE_STAT_LABEL.get(d.stat, d.stat)
        series = d.spec.get("series")
        return f"{d.name} ({base}, {series})" if series else f"{d.name} ({base})"
    return f"{d.name} ({d.stat})"


def perf_id(name: str) -> str:
    return f"perf:{name}"
