// ⑤ 등가성 판정 — 이력(equiv-check.md §7-5): EQ-번호·시각·사용자·A/B·레시피 이름 v·판정·메모 → 열기 · 이 레시피 불러오기.
import type { EqCheckListItem } from "../../api/equivCheck";
import { fmtTime } from "../../lib/format";
import { VerdictBadge } from "./ResultView";
import { versionNote } from "./recipeState";

export function HistoryList({ items, onOpen, onLoadRecipe, nextCursor, onMore, loading }: { items: EqCheckListItem[]; onOpen: (id: string) => void; onLoadRecipe: (id: string) => void; nextCursor: string | null; onMore: () => void; loading: boolean }) {
  if (!items.length) return <p className="muted small" data-testid="eq-history-empty">{loading ? "불러오는 중…" : "아직 판정 이력이 없습니다."}</p>;
  return (
    <div className="eq-history" data-testid="eq-history">
      <table className="table compact" aria-label="판정 이력">
        <thead>
          <tr>
            <th>번호</th>
            <th>시각</th>
            <th>사용자</th>
            <th>A / B</th>
            <th>레시피</th>
            <th>판정</th>
            <th>메모</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {items.map((it) => {
            const note = versionNote(it.recipe);
            return (
              <tr key={it.id} data-testid={`eq-hist-${it.label}`}>
                <td>{it.label}</td>
                <td>{fmtTime(it.created_at)}</td>
                <td>{it.created_by_name}</td>
                <td className="small">
                  {it.side_a.label} / {it.side_b.label}
                </td>
                <td className="small">
                  {it.recipe.name ?? (it.recipe.source === "adhoc" ? "1회용" : "—")}
                  {it.recipe.version != null ? ` v${it.recipe.version}` : ""}
                  {it.recipe.modified ? "(수정됨)" : ""}
                  {it.recipe.deleted ? " · 삭제된 레시피" : ""}
                  {note && !it.recipe.deleted && it.recipe.source !== "adhoc" ? <span className="muted"> · {note}</span> : null}
                </td>
                <td>
                  <VerdictBadge check={it} />
                  {it.summary_line && <span className="muted small"> {it.summary_line.split(" · ").slice(0, 2).join(" · ")}</span>}
                </td>
                <td className="small">{it.note ?? ""}</td>
                <td className="eq-hist-actions">
                  <button type="button" className="btn ghost small" onClick={() => onOpen(it.id)}>
                    열기
                  </button>
                  <button type="button" className="btn ghost small" onClick={() => onLoadRecipe(it.id)}>
                    이 레시피 불러오기
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {nextCursor && (
        <button type="button" className="btn ghost small" onClick={onMore} disabled={loading}>
          더 보기
        </button>
      )}
    </div>
  );
}
