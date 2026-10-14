// 스위스 격자 컴포넌트(docs/design/swiss-grid-mockup.html): Grid(12열 바둑판) · Cell(칸) · Rail(10~12열 공통 칸 띠).
// 칸은 행 높이(--row)의 정수배만 차지한다. 내용이 넘치면 내부 스크롤 대신 span 행 수를 늘린다(maxRows까지, 넘으면 본문만 스크롤).
import {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ElementType,
  type ReactNode,
} from "react";

export type Span = 2 | 3 | 4 | 6 | 9 | 12;

/** 본문 칸 최대 행 수 기본값(넘으면 본문 스크롤) */
export const MAX_ROWS = 16;

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

/** 내용 높이 → 차지할 행 수 n(칸 높이 = n·row + (n−1)·rule) */
export function rowsFor(contentPx: number, rowPx: number, rulePx: number, min: number, max: number): number {
  const n = Math.ceil((contentPx + rulePx) / (rowPx + rulePx) - 1e-6);
  return Math.max(min, Math.min(max, n));
}

function px(v: string): number {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : 0;
}

/** 칸의 자연 높이(머리·본문 안쪽·발 높이 + 안쪽 여백 + 간격)를 재어 행 수를 정한다 */
function useAutoRows(min: number, max: number) {
  const ref = useRef<HTMLElement | null>(null);
  const [rows, setRows] = useState(min);
  useLayoutEffect(() => {
    const cell = ref.current;
    if (!cell || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const cs = getComputedStyle(cell);
      const row = px(cs.getPropertyValue("--row")) || 176;
      const rule = px(cs.getPropertyValue("--rule-w")) || 1;
      const kids = Array.from(cell.children) as HTMLElement[];
      let h = px(cs.paddingTop) + px(cs.paddingBottom) + px(cs.rowGap) * Math.max(0, kids.length - 1);
      for (const k of kids) {
        const inner = k.classList.contains("cell-body") ? (k.firstElementChild as HTMLElement | null) : null;
        h += inner ? inner.offsetHeight : k.offsetHeight;
      }
      setRows(rowsFor(h, row, rule, min, max));
    };
    const ro = new ResizeObserver(measure);
    ro.observe(cell);
    const watch = () => {
      for (const k of Array.from(cell.children)) {
        ro.observe(k);
        if (k.classList.contains("cell-body") && k.firstElementChild) ro.observe(k.firstElementChild);
      }
    };
    watch();
    const mo = new MutationObserver(() => (watch(), measure()));
    mo.observe(cell, { childList: true });
    measure();
    return () => {
      ro.disconnect();
      mo.disconnect();
    };
  }, [min, max]);
  return { ref, rows };
}

// ---------------------------------------------------------------- Rail(공통 칸 띠)
interface RailApi {
  start: (i: number) => number;
  report: (i: number, rows: number) => void;
}
const RailCtx = createContext<RailApi | null>(null);
const SlotCtx = createContext<number | null>(null);

/** 10~12열 세로 띠: 자식 RailSlot 칸을 1행부터 차례로 쌓는다(각 칸의 시작 행 = 앞 칸 행 수 합 + 1) */
export function Rail({ children }: { children: ReactNode }) {
  const [spans, setSpans] = useState<Record<number, number>>({});
  const report = useCallback((i: number, rows: number) => setSpans((s) => (s[i] === rows ? s : { ...s, [i]: rows })), []);
  const api = useMemo<RailApi>(
    () => ({
      report,
      start: (i) => {
        let r = 1;
        for (let j = 0; j < i; j++) r += spans[j] ?? 0;
        return r;
      },
    }),
    [spans, report],
  );
  return <RailCtx.Provider value={api}>{children}</RailCtx.Provider>;
}

export function RailSlot({ index, children }: { index: number; children: ReactNode }) {
  return <SlotCtx.Provider value={index}>{children}</SlotCtx.Provider>;
}

// ---------------------------------------------------------------- Cell
export interface CellProps {
  span?: Span;
  /** 최소 행 수(기본 1) */
  rows?: number;
  maxRows?: number;
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

export function Cell({ span = 3, rows: minRows = 1, maxRows = MAX_ROWS, title, refText, aside, foot, as: Tag = "section", label, className, testId, children }: CellProps) {
  const { ref, rows } = useAutoRows(minRows, maxRows);
  const slot = useContext(SlotCtx);
  const rail = useContext(RailCtx);
  const inRail = slot !== null && !!rail;
  useLayoutEffect(() => {
    if (inRail) rail!.report(slot!, rows);
  }, [inRail, rail, slot, rows]);
  useLayoutEffect(() => {
    if (!inRail) return;
    return () => rail!.report(slot!, 0);
    // 칸이 사라질 때만 0으로
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inRail]);
  const style = { "--span": rows, ...(inRail ? { "--row-start": rail!.start(slot!) } : {}) } as CSSProperties;
  const cls = `cell c${span}${inRail ? " rail" : ""}${className ? ` ${className}` : ""}`;
  const head = title !== undefined || refText !== undefined || aside !== undefined;
  return (
    <Tag ref={ref} className={cls} style={style} aria-label={label} data-testid={testId} data-rows={rows}>
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
