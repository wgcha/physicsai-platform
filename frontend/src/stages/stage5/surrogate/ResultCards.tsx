// ⑤ 내장 최적화 결과 카드(D3-61): 최적안 — 기준안 대비(변수별 학습 범위 막대·표·범위 끝 안내), 결과 요약 타일,
// 컨투어 비교(contour3d-default: 기존안·최적안 3D 두 뷰어 — 시점 연결·공통 범례·공용 시간. 마무리 캡처 PNG는 [그림/영상] 창·폴백, 같은 범례·방향 공유).
import { useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage, type Contour3dCreate, type ViewKey } from "../../../api";
import { surrogateApi, type SoCandidate, type SoIteration, type SurrogateOpt } from "../../../api/surrogateOpt";
import { useCanExecute } from "../../../hooks/useJobRunner";
import { Card } from "../../../components/ui";
import { fmtNum } from "../../../lib/format";
import { ContourMedia } from "../../stage4/ContourMedia";
import { ContourCompare3D } from "../../stage4/geomview/contour/ContourCompare3D";
import { useFemVerifyButton } from "../../stage4/verify/useFemVerifyButton";
import { UNVERIFIED_BADGE, boundNote, compareRows, fmtVar, kpis, levelsOf, objectiveDefs, rangeBasis, rangeHeader } from "./soRules";

export const VERIFY_HINT = "목적 값도 PhysicsAI 예측입니다 — FEM 검증 버튼으로 조립 상태 해석과 비교할 수 있습니다";
export const FINAL_TEXT: Record<string, string> = {
  PENDING: "기존안·최적안 컨투어를 캡처하는 중입니다",
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
  const rows = compareRows(o.parameters ?? [], fin?.baseline_values ?? null, b?.values ?? null, rangeBasis(o.settings));
  const note = boundNote(rows);
  const fem = useFemVerifyButton(b ? { kind: "opt_design", opt_id: o.id, pick: "best" } : null, !!b);
  const noun = o.mode === "multi" ? "추천점" : "최적안";
  return (
    <Card span="half" title={o.mode === "multi" ? "최적안(가중 추천점) — 기존안 대비" : "최적안 — 기존안 대비"} className="so-compare"
      aside={b?.batch_id ? <Link className="small" to={`${base}/stage/4/batch/${b.batch_id}`} data-testid="so-best-link">{b.batch_label} DOE #{b.doe_no}</Link> : undefined}>
      {!b ? (
        <p className="muted small">아직 검증된 {noun}이 없습니다.</p>
      ) : (
        <>
          <div className="table-wrap">
            <table className="table compact" aria-label="기존안 대비">
              <thead>
                <tr><th>변수</th><th>{rangeHeader(rows)}</th><th className="num">기존안</th><th className="num">{noun === "추천점" ? "추천점" : "최적안"}</th><th className="num">변화</th></tr>
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
                      <span className="muted small mono">{fmtNum(r.min)} – {fmtNum(r.max)}{r.rangeLabel === "템플릿 범위" && rangeHeader(rows) === "학습 범위" ? " (템플릿)" : ""}</span>
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
            <span><span className="mk-key base" />기존안(템플릿 nominal)</span>
            <span><span className="mk-key opt" />{noun}</span>
            <span>{b.feasible ? "제약 만족" : "제약 만족 설계 없음 — 위반 최소"}</span>
          </p>
          {note && <p className="small bound-flag" data-testid="bound-note">범위 상한/하한 도달 — {note}</p>}
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
    <Card span={12} title="결과 요약">
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
  const title = `컨투어 비교 — 기존안 · ${noun}`;
  if (!fin || !ready || !fin.baseline || !fin.best)
    return (
      <Card span="half" title={title} className="so-contour-card" aside={<span className="run-action-row">{fem.button}</span>}>
        {!fin ? (
          <p className="muted small" data-testid="contour-none">최적화가 끝나면 기존안·{noun}을 같은 범례로 비교합니다.</p>
        ) : (
          <p className="muted small" data-testid="contour-none">
            {FINAL_TEXT[fin.status ?? ""] ?? "캡처 없음"}{fin.reason ? ` — ${fin.reason}` : ""}
            {fin.status === "PENDING" && fin.batch ? ` (${fin.batch.label} 예측 ${fin.batch.predict.succeeded}/${fin.batch.gen.total})` : ""}
          </p>
        )}
      </Card>
    );
  const pairs = [["기존안", fin.baseline], [noun, fin.best]] as const;
  const head = (run: (typeof pairs)[number][1]) => (
    <>
      <span className="small">{objLabel} <span className="mono">{fmtNum(run.objective)}</span></span>
      <span className="muted small mono">{Object.entries(run.values).map(([k, v]) => `${k} ${fmtNum(v)}`).join(" · ")}</span>
    </>
  );
  // [그림/영상] 창·3D 폴백: 기존 PNG·영상 두 열(D3-61 같은 범례·방향 공유)
  const media = (
    <>
      <p className="muted small" data-testid="so-legend-text">{legend}</p>
      <div className="so-contours">
        {pairs.map(([lbl, run]) => (
          <div key={lbl} data-testid={`contour-${lbl}`}>
            <div className="so-contour-head">
              <b>{lbl}</b>
              {head(run)}
            </div>
            <ContourMedia jobId={run.job_id!} view={view} onView={setView} canCapture={false} />
          </div>
        ))}
      </div>
    </>
  );
  const src = (run: (typeof pairs)[number][1]): Contour3dCreate => ({ source_kind: "PREDICT_H3D", source_ref: { job_id: run.job_id! } });
  return (
    <ContourCompare3D
      left={{ label: pairs[0][0], source: src(pairs[0][1]), head: head(pairs[0][1]) }}
      right={{ label: pairs[1][0], source: src(pairs[1][1]), head: head(pairs[1][1]) }}
      media={media}
      mediaTitle={`그림/영상 — ${title}`}
    >
      {({ aside, body }) => (
        <Card span="half" title={title} className="so-contour-card" aside={<span className="run-action-row">{aside}{fem.button}</span>}>
          {body}
        </Card>
      )}
    </ContourCompare3D>
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
                  {names.map((n) => <td key={n} className="num mono">{fmtVar(n, c.values[n], levelsOf(o))}</td>)}
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
