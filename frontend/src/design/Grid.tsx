// 카드 격자 컴포넌트(대시보드 톤, 2026-10-17): Grid(12열) · Cell(카드 1개: 머리 → 본문 → 발).
// 높이는 내용대로(행 높이 고정 없음). 우측 고정 열(Rail)은 레이아웃 A에서 없앴다 — 대기열·자원은 상단 칩 → 서랍.
import type { ElementType, ReactNode } from "react";

export type Span = 2 | 3 | 4 | 6 | 8 | 9 | 12;

export function Grid({
  as: Tag = "div",
  className,
  children,
  label,
}: {
  as?: ElementType;
  className?: string;
  children: ReactNode;
  label?: string;
}) {
  return (
    <Tag className={`grid${className ? ` ${className}` : ""}`} aria-label={label}>
      {children}
    </Tag>
  );
}

export interface CellProps {
  span?: Span;
  /** 머리: 제목(이미 heading 요소) + 참조 번호 + 보조 요소 */
  title?: ReactNode;
  refText?: ReactNode;
  aside?: ReactNode;
  /** 발: 참조 설명·버튼 */
  foot?: ReactNode;
  as?: ElementType;
  label?: string;
  className?: string;
  testId?: string;
  children?: ReactNode;
}

export function Cell({ span = 3, title, refText, aside, foot, as: Tag = "section", label, className, testId, children }: CellProps) {
  const cls = `cell c${span}${className ? ` ${className}` : ""}`;
  const head = title !== undefined || refText !== undefined || aside !== undefined;
  return (
    <Tag className={cls} aria-label={label} data-testid={testId}>
      {head && (
        <header className="cell-head">
          {title ?? <span />}
          {aside}
          {refText !== undefined && <span className="cell-ref R">{refText}</span>}
        </header>
      )}
      <div className="cell-body">
        <div className="cell-body-in">{children}</div>
      </div>
      {foot && <footer className="cell-foot">{foot}</footer>}
    </Tag>
  );
}
