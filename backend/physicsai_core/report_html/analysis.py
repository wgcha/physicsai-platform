"""⑤ 결과분석 보고서 본문(upload-report.md §9.3.1): 결과 표 1종(+선택 비교) → 출처 요약·결과 표·통계·변수–응답·설계공간 지도·영향도·커브.

입력 `table`/`other` = 서버가 기존 서비스(`GET /predict-batches/{id}`·`design-map`·`/train-does/{id}/result-table`)에서 만든 결과 표 dict
(프런트 `analysis/resultTable.ts`와 같은 모양: source·origin·parameters·responses·rows·counts·influence·notes). 화면 기본값 규칙은 프런트와 같다.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .common import engine_text, model_text, param_set_text, study_meta
from .influence import WEAK_R2, WEAK_R2_TEXT, compute_influence, influence_rows
from .page import (Ctx, Doc, Raw, badge, bars_h, cards, details, empty, esc, finite, fmt, kv_table, line_chart, note, scatter_chart,
                   table)

OK_STATES = ("SUCCEEDED", "SOLVED", "COLLECTED")
NO_RESP_HINT = "④ 템플릿에 성능을 정의하거나 커브 대표값을 고르세요"
OFF_FALLBACK_TEXT = "영향도를 계산할 수 없습니다"
MAX_VARS = 4
MAX_CURVE_LINES = 20
MAX_INFLUENCE_RESP = 6
SOURCE_TEXT = {"predict": "일괄 예측 결과(④ 예측)", "solver": "해석 DOE 결과(① 해석)"}
NO_COMMON_RESP_TEXT = "두 표에 같은 이름의 응답이 없어 값을 겹쳐 볼 수 없습니다"


def is_ok(state: Any) -> bool:
    return state in OK_STATES


def _fin(v: Any) -> float | None:
    return float(v) if finite(v) else None


def min_influence_runs(p: int) -> int:
    return max(5, p + 2)


# ---- 화면 규칙 ---------------------------------------------------------------------------------------------


def name_set_diff(a: Mapping[str, Any], b: Mapping[str, Any]) -> tuple[bool, list[str], list[str]]:
    sa = [p["name"] for p in a["parameters"]]
    sb = [p["name"] for p in b["parameters"]]
    only_a = [n for n in sa if n not in set(sb)]
    only_b = [n for n in sb if n not in set(sa)]
    return (not only_a and not only_b), only_a, only_b


def common_responses(a: Mapping[str, Any], b: Mapping[str, Any]) -> list[str]:
    sb = {r["name"] for r in b["responses"]}
    return [r["name"] for r in a["responses"] if r["name"] in sb]


def compare_state(rt: Mapping[str, Any], other: Mapping[str, Any] | None) -> tuple[Mapping[str, Any] | None, str | None]:
    """(실제로 겹쳐 그릴 비교 표 | None, 생략 문구 | None) — s14 A6."""
    if other is None:
        return None, None
    same, oa, ob = name_set_diff(rt, other)
    if not same:
        return None, f"파라미터 이름이 달라 겹쳐 볼 수 없습니다 — 다른 쪽에만 있음: {', '.join([*oa, *ob])}"
    if not common_responses(rt, other):
        return None, NO_COMMON_RESP_TEXT
    return other, None


def sort_rows(rows: Sequence[Mapping[str, Any]], resp: str | None) -> list[Mapping[str, Any]]:
    """화면 기본 정렬: 첫 응답 오름차순, 값 없는 행은 뒤, 같으면 번호 순."""
    if not resp:
        return sorted(rows, key=lambda r: r["no"])
    return sorted(rows, key=lambda r: (not finite(r["responses"].get(resp)), r["responses"].get(resp) if finite(r["responses"].get(resp)) else 0, r["no"]))


def resolve_selection(rt: Mapping[str, Any], other: Mapping[str, Any] | None, vars_: Sequence[str] | None, resp: str | None
                      ) -> tuple[list[str], str | None, list[str]]:
    """쿼리 `vars`·`resp` → (변수, 응답, 경고). 빈 값은 화면 기본(첫 변수 1개·첫 선택 가능 응답), 알 수 없는 이름은 무시하고 경고."""
    warns: list[str] = []
    names = [p["name"] for p in rt["parameters"]]
    pick = [v for v in dict.fromkeys(vars_ or []) if v in names]
    bad = [v for v in dict.fromkeys(vars_ or []) if v not in names]
    if bad:
        warns.append(f"알 수 없는 변수를 무시했습니다: {', '.join(bad)}")
    if len(pick) > MAX_VARS:
        warns.append(f"변수는 최대 {MAX_VARS}개까지 표시합니다(앞 {MAX_VARS}개만 사용)")
        pick = pick[:MAX_VARS]
    if not pick:
        pick = names[:1]
    selectable = common_responses(rt, other) if other else [r["name"] for r in rt["responses"]]
    if resp and resp not in selectable:
        warns.append(f"알 수 없는 응답 '{resp}'을(를) 무시하고 첫 응답을 씁니다")
        resp = None
    return pick, (resp or (selectable[0] if selectable else None)), warns


def influence_for(rt: Mapping[str, Any], resp: str | None) -> dict[str, Any]:
    """색 값(응답) 1개의 영향도 — 프런트 `influenceFor`와 같은 규칙(사용 조건·문구·부호 불일치·R² 약함)."""
    def off(why: str) -> dict[str, Any]:
        return {"disabled": why, "note": None, "result": None, "rows": [], "mismatch": [], "weak": False}

    inf = rt["influence"]
    if rt["source"] == "solver" and not inf.get("ok"):
        return off(inf.get("reason") or OFF_FALLBACK_TEXT)
    any_resp = any(finite(r["responses"].get(x["name"])) for x in rt["responses"] for r in rt["rows"])
    hint = f" — {NO_RESP_HINT}" if rt["source"] == "predict" and not any_resp else ""
    if not resp:
        return off(f"응답이 없어 영향도를 계산할 수 없습니다{hint}")
    names = [p["name"] for p in rt["parameters"]]
    use = [r for r in rt["rows"] if is_ok(r["state"]) and finite(r["responses"].get(resp)) and all(finite(r["params"].get(n)) for n in names)]
    need = min_influence_runs(len(names))
    if len(use) < need:
        return off(f"영향도에는 유효 run이 {need}개 이상 필요합니다(현재 {len(use)}개){hint}")
    try:
        res = compute_influence(names, [[r["params"][n] for r in use] for n in names], [r["responses"][resp] for r in use])
    except ImportError:  # numpy 없음(설치 오류) — 보고서는 계속
        return off("영향도를 계산할 수 없습니다(numpy 없음)")
    if res.unavailable:
        return off(res.unavailable)
    rows = influence_rows(res)
    return {"disabled": None, "note": inf.get("note") if inf.get("cls") == "reference" else None, "result": res, "rows": rows,
            "mismatch": [r["name"] for r in rows if r["mismatch"]], "weak": res.r2 is not None and res.r2 < WEAK_R2}


def response_stats(rt: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for r in rt["responses"]:
        vs = [x["responses"][r["name"]] for x in rt["rows"] if is_ok(x["state"]) and finite(x["responses"].get(r["name"]))]
        n = len(vs)
        mean = sum(vs) / n if n else None
        sd = math.sqrt(sum((v - mean) ** 2 for v in vs) / (n - 1)) if n > 1 and mean is not None else None
        out.append({"name": r["name"], "label": r.get("label") or r["name"], "unit": r.get("unit"), "n": n, "min": min(vs) if vs else None,
                    "max": max(vs) if vs else None, "mean": mean, "std": sd})
    return out


# ---- 구역 --------------------------------------------------------------------------------------------------


def _rlabel(rt: Mapping[str, Any], name: str | None) -> str:
    if name is None:
        return "—"
    r = next((x for x in rt["responses"] if x["name"] == name), None)
    base = (r or {}).get("label") or name
    return f"{base}{(' [' + r['unit'] + ']') if r and r.get('unit') else ''}"


def _summary(rt: Mapping[str, Any], other: Mapping[str, Any] | None, msg: str | None) -> str:
    c = rt["counts"]
    sm = rt.get("sampling") or {}
    kv: list[tuple[str, Any]] = [("출처 종류", SOURCE_TEXT.get(rt["source"], rt["source"])), ("라벨", rt["origin"]["label"]),
                                  ("표본 방식", f"{sm.get('label') or '알 수 없음'}{' (LHS)' if sm.get('lhs') else ''}"),
                                  ("run 수", f"전체 {c['total']} · 유효 {c['usable']} · 응답 없음 {c['no_response']}")]
    meta = rt.get("meta") or {}
    chips = [f"{k} {meta.get(key) or '—'}" for k, key in (("엔진", "engine_version"), ("기준안", "baseline_id"), ("scene", "scene"))]
    kv.append(("메타", " · ".join(chips)))
    if other:
        kv.append(("비교 출처", f"{SOURCE_TEXT.get(other['source'])} · {other['origin']['label']} (run {other['counts']['total']}개)"))
        om = other.get("meta") or {}
        if any(meta.get(k) is not None and om.get(k) is not None and meta[k] != om[k] for k in ("engine_version", "baseline_id", "scene")):
            kv.append(("메타 비교", "메타 다름"))
    elif msg:
        kv.append(("비교 출처", msg))
    out = [kv_table(kv)]
    if rt.get("influence", {}).get("note") and rt["influence"].get("cls") == "reference":
        out.append(note(rt["influence"]["note"]))
    for n in rt.get("notes") or []:
        out.append(note(n))
    return "".join(out)


def _input(inp: Mapping[str, Any], rt: Mapping[str, Any]) -> str:
    kv: list[tuple[str, Any]] = [("Study", f"{(inp.get('study') or {}).get('title') or ''} ({(inp.get('study') or {}).get('folder_name') or ''})")]
    if inp.get("param_set"):
        kv.append(("파라미터 세트(템플릿)", param_set_text(inp["param_set"])))
    if inp.get("engine"):
        kv.append(("형상 엔진", engine_text(inp["engine"])))
    if inp.get("model"):
        kv.append(("모델", model_text(inp["model"])))
    kv.extend(inp.get("origins") or [])
    rows = [[p["name"], str(p.get("unit") or ""), "정수" if p.get("integer") else "연속",
             Raw(f"{fmt(p.get('min'))} ~ {fmt(p.get('max'))}" if finite(p.get("min")) and finite(p.get("max")) else "—")]
            for p in rt["parameters"]]
    return kv_table(kv) + "<h3>변수와 범위</h3>" + (table(["변수", "단위", "종류", "범위"], rows) if rows else empty("변수 없음"))


def _result_table(ctx: Ctx, rt: Mapping[str, Any], first_resp: str | None) -> str:
    rows = sort_rows(rt["rows"], first_resp)
    capped, more = ctx.cap_rows(rows, "결과 표")
    pn = [p["name"] for p in rt["parameters"]]
    rn = rt["responses"]
    heads = ["#", "run", "상태", *pn, *[(x.get("label") or x["name"]) + (f" [{x['unit']}]" if x.get("unit") else "") for x in rn]]
    body = []
    for r in capped:
        body.append([r["no"], r["run_id"], r["state"], *[Raw(fmt(r["params"].get(n), 5)) for n in pn],
                     *[Raw(fmt(r["responses"].get(x["name"]), 5)) for x in rn]])
    out = [table(heads, body, num=[0, *range(3, len(heads))]) + more]
    stats = response_stats(rt)
    if stats:
        out.append("<h3>응답별 통계(유효 run)</h3>")
        out.append(table(["응답", "n", "최소", "최대", "평균", "표준편차"], [[s["label"], s["n"], Raw(fmt(s["min"])), Raw(fmt(s["max"])), Raw(fmt(s["mean"])),
                                                                     Raw(fmt(s["std"]))] for s in stats], num=[1, 2, 3, 4, 5]))
    return "".join(out)


def _points(rt: Mapping[str, Any], var: str, resp: str, **style: Any) -> list[dict[str, Any]]:
    out = []
    for r in rt["rows"]:
        x, y = r["params"].get(var), r["responses"].get(resp)
        if is_ok(r["state"]) and finite(x) and finite(y):
            out.append({"x": x, "y": y, "label": f"{rt['origin']['label']} #{r['no']} · {var} {fmt(x, 4)} · {resp} {fmt(y, 4)}", **style})
    return out


def _var_resp(ctx: Ctx, rt: Mapping[str, Any], other: Mapping[str, Any] | None, vars_: Sequence[str], resp: str | None,
              selected: int | None) -> str:
    if not resp:
        return empty("응답이 없어 그릴 수 없습니다")
    charts = []
    for v in vars_:
        pts = _points(rt, v, resp, cls="pt", hollow=rt["source"] == "solver")
        for p in pts:
            if selected is not None and f"#{selected} " in p["label"]:
                p.update(cls="pt2", r=6)
        if other:
            pts += _points(other, v, resp, cls="pt2", hollow=other["source"] == "solver")
        charts.append(scatter_chart(pts, xlabel=v, ylabel=_rlabel(rt, resp), width=420, height=300, max_points=ctx.pts(1500)))
    if not charts:
        return empty("변수가 없습니다")
    legend = (f"<p class=\"muted small\">파랑 = {esc(rt['origin']['label'])}"
              + (f" · 주황 = {esc(other['origin']['label'])}" if other else "") + " · 속 빈 원 = 해석 값, 채운 점 = 예측 값"
              + (" · 큰 주황 점 = 선택 run" if selected is not None else "") + "</p>")
    return legend + '<div class="grid2">' + "".join(charts) + "</div>"


def _design_map(ctx: Ctx, rt: Mapping[str, Any], other: Mapping[str, Any] | None, resp: str | None) -> str:
    names = [p["name"] for p in rt["parameters"]]
    if len(names) < 2:
        return empty("설계공간 지도는 변수가 2개 이상일 때 그립니다")
    if not resp:
        return empty("응답이 없어 색을 칠할 수 없습니다")
    xv, yv = names[0], names[1]
    base = []
    for r in rt["rows"]:
        x, y, z = r["params"].get(xv), r["params"].get(yv), r["responses"].get(resp)
        if is_ok(r["state"]) and finite(x) and finite(y) and finite(z):
            base.append((x, y, z, r["no"]))
    oth = []
    if other:
        for r in other["rows"]:
            x, y, z = r["params"].get(xv), r["params"].get(yv), r["responses"].get(resp)
            if is_ok(r["state"]) and finite(x) and finite(y) and finite(z):
                oth.append((x, y, z, r["no"]))
    zs = [p[2] for p in base + oth]
    if not zs:
        return empty("응답 값이 있는 run이 없습니다")
    lo, hi = min(zs), max(zs)
    from .page import viridis

    col = (lambda v: viridis((v - lo) / (hi - lo))) if hi > lo else (lambda v: viridis(0.5))
    pts = [{"x": x, "y": y, "color": col(z), "cls": "pt", "r": 4.5,
            "label": f"#{no} · {xv} {fmt(x, 4)} · {yv} {fmt(y, 4)} · {resp} {fmt(z, 4)}"} for x, y, z, no in base]
    pts += [{"x": x, "y": y, "color": col(z), "cls": "pt2", "r": 4.5,
             "label": f"비교 #{no} · {resp} {fmt(z, 4)}"} for x, y, z, no in oth]
    return (f'<p class="muted small">축 = {esc(xv)}·{esc(yv)}(화면 기본 축), 색 = {esc(_rlabel(rt, resp))}</p>'
            + scatter_chart(pts, xlabel=xv, ylabel=yv, width=560, height=340, max_points=ctx.pts(2000), colorbar=(lo, hi, resp)))


def _influence(rt: Mapping[str, Any], resp: str | None, selectable: Sequence[str]) -> tuple[str, dict[str, Any]]:
    order = ([resp] if resp else []) + [n for n in selectable if n != resp and not n.startswith("curve:")]
    out, data = [], {}
    for name in order[:MAX_INFLUENCE_RESP]:
        v = influence_for(rt, name)
        out.append(f"<h3>{esc(_rlabel(rt, name))}{' (선택 응답)' if name == resp else ''}</h3>")
        if v["disabled"]:
            out.append(note(v["disabled"]))
            data[name] = None
            continue
        if v["note"]:
            out.append(note(v["note"]))
        res = v["result"]
        rows = v["rows"]
        out.append(table(["변수", "PRCC", "표준화 회귀계수", "부호"], [[r["name"], Raw(fmt(r["prcc"])), Raw(fmt(r["src"])),
                                                              "불일치" if r["mismatch"] else ""] for r in rows], num=[1, 2]))
        out.append(bars_h([(r["name"], [(r["prcc"], "bar"), (r["src"], "bar2")]) for r in rows], title="파랑 = PRCC, 주황 = 표준화 회귀계수"))
        out.append(f'<p class="muted small">n {res.n} · R² {fmt(res.r2, 3)}</p>')
        if v["weak"]:
            out.append(note(WEAK_R2_TEXT))
        if v["mismatch"]:
            out.append(note(f"부호 불일치: {', '.join(v['mismatch'])}"))
        data[name] = {"n": res.n, "r2": res.r2, "prcc": dict(zip(res.names, res.prcc)), "src": dict(zip(res.names, res.src))}
    return ("".join(out) or empty("응답이 없어 영향도를 계산할 수 없습니다")), data


def _curves(ctx: Ctx, cv: Mapping[str, Any] | None, selected: int | None) -> str:
    if not cv or not cv.get("series"):
        return empty("완료된 run의 커브가 없습니다")
    series = list(cv["series"])
    pick = [s for s in series if s["doe_no"] != selected][: MAX_CURVE_LINES - 1]
    sel = [s for s in series if s["doe_no"] == selected][:1]
    lines = [{"x": s["x"], "y": s["y"], "cls": "ln", "label": s["run_key"]} for s in pick] + [
        {"x": s["x"], "y": s["y"], "cls": "ln-on", "label": f"{s['run_key']}(선택)"} for s in sel]
    names = cv.get("names") or []
    more = f" · 계열 {len(names)}개 중 '{esc(cv.get('name'))}'" if len(names) > 1 else f" · 계열 '{esc(cv.get('name'))}'"
    return (line_chart(lines, xlabel="x", ylabel=str(cv.get("name") or "커브"), max_points=ctx.pts(300), width=640, height=300)
            + f'<p class="muted small">run {len(pick) + len(sel)}개(최대 {MAX_CURVE_LINES}개){more} · 진한 선 = 선택 run</p>')


# ---- 진입점 -----------------------------------------------------------------------------------------------


def analysis_doc(inp: Mapping[str, Any], ctx: Ctx) -> Doc:
    rt = inp["table"]
    other, msg = compare_state(rt, inp.get("other"))
    vars_, resp, qwarn = resolve_selection(rt, other, inp.get("vars"), inp.get("resp"))
    selectable = common_responses(rt, other) if other else [r["name"] for r in rt["responses"]]
    sorted_rows = sort_rows(rt["rows"], selectable[0] if selectable else None)
    selected = next((r["no"] for r in sorted_rows if is_ok(r["state"])), sorted_rows[0]["no"] if sorted_rows else None)
    infl_html, infl_data = _influence(rt, resp, selectable)
    study = inp.get("study") or {}
    secs: list[tuple[str, str, str]] = [
        ("summary", "출처 요약", _summary(rt, inp.get("other"), msg)),
        ("input", "입력 요약", _input(inp, rt)),
        ("table", "결과 표·통계", _result_table(ctx, rt, selectable[0] if selectable else None)),
        ("varresp", f"변수–응답 (응답 {_rlabel(rt, resp)})", _var_resp(ctx, rt, other, vars_, resp, selected)),
        ("map", "설계공간 지도", _design_map(ctx, rt, other, resp)),
        ("influence", "영향도(PRCC·표준화 회귀계수)", infl_html),
    ]
    if rt["source"] == "predict":
        secs.append(("curves", "커브", _curves(ctx, inp.get("curves"), selected)))
    warns = [*qwarn, *(inp.get("warnings") or [])]
    if msg:
        warns.append(msg)
    label = f"{'일괄 예측' if rt['source'] == 'predict' else '해석 DOE'} {rt['origin']['label']}"
    return Doc(title="⑤ 결과분석 요약",
               meta=[*study_meta(study, inp.get("generated_by"), label, rt["origin"]["id"]),
                     ("선택", f"변수 {', '.join(vars_) or '—'} · 응답 {resp or '—'}"), ("생성 시각", ctx.generated_at), ("플랫폼 버전", ctx.platform_version)],
               sections=secs, warnings=warns,
               sources=[f"{'predict_batch' if rt['source'] == 'predict' else 'train_doe'}:{rt['origin']['id']}",
                        *([f"{'predict_batch' if other['source'] == 'predict' else 'train_doe'}:{other['origin']['id']}"] if other else [])],
               data={"target": "analysis", "source": rt["source"], "id": rt["origin"]["id"], "vars": vars_, "resp": resp,
                     "counts": rt["counts"], "compare": other["origin"]["id"] if other else None, "influence": infl_data,
                     "stats": [{k: s[k] for k in ("name", "n", "min", "max", "mean", "std")} for s in response_stats(rt)]})
