// ⑤ 등가성 판정 — 결과(equiv-check.md §7-4): 종합 배지 + 한 줄, 지표 표(행 펼치면 쌍별 값), 쌍 선택 → 곡선 겹쳐 그림(A 실선·B 점선, r·NRMSE), table.csv,
// 메모(작성자·관리자만 사후 수정 — PATCH note, §5.1).
import { useEffect, useState } from "react";
import { errorMessage } from "../../api";
import { equivApi, type EqCheck, type EqCurves, type EqMetricAgg } from "../../api/equivCheck";
import { Chart } from "../../components/Chart";
import { fmtNum } from "../../lib/format";
import { STATUS_TEXT, VERDICT_CLASS, VERDICT_TEXT } from "./recipeState";

export function VerdictBadge({ check }: { check: EqCheck | { verdict: EqCheck["verdict"]; status: EqCheck["status"]; status_text: string } }) {
  if (check.status !== "DONE" || !check.verdict) return <span className="pill" data-testid="eq-verdict">{check.status_text}</span>;
  return (
    <span className={`pill ${VERDICT_CLASS[check.verdict]}`} data-testid="eq-verdict">
      {VERDICT_TEXT[check.verdict]}
    </span>
  );
}

function MetricRow({ m, rows, open, onToggle }: { m: EqMetricAgg; rows: EqCheck["rows"]; open: boolean; onToggle: () => void }) {
  const curve = m.kind === "curve_corr" || m.kind === "curve_nrmse";
  const npairs = m.n_pairs ?? rows.length;
  return (
    <>
      <tr className={`eq-metric ${m.status.toLowerCase()}`} data-testid={`eq-metric-${m.id}`}>
        <td>
          <button type="button" className="btn ghost small" aria-expanded={open} aria-label={`${m.label} 쌍별 값`} onClick={onToggle}>
            {open ? "▾" : "▸"}
          </button>{" "}
          {m.label}
        </td>
        <td>{curve ? "—" : fmtNum(m.a_mean)}</td>
        <td>{curve ? "—" : fmtNum(m.b_mean)}</td>
        <td>{curve ? "—" : m.max_abs_rel_pct == null ? "—" : `${fmtNum(m.max_abs_rel_pct, 3)}%`}</td>
        <td>{curve ? "—" : fmtNum(m.max_abs_diff)}</td>
        <td>{m.kind === "curve_corr" ? fmtNum(m.min_corr) : "—"}</td>
        <td>{m.tol_text}</td>
        <td>
          {m.n_pass ?? 0}/{npairs}
        </td>
        <td>
          <span className={`pill ${m.status === "PASS" ? "ok" : m.status === "FAIL" ? "bad" : ""}`}>{STATUS_TEXT[m.status] ?? m.status}</span>
        </td>
        <td>{m.required ? "필수" : "참고"}</td>
      </tr>
      {open &&
        rows.map((r) => (
          <tr key={`${m.id}-${r.pair_no}`} className="eq-pair-row" data-testid={`eq-pair-${m.id}-${r.pair_no}`}>
            <td className="muted small">
              쌍 {r.pair_no} · {r.a_run} ↔ {r.b_run}
            </td>
            <td>{fmtNum(r.a)}</td>
            <td>{fmtNum(r.b)}</td>
            <td>{r.rel_pct == null ? "—" : `${fmtNum(r.rel_pct, 3)}%`}</td>
            <td>{fmtNum(r.diff)}</td>
            <td>{fmtNum(r.corr)}</td>
            <td colSpan={2} className="muted small">
              {r.reason_text ?? ""}
            </td>
            <td>
              <span className={`pill ${r.status === "PASS" ? "ok" : r.status === "FAIL" ? "bad" : ""}`}>{STATUS_TEXT[r.status] ?? r.status}</span>
            </td>
            <td />
          </tr>
        ))}
    </>
  );
}

export function CurvePair({ eqId, pair, metric }: { eqId: string; pair: number; metric: string }) {
  const [data, setData] = useState<EqCurves | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);
    equivApi
      .curves(eqId, pair, metric)
      .then((c) => alive && setData(c))
      .catch((e) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [eqId, pair, metric]);
  if (error) return <p className="error-text small" role="alert">{error}</p>;
  if (!data) return <p className="muted small">곡선 불러오는 중…</p>;
  const pts = (ys: number[]) => data.t.map((x, i) => [x, ys[i]] as [number, number]);
  return (
    <div className="eq-curve" data-testid="eq-curve">
      <Chart height={240} aspect={0.4} maxHeight={480} ariaLabel={`곡선 겹쳐 보기 쌍 ${data.pair_no}`} lines={[{ name: `A ${data.a_run}`, pts: pts(data.a), className: "chart-line fv-pred" }, { name: `B ${data.b_run}`, pts: pts(data.b), className: "chart-line fv-fem" }]} />
      <div className="legend small">
        <span>
          <span className="lg line fv-pred" /> A(기준, 실선) {data.a_run}
        </span>
        <span>
          <span className="lg line fv-fem" /> B(비교, 점선) {data.b_run}
        </span>
        <span data-testid="eq-curve-stats">
          r = {fmtNum(data.corr)} · NRMSE = {data.nrmse_pct == null ? "—" : `${fmtNum(data.nrmse_pct, 3)}%`}
          {data.overlap_ratio != null && data.overlap_ratio < 1 ? ` · 공통 구간 ${Math.round(data.overlap_ratio * 100)}%` : ""}
        </span>
      </div>
    </div>
  );
}

export function NoteField({ check, onSaved }: { check: EqCheck; onSaved?: (note: string | null) => void }) {
  const [text, setText] = useState(check.note ?? "");
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => setText(check.note ?? ""), [check.id, check.note]);
  if (!check.can_edit_note) return check.note ? <p className="small" data-testid="eq-note">메모: {check.note}</p> : null;
  const save = async () => {
    setMsg(null);
    try {
      const r = await equivApi.patchNote(check.id, text.trim() || null);
      setMsg("메모를 저장했습니다");
      onSaved?.(r.note);
    } catch (e) {
      setMsg(errorMessage(e));
    }
  };
  return (
    <div className="eq-row" data-testid="eq-note-edit">
      <input aria-label="판정 메모" placeholder="메모(500자 이내)" maxLength={500} value={text} onChange={(e) => setText(e.target.value)} />
      <button type="button" className="btn ghost small" disabled={(check.note ?? "") === text.trim()} onClick={() => void save()}>
        메모 저장
      </button>
      {msg && <span className="muted small">{msg}</span>}
    </div>
  );
}

export function ResultView({ check, onNoteSaved }: { check: EqCheck; onNoteSaved?: (note: string | null) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const [pair, setPair] = useState<number | null>(null);
  const [metric, setMetric] = useState<string | null>(null);
  const curveMetrics = check.metrics.filter((m) => m.kind === "curve_corr" || m.kind === "curve_nrmse");
  const pickMetric = metric && curveMetrics.some((m) => m.id === metric) ? metric : curveMetrics[0]?.id ?? null;
  const pickPair = pair ?? check.pairs[0]?.no ?? null;
  const v = check.summary?.verdict;
  const rec = check.recipe;
  const download = async () => {
    const blob = await equivApi.tableCsv(check.id);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${check.label}_metrics.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="eq-result" data-testid="eq-result">
      <div className="eq-result-head">
        <VerdictBadge check={check} />
        <strong>{check.label}</strong>
        {v && (
          <span className="muted small" data-testid="eq-summary-line">
            필수 {v.required_pass}/{v.required_total} · 참고 미달 {v.reference_fail} · 쌍 {check.pairing.n_pairs} · {rec.name ?? (rec.source === "adhoc" ? "1회용 레시피" : "레시피")}
            {rec.version != null ? ` v${rec.version}` : ""}
            {rec.modified ? "(수정됨)" : ""}
          </span>
        )}
        {check.status === "FAILED" && check.failure && (
          <span className="error-text small" role="alert">
            {check.failure.code}: {check.failure.message}
          </span>
        )}
        <span className="eq-spacer" />
        <span className="muted small">
          A {check.side_a.label} · B {check.side_b.label}
        </span>
        {check.status === "DONE" && (
          <button type="button" className="btn ghost small" onClick={() => void download()}>
            table.csv 받기
          </button>
        )}
      </div>
      <NoteField check={check} onSaved={onNoteSaved} />
      {check.warnings.length > 0 && (
        <ul className="muted small eq-warnings" data-testid="eq-warnings">
          {check.warnings.slice(0, 8).map((w, i) => (
            <li key={`${w.code}-${i}`}>
              {w.code}: {w.message}
            </li>
          ))}
        </ul>
      )}
      {check.status === "DONE" && (
        <table className="table compact" aria-label="지표 판정">
          <thead>
            <tr>
              <th>지표</th>
              <th>A 평균</th>
              <th>B 평균</th>
              <th>최대 상대차</th>
              <th>최대 절대차</th>
              <th>상관 최소</th>
              <th>허용</th>
              <th>통과 쌍</th>
              <th>상태</th>
              <th>구분</th>
            </tr>
          </thead>
          <tbody>
            {check.metrics.map((m) => (
              <MetricRow key={m.id} m={m} rows={check.rows.filter((r) => r.metric_id === m.id)} open={open === m.id} onToggle={() => setOpen(open === m.id ? null : m.id)} />
            ))}
          </tbody>
        </table>
      )}
      {check.status === "DONE" && curveMetrics.length > 0 && pickMetric && pickPair != null && (
        <div className="eq-curve-pick">
          <label className="inline-field">
            쌍
            <select aria-label="곡선 쌍 선택" value={pickPair} onChange={(e) => setPair(Number(e.target.value))}>
              {check.pairs.map((p) => (
                <option key={p.no} value={p.no}>
                  {p.no}: {p.a} ↔ {p.b}
                </option>
              ))}
            </select>
          </label>
          {curveMetrics.length > 1 && (
            <label className="inline-field">
              곡선 지표
              <select aria-label="곡선 지표 선택" value={pickMetric} onChange={(e) => setMetric(e.target.value)}>
                {curveMetrics.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <CurvePair eqId={check.id} pair={pickPair} metric={pickMetric} />
        </div>
      )}
      {(check.unmatched_a.length > 0 || check.unmatched_b.length > 0) && (
        <p className="muted small" data-testid="eq-unmatched">
          짝 없음 — A: {check.unmatched_a.join(", ") || "없음"} · B: {check.unmatched_b.join(", ") || "없음"}
        </p>
      )}
    </div>
  );
}
