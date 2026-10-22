// "반복-성능" 그래프 축 편집(v0.2.8 C3): 그래프 오른쪽 위 작은 "축" 버튼 1개 → 팝오버(x·y 최소/최대, y 표기·소수 자리, 기본값).
// 입력이 숫자가 아니거나 최소 < 최대가 아니면 적용하지 않고 칸 아래에 경고를 보인다. 저장은 lib/chartAxis(localStorage, 실패해도 동작).
import { useCallback, useEffect, useRef, useState } from "react";
import {
  DEFAULT_AXIS,
  DEFAULT_DIGITS,
  MAX_DIGITS,
  checkAxisInput,
  isDefaultAxis,
  readAxisPrefs,
  writeAxisPrefs,
  type AxisKind,
  type AxisPrefs,
} from "../lib/chartAxis";

/** 그래프 종류별 축 설정(상태 + localStorage). kind=null이면 저장하지 않는다. */
export function useAxisPrefs(kind: AxisKind | null) {
  const [prefs, setPrefs] = useState<AxisPrefs>(() => (kind ? readAxisPrefs(kind) : { ...DEFAULT_AXIS }));
  const update = useCallback(
    (next: AxisPrefs) => {
      setPrefs(next);
      if (kind) writeAxisPrefs(kind, next);
    },
    [kind],
  );
  return [prefs, update] as const;
}

const show = (v: number | null) => (v == null ? "" : String(v));
const autoText = (v: number) => String(Number(v.toPrecision(4)));

export interface AxisEditorProps {
  prefs: AxisPrefs;
  onChange: (p: AxisPrefs) => void;
  /** 자동일 때의 범위: x = 0~마지막 반복, y = 데이터 범위 */
  auto: { x: [number, number]; y: [number, number] };
  xName?: string;
}

export function AxisEditor({ prefs, onChange, auto, xName = "반복" }: AxisEditorProps) {
  const [open, setOpen] = useState(false);
  const [d, setD] = useState({ xMin: "", xMax: "", yMin: "", yMax: "", digits: "" });
  const [err, setErr] = useState<{ xMin?: string; xMax?: string; yMin?: string; yMax?: string; digits?: string }>({});
  const wrap = useRef<HTMLDivElement>(null);

  const fill = (p: AxisPrefs) => setD({ xMin: show(p.xMin), xMax: show(p.xMax), yMin: show(p.yMin), yMax: show(p.yMax), digits: String(p.yDigits) });
  const toggle = () => {
    if (!open) {
      fill(prefs);
      setErr({});
    }
    setOpen(!open);
  };

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const editRange = (axis: "x" | "y", which: "Min" | "Max", text: string) => {
    const next = { ...d, [`${axis}${which}`]: text };
    setD(next);
    const lo = axis === "x" ? next.xMin : next.yMin;
    const hi = axis === "x" ? next.xMax : next.yMax;
    const [a0, a1] = auto[axis];
    const r = checkAxisInput(lo, hi, a0, a1);
    setErr((e) => ({ ...e, [`${axis}Min`]: r.minError, [`${axis}Max`]: r.maxError }));
    if (r.ok) onChange(axis === "x" ? { ...prefs, xMin: r.min, xMax: r.max } : { ...prefs, yMin: r.min, yMax: r.max });
  };

  const editDigits = (text: string) => {
    setD({ ...d, digits: text });
    const n = Number(text);
    if (text.trim() === "" || !Number.isInteger(n) || n < 0 || n > MAX_DIGITS) {
      setErr((e) => ({ ...e, digits: `0~${MAX_DIGITS} 정수` }));
      return;
    }
    setErr((e) => ({ ...e, digits: undefined }));
    onChange({ ...prefs, yDigits: n });
  };

  const reset = () => {
    onChange({ ...DEFAULT_AXIS });
    fill(DEFAULT_AXIS);
    setErr({});
  };

  const warn = (m?: string) => (m ? <span className="error-text small axis-warn" role="alert">{m}</span> : null);

  return (
    <div className="chart-axis-bar" ref={wrap}>
      <button type="button" className={`btn small${isDefaultAxis(prefs) ? "" : " on"}`} aria-haspopup="dialog" aria-expanded={open} onClick={toggle} data-testid="axis-btn">
        축
      </button>
      {open && (
        <div className="axis-pop" role="dialog" aria-label="축 편집" data-testid="axis-pop">
          <div className="axis-row">
            <span className="field-label">x축({xName})</span>
            <input aria-label="x 최소" aria-invalid={!!err.xMin} inputMode="decimal" placeholder={autoText(auto.x[0])} value={d.xMin} onChange={(e) => editRange("x", "Min", e.target.value)} />
            <span className="muted">~</span>
            <input aria-label="x 최대" aria-invalid={!!err.xMax} inputMode="decimal" placeholder={autoText(auto.x[1])} value={d.xMax} onChange={(e) => editRange("x", "Max", e.target.value)} />
            <span className="muted small">정수 눈금</span>
          </div>
          {(err.xMin || err.xMax) && <div className="axis-warns">{warn(err.xMin)}{warn(err.xMax)}</div>}
          <div className="axis-row">
            <span className="field-label">y축(성능)</span>
            <input aria-label="y 최소" aria-invalid={!!err.yMin} inputMode="decimal" placeholder={autoText(auto.y[0])} value={d.yMin} onChange={(e) => editRange("y", "Min", e.target.value)} />
            <span className="muted">~</span>
            <input aria-label="y 최대" aria-invalid={!!err.yMax} inputMode="decimal" placeholder={autoText(auto.y[1])} value={d.yMax} onChange={(e) => editRange("y", "Max", e.target.value)} />
            <span className="muted small">비우면 자동</span>
          </div>
          {(err.yMin || err.yMax) && <div className="axis-warns">{warn(err.yMin)}{warn(err.yMax)}</div>}
          <div className="axis-row">
            <span className="field-label">y 표기</span>
            <select aria-label="y 표기" value={prefs.yFormat} onChange={(e) => onChange({ ...prefs, yFormat: e.target.value === "plain" ? "plain" : "exp" })}>
              <option value="exp">지수</option>
              <option value="plain">일반</option>
            </select>
            <input aria-label="소수 자리" type="number" min={0} max={MAX_DIGITS} step={1} aria-invalid={!!err.digits} value={d.digits} onChange={(e) => editDigits(e.target.value)} />
            <span className="muted small">소수 자리(기본 {DEFAULT_DIGITS})</span>
            {warn(err.digits)}
          </div>
          <div className="axis-foot">
            <button type="button" className="btn small" onClick={reset}>기본값</button>
          </div>
        </div>
      )}
    </div>
  );
}
