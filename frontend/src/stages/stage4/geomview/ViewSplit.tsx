// 표(좌) | 3D 미리보기 창(우) 2열(geometry-view.md §7.2). 높이는 뷰포트 기준 고정 — 표는 내부 스크롤(헤더 sticky), 3D 창은 같은 높이로
// 나란히(행 수와 무관하게 페이지 길이 일정). 좁은 화면은 3D 창(고정 높이) 위 + 표(고정 높이) 아래. view가 없으면 표만.
import type { ReactNode } from "react";

export function ViewSplit({ table, view }: { table: ReactNode; view: ReactNode }) {
  if (!view) return <>{table}</>;
  return (
    <div className="gv-split" data-testid="gv-split">
      <div className="gv-split-view" data-testid="gv-split-view">
        {view}
      </div>
      <div className="gv-split-table" data-testid="gv-split-table">
        {table}
      </div>
    </div>
  );
}
