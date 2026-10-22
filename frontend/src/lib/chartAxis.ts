// "반복-성능" 그래프 공용 축 규칙(v0.2.8 C1~C4): 순수 함수 + localStorage 저장(try/catch).
// C1 x(반복): 0 시작·정수 눈금. 데이터 값은 바꾸지 않고 범위·눈금만 정한다.
// C2 y(성능): 지수 표기 소수 3자리(1.235e+2). 툴팁도 같은 형식.
// C3 편집: 최소·최대(비우면 자동)·y 표기(지수/일반)·소수 자리 0~6. 최소 < 최대가 아니거나 숫자가 아니면 적용하지 않는다(로그축 없음).
// C4 저장: 그래프 종류별 localStorage — 읽기·쓰기 실패는 기본값으로 동작.
//    yKey(예: 설계 이력의 y 열 이름)를 주면 x 설정은 그래프 종류 단위로 공유하고 y 최소/최대·표기는 종류+yKey 단위로 따로 저장한다.

export type YFormat = "exp" | "plain";

export interface AxisPrefs {
  xMin: number | null;
  xMax: number | null;
  yMin: number | null;
  yMax: number | null;
  yFormat: YFormat;
  yDigits: number;
}

export const DEFAULT_DIGITS = 3;
export const MAX_DIGITS = 6;
export const DEFAULT_AXIS: AxisPrefs = { xMin: null, xMax: null, yMin: null, yMax: null, yFormat: "exp", yDigits: DEFAULT_DIGITS };

/** 그래프 종류(저장 키 단위) */
export type AxisKind = "convergence" | "hv" | "history";
export const AXIS_KEY_PREFIX = "physicsai.chartAxis.";
export const axisStorageKey = (kind: AxisKind, yKey?: string) => (yKey ? `${AXIS_KEY_PREFIX}${kind}.y.${yKey}` : `${AXIS_KEY_PREFIX}${kind}`);

export function clampDigits(n: unknown): number {
  const v = Math.round(Number(n));
  if (!Number.isFinite(v)) return DEFAULT_DIGITS;
  return Math.min(MAX_DIGITS, Math.max(0, v));
}

/** 지수 표기: 1.235e+2, -4.120e-3, 0.000e+0 */
export function fmtExp(v: number, digits = DEFAULT_DIGITS): string {
  if (!Number.isFinite(v)) return "–";
  return v.toExponential(clampDigits(digits));
}

export function fmtAxisY(v: number, p: Pick<AxisPrefs, "yFormat" | "yDigits"> = DEFAULT_AXIS): string {
  if (!Number.isFinite(v)) return "–";
  const d = clampDigits(p.yDigits);
  return p.yFormat === "plain" ? v.toFixed(d) : v.toExponential(d);
}

/** 정수 눈금만(소수 없음): 개수가 maxCount를 넘지 않도록 1·2·5·10… 간격 */
export function intTicks(min: number, max: number, maxCount = 10): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || max < min) return [];
  const lo = Math.ceil(min - 1e-9) + 0; // -0 방지
  const hi = Math.floor(max + 1e-9);
  if (hi < lo) return [];
  const n = Math.max(1, Math.floor(maxCount));
  let step = 1;
  for (let mag = 1; (hi - lo) / step + 1 > n; mag *= 10) {
    for (const m of [1, 2, 5]) {
      step = m * mag;
      if ((hi - lo) / step + 1 <= n) break;
    }
  }
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step + 0; v <= hi; v += step) out.push(v);
  return out;
}

/** x 범위: 자동 = 0 ~ 마지막 반복. 최대가 최소 이하로 남으면 최소 + 1 */
export function resolveXDomain(p: Pick<AxisPrefs, "xMin" | "xMax">, lastIter: number): [number, number] {
  const last = Number.isFinite(lastIter) ? lastIter : 0;
  const x0 = p.xMin ?? 0;
  let x1 = p.xMax ?? Math.max(last, x0 + 1);
  if (!(x1 > x0)) x1 = x0 + 1;
  return [x0, x1];
}

/** y 범위: 자동 = 데이터 범위(전부 같으면 5% 또는 ±1 펼침) */
export function resolveYDomain(p: Pick<AxisPrefs, "yMin" | "yMax">, dataMin: number, dataMax: number): [number, number] {
  let lo = Number.isFinite(dataMin) ? dataMin : 0;
  let hi = Number.isFinite(dataMax) ? dataMax : 1;
  if (lo === hi) {
    const d = Math.abs(lo) * 0.05 || 1;
    lo -= d;
    hi += d;
  }
  const y0 = p.yMin ?? lo;
  let y1 = p.yMax ?? hi;
  if (!(y1 > y0)) y1 = y0 + (Math.abs(y0) * 0.05 || 1);
  return [y0, y1];
}

// ---- 입력 검증(C3) ---------------------------------------------------------------------------

const NUM_RE = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;

/** 빈 칸 = 자동(null), 숫자 아님 = 오류 */
export function parseBound(text: string): { ok: true; value: number | null } | { ok: false; error: string } {
  const t = text.trim();
  if (t === "") return { ok: true, value: null };
  if (!NUM_RE.test(t)) return { ok: false, error: "숫자만 입력하세요" };
  const v = Number(t);
  if (!Number.isFinite(v)) return { ok: false, error: "숫자만 입력하세요" };
  return { ok: true, value: v };
}

export interface AxisCheck {
  ok: boolean;
  min: number | null;
  max: number | null;
  minError?: string;
  maxError?: string;
}

/** 최소·최대 칸 검사. 한쪽만 입력하면 다른 쪽 자동값(autoMin/autoMax)과 비교한다. 통과하지 못하면 적용하지 않는다. */
export function checkAxisInput(minText: string, maxText: string, autoMin: number, autoMax: number): AxisCheck {
  const a = parseBound(minText);
  const b = parseBound(maxText);
  const r: AxisCheck = { ok: true, min: null, max: null };
  if (!a.ok) (r.ok = false, (r.minError = a.error));
  if (!b.ok) (r.ok = false, (r.maxError = b.error));
  if (!r.ok) return r;
  const min = (a as { value: number | null }).value;
  const max = (b as { value: number | null }).value;
  const lo = min ?? autoMin;
  const hi = max ?? autoMax;
  if (Number.isFinite(lo) && Number.isFinite(hi) && !(lo < hi)) {
    r.ok = false;
    const msg = "최소는 최대보다 작아야 합니다";
    if (max != null) r.maxError = msg;
    else r.minError = msg;
    return r;
  }
  return { ok: true, min, max };
}

// ---- 저장(C4) --------------------------------------------------------------------------------

const optNum = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** 저장값 정리: 깨진 값은 기본값으로 */
export function sanitizePrefs(raw: unknown): AxisPrefs {
  if (!raw || typeof raw !== "object") return { ...DEFAULT_AXIS };
  const r = raw as Record<string, unknown>;
  let xMin = optNum(r.xMin);
  let xMax = optNum(r.xMax);
  let yMin = optNum(r.yMin);
  let yMax = optNum(r.yMax);
  if (xMin != null && xMax != null && !(xMin < xMax)) (xMin = null, (xMax = null));
  if (yMin != null && yMax != null && !(yMin < yMax)) (yMin = null, (yMax = null));
  return { xMin, xMax, yMin, yMax, yFormat: r.yFormat === "plain" ? "plain" : "exp", yDigits: r.yDigits === undefined ? DEFAULT_DIGITS : clampDigits(r.yDigits) };
}

function readOne(key: string): AxisPrefs {
  try {
    const raw = globalThis.localStorage?.getItem(key);
    return raw ? sanitizePrefs(JSON.parse(raw)) : { ...DEFAULT_AXIS };
  } catch {
    return { ...DEFAULT_AXIS };
  }
}

function writeOne(key: string, p: AxisPrefs): boolean {
  try {
    const ls = globalThis.localStorage;
    if (!ls) return false;
    if (isDefaultAxis(p)) ls.removeItem(key);
    else ls.setItem(key, JSON.stringify(p));
    return true;
  } catch {
    return false;
  }
}

/** yKey 없음: 종류 단위 전체. yKey 있음: x = 종류 단위, y(최소·최대·표기·자리) = 종류+yKey 단위 */
export function readAxisPrefs(kind: AxisKind, yKey?: string): AxisPrefs {
  const base = readOne(axisStorageKey(kind));
  if (!yKey) return base;
  const y = readOne(axisStorageKey(kind, yKey));
  return { ...base, yMin: y.yMin, yMax: y.yMax, yFormat: y.yFormat, yDigits: y.yDigits };
}

/** 기본값과 같으면 저장 항목을 지운다. 실패하면 false(화면 상태는 그대로 동작). */
export function writeAxisPrefs(kind: AxisKind, p: AxisPrefs, yKey?: string): boolean {
  if (!yKey) return writeOne(axisStorageKey(kind), p);
  const a = writeOne(axisStorageKey(kind), { ...DEFAULT_AXIS, xMin: p.xMin, xMax: p.xMax });
  const b = writeOne(axisStorageKey(kind, yKey), { ...DEFAULT_AXIS, yMin: p.yMin, yMax: p.yMax, yFormat: p.yFormat, yDigits: p.yDigits });
  return a && b;
}

export function isDefaultAxis(p: AxisPrefs): boolean {
  return p.xMin == null && p.xMax == null && p.yMin == null && p.yMax == null && p.yFormat === "exp" && p.yDigits === DEFAULT_DIGITS;
}
