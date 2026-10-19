// S17 가중치 카드(phase3.md §22.12): 목적마다 슬라이더(0~100, step 5, 초기값 = settings.weights×100)와 정규화 %, 가중합 추천 문구·계산식 툴팁.
// 슬라이더를 바꾸면 추천 링이 즉시 이동한다(서버 왕복 없음). localStorage `physicsai.stage6.weights.<optId>`(try/catch)는 부모가 읽고 쓴다.
import { Card } from "../../../components/ui";
import { fmtNum } from "../../../lib/format";
import type { ParetoModel } from "./paretoView";
import { SCORE_TIP } from "./paretoView";

export function WeightSliders({ model, u, onChange, onReset, isDefault }: { model: ParetoModel; u: number[]; onChange: (i: number, v: number) => void; onReset: () => void; isDefault: boolean }) {
  const w = model.rec.weights;
  const recPt = model.front.find((p) => p.key === model.rec.key) ?? null;
  return (
    <Card span={3} title="가중치" className="so-weights" aside={<button type="button" className="btn small ghost" disabled={isDefault} onClick={onReset}>기본값으로</button>}>
      {model.defs.map((d, i) => (
        <div key={d.metric} className="so-weight-row" data-testid={`weight-${i}`}>
          <label className="small" htmlFor={`so-w-${i}`}>{d.label} <span className="muted">{d.sense === "max" ? "최대" : "최소"}</span></label>
          <div className="so-weight-ctl">
            <input id={`so-w-${i}`} type="range" min={0} max={100} step={5} value={u[i] ?? 50} aria-label={`${d.label} 가중치`} onChange={(e) => onChange(i, Number(e.target.value))} />
            <span className="mono small so-weight-pct" data-testid={`weight-pct-${i}`}>{Math.round((w[i] ?? 0) * 100)}%</span>
          </div>
        </div>
      ))}
      <p className="small so-recommend" data-testid="so-recommend" title={SCORE_TIP}>
        {recPt ? (
          <>
            가중합 추천: <b>{recPt.batch_label ?? "—"} DOE #{recPt.doe_no}</b> · 점수 <span className="mono">{fmtNum(model.rec.scores[model.front.indexOf(recPt)], 2)}</span>
          </>
        ) : (
          "가중합 추천: 검증된 파레토 해가 아직 없습니다"
        )}
      </p>
      <p className="muted small" data-testid="so-score-tip">{SCORE_TIP}</p>
    </Card>
  );
}
