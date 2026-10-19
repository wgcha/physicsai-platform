// S14 영향도(phase3.md §19.6, A5): 순수 함수 — PRCC(순위 편상관)와 표준화 회귀계수(SRC)·R². 새 의존성 없음, linalg.ts는 건드리지 않는다.
// PRCC: 모든 열(변수 + 응답)을 순위(동순위 평균)로 바꾼 뒤, 순위 상관행렬 R의 역행렬 P에서 ρ_j = −P[j][y] / √(P[j][j]·P[y][y]).
// SRC: 변수·응답을 z-점수(ddof=1)로 표준화한 OLS(절편 포함)의 계수 = R_xx⁻¹ r_xy, R² = r_xyᵀ·β. 유의성은 보고하지 않는다(값만).
// 행렬이 특이(공선·n 부족)하면 해당 값은 null("계산 불가"). 상수 변수는 행렬에서 빼고 그 변수만 null.

import { isFin, isOkState, type ResultTable } from "./resultTable";
import { NO_RESP_HINT } from "./perfColumns";

export const SINGULAR_EPS = 1e-10;
export const WEAK_R2 = 0.7;

/** 평균 순위(1부터, 동순위는 평균) */
export function avgRanks(v: number[]): number[] {
  const idx = v.map((x, i) => [x, i] as const).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const out = new Array<number>(v.length);
  let i = 0;
  while (i < idx.length) {
    let j = i;
    while (j + 1 < idx.length && idx[j + 1][0] === idx[i][0]) j++;
    const r = (i + j) / 2 + 1;
    for (let k = i; k <= j; k++) out[idx[k][1]] = r;
    i = j + 1;
  }
  return out;
}

const mean = (v: number[]) => v.reduce((a, b) => a + b, 0) / v.length;

/** 열(길이 n 배열)들의 피어슨 상관행렬. 표준편차 0인 열이 있으면 null */
export function corrMatrix(cols: number[][]): number[][] | null {
  const n = cols[0]?.length ?? 0;
  if (n < 2) return null;
  const cs = cols.map((c) => {
    const m = mean(c);
    const d = c.map((x) => x - m);
    const ss = d.reduce((a, b) => a + b * b, 0);
    return { d, ss };
  });
  if (cs.some((c) => !(c.ss > 0))) return null;
  return cs.map((a) => cs.map((b) => a.d.reduce((s, x, k) => s + x * b.d[k], 0) / Math.sqrt(a.ss * b.ss)));
}

/** Gauss-Jordan(부분 피벗) 역행렬. 피벗 절댓값 < SINGULAR_EPS면 null */
export function invert(M: number[][]): number[][] | null {
  const n = M.length;
  const A = M.map((r, i) => [...r, ...Array.from({ length: n }, (_, j) => (i === j ? 1 : 0))]);
  for (let c = 0; c < n; c++) {
    let p = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
    if (Math.abs(A[p][c]) < SINGULAR_EPS) return null;
    [A[c], A[p]] = [A[p], A[c]];
    const d = A[c][c];
    for (let k = 0; k < 2 * n; k++) A[c][k] /= d;
    for (let r = 0; r < n; r++) {
      if (r === c) continue;
      const f = A[r][c];
      if (f !== 0) for (let k = 0; k < 2 * n; k++) A[r][k] -= f * A[c][k];
    }
  }
  return A.map((r) => r.slice(n));
}

export interface InfluenceResult {
  n: number;
  names: string[];
  prcc: (number | null)[];
  src: (number | null)[];
  r2: number | null;
  /** 계산 자체를 못 하는 사유(n < p+2, 응답 상수 …). 있으면 prcc·src는 전부 null */
  unavailable: string | null;
}

/** 열(변수) 선택 후 PRCC·SRC 계산. cols[j] = 변수 j의 값(길이 n), y = 응답 */
export function computeInfluence(names: string[], cols: number[][], y: number[]): InfluenceResult {
  const n = y.length;
  const p = names.length;
  const none = (why: string): InfluenceResult => ({ n, names, prcc: names.map(() => null), src: names.map(() => null), r2: null, unavailable: why });
  if (n < p + 2) return none(`유효 run이 부족합니다(n ${n} < 변수 ${p} + 2)`);
  if (!(Math.max(...y) > Math.min(...y))) return none("응답 값이 모두 같아 계산할 수 없습니다");
  const live = cols.map((c, j) => (Math.max(...c) > Math.min(...c) ? j : -1)).filter((j) => j >= 0);
  const prcc: (number | null)[] = names.map(() => null);
  const src: (number | null)[] = names.map(() => null);
  let r2: number | null = null;
  if (live.length) {
    // PRCC — 순위 상관행렬의 역행렬
    const rk = [...live.map((j) => avgRanks(cols[j])), avgRanks(y)];
    const R = corrMatrix(rk);
    const P = R && invert(R);
    if (P) {
      const iy = live.length;
      live.forEach((j, a) => {
        const d = P[a][a] * P[iy][iy];
        prcc[j] = d > 0 ? -P[a][iy] / Math.sqrt(d) : null;
      });
    }
    // SRC — 표준화 OLS: β = R_xx⁻¹ r_xy
    const C = corrMatrix([...live.map((j) => cols[j]), y]);
    if (C) {
      const k = live.length;
      const Rxx = C.slice(0, k).map((r) => r.slice(0, k));
      const rxy = C.slice(0, k).map((r) => r[k]);
      const inv = invert(Rxx);
      if (inv) {
        const beta = inv.map((row) => row.reduce((s, v, i) => s + v * rxy[i], 0));
        live.forEach((j, a) => (src[j] = beta[a]));
        r2 = beta.reduce((s, b, i) => s + b * rxy[i], 0);
      }
    }
  }
  return { n, names, prcc, src, r2, unavailable: null };
}

export interface InfluenceRow {
  name: string;
  prcc: number | null;
  src: number | null;
  /** PRCC와 SRC 부호가 다름 */
  mismatch: boolean;
}

/** |PRCC| 내림차순(계산 불가는 뒤, 같으면 원래 순서) */
export function influenceRows(r: InfluenceResult): InfluenceRow[] {
  return r.names
    .map((name, i) => ({ name, prcc: r.prcc[i], src: r.src[i], i }))
    .sort((a, b) => (a.prcc === null ? 1 : 0) - (b.prcc === null ? 1 : 0) || Math.abs(b.prcc ?? 0) - Math.abs(a.prcc ?? 0) || a.i - b.i)
    .map(({ i: _i, ...x }) => ({ ...x, mismatch: x.prcc !== null && x.src !== null && Math.sign(x.prcc) !== Math.sign(x.src) && x.prcc !== 0 && x.src !== 0 }));
}

export const WEAK_R2_TEXT = "선형 근사가 약합니다 — PRCC·지도를 함께 보세요";
export const MISMATCH_TEXT = (names: string[]) => `부호 불일치: ${names.join(", ")}`;

// ---- 결과 표 → 영향도 보기(화면 규칙) ---------------------------------------------------------------

/** 서버가 알려 주지 않을 때만 쓰는 대체 문구(문구 본문은 서버 influence_note — S15 §20.7) */
export const UNKNOWN_METHOD_TEXT = "표본 방식을 알 수 없어 영향도는 참고용입니다";
export const OFF_FALLBACK_TEXT = "영향도를 계산할 수 없습니다";

export interface InfluenceView {
  /** 비활성 사유(있으면 표를 그리지 않는다) */
  disabled: string | null;
  /** 참고용 방식(reference)의 회색 안내 한 줄(정식이면 null) */
  note: string | null;
  result: InfluenceResult | null;
  rows: InfluenceRow[];
  mismatch: string[];
  weak: boolean;
}

/** 색 값(응답) 1개의 영향도. 사용 조건: 출처 (b) 서버 등급 ≠ off, 출처 (a) 유효 run ≥ max(5, p+2)(§19.6, §20.7) */
export function influenceFor(rt: ResultTable, resp: string | null): InfluenceView {
  const off = (disabled: string): InfluenceView => ({ disabled, note: null, result: null, rows: [], mismatch: [], weak: false });
  if (rt.source === "solver" && !rt.influence.ok) return off(rt.influence.reason ?? OFF_FALLBACK_TEXT);
  // S17 D3-65 보강 2: 일괄 예측 출처에서 응답 열이 모두 비면 사유에 안내를 덧붙인다
  const hint = rt.source === "predict" && !rt.responses.some((x) => rt.rows.some((r) => isFin(r.responses[x.name]))) ? ` — ${NO_RESP_HINT}` : "";
  if (!resp) return off(`응답이 없어 영향도를 계산할 수 없습니다${hint}`);
  const names = rt.parameters.map((p) => p.name);
  const use = rt.rows.filter((r) => isOkState(r.state) && isFin(r.responses[resp]) && names.every((n) => isFin(r.params[n])));
  const need = Math.max(5, names.length + 2);
  if (use.length < need) return off(`영향도에는 유효 run이 ${need}개 이상 필요합니다(현재 ${use.length}개)${hint}`);
  const result = computeInfluence(names, names.map((n) => use.map((r) => r.params[n] as number)), use.map((r) => r.responses[resp] as number));
  if (result.unavailable) return off(result.unavailable);
  const rows = influenceRows(result);
  return { disabled: null, note: rt.influence.cls === "reference" ? rt.influence.note : null, result, rows, mismatch: rows.filter((r) => r.mismatch).map((r) => r.name), weak: result.r2 !== null && result.r2 < WEAK_R2 };
}
