// "적용 조건: …" 한 줄(extract-filter.md §6.4) + 추출 요약 접힘(§7.2: 종류별 채택·제외 수, 리브 후보 탈락 사유).
// ①-2 파라미터 표 머리줄(train/setup)과 ④ 세트 상세(native.extract_filter)가 같이 쓴다.
import { useState, type ReactNode } from "react";
import type { ExtractFilter } from "../api/types";
import { filterText, reasonText, summaryView } from "../lib/extractFilter";

export function AppliedFilter({ filter, summary, note }: { filter: ExtractFilter | null | undefined; summary?: unknown; note?: ReactNode }) {
  const [open, setOpen] = useState(false);
  const view = summaryView(summary);
  const hasSummary = !!view && (view.rows.length > 0 || view.ribTotal > 0);
  return (
    <div className="applied-filter small" data-testid="applied-filter">
      <div className="applied-filter-line">
        <span>
          <b>적용 조건:</b> <span data-testid="applied-filter-text">{filterText(filter)}</span>
        </span>
        {note && <span className="muted">{note}</span>}
        {hasSummary && (
          <button type="button" className={`btn small ghost ${open ? "on" : ""}`} aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            추출 요약 {open ? "▾" : "▸"}
          </button>
        )}
      </div>
      {hasSummary && open && (
        <ul className="plain extract-sum" aria-label="추출 요약">
          {view!.rows.map((r) => (
            <li key={r.type}>
              {r.label}: 채택 {r.kept} · 제외 {r.excluded}
              {r.reasons.length > 0 && `(${reasonText(r.reasons)})`}
            </li>
          ))}
          {view!.ribTotal > 0 && (
            <li>
              리브 후보 탈락 {view!.ribTotal}({reasonText(view!.ribRejects)})
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
