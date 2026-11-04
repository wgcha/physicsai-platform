"""run 판정·점수·`report.json`·`runs.csv`(data-health.md §3.5·§3.6·§6.2). 입력은 스캔 행(dict) 목록 — 파일·DB·도구 없음.

스캔 행: `{file_rel, run_key, doe_id, params|None, values{id: 원값}, na{id: 사유}, t_end|None}`.
판정: required(일관성 위반) · ① FAIL · 견고 z(ROBUST_Z) · kNN(KNN_JUMP)만 추천 — 일반 3σ는 "3σ만" 표시(sigma_only).
"""

from __future__ import annotations

import csv
import io
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import knn as knn_mod
from . import metrics as mx
from .stats import SKIP_SMALL_N, finite, summarize

REQUIRED_SCORE = 100.0
MIN_REF_RUNS = 3   # 설정 기대값 없이 최빈값으로 기준을 정하려면 유효 run ≥ 3(§3.6)
RAW_BASE = ("term", "energy_err_pct", "added_mass", "hg_ratio", "contact_ratio", "frames", "t_last", "t_end")


@dataclass
class Reference:
    value: float | int | None
    source: str | None       # "설정" | "최빈"
    code: str | None = None  # 기준이 없을 때 사유(DH_REF_TIE·SKIP_SMALL_N)


def _fmt(v: Any) -> str:
    return f"{v:.6g}" if isinstance(v, float) else str(v)


def mode_int(values: Sequence[int]) -> Reference:
    if len(values) < MIN_REF_RUNS:
        return Reference(None, None, SKIP_SMALL_N)
    top = Counter(values).most_common()
    if len(top) > 1 and top[0][1] == top[1][1]:
        return Reference(None, None, "DH_REF_TIE")
    return Reference(top[0][0], "최빈")


def mode_time(values: Sequence[float], tol: float) -> Reference:
    """상대 차 ≤ tol인 값을 같은 값으로 묶어 최빈 군집을 센다. 군집 값 = 군집 중앙값. 최빈 동률 → 기준 없음."""
    if len(values) < MIN_REF_RUNS:
        return Reference(None, None, SKIP_SMALL_N)
    groups: list[list[float]] = []
    for v in sorted(values):
        if groups and abs(v - groups[-1][0]) <= tol * abs(groups[-1][0]):
            groups[-1].append(v)
        else:
            groups.append([v])
    groups.sort(key=lambda g: -len(g))
    if len(groups) > 1 and len(groups[0]) == len(groups[1]):
        return Reference(None, None, "DH_REF_TIE")
    g = sorted(groups[0])
    return Reference(g[len(g) // 2] if len(g) % 2 else (g[len(g) // 2 - 1] + g[len(g) // 2]) / 2, "최빈")


def references(rows: Sequence[Mapping[str, Any]], d: Any) -> tuple[dict[str, Reference], dict[str, Reference], list[dict[str, str]]]:
    """DOE마다(DOE 연결이 없으면 입력 전체) F_ref·T_ref. 설정 기대값 우선. 반환 (frames 기준, t_end 기준, 경고)."""
    fr: dict[str, Reference] = {}
    tr: dict[str, Reference] = {}
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for r in rows:
        groups.setdefault(r.get("doe_id") or "", []).append(r)
    for g, rs in groups.items():
        if d.expected_frames is not None:
            fr[g] = Reference(int(d.expected_frames), "설정")
        else:
            fr[g] = mode_int([int(v) for v in (finite(x["values"].get("frames")) for x in rs) if v is not None])
        if d.expected_t_end is not None:
            tr[g] = Reference(float(d.expected_t_end), "설정")
        else:
            tr[g] = mode_time([v for v in (finite(x.get("t_end")) for x in rs) if v is not None], d.t_end_tol)
    warns: list[dict[str, str]] = []
    if any(r.code == "DH_REF_TIE" for r in [*fr.values(), *tr.values()]):
        warns.append({"code": "DH_REF_TIE", "message": "프레임 수 또는 종료 시각의 최빈값이 같은 횟수로 갈려 기준을 정할 수 없습니다 — 그 지표는 검사하지 않았습니다"})
    for what, refs in (("프레임 수", fr), ("종료 시각", tr)):
        vals = {r.value for r in refs.values() if r.value is not None}
        if len(vals) > 1:
            warns.append({"code": "DH_REF_DOE_DIFF", "message": f"DOE마다 {what} 기준이 다릅니다({', '.join(_fmt(v) for v in sorted(vals))}) — 한 데이터셋 안 불일치입니다"})
            break
    return fr, tr, warns


def _label(m: mx.MetricDef) -> str:
    return m.label


def _reason(code: str, metric: str | None, message: str, **kw: Any) -> dict[str, Any]:
    return {"code": code, "metric": metric, "value": kw.get("value"), "z": kw.get("z"), "zr": kw.get("zr"), "s": kw.get("s"), "message": message}


@dataclass
class Scored:
    report: dict[str, Any]
    runs: list[dict[str, Any]] = field(default_factory=list)   # report.runs(전체, 정렬됨)
    summary: dict[str, Any] = field(default_factory=dict)
    zmetric_ids: list[str] = field(default_factory=list)


def score(rows: Sequence[Mapping[str, Any]], zmetrics: Sequence[mx.MetricDef], d: Any, *,
          snapshots: Mapping[str, Sequence[Mapping[str, Any]]] | None = None, extra_warnings: Sequence[Mapping[str, str]] = (),
          limited: bool = False) -> Scored:
    warnings: list[dict[str, Any]] = [dict(w) for w in extra_warnings]
    fref, tref, w2 = references(rows, d)
    warnings += w2
    # ---- z 통계 ----
    stats = {m.id: summarize([r["values"].get(m.id) for r in rows], d.min_n) for m in zmetrics}
    # ---- kNN ----
    snap_all: dict[str, dict[str, Any]] = {}
    for sn in (snapshots or {}).values():
        for s in sn:
            nm = str(s.get("name"))
            a, b = finite(s.get("min")), finite(s.get("max"))
            cur = snap_all.get(nm)
            if a is None or b is None:
                continue
            snap_all[nm] = {"name": nm, "min": a if cur is None else min(cur["min"], a), "max": b if cur is None else max(cur["max"], b)}
    space = knn_mod.build_space({r["file_rel"]: r.get("params") for r in rows}, list(snap_all.values()))
    if space.mixed:
        warnings.append({"code": "DH_PARAMS_MIXED", "message": "run마다 파라미터 이름이 달라 파라미터 공간 이웃 비교(kNN)를 건너뛰었습니다(여러 DOE 혼합)"})
    knn = {m.id: knn_mod.knn_scores(space, {r["file_rel"]: r["values"].get(m.id) for r in rows}, knn_k=d.knn_k, knn_min_n=d.knn_min_n)
           for m in zmetrics}
    # ---- run별 ----
    out_runs: list[dict[str, Any]] = []
    n_frames_unknown = 0
    n_undecided = 0
    for i, r in enumerate(rows):
        g = r.get("doe_id") or ""
        vals, na = r["values"], r.get("na") or {}
        reasons: list[dict[str, Any]] = []
        required = False
        undecided = False  # 값은 있지만 기준(F_ref·T_ref)이 없어 판정하지 못함(동률·유효 run 3 미만·기대값 없음)
        # 일관성
        cons: dict[str, Any] = {}
        fv = finite(vals.get("frames"))
        if fv is None:
            n_frames_unknown += 1
            cons["frames"] = {"status": "NA", "value": None, "ref": fref[g].value, "code": na.get("frames") or "FRAMES_SOURCE_NONE"}
        elif fref[g].value is None:
            undecided = True
            cons["frames"] = {"status": "NA", "value": int(fv), "ref": None, "code": fref[g].code}
        else:
            bad = int(fv) != int(fref[g].value)
            cons["frames"] = {"status": "FAIL" if bad else "OK", "value": int(fv), "ref": int(fref[g].value), "code": "CONSISTENCY_FRAMES" if bad else None}
            if bad:
                required = True
                reasons.append(_reason("CONSISTENCY_FRAMES", "frames", f"h3d 프레임 수 {int(fv)}가 기준 {int(fref[g].value)}와 다름", value=int(fv)))
        tv, tref_v = finite(vals.get("t_last")), tref[g].value
        if tv is None:
            cons["t_last"] = {"status": "NA", "value": None, "ref": tref_v, "code": na.get("t_last") or "TIME_SOURCE_NONE"}
        elif tref_v is None:
            undecided = True
            cons["t_last"] = {"status": "NA", "value": tv, "ref": None, "code": tref[g].code}
        else:
            bad = tv < tref_v * (1 - d.t_end_tol)
            cons["t_last"] = {"status": "FAIL" if bad else "OK", "value": tv, "ref": tref_v, "code": "CONSISTENCY_TEND" if bad else None}
            if bad:
                required = True
                reasons.append(_reason("CONSISTENCY_TEND", "t_last", f"마지막 해석 시각 {tv:.6g}이 기준 {tref_v:.6g}에 못 미침(허용 −{d.t_end_tol * 100:g}%)", value=tv))
        te = finite(r.get("t_end"))
        if te is not None and tref_v is not None and abs(te - tref_v) > d.t_end_tol * abs(tref_v):
            required = True
            reasons.append(_reason("CONSISTENCY_TEND_DIFF", "t_last", f"입력 종료 시각(Tstop) {te:.6g}이 기준 {tref_v:.6g}와 다름", value=te))
        n_undecided += undecided
        # ① 건전성
        sound = mx.judge_sound(vals, na, d)
        fails = [s for s in sound.values() if s.status == "FAIL"]
        for s in fails:
            reasons.append(_reason(s.code or "SOUND", s.id, s.message or "", value=s.value))
        # 통계·kNN
        vv: dict[str, dict[str, Any]] = {}
        max_zr = max_s = 0.0
        sigma = False
        for m in zmetrics:
            v = finite(vals.get(m.id))
            st, kr = stats[m.id], knn[m.id]
            if v is None:
                vv[m.id] = {"v": None, "z": None, "zr": None, "s": None, "na": na.get(m.id) or "NA", "fail": False}
                continue
            z, zr = st.z[i], st.zr[i]
            s_ = kr.s.get(r["file_rel"])
            e = {"v": v, "z": z, "zr": zr, "s": s_, "na": SKIP_SMALL_N if st.skipped else None,
                 "knn_dist": kr.mean_dist.get(r["file_rel"])}
            e["fail"] = False
            vv[m.id] = e
            if zr is not None:
                max_zr = max(max_zr, abs(zr))
                if abs(zr) > d.robust_z:
                    e["fail"] = True
                    reasons.append(_reason("ROBUST_Z", m.id, f"{m.label} 견고 z {zr:.2f}(값 {v:.6g}, 중앙값 {st.median:.6g}, MAD {st.mad:.6g})",
                                           value=v, z=z, zr=zr))
            if z is not None and abs(z) > d.sigma_z:
                sigma = True
            if s_ is not None:
                max_s = max(max_s, abs(s_))
                if abs(s_) > d.knn_z:
                    e["fail"] = True
                    reasons.append(_reason("KNN_JUMP", m.id, f"이웃 대비 튐 {m.label} 점수 {s_:.2f}", value=v, s=s_))
        sc = max(REQUIRED_SCORE if required else 0.0, (1 + len(fails)) if fails else 0.0, max_zr / d.robust_z, max_s / d.knn_z)
        recommended = required or bool(fails) or any(x["code"] in ("ROBUST_Z", "KNN_JUMP") for x in reasons)
        out_runs.append({
            "file_rel": r["file_rel"], "run_key": r.get("run_key"), "doe_id": r.get("doe_id"), "recommended": recommended, "required": required,
            "score": round(sc, 4), "sigma_only": bool(sigma and not recommended), "sound": {k: _sound_dict(s) for k, s in sound.items()},
            "consistency": cons, "values": vv, "reasons": reasons, "t_end": te,
        })
    out_runs.sort(key=lambda x: (not x["required"], -x["score"], x["file_rel"]))
    # ---- 지표 요약 ----
    mlist = []
    for m in zmetrics:
        st = stats[m.id]
        if st.n == 0:
            continue
        mlist.append({"id": m.id, "label": m.label, "unit": m.unit, "group": m.group, "n": st.n, "mean": st.mean, "std": st.std,
                      "median": st.median, "mad": st.mad, "skipped": st.skipped, "knn_skipped": knn[m.id].skipped})
    n_na: dict[str, int] = {}
    for mid in (*RAW_BASE, *(m.id for m in zmetrics)):
        c = sum(1 for r in rows if (finite(r.get("t_end")) if mid == "t_end" else r["values"].get(mid)) is None)
        if c:
            n_na[mid] = c
    if n_undecided:
        warnings.append({"code": "DH_CONSISTENCY_UNDECIDED", "count": n_undecided, "message":
                         f"기준값(프레임 수·종료 시각 최빈값)을 정하지 못해 일관성을 판정하지 못한 run {n_undecided}개 — 기준 동률이거나 유효 run이 {MIN_REF_RUNS}개 미만입니다"
                         "(설정 data_health.expected_frames·expected_t_end로 기준을 지정할 수 있습니다)"})
    fr_vals = {x.value for x in fref.values() if x.value is not None}
    tr_vals = {x.value for x in tref.values() if x.value is not None}
    summary = {
        "n_runs": len(rows), "n_required": sum(1 for x in out_runs if x["required"]), "n_recommended": sum(1 for x in out_runs if x["recommended"]),
        "n_sigma_only": sum(1 for x in out_runs if x["sigma_only"]),
        "n_sound_fail": sum(1 for x in out_runs if any(s["status"] == "FAIL" for s in x["sound"].values())),
        "n_frames_unknown": n_frames_unknown, "n_consistency_undecided": n_undecided,
        "frames_ref": next(iter(fr_vals)) if len(fr_vals) == 1 else None, "t_end_ref": next(iter(tr_vals)) if len(tr_vals) == 1 else None,
        "ref_source": "config" if any(x.source == "설정" for x in (*fref.values(), *tref.values())) else
        ("mode" if any(x.value is not None for x in (*fref.values(), *tref.values())) else None),
        "frames_ref_source": next((x.source for x in fref.values() if x.value is not None), None),
        "t_end_ref_source": next((x.source for x in tref.values() if x.value is not None), None),
        "refs_by_doe": {g: {"frames": fref[g].value, "t_end": tref[g].value} for g in fref} if len(fref) > 1 else {},
        "n_na_by_metric": n_na, "metrics_used": [m["id"] for m in mlist], "limited": limited, "warnings": warnings,
    }
    report = {"summary": summary, "metrics": mlist, "runs": out_runs, "truncated": False}
    return Scored(report, out_runs, summary, [m.id for m in zmetrics])


def _sound_dict(s: mx.SoundResult) -> dict[str, Any]:
    return {"status": s.status, "value": s.value, "limit": s.limit, "code": s.code, "v": s.value if isinstance(s.value, (int, float)) else None,
            "na": s.code if s.status == "NA" else None, "fail": s.status == "FAIL"}


def clean_json(obj: Any) -> Any:
    """NaN·무한을 None으로(JSON 표준). 읽는 쪽(브라우저)이 NaN 토큰을 못 읽는다."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v) for v in obj]
    return obj


def fit_report(report: dict[str, Any], max_bytes: int, max_rows: int) -> dict[str, Any]:
    """직렬화 크기 > max_bytes면 runs를 score 상위 max_rows로 자른다(truncated=true). 그래도 크면 절반씩 줄인다."""
    rep = clean_json(report)
    size = len(json.dumps(rep, ensure_ascii=False).encode("utf-8"))
    if size <= max_bytes:
        return rep
    runs = sorted(rep["runs"], key=lambda x: (not x["required"], -x["score"], x["file_rel"]))
    keep = min(len(runs), max_rows)
    while True:
        rep = {**rep, "runs": runs[:keep], "truncated": True}
        if keep <= 1 or len(json.dumps(rep, ensure_ascii=False).encode("utf-8")) <= max_bytes:
            return rep
        keep = max(1, keep // 2)


# ---- CSV ---------------------------------------------------------------------------------------------


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return repr(v) if math.isfinite(v) else ""
    return str(v)


def raw_columns(zmetric_ids: Sequence[str]) -> list[str]:
    return [*RAW_BASE, *zmetric_ids]


def raw_csv_text(rows: Sequence[Mapping[str, Any]], zmetric_ids: Sequence[str]) -> str:
    cols = raw_columns(zmetric_ids)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["file_rel", "run_key", "doe_id", *cols, *[f"{c}_na" for c in cols]])
    for r in rows:
        def val(c: str) -> Any:
            return r.get("t_end") if c == "t_end" else r["values"].get(c)

        na = r.get("na") or {}
        w.writerow([r["file_rel"], r.get("run_key") or "", r.get("doe_id") or "", *[_cell(val(c)) for c in cols],
                    *[_cell(na.get(c)) if val(c) is None else "" for c in cols]])
    return buf.getvalue()


def runs_csv_text(rows: Sequence[Mapping[str, Any]], scored: Scored) -> str:
    by = {x["file_rel"]: x for x in scored.runs}
    zids = scored.zmetric_ids
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    cols = raw_columns(zids)
    w.writerow(["file_rel", "run_key", "doe_id", *cols, *[f"{c}_na" for c in cols], *[f"{m}_{k}" for m in zids for k in ("z", "zr", "s")],
                "recommended", "required", "score", "sigma_only", "reasons"])
    for r in rows:
        x = by[r["file_rel"]]
        na = r.get("na") or {}

        def val(c: str) -> Any:
            return r.get("t_end") if c == "t_end" else r["values"].get(c)

        stat = []
        for m in zids:
            e = x["values"].get(m) or {}
            stat += [_cell(e.get("z")), _cell(e.get("zr")), _cell(e.get("s"))]
        w.writerow([r["file_rel"], r.get("run_key") or "", r.get("doe_id") or "", *[_cell(val(c)) for c in cols],
                    *[_cell(na.get(c)) if val(c) is None else "" for c in cols], *stat, str(x["recommended"]).lower(),
                    str(x["required"]).lower(), _cell(x["score"]), str(x["sigma_only"]).lower(), ";".join(q["code"] for q in x["reasons"])])
    return buf.getvalue()
