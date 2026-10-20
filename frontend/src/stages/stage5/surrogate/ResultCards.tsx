// ⑤ 내장 최적화 결과 카드(D3-61): 최적안 — 기준안 대비(변수별 학습 범위 막대·표·범위 끝 안내), 결과 요약 타일,
// 컨투어 비교(기준안·최적안 마무리 캡처 — 같은 범례, 방향 공유, 이미지·영상 받기는 ContourMedia).
import { useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage, type ViewKey } from "../../../api";
import { surrogateApi, type SoCandidate, type SoIteration, type SurrogateOpt } from "../../../api/surrogateOpt";
import { useCanExecute } from "../../../hooks/useJobRunner";
import { Card } from "../../../components/ui";
import { fmtNum } from "../../../lib/format";
import { ContourMedia } from "../../stage4/ContourMedia";
import { useFemVerifyButton } from "../../stage4/verify/useFemVerifyButton";
import { UNVERIFIED_BADGE, boundNote, compareRows, kpis, objectiveDefs } from "./soRules";

export const VERIFY_HINT = "목적 값도 PhysicsAI 예측입니다 — FEM 검증 버튼으로 조립 상태 해석과 비교할 수 있습니다";
export const FINAL_TEXT: Record<string, string> = {
  PENDING: "기준안·최적안 컨투어를 캡처하는 중입니다",
  SKIPPED: "캡처 없음",
  FAILED: "캡처 없음",
  CANCELED: "캡처 없음",
};

function signed(v: number | null): string {
  if (v == null) return "–";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmtNum(Math.abs(v))}`;
}

export function OptimumCompareCard({ o, base }: { o: SurrogateOpt; base: string }) {
  const b = o.best;
  const fin = o.final;
  const rows = compareRows(o.parameters ?? [], fin?.baseline_values ?? null, b?.values ?? null);
  const note = boundNote(rows);
  const fem = useFemVerifyButton(b ? { kind: "opt_design", opt_id: o.id, pick: "best" } : null, !!b);
  const noun = o.mode === "multi" ? "추천점" : "최적안";
  return (
    <Card span={8} title={o.mode === "multi" ? "최적안(가중 추천점) — 기준안 대비" : "최적안 — 기준안 대비"} className="so-compare"
      aside={b?.batch_id ? <Link className="small" to={`${base}/stage/4/batch/${b.batch_id}`} data-testid="so-best-link">{b.batch_label} DOE #{b.doe_no}</Link> : undefined}>
      {!b ? (
        <p className="muted small">아직 검증된 {noun}이 없습니다.</p>
      ) : (
        <>
          <div className="table-wrap">
            <table className="table compact" aria-label="기준안 대비">
              <thead>
                <tr><th>변수</th><th>범위(학습)</th><th className="num">기준안</th><th className="num">{noun === "추천점" ? "추천점" : "최적안"}</th><th className="num">변화</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.name} data-testid={`cmp-${r.name}`}>
                    <td className="mono">{r.name}{r.unit ? <span className="muted"> [{r.unit}]</span> : null}</td>
                    <td>
                      <div className="so-range" title={`${fmtNum(r.min)} ~ ${fmtNum(r.max)}`} aria-hidden="true">
                        <span className="track" />
                        {r.basePos != null && r.optPos != null && (
                          <span className="seg" style={{ left: `${Math.min(r.basePos, r.optPos) * 100}%`, width: `${Math.abs(r.optPos - r.basePos) * 100}%` }} />
                        )}
                        {r.basePos != null && <span className="mk base" style={{ left: `${r.basePos * 100}%` }} />}
                        {r.optPos != null && <span className={`mk opt${r.bound ? " at-bound" : ""}`} style={{ left: `${r.optPos * 100}%` }} />}
                      </div>
                      <span className="muted small mono">{fmtNum(r.min)} – {fmtNum(r.max)}</span>
                    </td>
                    <td className="num mono">{fmtNum(r.base)}</td>
                    <td className="num mono"><b>{fmtNum(r.opt)}</b></td>
                    <td className={`num mono delta${r.delta == null || r.delta === 0 ? "" : r.delta > 0 ? " up" : " down"}`}>
                      {signed(r.delta)}
                      {r.bound && <span className="bound-flag"> ({r.bound === "upper" ? "상한" : "하한"})</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small so-legend-keys">
            <span><span className="mk-key base" />기준안(템플릿 nominal)</span>
            <span><span className="mk-key opt" />{noun}</span>
            <span>{b.feasible ? "제약 만족" : "제약 만족 설계 없음 — 위반 최소"}</span>
          </p>
          {note && <p className="small bound-flag" data-testid="bound-note">학습 범위 상한/하한 도달 — {note}</p>}
          <p className="muted small">{VERIFY_HINT}</p>
          <div className="run-action-row">{fem.button}</div>
          {fem.notes}
        </>
      )}
    </Card>
  );
}

export function ResultSummaryCard({ o }: { o: SurrogateOpt }) {
  return (
    <Card span={4} title="결과 요약">
      <div className="so-kpis" data-testid="so-kpis">
        {kpis(o).map((k) => (
          <div key={k.label} className="so-kpi">
            <div className="muted small">{k.label}</div>
            <div className="T kpi-value mono">{k.value}{k.unit ? <span className="muted small"> {k.unit}</span> : null}</div>
            <div className={`small kpi-sub ${k.tone}`}>{k.sub}</div>
          </div>
        ))}
      </div>
    </Card>
  );
}

export function ContourCompareCard({ o }: { o: SurrogateOpt }) {
  const fin = o.final;
  const [view, setView] = useState<ViewKey | null>(null);
  const objLabel = objectiveDefs(o)[0]?.label ?? "";
  const noun = o.mode === "multi" ? "추천점" : "최적안";
  const legend = fin?.legend ? `같은 범례(${fmtNum(fin.legend.min)}–${fmtNum(fin.legend.max)})로 비교` : `범례 개별${fin?.legend_note ? ` — ${fin.legend_note}` : ""}`;
  const ready = fin?.status === "DONE" && fin.baseline?.job_id && fin.best?.job_id;
  const fem = useFemVerifyButton(fin?.best ? { kind: "opt_design", opt_id: o.id, pick: "final_optimum" } : null, !!ready);
  return (
    <Card span={9} title={`컨투어 비교 — 기준안 · ${noun}`} className="so-contour-card" aside={<span className="run-action-row"><span className="muted small">{legend}</span>{fem.button}</span>}>
      {!fin ? (
        <p className="muted small" data-testid="contour-none">최적화가 끝나면 기준안·{noun}을 같은 범례로 캡처합니다.</p>
      ) : !ready ? (
        <p className="muted small" data-testid="contour-none">
          {FINAL_TEXT[fin.status ?? ""] ?? "캡처 없음"}{fin.reason ? ` — ${fin.reason}` : ""}
          {fin.status === "PENDING" && fin.batch ? ` (${fin.batch.label} 예측 ${fin.batch.predict.succeeded}/${fin.batch.gen.total})` : ""}
        </p>
      ) : (
        <div className="so-contours">
          {([["기준안", fin.baseline!], [noun, fin.best!]] as const).map(([lbl, run]) => (
            <div key={lbl} data-testid={`contour-${lbl}`}>
              <div className="so-contour-head">
                <b>{lbl}</b>
                <span className="small">{objLabel} <span className="mono">{fmtNum(run.objective)}</span></span>
                <span className="muted small mono">{Object.entries(run.values).map(([k, v]) => `${k} ${fmtNum(v)}`).join(" · ")}</span>
              </div>
              <ContourMedia jobId={run.job_id!} view={view} onView={setView} canCapture={false} />
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

/** opt-native ON-4 단일 목적 `대리모델만` 결과: 미검증 후보(반복 0 행 candidates) 표 + 선택 해 예측 검증(§22.7 EXTRA, 강조) */
export function UnverifiedCard({ o, onChanged }: { o: SurrogateOpt; onChanged: () => void }) {
  const canExec = useCanExecute();
  const cands = ((o.iterations ?? []) as SoIteration[]).flatMap((it) => (it.candidates ?? []).filter((c) => c.state === "UNVERIFIED")) as SoCandidate[];
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const names = (o.settings as { names?: string[] }).names ?? [];
  const label = objectiveDefs(o)[0]?.label ?? "목적";
  const chosen = cands.filter((c) => sel.has(c.doe_no));
  const reason = !o.can_verify_more ? "지금은 추가 검증을 시작할 수 없습니다" : !chosen.length ? "검증할 후보를 고르세요" : null;
  const verify = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await surrogateApi.verify(o.id, { points: chosen.map((c) => ({ values: c.values })), capture: false });
      setDone(r.batch_label);
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card span={9} title="대리모델 최적 후보" className="so-unverified" aside={<span className="pill warn" data-testid="unverified-badge">{UNVERIFIED_BADGE}</span>}>
      {!cands.length ? (
        <p className="muted small">미검증 후보가 없습니다.</p>
      ) : (
        <div className="table-wrap">
          <table className="table compact" aria-label="미검증 후보">
            <thead>
              <tr><th /><th className="num">#</th><th>역할</th>{names.map((n) => <th key={n} className="num mono">{n}</th>)}<th className="num">{label} 예측</th><th className="num">±</th></tr>
            </thead>
            <tbody>
              {cands.map((c) => (
                <tr key={c.doe_no} data-testid={`ucand-${c.doe_no}`} className={sel.has(c.doe_no) ? "selected" : ""}>
                  <td><input type="checkbox" checked={sel.has(c.doe_no)} aria-label={`후보 ${c.doe_no} 선택`}
                    onChange={() => setSel((x) => { const n = new Set(x); if (n.has(c.doe_no)) n.delete(c.doe_no); else n.add(c.doe_no); return n; })} /></td>
                  <td className="num">{c.doe_no}</td>
                  <td className="small">{c.role ?? ""}</td>
                  {names.map((n) => <td key={n} className="num mono">{fmtNum(c.values[n])}</td>)}
                  <td className="num mono">{fmtNum(c.predicted ?? null)}</td>
                  <td className="num mono muted">{fmtNum(c.predicted_std?.[0] ?? null)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {canExec && (
        <div className="run-action-row so-actions">
          <button type="button" className="btn primary" disabled={!!reason || busy} title={reason ?? undefined} onClick={() => void verify()} data-testid="unverified-verify">
            선택 해 예측 검증{chosen.length ? ` (${chosen.length})` : ""}
          </button>
        </div>
      )}
      <p className="small" data-testid="unverified-hint">대리모델만으로 고른 후보입니다 — 예측 체인으로 확인하려면 후보를 골라 '선택 해 예측 검증'을 누르세요.</p>
      {done && <p className="small" data-testid="unverified-done">추가 검증 {done} 시작 — 끝나면 검증 run 표에 나타납니다</p>}
      {error && <p className="error-text small" role="alert">{error}</p>}
    </Card>
  );
}
