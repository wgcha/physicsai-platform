// S12 연속 색지도(phase3.md §17.6): viridis 9점 보간, 다크·라이트 공통(밝기 단조 — 두 테마 바탕 모두에서 구분).
export const VIRIDIS = ["#440154", "#472d7b", "#3b528b", "#2c728e", "#21918c", "#28ae80", "#5ec962", "#addc30", "#fde725"];

function rgb(hex: string): [number, number, number] {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number];
}

function hex2(v: number): string {
  return Math.round(Math.min(255, Math.max(0, v)))
    .toString(16)
    .padStart(2, "0");
}

/** t ∈ [0,1] → 색(#rrggbb). 범위 밖·NaN은 끝으로 자른다 */
export function viridis(t: number): string {
  const x = Number.isFinite(t) ? Math.min(1, Math.max(0, t)) : 0;
  const f = x * (VIRIDIS.length - 1);
  const i = Math.min(VIRIDIS.length - 2, Math.floor(f));
  const u = f - i;
  const a = rgb(VIRIDIS[i]);
  const b = rgb(VIRIDIS[i + 1]);
  return `#${hex2(a[0] + (b[0] - a[0]) * u)}${hex2(a[1] + (b[1] - a[1]) * u)}${hex2(a[2] + (b[2] - a[2]) * u)}`;
}

/** 값 → 색. 최소 = 최대(값 전부 같음)면 색 1개(중간색) */
export function colorScale(min: number, max: number): (v: number) => string {
  if (!(max > min)) return () => viridis(0.5);
  return (v) => viridis((v - min) / (max - min));
}
