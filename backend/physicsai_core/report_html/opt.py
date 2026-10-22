"""⑥ 최적화 보고서 본문(upload-report.md §9.3.3): 내장 `surrogate-opt`(ego·ga·nsga2)와 HyperStudy 레거시 `optimization`.

입력은 일반 dict — 내장은 `GET /surrogate-opts/{id}` 상세(+ 입력 요약·컨투어 그림 경로), 레거시는 `GET /optimizations/{id}` 응답(+ 결과 표).
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..sampling.registry import METHODS
from .common import (OP_TEXT, SENSE_TEXT, STATUS_TEXT, con_key, con_text, engine_text, metric_name, model_text, param_set_text,
                     study_meta, values_text, verdict_badge)
from .page import (Ctx, Doc, Raw, badge, bars_h, cards, details, empty, esc, finite, fmt, kv_table, line_chart, note, pct,
                   scatter_chart, table)

ALGO_TEXT = {"ego": "EGO(기대 개선)", "ga": "GA(유전 알고리즘)", "nsga2": "NSGA-II"}
VERIFY_TEXT = {"loop": "반복 검증(대리모델 → 해석 예측으로 검증을 되풀이)", "none": "검증 없음(대리모델만)"}
KIND_TEXT = {"EXPLORE": "탐색", "REUSE": "재사용", "VERIFY": "검증", "EXTRA": "추가 검증"}
STATE_TEXT = {"SUCCEEDED": "성공", "FAILED": "실패", "GEN_FAILED": "생성 실패", "CANCELED": "취소", "UNVERIFIED": "미검증"}


def _f(v: Any, d: int = 4) -> Raw:
    return Raw(fmt(v, d))


def _opt_defs(d: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = list(d.get("objectives") or [])
    if out:
        return out
    s = d.get("settings") or {}
    return [{"metric": o["metric"], "series": o.get("series"), "sense": o.get("sense"), "label": metric_name(o["metric"], o.get("series")), "unit": ""}
            for o in (s.get("objectives") or ([s["objective"]] if s.get("objective") else []))]


def _obj_label(o: Mapping[str, Any]) -> str:
    return f"{o.get('label') or metric_name(o['metric'], o.get('series'))}{(' [' + o['unit'] + ']') if o.get('unit') else ''}"


# ---- 입력 요약·설정 ---------------------------------------------------------------------------------------


def _input_section(inp: Mapping[str, Any], d: Mapping[str, Any]) -> str:
    s = d.get("settings") or {}
    kv: list[tuple[str, Any]] = [
        ("Study", f"{(inp.get('study') or {}).get('title') or ''} ({(inp.get('study') or {}).get('folder_name') or ''})"),
        ("파라미터 세트(템플릿)", param_set_text(inp.get("param_set") or d.get("param_set"))),
        ("형상 엔진", engine_text(inp.get("engine"))),
        ("모델", model_text(inp.get("model") or d.get("model"))),
        ("최적화", f"{d.get('label')} · {d.get('progress_text') or STATUS_TEXT.get(str(d.get('status')), d.get('status'))}")]
    for k, v in (inp.get("origins") or []):
        kv.append((k, v))
    out = [kv_table(kv)]
    vars_ = s.get("vars") or {}
    vrows = {v["name"]: v for v in (vars_.get("variables") or []) if isinstance(v, dict) and v.get("name")}
    bounds = s.get("bounds") or {}
    integer = set(s.get("integer") or [])
    params = d.get("parameters") or []
    rows = []
    for p in params:
        n = p["name"]
        b = bounds.get(n)
        tr = (vrows.get(n) or {}).get("train")
        rows.append([n, str(p.get("unit") or ""), Raw(fmt(p.get("nominal"))), Raw(f"{fmt(p.get('min'))} ~ {fmt(p.get('max'))}"),
                     Raw(f"{fmt(b[0])} ~ {fmt(b[1])}" if b else "—"),
                     Raw(f"{fmt(tr['min'])} ~ {fmt(tr['max'])}" if isinstance(tr, dict) and finite(tr.get("min")) else "—"),
                     "정수" if n in integer else "연속"])
    heads = ["변수", "단위", "공칭", "기준 범위", "최적화 범위(탐색)", "학습 범위", "종류"]
    cap = "실행 스냅숏(settings.vars)" if vars_ else "파라미터 세트(settings.vars 스냅숏 없음)"
    out.append(f'<h3>변수와 범위 <span class="muted small">— {esc(cap)}</span></h3>')
    out.append(table(heads, rows, num=[2]) if rows else empty("변수 정보 없음"))
    if vars_.get("excluded"):
        out.append(f'<p class="muted small">제외한 변수: {esc(", ".join(vars_["excluded"]))}</p>')
    return "".join(out)


def _setting_section(d: Mapping[str, Any], defs: Sequence[Mapping[str, Any]]) -> str:
    s = d.get("settings") or {}
    w = d.get("weights") or []
    obj_rows = [[i + 1, _obj_label(o), SENSE_TEXT.get(str(o.get("sense")), o.get("sense")), Raw(fmt(w[i]) if i < len(w) else "—")]
                for i, o in enumerate(defs)]
    out = ['<h3>목적</h3>', table(["#", "목적(성능·지표)", "방향", "가중치"], obj_rows, num=[0, 3]) if obj_rows else empty("목적 없음")]
    cons = d.get("constraints_def") or []
    out.append("<h3>제약</h3>")
    out.append(table(["제약", "조건(임계값)"], [[f"{c.get('label') or metric_name(c['metric'], c.get('series'))}"
                                               f"{(' [' + c['unit'] + ']') if c.get('unit') else ''}", con_text(c)] for c in cons])
               if cons else empty("제약 없음"))
    algo = str(s.get("algorithm") or "ego")
    ex = s.get("explore") or {}
    method = METHODS[ex["method"]][1] if ex.get("method") in METHODS else "LHS"  # doe-methods.md DM-C5: 저장 안 된 method = 기존 LHS
    explore = (f"새 탐색 {method} {ex.get('count')}개(시드 {ex.get('seed')})" if ex.get("kind") == "new"
               else f"완료 배치 재사용 {str(ex.get('batch_id') or '')[:8]}")
    kv: list[tuple[str, Any]] = [
        ("알고리즘", ALGO_TEXT.get(algo, algo)), ("검증 방식", VERIFY_TEXT.get(str(s.get("verification") or "loop"), s.get("verification"))),
        ("탐색", explore), ("반복 / 후보 수", f"{s.get('iterations')} / {s.get('candidates')}"),
        ("개선 수렴 기준(tol_rel)", Raw(fmt(s.get("tol_rel")))), ("시드", Raw(fmt(s.get("seed")))),
        ("동시 실행", Raw(fmt(s.get("multi_execution")))), ("대리모델", str(s.get("surrogate") or "—"))]
    ao = s.get("algo_options") or {}
    if ao:
        kv.append(("하이퍼파라미터", ", ".join(f"{k}={fmt(v, 5)}" for k, v in sorted(ao.items()) if v is not None) or "기본값"))
    out.append("<h3>알고리즘·실행 조건</h3>" + kv_table(kv))
    perfs = s.get("performances") or {}
    if perfs:
        out.append("<h3>성능 정의</h3>" + table(["성능", "단위", "추출 정의"], [[k, str(v.get("unit") or ""), _spec_text(v.get("spec"))]
                                                                       for k, v in sorted(perfs.items())]))
    return "".join(out)


def _spec_text(spec: Any) -> str:
    if not isinstance(spec, Mapping):
        return "—"
    return ", ".join(f"{k}={v}" for k, v in sorted(spec.items()) if v not in (None, ""))


# ---- 결과 -------------------------------------------------------------------------------------------------


def _compare_section(ctx: Ctx, d: Mapping[str, Any], defs: Sequence[Mapping[str, Any]], images: Sequence[Mapping[str, Any]]) -> str:
    best = d.get("best")
    fin = d.get("final") or {}
    multi = len(defs) >= 2
    noun = "추천점(가중)" if multi else "최적안"
    if not best:
        return empty("검증된 최적안이 아직 없습니다")
    base_vals = fin.get("baseline_values") or {}
    out = []
    # 변수 비교
    rows = []
    for p in d.get("parameters") or []:
        n = p["name"]
        b = base_vals.get(n, p.get("nominal"))
        o = (best.get("values") or {}).get(n)
        span = (p.get("max") or 0) - (p.get("min") or 0)
        tol = 1e-9 * max(1.0, abs(span))
        end = ""
        if o is not None and span > 0:
            end = "상한" if o >= p["max"] - tol else "하한" if o <= p["min"] + tol else ""
        rows.append([n, Raw(f"{fmt(p.get('min'))} ~ {fmt(p.get('max'))}"), Raw(fmt(b)), Raw(fmt(o)),
                     Raw(fmt(o - b) if finite(o) and finite(b) else "—"), end])
    out.append(f"<h3>{noun} — 기준안 대비 변수</h3>")
    out.append(table(["변수", "범위", "기준안", noun, "변화", "범위 끝"], rows, num=[2, 3, 4]))
    hit = [r[0] + f"({r[5]})" for r in rows if r[5]]
    if hit:
        out.append(note(f"{', '.join(hit)}이(가) 범위 끝에 닿았습니다 — 범위를 넓히면 추가 개선 여지가 있습니다"))
    # 목적·제약 비교
    base_run = fin.get("baseline") or {}
    best_run = fin.get("best") or {}
    obj_rows = []
    bobjs = best.get("objectives") if isinstance(best.get("objectives"), Mapping) else None
    for i, o in enumerate(defs):
        v = (bobjs or {}).get(o["metric"]) if bobjs else (best.get("objective") if i == 0 else None)
        bv = base_run.get("objective") if i == 0 else None
        if bv is None and i == 0:
            bv = fin.get("baseline_predicted")
        delta = (v - bv) if finite(v) and finite(bv) else None
        rel = (delta / abs(bv) * 100) if delta is not None and bv else None
        better = None if delta is None else (delta <= 0 if o.get("sense") == "min" else delta >= 0)
        obj_rows.append([_obj_label(o), SENSE_TEXT.get(str(o.get("sense")), ""), Raw(fmt(bv)), Raw(fmt(v)), Raw(fmt(delta)), Raw(pct(rel, 3)),
                         verdict_badge(better, "개선", "악화")])
    out.append(f"<h3>목적 — {noun} vs 기준안</h3>")
    out.append(table(["목적", "방향", "기준안", noun, "차이", "상대", "판정"], obj_rows, num=[2, 3, 4, 5]))
    cons = d.get("constraints_def") or []
    if cons:
        crow = []
        bc = base_run.get("constraints") or []
        for i, c in enumerate(cons):
            v = (best.get("constraints") or {}).get(con_key(c))
            ok = _satisfies(c, v)
            crow.append([f"{c.get('label')}", con_text(c), Raw(fmt(bc[i]) if i < len(bc) else "—"), Raw(fmt(v)), verdict_badge(ok, "만족", "위반")])
        out.append("<h3>제약 — 만족 여부</h3>" + table(["제약", "조건", "기준안", noun, "판정"], crow, num=[2, 3]))
    out.append(f'<p class="muted small">{esc(noun)}: {esc(best.get("batch_label"))} DOE #{esc(best.get("doe_no"))} · {esc(best.get("run_key"))}'
               f'{" · 만족" if best.get("feasible") else " · 제약 위반"}</p>')
    if fin.get("legend_note") or fin.get("reason"):
        out.append(f'<p class="muted small">{esc(fin.get("legend_note") or fin.get("reason"))}</p>')
    shots = [ctx.image(i.get("path"), str(i.get("label"))) for i in images]
    if shots:
        out.append("<h3>기준안·최적안 컨투어(정적 이미지)</h3><div class=\"grid2\">" + "".join(shots) + "</div>")
    return "".join(out)


def _satisfies(c: Mapping[str, Any], v: Any) -> bool | None:
    if not finite(v):
        return None
    op = c.get("op")
    if op == "range":
        return finite(c.get("lo")) and finite(c.get("hi")) and c["lo"] <= v <= c["hi"]
    if op == "<=":
        return v <= (c.get("value") if finite(c.get("value")) else float("inf"))
    return v >= (c.get("value") if finite(c.get("value")) else float("-inf"))


def _pareto_section(ctx: Ctx, d: Mapping[str, Any], defs: Sequence[Mapping[str, Any]]) -> str:
    par = d.get("pareto")
    if not par:
        return empty("파레토 결과 없음")
    front = list(par.get("front") or [])
    rec = par.get("recommended_key")
    out = [cards([("검증된 파레토 해", len(front)), ("HV", Raw(fmt(par.get("hv"), 4))), ("추천 해(가중)", rec or "—")])]
    names = [p["name"] for p in d.get("parameters") or []]
    cols = ["키", *names, *[_obj_label(o) for o in defs]]
    rows, extra = ctx.cap_rows(front, "파레토 표")
    out.append(table(cols, [[("★ " if r["key"] == rec else "") + str(r["key"]), *[Raw(fmt((r.get("values") or {}).get(n), 5)) for n in names],
                             *[Raw(fmt(x)) for x in r.get("objectives") or []]] for r in rows],
                     num=list(range(1, len(cols)))) + extra)
    pts: list[dict[str, Any]] = []
    for r in (d.get("runs") or []):
        ob = r.get("objectives") or []
        if r.get("state") == "SUCCEEDED" and len(ob) >= 2 and finite(ob[0]) and finite(ob[1]):
            pts.append({"x": ob[0], "y": ob[1], "cls": "ptg", "r": 3,
                        "label": f"{r.get('batch_label')} #{r.get('doe_no')}"})
    for r in front:
        ob = r.get("objectives") or []
        if len(ob) >= 2:
            pts.append({"x": ob[0], "y": ob[1], "cls": "ptb" if r["key"] == rec else "pt", "r": 5 if r["key"] == rec else 4,
                        "label": f"파레토 {r['key']}"})
    for p_ in par.get("predicted") or []:
        m = p_.get("mean") or []
        if len(m) >= 2:
            pts.append({"x": m[0], "y": m[1], "cls": "pt2", "hollow": True, "r": 3, "label": "예측 전선(미검증)"})
    if len(defs) >= 2 and pts:
        pair_n = min(6, len(defs) * (len(defs) - 1) // 2)
        pairs = [(i, j) for i in range(len(defs)) for j in range(i + 1, len(defs))][:pair_n]
        charts = []
        for i, j in pairs:
            cp = []
            for r in (d.get("runs") or []):
                ob = r.get("objectives") or []
                if r.get("state") == "SUCCEEDED" and len(ob) > max(i, j) and finite(ob[i]) and finite(ob[j]):
                    cp.append({"x": ob[i], "y": ob[j], "cls": "ptg", "r": 3, "label": f"{r.get('batch_label')} #{r.get('doe_no')}"})
            for r in front:
                ob = r.get("objectives") or []
                if len(ob) > max(i, j):
                    cp.append({"x": ob[i], "y": ob[j], "cls": "ptb" if r["key"] == rec else "pt", "r": 5 if r["key"] == rec else 4,
                               "label": f"파레토 {r['key']}"})
            charts.append(scatter_chart(cp, xlabel=_obj_label(defs[i]), ylabel=_obj_label(defs[j]), width=420, height=300,
                                        max_points=ctx.pts(1500), title=f"f{i + 1}–f{j + 1}"))
        out.append("<h3>파레토 산점</h3><p class=\"muted small\">회색 = 검증 run 전체, 파랑 = 검증된 파레토 해, 빨강 = 추천 해, 속 빈 원 = 대리모델 예측 전선(미검증)</p>"
                   '<div class="grid2">' + "".join(charts) + "</div>")
    hv = [h for h in (d.get("hv_history") or []) if finite(h.get("hv"))]
    if hv:
        out.append("<h3>HV 추이</h3>" + line_chart([{"x": [h["iter_no"] for h in hv], "y": [h["hv"] for h in hv], "cls": "s1", "label": "HV"}],
                                                 xlabel="반복", ylabel="HV", markers=[{"x": h["iter_no"], "y": h["hv"], "label": f"반복 {h['iter_no']}"} for h in hv]))
    return "".join(out)


def _convergence_section(ctx: Ctx, d: Mapping[str, Any], defs: Sequence[Mapping[str, Any]]) -> str:
    its = [it for it in (d.get("iterations") or [])]
    rows = []
    for it in its:
        fit = it.get("fit") or {}
        rows.append([it.get("iter_no"), KIND_TEXT.get(str(it.get("kind")), it.get("kind")), (it.get("batch") or {}).get("label") or "—",
                     Raw(fmt(it.get("best_value"))), Raw(pct((it["improvement_rel"] * 100) if finite(it.get("improvement_rel")) else None, 3)),
                     Raw(fmt(fit.get("q2"), 3)), Raw(fmt(fit.get("loo_nrmse"), 3)), Raw(fmt(it.get("hv"))), len(it.get("candidates") or [])])
    out = [table(["반복", "종류", "배치", "최선 값", "개선", "Q²", "LOO NRMSE", "HV", "후보"], rows, num=[0, 3, 4, 5, 6, 7, 8]) if rows else empty("반복 없음")]
    if len(defs) < 2:
        sense = (defs[0].get("sense") if defs else "min") or "min"
        runs = [r for r in (d.get("runs") or []) if r.get("state") == "SUCCEEDED" and finite(r.get("objective"))]
        order = {k: i for i, k in enumerate(("EXPLORE", "REUSE", "VERIFY", "EXTRA"))}
        runs.sort(key=lambda r: (r.get("iter_no", 0), order.get(str(r.get("kind")), 9), r.get("doe_no", 0)))
        best, line = None, []
        for i, r in enumerate(runs, 1):
            if r.get("feasible") is not False:
                best = r["objective"] if best is None else (min if sense == "min" else max)(best, r["objective"])
            line.append(best)
        xs = list(range(1, len(runs) + 1))
        if runs:
            pts = [{"x": i, "y": r["objective"], "cls": "pt" if r.get("feasible") is not False else "ptg", "r": 3,
                    "label": f"{r.get('batch_label')} #{r.get('doe_no')} ({KIND_TEXT.get(str(r.get('kind')), '')})"} for i, r in enumerate(runs, 1)]
            # 수렴: 점(run별 목적 값, 제약 위반은 회색) + 선(제약 만족 최선 값 추이)
            out.append("<h3>수렴 그래프</h3>" + _convergence_svg(ctx, xs, pts, line, _obj_label(defs[0]) if defs else "목적"))
    return "".join(out)


def _convergence_svg(ctx: Ctx, xs: list[int], pts: list[dict[str, Any]], line: list[Any], ylabel: str) -> str:
    # 점과 선을 한 SVG에: line_chart 마커 기능을 점 표시에 재사용
    ser = [{"x": [x for x, y in zip(xs, line) if y is not None], "y": [y for y in line if y is not None], "cls": "s2", "label": "제약 만족 최선 값"}]
    marks = [{"x": p["x"], "y": p["y"], "cls": "mk" if p["cls"] == "pt" else "ptg", "label": p["label"]} for p in pts[: ctx.pts(1500)]]
    return line_chart(ser, xlabel="검증 run 순서", ylabel=ylabel, markers=marks)


def _verify_section(ctx: Ctx, d: Mapping[str, Any]) -> str:
    s = d.get("settings") or {}
    if s.get("verification") == "none" and not any(r.get("kind") == "EXTRA" for r in d.get("runs") or []):
        return empty("검증 없음 — 대리모델 예측만으로 고른 미검증 후보입니다(결과 화면의 추가 검증으로 해석 예측과 비교할 수 있습니다)")
    rows = []
    pts = []
    for it in d.get("iterations") or []:
        for c in it.get("candidates") or []:
            pred, ver = c.get("predicted"), c.get("verified")
            diff = (ver - pred) if finite(pred) and finite(ver) else None
            rows.append([it.get("iter_no"), c.get("doe_no"), STATE_TEXT.get(str(c.get("state")), c.get("state") or "—"),
                         Raw(fmt(pred)), Raw(fmt(ver)), Raw(fmt(diff)),
                         Raw(pct(diff / abs(ver) * 100, 3) if diff is not None and ver else None)])
            if diff is not None:
                pts.append({"x": pred, "y": ver, "cls": "pt", "label": f"반복 {it.get('iter_no')} #{c.get('doe_no')}"})
    extra = [r for r in d.get("runs") or [] if r.get("kind") == "EXTRA"]
    out = []
    if rows:
        out.append("<h3>예측 vs 해석(검증 run)</h3>")
        capped, more = ctx.cap_rows(rows, "검증 표")
        out.append(table(["반복", "DOE #", "상태", "예측(대리모델)", "검증(해석 예측)", "차이", "상대 차"], capped, num=[0, 1, 3, 4, 5, 6]) + more)
        if pts:
            lo = min(min(p["x"], p["y"]) for p in pts)
            hi = max(max(p["x"], p["y"]) for p in pts)
            out.append(scatter_chart([*pts, {"x": lo, "y": lo, "cls": "ptg", "r": 0.1}, {"x": hi, "y": hi, "cls": "ptg", "r": 0.1}],
                                     xlabel="예측(대리모델)", ylabel="검증 값", title="예측 vs 검증", width=420, height=300))
    if extra:
        out.append("<h3>추가 검증(EXTRA)</h3>" + table(["배치", "DOE #", "목적", "상태", "제약 만족"], [
            [r.get("batch_label"), r.get("doe_no"), Raw(fmt(r.get("objective"))), STATE_TEXT.get(str(r.get("state")), r.get("state")),
             verdict_badge(r.get("feasible"), "만족", "위반")] for r in extra], num=[1, 2]))
    return "".join(out) or empty("검증 결과 없음")


def _runs_section(ctx: Ctx, d: Mapping[str, Any], defs: Sequence[Mapping[str, Any]]) -> str:
    runs = list(d.get("runs") or [])
    if not runs:
        return empty("run 없음")
    names = [p["name"] for p in d.get("parameters") or []]
    cons = d.get("constraints_def") or []
    cols = ["반복", "종류", "DOE #", *names, *[_obj_label(o) for o in defs], *[str(c.get("label")) for c in cons], "만족", "상태"]
    rows = []
    for r in runs:
        ob = r.get("objectives") or ([r.get("objective")] if r.get("objective") is not None else [])
        rows.append([r.get("iter_no"), KIND_TEXT.get(str(r.get("kind")), r.get("kind")), r.get("doe_no"),
                     *[Raw(fmt((r.get("values") or {}).get(n), 5)) for n in names],
                     *[Raw(fmt(ob[i]) if i < len(ob) else "—") for i in range(len(defs))],
                     *[Raw(fmt((r.get("constraints") or [None] * len(cons))[i] if i < len(r.get("constraints") or []) else None)) for i in range(len(cons))],
                     verdict_badge(r.get("feasible"), "만족", "위반"), STATE_TEXT.get(str(r.get("state")), r.get("state"))])
    capped, more = ctx.cap_rows(rows, "run 표")
    return details(f"검증 run 표({len(runs)}행)", table(cols, capped, num=list(range(2, len(cols) - 2))) + more)


def _kpi_cards(d: Mapping[str, Any], defs: Sequence[Mapping[str, Any]]) -> str:
    runs = d.get("runs") or []
    ok = sum(1 for r in runs if r.get("state") == "SUCCEEDED")
    best = d.get("best") or {}
    items: list[tuple[str, Any]] = [("상태", STATUS_TEXT.get(str(d.get("status")), d.get("status"))), ("검증 run", f"{ok}/{len(runs)}")]
    if len(defs) == 1:
        items.insert(1, (f"최적 {_obj_label(defs[0])}", Raw(fmt(best.get("objective")))))
    elif defs:
        items.insert(1, ("검증된 파레토 해", len(((d.get("pareto") or {}).get("front")) or [])))
    last_fit = next((it["fit"] for it in reversed(d.get("iterations") or []) if it.get("fit")), None)
    if last_fit:
        items.append(("대리모델 Q²", Raw(fmt(last_fit.get("q2"), 3))))
    return cards(items)


# ---- 진입점 ----------------------------------------------------------------------------------------------


def surrogate_doc(inp: Mapping[str, Any], ctx: Ctx) -> Doc:
    d = inp["detail"]
    defs = _opt_defs(d)
    multi = len(defs) >= 2
    study = inp.get("study") or {}
    secs: list[tuple[str, str, str]] = [
        ("summary", "요약", _kpi_cards(d, defs)),
        ("input", "입력 요약", _input_section(inp, d)),
        ("setting", "설정(목적·제약·알고리즘)", _setting_section(d, defs)),
        ("result", "최적안 · 기준안 비교", _compare_section(ctx, d, defs, inp.get("images") or [])),
    ]
    if multi:
        secs.append(("pareto", "파레토 결과", _pareto_section(ctx, d, defs)))
    secs.append(("convergence", "반복 이력·수렴", _convergence_section(ctx, d, defs)))
    secs.append(("verify", "검증", _verify_section(ctx, d)))
    secs.append(("runs", "검증 run 표", _runs_section(ctx, d, defs)))
    warns = [f"{w.get('code', '')} {w.get('message', '')}".strip() for w in (d.get("warnings") or [])]
    if d.get("status") not in ("DONE",):
        warns.append(f"상태 {STATUS_TEXT.get(str(d.get('status')), d.get('status'))}")
    best = d.get("best") or {}
    return Doc(title="⑥ 최적화 결과 요약",
               meta=[*study_meta(study, inp.get("generated_by"), f"내장 최적화 {d.get('label')}", d["id"]),
                     ("엔진", engine_text(inp.get("engine"))), ("생성 시각", ctx.generated_at), ("플랫폼 버전", ctx.platform_version)],
               sections=secs, warnings=warns,
               sources=[f"surrogate_opt:{d['id']}", *[f"batch:{(it.get('batch') or {}).get('id')}" for it in (d.get("iterations") or []) if it.get("batch")]],
               data={"target": "surrogate-opt", "id": d["id"], "label": d.get("label"), "status": d.get("status"), "mode": "multi" if multi else "single",
                     "algorithm": (d.get("settings") or {}).get("algorithm"), "best": {"values": best.get("values"), "objective": best.get("objective"),
                                                                                       "objectives": best.get("objectives")},
                     "pareto_size": len(((d.get("pareto") or {}).get("front")) or []), "runs": len(d.get("runs") or [])})


# ---- 레거시(HyperStudy) -----------------------------------------------------------------------------------


def legacy_doc(inp: Mapping[str, Any], ctx: Ctx) -> Doc:
    o = inp["opt"]
    tab = inp.get("table")  # {"columns": [...], "rows": [[...]]} 또는 None
    study = inp.get("study") or {}
    responses = o.get("responses") or []
    goal_text = {"MINIMIZE": "최소화", "MAXIMIZE": "최대화", "NONE": "관찰", None: "—"}
    secs: list[tuple[str, str, str]] = [
        ("summary", "요약", cards([("상태", STATUS_TEXT.get(str(o.get("status")), o.get("status"))), ("방식", f"{o.get('approach')} · {o.get('opt_method')}"),
                                  ("시작한 run", Raw(fmt(o.get("runs_started")))), ("최대 설계 수", Raw(fmt(o.get("max_designs"))))])),
        ("input", "입력 요약", kv_table([("Study", f"{study.get('title') or ''} ({study.get('folder_name') or ''})"),
                                    ("파라미터 세트(템플릿)", param_set_text(inp.get("param_set"))), ("형상 엔진", engine_text(inp.get("engine"))),
                                    ("모델", model_text(inp.get("model") or {"name": o.get("model_name")})),
                                    ("폴더", o.get("folder_display_path") or "—"), *(inp.get("origins") or [])])),
        ("setting", "설정(목적·제약)", table(["응답", "목적", "단위", "제약/설정"], [
            [str(r.get("name")), goal_text.get(r.get("goal"), r.get("goal")), str(r.get("unit") or ""),
             ", ".join(f"{k}={v}" for k, v in sorted(r.items()) if k not in ("name", "goal", "unit", "source", "subcase", "datatype", "component", "layer", "stat")
                       and v not in (None, ""))] for r in responses]) if responses else empty("응답 설정 없음")),
    ]
    secs.append(("result", "결과 표·최적점", _legacy_table(ctx, tab, responses)))
    warns = [] if o.get("status") == "DONE" else [f"상태 {STATUS_TEXT.get(str(o.get('status')), o.get('status'))}"]
    if o.get("summary_status") != "PARSED":
        warns.append(f"결과 요약 파일 상태 {o.get('summary_status')} — 결과 표를 만들 수 없습니다")
    return Doc(title="⑥ 최적화 결과 요약", badge_html=badge("HyperStudy(레거시)", "warnb"),
               meta=[*study_meta(study, inp.get("generated_by"), "HyperStudy 최적화", o["id"]), ("엔진", engine_text(inp.get("engine"))),
                     ("생성 시각", ctx.generated_at), ("플랫폼 버전", ctx.platform_version)],
               sections=secs, warnings=warns, sources=[f"optimization:{o['id']}", f"job:{o.get('job_id')}"],
               data={"target": "optimization", "id": o["id"], "status": o.get("status"), "legacy": True})


def _legacy_table(ctx: Ctx, tab: Mapping[str, Any] | None, responses: Sequence[Mapping[str, Any]]) -> str:
    if not tab or not tab.get("columns"):
        return empty("결과 표 없음")
    cols = [str(c) for c in tab["columns"]]
    rows = [list(r) for r in tab.get("rows") or []]
    out = []

    def num(v: Any) -> float | None:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if finite(f) else None

    goals = {r.get("name"): r.get("goal") for r in responses}
    obj_cols = [i for i, c in enumerate(cols) if i > 0 and c in goals and goals[c] in ("MINIMIZE", "MAXIMIZE")]
    for ci in obj_cols[:1]:
        vals = [(i, num(r[ci])) for i, r in enumerate(rows) if ci < len(r)]
        vals = [(i, v) for i, v in vals if v is not None]
        if vals:
            pick = (min if goals[cols[ci]] == "MINIMIZE" else max)(vals, key=lambda x: x[1])
            out.append(cards([("최적점(설계 번호)", pick[0] + 1), (cols[ci], Raw(fmt(pick[1])))]))
            out.append("<h3>최적점</h3>" + table(cols, [[Raw(fmt(num(x))) if num(x) is not None and j > 0 else str(x) for j, x in enumerate(rows[pick[0]])]],
                                                  num=list(range(1, len(cols)))))
            best, line = None, []
            for i, v in vals:
                best = v if best is None else (min if goals[cols[ci]] == "MINIMIZE" else max)(best, v)
                line.append(best)
            out.append("<h3>반복 이력</h3>" + line_chart([{"x": [i + 1 for i, _ in vals], "y": line, "cls": "s2", "label": "최적값 추이"}],
                                                     xlabel="설계", ylabel=cols[ci], markers=[{"x": i + 1, "y": v, "cls": "mk", "label": f"설계 {i + 1}: {fmt(v)}"}
                                                                                              for i, v in vals[: ctx.pts(1500)]]))
    capped, more = ctx.cap_rows(rows, "결과 표")
    out.append("<h3>결과 표</h3>" + table(cols, [[Raw(fmt(num(x))) if num(x) is not None and j > 0 else ("" if x is None else str(x)) for j, x in enumerate(r)]
                                                for r in capped], num=list(range(1, len(cols)))) + more)
    return "".join(out)
