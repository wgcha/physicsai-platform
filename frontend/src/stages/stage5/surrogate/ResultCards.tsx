// ⑤ 내장 최적화 결과 카드(D3-61): 최적안 — 기준안 대비(변수별 학습 범위 막대·표·범위 끝 안내), 결과 요약 타일,
// 컨투어 비교(기준안·최적안 마무리 캡처 — 같은 범례, 방향 공유, 이미지·영상 받기는 ContourMedia).
import { useState } from "react";
import { Link } from "react-router-dom";
import type { ViewKey } from "../../../api";
import type { SurrogateOpt } from "../../../api/surrogateOpt";
import { Card } from "../../../components/ui";
import { fmtNum } from "../../../lib/format";
import { ContourMedia } from "../../stage4/ContourMedia";
import { boundNote, compareRows, kpis, metricLabel } from "./soRules";

export const VERIFY_HINT = "목적 값도 PhysicsAI 예측입니다 — 최적안은 PBS 검증 해석으로 실해석 확인을 권장합니다";
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
  return (
    <Card span={8} title="최적안 — 기준안 대비" className="so-compare"
      aside={b?.batch_id ? <Link className="small" to={`${base}/stage/4/batch/${b.batch_id}`} data-testid="so-best-link">{b.batch_label} DOE #{b.doe_no}</Link> : undefined}>
      {!b ? (
        <p className="muted small">아직 검증된 최적안이 없습니다.</p>
      ) : (
        <>
          <div className="table-wrap">
            <table className="table compact" aria-label="기준안 대비">
              <thead>
                <tr><th>변수</th><th>범위(학습)</th><th className="num">기준안</th><th className="num">최적안</th><th className="num">변화</th></tr>
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
            <span><span className="mk-key opt" />최적안</span>
            <span>{b.feasible ? "제약 만족" : "제약 만족 설계 없음 — 위반 최소"}</span>
          </p>
          {note && <p className="small bound-flag" data-testid="bound-note">학습 범위 상한/하한 도달 — {note}</p>}
          <p className="muted small">{VERIFY_HINT}</p>
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
  const s = o.settings as { objective: { metric: string; series?: string | null } };
  const objLabel = metricLabel(s.objective.metric, s.objective.series);
  const legend = fin?.legend ? `같은 범례(${fmtNum(fin.legend.min)}–${fmtNum(fin.legend.max)})로 비교` : `범례 개별${fin?.legend_note ? ` — ${fin.legend_note}` : ""}`;
  const ready = fin?.status === "DONE" && fin.baseline?.job_id && fin.best?.job_id;
  return (
    <Card span={9} title="컨투어 비교 — 기준안 · 최적안" className="so-contour-card" aside={<span className="muted small">{legend}</span>}>
      {!fin ? (
        <p className="muted small" data-testid="contour-none">최적화가 끝나면 기준안·최적안을 같은 범례로 캡처합니다.</p>
      ) : !ready ? (
        <p className="muted small" data-testid="contour-none">
          {FINAL_TEXT[fin.status ?? ""] ?? "캡처 없음"}{fin.reason ? ` — ${fin.reason}` : ""}
          {fin.status === "PENDING" && fin.batch ? ` (${fin.batch.label} 예측 ${fin.batch.predict.succeeded}/${fin.batch.gen.total})` : ""}
        </p>
      ) : (
        <div className="so-contours">
          {([["기준안", fin.baseline!], ["최적안", fin.best!]] as const).map(([lbl, run]) => (
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
