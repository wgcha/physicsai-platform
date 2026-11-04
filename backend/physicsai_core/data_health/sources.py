"""run 출력·입력 읽기(data-health.md §3.1·§3.6·§4) — 꼬리·요약만, 결과 파일 본문을 대량으로 읽지 않는다. 외부 도구 실행 없음.

- `engine_out_info`  `R(run)` 재귀 `engine_out_glob` 정확히 1개의 꼬리 → 종료 판정·마지막 사이클 줄(에너지 오차·MAS.ERR·시각)
- `starter_mass_of`  `starter_out_glob` 첫 일치 총질량(상한 넘으면 OUT_TOO_LARGE)
- `rad_tstop`        입력 폴더 `engine_rad_glob`의 `/RUN` 다음 줄 Tstop
- `frames_from_cache`·`frames_from_out`  프레임 원천 ①②(③ DH_FRAMES는 워커)
- `t01_ratios`       ②-4 곡선 JSON series → hg/접촉 에너지 비
- `read_responses`   ①-6 `responses_run.csv` 재사용(spec 일치)
"""

from __future__ import annotations

import fnmatch
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..equiv.sides import _files
from ..parsers import radioss_out
from ..parsers.name_value import read_name_value_csv
from ..path_links import is_link_or_reparse
from .stats import finite


def list_files(folder: str | None, pattern: str, *, recursive: bool) -> list[str]:
    """폴더(직계 또는 재귀, `_backup`·링크 제외)의 패턴(대소문자 무시) 일치 파일 — equiv `sides._files` 그대로."""
    return _files(folder, pattern.lower(), recursive=recursive) if folder else []


# ---- engine out ------------------------------------------------------------------------------------


@dataclass
class OutInfo:
    values: dict[str, Any]   # term, energy_err_pct, added_mass, t_last_out (찾은 것만)
    na: dict[str, str]       # 지표 id → 사유(OUT_MISSING·OUT_AMBIGUOUS·NO_CYCLE_LINE)


def engine_out_info(folder: str | None, d: Any, *, recursive: bool) -> OutInfo:
    files = list_files(folder, d.engine_out_glob, recursive=recursive)
    info = OutInfo({}, {})
    if len(files) != 1:
        reason = "OUT_MISSING" if not files else "OUT_AMBIGUOUS"
        for mid in ("term", "energy_err_pct", "added_mass"):
            info.na[mid] = reason
        info.na["t_last_out"] = reason
        return info
    try:
        tail = radioss_out.read_engine_tail(files[0], limit=d.out_tail_bytes, normal_regex=d.normal_regex,
                                            error_regex=d.error_regex, cycle_regex=d.cycle_regex)
    except OSError:
        for mid in ("term", "energy_err_pct", "added_mass", "t_last_out"):
            info.na[mid] = "OUT_MISSING"
        return info
    info.values["term"] = tail.term
    cyc = tail.cycle
    for mid, v in (("energy_err_pct", cyc.err if cyc else None), ("added_mass", cyc.mas if cyc else None),
                   ("t_last_out", cyc.time if cyc else None)):
        if v is None:
            info.na[mid] = "NO_CYCLE_LINE"
        else:
            info.values[mid] = v
    return info


def starter_mass_of(folders: Sequence[str | None], d: Any) -> tuple[float | None, str | None]:
    """R(run)→입력 폴더 순서로 starter 출력의 `TOTAL MASS`. (값, NA 사유)."""
    too_large = False
    for f in folders:
        if not f or not os.path.isdir(f):
            continue
        for n in sorted(os.listdir(f)):
            if not any(fnmatch.fnmatch(n.lower(), g.lower()) for g in d.starter_out_glob):
                continue
            p = os.path.join(f, n)
            if not os.path.isfile(p) or is_link_or_reparse(p):
                continue
            try:
                m = radioss_out.starter_total_mass(p, regex=d.total_mass_regex, max_bytes=d.starter_scan_max_bytes)
            except radioss_out.ScanTooLarge:
                too_large = True
                continue
            except (OSError, ValueError):
                continue
            if m is not None and math.isfinite(m):
                return m, None
    return None, "OUT_TOO_LARGE" if too_large else "MASS_SOURCE_MISSING"


# ---- 입력 rad ---------------------------------------------------------------------------------------


def parse_rad_tstop(lines: Sequence[str]) -> float | None:
    """`/RUN/...` 줄 다음 첫 데이터 줄(빈 줄·`#` 주석 제외)의 첫 수 = Tstop. 다른 `/` 블록이 먼저 오면 None."""
    seen = False
    for raw in lines:
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if not seen:
            seen = s.upper().startswith("/RUN")
            continue
        if s.startswith("/"):
            return None
        tok = s.replace(",", " ").split()
        return finite(_to_float(tok[0])) if tok else None
    return None


def _to_float(s: str) -> float | None:
    try:
        return float(s.replace("D", "E").replace("d", "e"))
    except ValueError:
        return None


def rad_tstop(folder: str | None, d: Any) -> tuple[float | None, str | None]:
    """입력 폴더의 `engine_rad_glob` 파일(정확히 1개)에서 Tstop. (값, NA 사유). 크기 > engine_rad_max_bytes → NA."""
    files = list_files(folder, d.engine_rad_glob, recursive=False)
    if len(files) != 1:
        return None, "RAD_MISSING" if not files else "RAD_AMBIGUOUS"
    try:
        if os.path.getsize(files[0]) > d.engine_rad_max_bytes:
            return None, "RAD_TOO_LARGE"
        with open(files[0], encoding="utf-8", errors="replace") as fh:
            v = parse_rad_tstop(fh.read().splitlines())
    except OSError:
        return None, "RAD_MISSING"
    return (v, None) if v is not None else (None, "RAD_NO_TSTOP")


# ---- 프레임 원천 ①② --------------------------------------------------------------------------------


def frames_from_manifest(man: Mapping[str, Any] | None) -> tuple[int | None, float | None]:
    """3D 컨투어 manifest → (h3d 전체 프레임 수, 마지막 원본 프레임 시각). 마지막 원본 프레임(src = 전체−1)이 목록에 있을 때만 시각."""
    if not isinstance(man, Mapping):
        return None, None
    total = (man.get("sampling") or {}).get("total_frames") if isinstance(man.get("sampling"), Mapping) else None
    if isinstance(total, bool) or not isinstance(total, int) or total < 1:
        return None, None
    lst = (man.get("frames") or {}).get("list") if isinstance(man.get("frames"), Mapping) else None
    t_last = None
    if isinstance(lst, list) and lst and isinstance(lst[-1], Mapping):
        last = lst[-1]
        if last.get("src") == total - 1:
            t_last = finite(last.get("time"))
    return total, t_last


def read_manifest(path: str, max_bytes: int) -> dict[str, Any] | None:
    try:
        if os.path.getsize(path) > max_bytes:
            return None
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def frames_from_out(folder: str | None, d: Any, *, recursive: bool) -> int | None:
    """② engine out(정확히 1개) 줄 단위 스캔: `frame_write_regex` 일치 수. regex 없음·파일 상한 초과·0건이면 None."""
    if not d.frame_write_regex:
        return None
    files = list_files(folder, d.engine_out_glob, recursive=recursive)
    if len(files) != 1:
        return None
    rx = re.compile(d.frame_write_regex, re.I)
    try:
        if os.path.getsize(files[0]) > d.engine_scan_max_bytes:
            return None
        with open(files[0], encoding="utf-8", errors="replace") as fh:
            n = sum(1 for line in fh if rx.search(line))
    except OSError:
        return None
    return n or None


# ---- T01 곡선(②-4) ----------------------------------------------------------------------------------


def curve_max(curve: Mapping[str, Any] | None, name: str | None) -> float | None:
    """곡선 JSON `{"series":[{name,x,y}]}`에서 이름(공백·대소문자 무시)이 맞는 계열의 최대 y."""
    if not isinstance(curve, Mapping) or not name:
        return None
    key = re.sub(r"\s+", "", name).casefold()
    for s in curve.get("series") or []:
        if isinstance(s, Mapping) and isinstance(s.get("name"), str) and re.sub(r"\s+", "", s["name"]).casefold() == key:
            ys = [f for f in (finite(v) for v in (s.get("y") or [])) if f is not None]
            return max(ys) if ys else None
    return None


def t01_ratios(curve: Mapping[str, Any] | None, series: Any, zero_tol: float) -> tuple[dict[str, float], dict[str, str]]:
    """(values{hg_ratio, contact_ratio}, na{id: 사유}). series = 설정 t01_series(null → T01_CURVE_NONE). IE 최대 ≤ zero_tol → IE_ZERO."""
    vals: dict[str, float] = {}
    na: dict[str, str] = {}
    if series is None or curve is None:
        return vals, {"hg_ratio": "T01_CURVE_NONE", "contact_ratio": "T01_CURVE_NONE"}
    ie = curve_max(curve, series.internal)
    for mid, nm in (("hg_ratio", series.hourglass), ("contact_ratio", series.contact)):
        if not nm:
            na[mid] = "T01_CURVE_NONE"
            continue
        top = curve_max(curve, nm)
        if ie is None or top is None:
            na[mid] = "T01_CURVE_NONE"
        elif ie <= zero_tol:
            na[mid] = "IE_ZERO"
        else:
            vals[mid] = top / ie
    return vals, na


# ---- 응답(①-6) ---------------------------------------------------------------------------------------


def _spec_key(spec: Mapping[str, Any] | None) -> tuple[str, ...]:
    from ..equiv.plan import RESPONSE_SPEC_KEYS

    sp = spec or {}
    return tuple(str(sp.get(k) or "").upper() if k != "series" else str(sp.get(k) or "") for k in RESPONSE_SPEC_KEYS)


def scalar_response_defs(responses: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """`D/responses.json`의 스칼라 응답(CURVE 종류 제외). `[{name, unit, spec}]`."""
    out = []
    for r in responses or []:
        if not isinstance(r, Mapping) or not r.get("name"):
            continue
        spec = r.get("spec") if isinstance(r.get("spec"), Mapping) else {}
        if str(spec.get("source") or "H3D").upper() == "CURVE":
            continue
        out.append({"name": str(r["name"]), "unit": str(r.get("unit") or ""), "spec": dict(spec)})
    return out


def read_responses(run_dir: str | None, defs: Sequence[Mapping[str, Any]], current: Sequence[Mapping[str, Any]] | None
                   ) -> tuple[dict[str, float], dict[str, str]]:
    """`R(run)/responses_run.csv`(이름,값) 재사용. 같은 이름의 현재 정의(`current` — 파라미터 세트 성능 정의)가 있고 spec이 다르면
    SPEC_CHANGED, 파일·값 없음은 RESP_NOT_EXTRACTED(추출은 하지 않는다). 반환 (값, NA 사유)."""
    cur = {str(c.get("name")): c for c in (current or []) if isinstance(c, Mapping)}
    path = os.path.join(run_dir, "responses_run.csv") if run_dir else None
    raw = read_name_value_csv(path) if path and os.path.isfile(path) and not is_link_or_reparse(path) else None
    vals: dict[str, float] = {}
    na: dict[str, str] = {}
    for df in defs:
        name = df["name"]
        c = cur.get(name)
        if c is not None and isinstance(c.get("spec"), Mapping) and _spec_key(c["spec"]) != _spec_key(df.get("spec")):
            na[name] = "SPEC_CHANGED"
            continue
        v = finite(raw.get(name)) if raw is not None else None
        if v is None:
            na[name] = "RESP_NOT_EXTRACTED"
        else:
            vals[name] = v
    return vals, na
