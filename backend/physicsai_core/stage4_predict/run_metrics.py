"""run별 대표값(지표) — S12 설계공간 지도·S13 내장 최적화 공용(phase3 §17.2·§17.3, D3-59).

지표 id(`METRIC_RE` fullmatch, ASCII):
- `curve:max|min|absmax` — 고른 계열 y의 최대·최소·max(|max|,|min|) (계열 이름은 id 밖 `series`, 생략 = 첫 계열)
- `resp:<NAME>_MIN|_MAX` — 원본 m_4 TCL `RESPONSES.txt`의 값(실패 줄은 키 없음)
- `tbl:<name>` — 결과 표 값(`predict_batch_runs.responses`, 옛 방식 run)

파일 I/O는 `load_run_metrics`(+ 경로 찾기 `locate_run_files`의 존재 확인)만. 파일별 LRU(키 = 경로·mtime_ns·크기,
2048개, 잠금) — 같은 파일을 두 번 읽지 않고, 파일이 바뀌면(mtime·크기) 다시 읽는다. 링크·Study 밖 경로는 읽지 않는다.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..path_links import is_link_or_reparse, is_under, real
from .responses import RESPONSES_FILE, read_responses

METRIC_RE = re.compile(
    r"curve:(max|min|absmax)|resp:[A-Za-z][A-Za-z0-9_]{0,63}_(MIN|MAX)|tbl:[A-Za-z][A-Za-z0-9_]{0,63}", re.ASCII)
CURVE_KINDS = ("max", "min", "absmax")
MAX_SERIES = 50
CACHE_SIZE = 2048


@dataclass(frozen=True)
class RunFiles:
    """run 1개의 입력 파일(절대경로, 없거나 안전하지 않으면 None)."""

    curve_json: str | None
    result_dir: str | None


@dataclass(frozen=True)
class RunMetrics:
    """curve = {계열: {"max","min","absmax","x_at_max","x_at_min","n"}}(curve.json 없음·너무 큼 = None),
    resp = {"CornerStress_MAX": 1.5e2, …}(RESPONSES.txt 없음 = None). 공유 캐시 값이므로 고치지 않는다."""

    curve: dict[str, dict[str, float]] | None
    resp: dict[str, float] | None


# ---- 순수 함수 ------------------------------------------------------------------------------------


def _finite_list(v: Any) -> list[float] | None:
    if not isinstance(v, list):
        return None
    out: list[float] = []
    for e in v:
        if isinstance(e, bool) or not isinstance(e, (int, float)) or not math.isfinite(e):
            return None
        out.append(float(e))
    return out


def curve_stats(curve: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    """curve.json(§8.9 `{"series":[{name,x,y}]}`) → 계열별 통계. NaN·무한·길이 불일치·빈 계열 제외,
    같은 이름은 첫 계열만, 계열 ≤ MAX_SERIES. x_at_max·x_at_min = 첫 최대·최소 위치의 x."""
    out: dict[str, dict[str, float]] = {}
    series = curve.get("series") if isinstance(curve, Mapping) else None
    for s in series if isinstance(series, list) else []:
        if len(out) >= MAX_SERIES:
            break
        if not isinstance(s, Mapping):
            continue
        name = s.get("name")
        if not isinstance(name, str) or not name or name in out:
            continue
        xs, ys = _finite_list(s.get("x")), _finite_list(s.get("y"))
        if xs is None or ys is None or len(xs) != len(ys) or not ys:
            continue
        i_max = max(range(len(ys)), key=ys.__getitem__)
        i_min = min(range(len(ys)), key=ys.__getitem__)
        hi, lo = ys[i_max], ys[i_min]
        out[name] = {"max": hi, "min": lo, "absmax": max(abs(hi), abs(lo)),
                     "x_at_max": xs[i_max], "x_at_min": xs[i_min], "n": float(len(ys))}
    return out


def _finite(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def metric_value(m: RunMetrics, metric_id: str, *, series: str | None,
                 table: Mapping[str, Any] | None) -> float | None:
    """지표 값(유한 수, 없으면 None). series 생략 = 그 run의 첫 계열. 지표 id가 문법 밖이면 ValueError."""
    if not isinstance(metric_id, str) or not METRIC_RE.fullmatch(metric_id):
        raise ValueError(f"알 수 없는 지표 id: {metric_id!r}")
    kind, _, key = metric_id.partition(":")
    if kind == "curve":
        if not m.curve:
            return None
        name = series if series is not None else next(iter(m.curve))
        stats = m.curve.get(name)
        return _finite(stats.get(key)) if stats else None
    if kind == "resp":
        return _finite((m.resp or {}).get(key))
    return _finite((table or {}).get(key))


# ---- 경로 ----------------------------------------------------------------------------------------


def safe_study_path(study_root: str, rel: str | None) -> str | None:
    """Study 기준 상대경로 → 절대경로. Study 밖(`..`·절대경로·realpath 탈출)·경로 중간이나 끝의 링크면 None."""
    if not isinstance(rel, str) or not rel.strip():
        return None
    r = rel.replace("\\", "/")
    if r.startswith("/") or re.match(r"^[A-Za-z]:", r):
        return None
    base = os.path.normpath(study_root)
    target = os.path.normpath(os.path.join(base, *[p for p in r.split("/") if p]))
    if not is_under(target, base) or target == base:
        return None
    cur = base
    for part in os.path.relpath(target, base).split(os.sep):
        cur = os.path.join(cur, part)
        if is_link_or_reparse(cur):
            return None
    if not is_under(real(target), real(base)):
        return None
    return target


def locate_run_files(conn: Any, study_root: str, job: Mapping[str, Any] | None,
                     *, get_artifact: Callable[[Any, str], Mapping[str, Any] | None] | None = None) -> RunFiles:
    """하위 PREDICT 작업 행 → 파일 위치. curve = `result.curve_artifact_id`의 artifacts 행 rel_path,
    결과 폴더 = dirname(`result.pred_h3d_rel`)(= P/RESULT, RESPONSES.txt 위치). 없거나 링크·Study 밖이면 None."""
    result = (job or {}).get("result") or {}
    if not isinstance(result, Mapping):
        result = {}
    curve_path = None
    aid = result.get("curve_artifact_id")
    if isinstance(aid, str) and aid:
        if get_artifact is None:
            from ..db.repositories import artifacts as artifacts_repo

            get_artifact = artifacts_repo.get
        a = get_artifact(conn, aid)
        p = safe_study_path(study_root, (a or {}).get("rel_path"))
        curve_path = p if p and os.path.isfile(p) else None
    result_dir = None
    pred = result.get("pred_h3d_rel")
    if isinstance(pred, str) and pred:
        parent = os.path.dirname(pred.replace("\\", "/"))
        p = safe_study_path(study_root, parent) if parent else None
        result_dir = p if p and os.path.isdir(p) else None
    return RunFiles(curve_json=curve_path, result_dir=result_dir)


# ---- 파일 LRU -----------------------------------------------------------------------------------


class _Lru:
    def __init__(self, size: int) -> None:
        self.size = size
        self.data: OrderedDict[tuple[Any, ...], Any] = OrderedDict()
        self.lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get_or_load(self, key: tuple[Any, ...], load: Callable[[], Any]) -> Any:
        with self.lock:
            if key in self.data:
                self.data.move_to_end(key)
                self.hits += 1
                return self.data[key]
            self.misses += 1
        value = load()  # 잠금 밖에서 읽는다(같은 파일 동시 첫 호출은 두 번 읽을 수 있음 — 값은 같다)
        with self.lock:
            self.data[key] = value
            self.data.move_to_end(key)
            while len(self.data) > self.size:
                self.data.popitem(last=False)
        return value

    def clear(self) -> None:
        with self.lock:
            self.data.clear()
            self.hits = self.misses = 0


_CACHE = _Lru(CACHE_SIZE)


def cache_info() -> dict[str, int]:
    """시험·진단용: {hits, misses, size}."""
    with _CACHE.lock:
        return {"hits": _CACHE.hits, "misses": _CACHE.misses, "size": len(_CACHE.data)}


def cache_clear() -> None:
    _CACHE.clear()


def _stat_key(kind: str, path: str) -> tuple[Any, ...] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (kind, path, st.st_mtime_ns, st.st_size)


def _load_curve(path: str) -> dict[str, dict[str, float]] | None:
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return curve_stats(data) if isinstance(data, Mapping) else None


def _load_resp(folder: str) -> dict[str, float] | None:
    try:
        parsed = read_responses(folder)
    except OSError:
        return None
    return None if parsed is None else dict(parsed.values)


def load_run_metrics(files: RunFiles, *, max_bytes: int) -> RunMetrics:
    """파일 → 지표(LRU). curve.json이 max_bytes보다 크면 커브 없음(None), RESPONSES.txt도 같은 상한."""
    curve = None
    if files.curve_json:
        key = _stat_key("curve", files.curve_json)
        if key is not None and key[3] <= max_bytes:
            curve = _CACHE.get_or_load(key, lambda: _load_curve(files.curve_json))  # type: ignore[arg-type]
    resp = None
    if files.result_dir:
        rp = os.path.join(files.result_dir, RESPONSES_FILE)
        key = None if is_link_or_reparse(rp) else _stat_key("resp", rp)
        if key is not None and key[3] <= max_bytes:
            resp = _CACHE.get_or_load(key, lambda: _load_resp(files.result_dir))  # type: ignore[arg-type]
    return RunMetrics(curve=curve, resp=resp)
