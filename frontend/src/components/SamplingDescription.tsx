// S15 방식 설명 상자(phase3.md §20.4·§20.10): ①·④ 공용. 선택창 아래 4줄(용도 / 장단점 / 영향도·AI 학습 / run 수·제약) + 추천 방식은 `추천` 배지.
// 문구는 lib/sampling.ts 한 곳(계약 그대로) — 계산값(현재 변수 수에서의 권장 run)은 4번째 줄 뒤 별도 칸으로 덧붙인다.
import { DESCRIPTIONS, type DescId } from "../lib/sampling";

export function SamplingDescription({ id, recommended, calc }: { id: DescId; recommended?: boolean; calc?: string | null }) {
  const d = DESCRIPTIONS[id];
  return (
    <div className="samp-desc" data-testid="samp-desc" data-desc-id={id} role="note" aria-label="방식 설명">
      <div className="samp-desc-head">
        <b>{d.name}</b>
        {recommended && (
          <span className="samp-badge" data-testid="samp-badge">
            추천
          </span>
        )}
      </div>
      {d.lines.map((l, i) => (
        <p key={i} className="small samp-line" data-testid={`samp-line-${i + 1}`}>
          {l}
          {i === 3 && calc && (
            <span className="samp-calc" data-testid="samp-calc">
              {" "}
              {calc}
            </span>
          )}
        </p>
      ))}
    </div>
  );
}
