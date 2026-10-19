// ⑤ 비교 슬롯(phase3.md §19.6 두 출처 겹쳐 보기): `비교 추가` → 비교 출처 선택. 두 표의 파라미터 이름 집합이 같을 때만 활성(대소문자 구분·순서 무관).
// 다르면 회색 안내 + 겹치지 않음, 공통 응답이 없어도 안내. 메타가 둘 다 있고 다르면 회색 "메타 다름" 한 줄은 머리(StageAnalysis)에서.
import type { PredictBatchSummary, TrainDoe } from "../../api";
import { SourcePicker, type SourceSel } from "./SourcePicker";

export function CompareSlot({ sel, batches, does, onChange, onRemove, onAdd, canAdd, message, loading, error }: { sel: SourceSel | null; batches: PredictBatchSummary[]; does: TrainDoe[]; onChange: (s: SourceSel) => void; onRemove: () => void; onAdd: () => void; canAdd: boolean; message: string | null; loading: boolean; error: string | null }) {
  if (!sel)
    return (
      <div className="compare-slot">
        <button type="button" className="btn small" disabled={!canAdd} onClick={onAdd}>
          비교 추가
        </button>
        <span className="muted small">해석 DOE와 일괄 예측을 같은 변수 이름일 때 겹쳐 봅니다(선택 사항)</span>
      </div>
    );
  return (
    <div className="compare-slot" role="group" aria-label="비교 슬롯">
      <SourcePicker slot="비교" sel={sel} batches={batches} does={does} onChange={onChange} />
      <button type="button" className="btn small ghost" onClick={onRemove}>
        비교 제거
      </button>
      {loading && <span className="muted small">불러오는 중…</span>}
      {error && <span className="error-text small">{error}</span>}
      {message && (
        <span className="muted small" data-testid="compare-message">
          {message}
        </span>
      )}
    </div>
  );
}
