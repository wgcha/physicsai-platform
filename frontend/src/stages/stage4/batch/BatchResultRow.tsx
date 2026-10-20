// ④ B 일괄 예측 결과 표의 행(BatchResult에서 분할, R-F — 동작 불변): 행 선택·응답 값·상태 pill·실패 사유·다시 실행, 캡처 있는 행 카메라 표시.
import { type PredictBatch, type PredictBatchRow } from "../../../api";
import { fmtNum } from "../../../lib/format";
import { OutDot } from "./BatchPreview";
import { ROW_STATE_LABEL, isRowFailed, rowTone } from "./batchTable";

export function ResultRow({ r, b, showResp, selected, onSelect, canRetry, onRetry }: { r: PredictBatchRow; b: PredictBatch; showResp: boolean; selected: boolean; onSelect: () => void; canRetry: boolean; onRetry: () => void }) {
  const failed = isRowFailed(r.state);
  return (
    <tr className={`clickable${selected ? " selected" : ""}`} onClick={onSelect} data-testid={`row-${r.doe_no}`}>
      <td>
        <button type="button" className={selected ? "link strong accent" : "link strong"} aria-pressed={selected} aria-label={`DOE #${r.doe_no} 선택`} onClick={(e) => (e.stopPropagation(), onSelect())}>
          {r.doe_no}
        </button>
        {!!r.media_views?.length && <CaptureMark views={r.media_views} />}
      </td>
      <td className="mono small">{r.run_key}</td>
      {b.parameters.map((n) => (
        <td key={n} className="num">
          {fmtNum(r.applied_values[n] ?? r.values[n])}
          <OutDot on={r.out_of_range.includes(n)} />
        </td>
      ))}
      {showResp &&
        b.responses.map((x) => (
          <td key={x.name} className={selected ? "num strong" : "num"}>
            {r.responses?.[x.name] == null ? <span className="muted">—</span> : fmtNum(r.responses[x.name])}
          </td>
        ))}
      <td className={`num row-state ${r.state.toLowerCase()}`}>
        <span className={`pill ${rowTone(r.state)}`}>{ROW_STATE_LABEL[r.state]}</span>
        {failed && (r.code || r.message) && (
          <span className="muted small row-reason" title={r.message ?? ""}>
            {" "}
            {r.code ?? ""}
            {r.message ? ` — ${r.message}` : ""}
          </span>
        )}
        {canRetry && (
          <button type="button" className="btn small ghost" onClick={(e) => (e.stopPropagation(), onRetry())}>
            다시 실행
          </button>
        )}
      </td>
    </tr>
  );
}

/** 미디어 있는 행 표시(작은 카메라 SVG, 이모지 아님) */
function CaptureMark({ views }: { views: string[] }) {
  const t = `캡처 ${views.length}방향`;
  return (
    <svg className="capture-mark" width="14" height="12" viewBox="0 0 14 12" role="img" aria-label={t} data-testid="capture-mark">
      <title>{t}</title>
      <path d="M1 3h3l1.5-2h3L10 3h3v8H1z" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <circle cx="7" cy="7" r="2.2" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}
