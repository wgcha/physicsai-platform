"""⑤ 등가성 판정 보고서 본문(upload-report.md §9.3.2, equiv-check.md §4·§7): 레시피 스냅숏·대상·종합 판정 배지·지표 표·불합격 쌍·대표 곡선.

입력 `detail` = `GET /equiv-checks/{id}` 응답(이력 행 + 스냅숏 + metrics.csv 표 — 삭제된 레시피도 스냅숏으로 표시)과 서비스가 읽은 대표 곡선.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .common import engine_text, study_meta
from .page import Ctx, Doc, Raw, badge, cards, details, empty, esc, finite, fmt, kv_table, line_chart, note, pct, table

VERDICT_KIND = {"PASS": "pass", "FAIL": "fail", "INCOMPLETE": "warnb"}
VERDICT_TEXT = {"PASS": "통과", "FAIL": "미달", "INCOMPLETE": "판정 불가"}
STATUS_KIND = {"PASS": "pass", "FAIL": "fail", "NA": "na"}
STATUS_TEXT = {"PASS": "통과", "FAIL": "미달", "NA": "판정 불가"}
KIND_TEXT = {"scalar": "스칼라", "curve_corr": "곡선 상관", "curve_nrmse": "곡선 NRMSE", "mesh_volume": "메시 부피"}
SIDE_TEXT = {"train_doe": "해석 DOE(①)", "predict_batch": "일괄 예측(④)", "fem_verify": "FEM 검증", "folder": "폴더"}
MAX_FAIL_ROWS = 30
MAX_CURVES_PER_METRIC = 3


def _badge(status: str | None, kinds: Mapping[str, str] = STATUS_KIND, texts: Mapping[str, str] = STATUS_TEXT) -> Raw:
    s = status or "NA"
    return Raw(badge(texts.get(s, s), kinds.get(s, "na")))


def _side(s: Mapping[str, Any] | None) -> str:
    x = s or {}
    return f"{SIDE_TEXT.get(str(x.get('kind')), x.get('kind') or '—')} · {x.get('label') or x.get('ref') or '—'}"


def _recipe_text(d: Mapping[str, Any]) -> str:
    r = d.get("recipe") or {}
    snap = d.get("recipe_snapshot") or {}
    name = r.get("name") or (snap.get("recipe") or {}).get("name") or ("시스템 기본" if r.get("source") == "system" else "레시피")
    bits = [f"{name}{(' v' + str(r['version'])) if r.get('version') else ''}"]
    if r.get("modified"):
        bits.append("수정됨(이번만 사용)")
    if r.get("deleted"):
        bits.append("삭제된 레시피 — 이력 스냅숏")
    elif r.get("current_version") and r.get("version") and r["current_version"] != r["version"]:
        bits.append(f"현재 v{r['current_version']} · 이력 v{r['version']}")
    return " · ".join(bits)


def pick_curve_pairs(rows: Sequence[Mapping[str, Any]], metrics: Sequence[Mapping[str, Any]]) -> list[tuple[int, str]]:
    """곡선 지표마다 대표 쌍 ≤3: 미달 쌍(상관 낮은 순) 먼저, 모자라면 앞 번호 쌍."""
    out: list[tuple[int, str]] = []
    for m in metrics:
        if not str(m.get("kind", "")).startswith("curve"):
            continue
        mine = [r for r in rows if r.get("metric_id") == m["id"] and r.get("pair_no") is not None]
        fails = sorted((r for r in mine if r.get("status") == "FAIL"),
                       key=lambda r: (r["corr"] if finite(r.get("corr")) else 9, -(abs(r["rel_pct"]) if finite(r.get("rel_pct")) else 0), int(r["pair_no"])))
        rest = sorted((r for r in mine if r.get("status") != "FAIL" and r.get("status") != "NA"), key=lambda r: int(r["pair_no"]))
        for r in [*fails, *rest][:MAX_CURVES_PER_METRIC]:
            out.append((int(r["pair_no"]), m["id"]))
    return out


def _metric_table(d: Mapping[str, Any]) -> str:
    rows = []
    for m in d.get("metrics") or []:
        n = m.get("n_pairs") or 0
        rows.append([m.get("label"), "필수" if m.get("required", True) else "참고", KIND_TEXT.get(str(m.get("kind")), m.get("kind")),
                     Raw(fmt(m.get("a_mean"))), Raw(fmt(m.get("b_mean"))), Raw(pct(m.get("max_abs_rel_pct"))), Raw(fmt(m.get("max_abs_diff"))),
                     Raw(fmt(m.get("min_corr"), 4)), m.get("tol_text") or "", f"{m.get('n_pass', 0)}/{n}", _badge(m.get("status"))])
    heads = ["지표", "구분", "종류", "A 평균", "B 평균", "최대 상대차", "최대 절대차", "상관 최소", "허용", "통과 쌍", "상태"]
    return table(heads, rows, num=[3, 4, 5, 6, 7, 9]) if rows else empty("지표 없음")


def _fail_rows(ctx: Ctx, d: Mapping[str, Any]) -> str:
    labels = {m["id"]: m.get("label") for m in d.get("metrics") or []}
    fails = [r for r in d.get("rows") or [] if r.get("status") == "FAIL"]
    if not fails:
        return empty("미달 쌍 없음")
    fails.sort(key=lambda r: (-(abs(r["rel_pct"]) if finite(r.get("rel_pct")) else 0), r["corr"] if finite(r.get("corr")) else 9, int(r.get("pair_no") or 0)))
    capped, more = ctx.cap_rows(fails, "미달 쌍", MAX_FAIL_ROWS)
    return table(["쌍", "A run", "B run", "지표", "A", "B", "차이", "상대 %", "상관"], [
        [r.get("pair_no"), r.get("a_run"), r.get("b_run"), labels.get(r.get("metric_id")) or r.get("metric_id"), Raw(fmt(r.get("a"))), Raw(fmt(r.get("b"))),
         Raw(fmt(r.get("diff"))), Raw(pct(r.get("rel_pct"))), Raw(fmt(r.get("corr"), 4))] for r in capped], num=[0, 4, 5, 6, 7, 8]) + more


def _curves(ctx: Ctx, d: Mapping[str, Any], curves: Sequence[Mapping[str, Any]]) -> str:
    if not curves:
        return empty("곡선 지표가 없거나 곡선 파일이 없습니다")
    labels = {m["id"]: m.get("label") for m in d.get("metrics") or []}
    charts = []
    for c in curves:
        title = f"{labels.get(c.get('metric_id')) or c.get('metric_id')} · 쌍 {c.get('pair_no')} ({c.get('a_run')} ↔ {c.get('b_run')})"
        charts.append("<div>" + line_chart([{"x": c["t"], "y": c["a"], "cls": "s1", "label": f"A {c.get('a_run')}"},
                                  {"x": c["t"], "y": c["b"], "cls": "s3", "label": f"B {c.get('b_run')}"}],
                                 xlabel="시간", ylabel="값", title=title[:70], width=460, height=280, max_points=ctx.pts(300))
                      + f'<p class="muted small">r {fmt(c.get("corr"), 4)} · NRMSE {pct(c.get("nrmse_pct"))} · 겹침 {pct((c["overlap_ratio"] * 100) if finite(c.get("overlap_ratio")) else None, 3)}</p></div>')
    return '<p class="muted small">A 실선(파랑) · B 점선(회색)</p><div class="grid2">' + "".join(charts) + "</div>"


def equiv_doc(inp: Mapping[str, Any], ctx: Ctx) -> Doc:
    d = inp["detail"]
    study = inp.get("study") or {}
    sm = d.get("summary") or {}
    v = sm.get("verdict") or {}
    verdict = d.get("verdict")
    snap = d.get("recipe_snapshot") or {}
    pairing = d.get("pairing") or {}
    head = (f'<p>{badge(VERDICT_TEXT.get(str(verdict), "판정 없음"), VERDICT_KIND.get(str(verdict), "na"))} '
            f'<span class="muted">{esc(d.get("summary_line") or "")}</span></p>')
    items: list[tuple[str, Any]] = [("필수", f"{v.get('required_pass', 0)}/{v.get('required_total', 0)}"), ("참고 미달", Raw(fmt(v.get("reference_fail", 0)))),
                                    ("쌍 수", Raw(fmt(pairing.get("n_pairs")))),
                                    ("짝 없음 A/B", f"{len(d.get('unmatched_a') or [])}/{len(d.get('unmatched_b') or [])}")]
    recipe_rows = [[m.get("id"), m.get("label"), KIND_TEXT.get(str(m.get("kind")), m.get("kind")), "필수" if m.get("required", True) else "참고",
                    m.get("tol_text") or "", _source_text(m.get("source"))] for m in d.get("metrics") or []]
    sec_recipe = (kv_table([("레시피", _recipe_text(d)), ("출처", {"system": "시스템 기본", "user": "사용자 레시피", "adhoc": "이번만 사용"}.get(
        str((d.get("recipe") or {}).get("source")), "—")),
        ("쌍 판정 규칙", f"{(snap.get('pair_rule') or {}).get('mode', 'all')}"
         + (f" (비율 ≥ {(snap.get('pair_rule') or {}).get('ratio')})" if (snap.get("pair_rule") or {}).get("mode") == "min_ratio" else "")),
        ("종합 규칙", {"required_all": "필수 지표 전부 통과"}.get(str(snap.get("verdict_rule")), str(snap.get("verdict_rule") or "—")))])
        + table(["id", "지표", "종류", "구분", "허용오차", "원천"], recipe_rows))
    sec_target = kv_table([("A (기준)", _side(d.get("side_a"))), ("B (비교)", _side(d.get("side_b"))),
                           ("쌍 방식", {"by_name": "이름", "by_params": "파라미터 값", "manual": "직접 지정"}.get(str(pairing.get("mode")), str(pairing.get("mode") or "—"))),
                           ("쌍 수", Raw(fmt(pairing.get("n_pairs")))),
                           ("짝 없음(A)", ", ".join(d.get("unmatched_a") or []) or "없음"), ("짝 없음(B)", ", ".join(d.get("unmatched_b") or []) or "없음")])
    rows = list(d.get("rows") or [])
    capped, more = ctx.cap_rows(rows, "쌍×지표 판정 표")
    labels = {m["id"]: m.get("label") for m in d.get("metrics") or []}
    full = details(f"쌍×지표 판정 표({len(rows)}행)", table(["쌍", "A run", "B run", "지표", "A", "B", "차이", "상대 %", "상관", "상태", "사유"], [
        [r.get("pair_no"), r.get("a_run"), r.get("b_run"), labels.get(r.get("metric_id")) or r.get("metric_id"), Raw(fmt(r.get("a"))), Raw(fmt(r.get("b"))),
         Raw(fmt(r.get("diff"))), Raw(pct(r.get("rel_pct"))), Raw(fmt(r.get("corr"), 4)), _badge(r.get("status")), r.get("reason_text") or ""]
        for r in capped], num=[0, 4, 5, 6, 7, 8]) + more) if rows else ""
    secs = [("summary", "종합 판정", head + cards(items) + (note(d["note"]) if d.get("note") else "")),
            ("recipe", "레시피 스냅숏", sec_recipe), ("target", "대상(A·B)", sec_target),
            ("metrics", "지표별 결과", _metric_table(d) + full), ("fails", "미달 쌍 상위 목록", _fail_rows(ctx, d)),
            ("curves", "대표 곡선 겹침", _curves(ctx, d, inp.get("curves") or []))]
    warns = [f"{w.get('code', '')} {w.get('message', '')}".strip() for w in d.get("warnings") or []]
    if d.get("failure"):
        warns.append(f"판정 실패 {d['failure'].get('code')}: {d['failure'].get('message')}")
    if d.get("status") != "DONE":
        warns.append(f"상태 {d.get('status_text') or d.get('status')}")
    return Doc(title="⑤ 등가성 판정 요약",
               meta=[*study_meta(study, inp.get("generated_by"), f"등가성 판정 {d.get('label')}", d["id"]), ("엔진", engine_text(inp.get("engine"))),
                     ("판정 생성", f"{d.get('created_by_name') or '—'} · {d.get('created_at')}"), ("생성 시각", ctx.generated_at),
                     ("플랫폼 버전", ctx.platform_version)],
               sections=secs, warnings=warns, sources=[f"eq_check:{d['id']}", f"job:{d.get('job_id')}"],
               data={"target": "equiv-check", "id": d["id"], "label": d.get("label"), "verdict": verdict, "status": d.get("status"),
                     "required": [v.get("required_pass"), v.get("required_total")], "n_pairs": pairing.get("n_pairs"),
                     "metrics": {m["id"]: {k: m.get(k) for k in ("status", "n_pairs", "n_pass", "n_fail", "n_na", "max_abs_rel_pct", "min_corr")}
                                 for m in d.get("metrics") or []}})


def _source_text(src: Any) -> str:
    if not isinstance(src, Mapping):
        return "연결 필요"
    t = src.get("type")
    if t == "perf":
        return f"성능 {src.get('perf')}"
    if t == "curve":
        return f"곡선 {src.get('series') or '첫 계열'}{(' · ' + str(src.get('stat'))) if src.get('stat') else ''}"
    if t == "mesh_volume":
        return f"메시 부피 {src.get('parts')}"
    if t == "h3d":
        return "H3D " + ", ".join(f"{k}={src[k]}" for k in ("datatype", "component", "stat") if src.get(k))
    return str(t)
