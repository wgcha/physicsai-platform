// 표 행 다중 선택 뒤 "사용 체크 | 사용 해제 | 선택 해제"(선택이 있을 때만) — ①-2 파라미터 표·④ 쉘 두께 표 공용.
export function BulkUseBar({ count, onCheck, onUncheck, onClear, disabled }: { count: number; onCheck: () => void; onUncheck: () => void; onClear: () => void; disabled?: boolean }) {
  if (count <= 0) return null;
  return (
    <div className="bulk-bar" data-testid="bulk-use-bar">
      <span className="muted small">{count}개 선택</span>
      <button type="button" className="btn small" disabled={disabled} onClick={onCheck}>
        사용 체크
      </button>
      <button type="button" className="btn small" disabled={disabled} onClick={onUncheck}>
        사용 해제
      </button>
      <button type="button" className="btn small ghost" onClick={onClear}>
        선택 해제
      </button>
    </div>
  );
}
