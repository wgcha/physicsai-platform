// 컬러맵(geometry-view.md §13.6): turbo류 256단계 표를 자체 구현(three `Lut` 미사용). 형상 미리보기 변위 색(§7.3)도 같은 표.
// 다항 근사(Google turbo, Apache-2.0 공개 근사식) → 0~255 정수 RGB 표. NaN = 회색.

export const LUT_SIZE = 256;
export const NAN_RGB: [number, number, number] = [0.55, 0.57, 0.6];

function turbo(t: number): [number, number, number] {
  const x = Math.min(1, Math.max(0, t));
  const r = 0.13572138 + x * (4.6153926 + x * (-42.66032258 + x * (132.13108234 + x * (-152.94239396 + x * 59.28637943))));
  const g = 0.09140261 + x * (2.19418839 + x * (4.84296658 + x * (-14.18503333 + x * (4.27729857 + x * 2.82956604))));
  const b = 0.1066733 + x * (12.64194608 + x * (-60.58204836 + x * (110.36276771 + x * (-89.90310912 + x * 27.34824973))));
  const c = (v: number) => Math.min(1, Math.max(0, v));
  return [c(r), c(g), c(b)];
}

/** 256×3 Float32(0~1) 표 */
export const LUT: Float32Array = (() => {
  const out = new Float32Array(LUT_SIZE * 3);
  // 양 끝의 아주 어두운 구간(검정에 가까운 남색·적갈색)은 어두운 배경에서 형상이 묻혀 0.06~0.94 구간만 쓴다
  for (let i = 0; i < LUT_SIZE; i++) out.set(turbo(0.06 + (0.88 * i) / (LUT_SIZE - 1)), i * 3);
  return out;
})();

/** three 정점 색용 선형 표(three는 정점 색을 선형으로 보고 출력 때 sRGB로 바꾼다 — sRGB 표를 그대로 넣으면 색이 바랜다) */
export const LUT_LINEAR: Float32Array = LUT.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
const NAN_LINEAR = NAN_RGB.map((c) => ((c + 0.055) / 1.055) ** 2.4) as [number, number, number];

/** 값 → 표 칸(0~255). 범위가 0이면 가운데 칸, NaN이면 -1 */
export function lutIndex(v: number, min: number, max: number): number {
  if (!Number.isFinite(v)) return -1;
  if (!(max > min)) return LUT_SIZE >> 1;
  const t = (v - min) / (max - min);
  return Math.min(LUT_SIZE - 1, Math.max(0, Math.round(t * (LUT_SIZE - 1))));
}

/** 정점 색(RGB Float32 ×3)을 채운다. out 길이 = values.length × 3. linear = three 정점 색용(선형 표) */
export function fillColors(values: ArrayLike<number>, min: number, max: number, out: Float32Array, linear = false): Float32Array {
  const lut = linear ? LUT_LINEAR : LUT;
  const nan = linear ? NAN_LINEAR : NAN_RGB;
  for (let i = 0; i < values.length; i++) {
    const k = lutIndex(values[i], min, max);
    if (k < 0) out.set(nan, i * 3);
    else {
      out[i * 3] = lut[k * 3];
      out[i * 3 + 1] = lut[k * 3 + 1];
      out[i * 3 + 2] = lut[k * 3 + 2];
    }
  }
  return out;
}

/** 범례 CSS 그라데이션(아래 = min, 위 = max) */
export function legendGradient(steps = 9): string {
  const stops: string[] = [];
  for (let i = 0; i < steps; i++) {
    const k = Math.round((i / (steps - 1)) * (LUT_SIZE - 1));
    const [r, g, b] = [LUT[k * 3], LUT[k * 3 + 1], LUT[k * 3 + 2]].map((x) => Math.round(x * 255));
    stops.push(`rgb(${r} ${g} ${b}) ${Math.round((i / (steps - 1)) * 100)}%`);
  }
  return `linear-gradient(to top, ${stops.join(", ")})`;
}

/** 범례 눈금 값(min~max 균등 n개, 위에서 아래 순서) */
export function legendTicks(min: number, max: number, n = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (!(max > min)) return [max];
  return Array.from({ length: n }, (_, i) => max - ((max - min) * i) / (n - 1));
}

/** 범례 숫자(유효 4자리, 큰 수·작은 수는 지수) */
export function fmtLegend(v: number): string {
  if (!Number.isFinite(v)) return "–";
  const a = Math.abs(v);
  if (a !== 0 && (a >= 1e5 || a < 1e-3)) return v.toExponential(2);
  return String(Number(v.toPrecision(4)));
}
