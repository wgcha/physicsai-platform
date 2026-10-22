// ⑤ 수렴 그래프(phase3.md §18.10, 자체 SVG — components/Chart): x = 반복 0..T(0 시작·정수 눈금, y 지수 3자리, "축" 버튼으로 편집 — lib/chartAxis), 회색 점 = 검증 run 값, 속 빈 점 = 대리모델 예측,
// 강조 선 = 지금까지 최선(검증된 설계만).
import { Chart } from "../../../components/Chart";
import type { SurrogateOpt } from "../../../api/surrogateOpt";
import { convergence, metricLabel } from "./soRules";

export function ConvergenceChart({ opt }: { opt: SurrogateOpt }) {
  const d = convergence(opt);
  const s = opt.settings as { objective: { metric: string; series?: string | null; sense: string }; tol_rel: number };
  const baseline = opt.final?.baseline?.objective ?? null; // D3-61 기준안(마무리 캡처 run) 수평선
  if (!d.verified.length && !d.predicted.length) return <p className="muted small">아직 검증된 run이 없습니다.</p>;
  return (
    <div className="so-convergence" data-testid="so-convergence">
      <Chart
        height={240}
        aspect={0.3}
        maxHeight={420}
        ariaLabel="수렴 그래프"
        xLabel="반복"
        yLabel={metricLabel(s.objective.metric, s.objective.series)}
        iterAxis={{ kind: "convergence", xLast: d.xMax }}
        lines={[
          ...(d.best.length ? [{ name: "best", pts: d.best, className: "chart-line" }] : []),
          ...(baseline != null ? [{ name: "baseline", pts: [[0, baseline], [d.xMax, baseline]] as [number, number][], className: "chart-line s1" }] : []),
        ]}
        points={[
          ...d.verified.map((p) => ({ ...p, r: 3, className: "chart-pt sample" })),
          ...d.predicted.map((p) => ({ ...p, r: 4.5, className: "chart-pt nearest" })),
          ...d.best.map(([x, y]) => ({ x, y, r: 3.5, className: "chart-pt", title: (fy: (v: number) => string) => `반복 ${x} 지금까지 최선 ${fy(y)}` })),
        ]}
      />
      <div className="legend small">
        <span className="lg sample" aria-hidden="true" />
        <span>검증 run</span>
        <span className="lg nearest" aria-hidden="true" />
        <span>대리모델 예측</span>
        <span className="lg line" aria-hidden="true" />
        <span>지금까지 최선({s.objective.sense === "max" ? "최대화" : "최소화"})</span>
        {baseline != null && (
          <>
            <span className="lg line s1" aria-hidden="true" />
            <span data-testid="baseline-key">기준안 {Number(baseline.toPrecision(4))}</span>
          </>
        )}
        <span className="muted">수렴 기준: 개선 &lt; {Number((s.tol_rel * 100).toPrecision(3))}%</span>
      </div>
    </div>
  );
}
