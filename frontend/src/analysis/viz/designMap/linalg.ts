// S12 설계공간 지도 수학(phase3.md §17.5, D3-59) — 순수 함수, 새 라이브러리 없음.
// 표준화(z-점수, ddof=1) · 대칭 Jacobi 고유분해 · PCA(상관행렬) · PLS1 NIPALS 2성분 · 구조 상관(바이플롯 화살표).
// 행렬은 행 우선 number[][] (n 행 × p 열). n ≤ 200, p ≤ ~20이라 단순 루프로 충분(1 ms 수준).

export type Mat = number[][];

export function mean(a: number[]): number {
  let s = 0;
  for (const v of a) s += v;
  return a.length ? s / a.length : NaN;
}

/** 표본 표준편차(ddof=1) */
export function sd(a: number[]): number {
  if (a.length < 2) return 0;
  const m = mean(a);
  let s = 0;
  for (const v of a) s += (v - m) * (v - m);
  return Math.sqrt(s / (a.length - 1));
}

export function corr(a: number[], b: number[]): number {
  const ma = mean(a);
  const mb = mean(b);
  let sab = 0;
  let saa = 0;
  let sbb = 0;
  for (let i = 0; i < a.length; i++) {
    const x = a[i] - ma;
    const y = b[i] - mb;
    sab += x * y;
    saa += x * x;
    sbb += y * y;
  }
  return saa > 0 && sbb > 0 ? sab / Math.sqrt(saa * sbb) : 0;
}

export function column(X: Mat, j: number): number[] {
  return X.map((r) => r[j]);
}

/** z-점수: 1개 벡터 (평균 0·표준편차 1, ddof=1). 표준편차 0이면 0 벡터 */
export function zscore(a: number[]): { z: number[]; mean: number; sd: number } {
  const m = mean(a);
  const s = sd(a);
  return { z: a.map((v) => (s > 0 ? (v - m) / s : 0)), mean: m, sd: s };
}

/** 열마다 z-점수 */
export function standardize(X: Mat): { Z: Mat; mean: number[]; sd: number[] } {
  const p = X[0]?.length ?? 0;
  const cols = Array.from({ length: p }, (_, j) => zscore(column(X, j)));
  return { Z: X.map((_, i) => cols.map((c) => c.z[i])), mean: cols.map((c) => c.mean), sd: cols.map((c) => c.sd) };
}

/** 대칭 행렬 고유분해(순환 Jacobi). values 내림차순, vectors[j][c] = c번째 고유벡터의 j 성분(열 = 고유벡터) */
export function jacobiEigen(A: Mat, tol = 1e-12, maxSweeps = 100): { values: number[]; vectors: Mat; sweeps: number } {
  const n = A.length;
  const a = A.map((r) => [...r]);
  const v: Mat = Array.from({ length: n }, (_, i) => Array.from({ length: n }, (_, j) => (i === j ? 1 : 0)));
  let sweeps = 0;
  for (; sweeps < maxSweeps; sweeps++) {
    let off = 0;
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) off += a[i][j] * a[i][j];
    if (Math.sqrt(off) < tol) break;
    for (let p = 0; p < n - 1; p++) {
      for (let q = p + 1; q < n; q++) {
        const apq = a[p][q];
        if (Math.abs(apq) < 1e-300) continue;
        const theta = (a[q][q] - a[p][p]) / (2 * apq);
        const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
        const c = 1 / Math.sqrt(t * t + 1);
        const s = t * c;
        for (let k = 0; k < n; k++) {
          const akp = a[k][p];
          const akq = a[k][q];
          a[k][p] = c * akp - s * akq;
          a[k][q] = s * akp + c * akq;
        }
        for (let k = 0; k < n; k++) {
          const apk = a[p][k];
          const aqk = a[q][k];
          a[p][k] = c * apk - s * aqk;
          a[q][k] = s * apk + c * aqk;
        }
        for (let k = 0; k < n; k++) {
          const vkp = v[k][p];
          const vkq = v[k][q];
          v[k][p] = c * vkp - s * vkq;
          v[k][q] = s * vkp + c * vkq;
        }
      }
    }
  }
  const order = Array.from({ length: n }, (_, i) => i).sort((i, j) => a[j][j] - a[i][i]);
  return { values: order.map((i) => a[i][i]), vectors: v.map((row) => order.map((i) => row[i])), sweeps };
}

/** 벡터의 |최대| 성분이 음수면 -1(부호 규칙). 동률이면 앞 성분 */
function signOfMaxAbs(vec: number[]): number {
  let k = 0;
  for (let j = 1; j < vec.length; j++) if (Math.abs(vec[j]) > Math.abs(vec[k])) k = j;
  return vec[k] < 0 ? -1 : 1;
}

export interface PcaResult {
  /** n × k 점수 */
  scores: Mat;
  /** 고유값 전부(내림차순) */
  eigenvalues: number[];
  /** p × k 고유벡터(열) */
  vectors: Mat;
  /** 성분별 X 분산 % = λ_c / p × 100 */
  pct: number[];
}

/** PCA(상관행렬 R = ZᵀZ/(n−1)). Z는 표준화된 자료. 부호: 고유벡터마다 |최대| 성분 양수 */
export function pca(Z: Mat, k = 2): PcaResult {
  const n = Z.length;
  const p = Z[0]?.length ?? 0;
  const R: Mat = Array.from({ length: p }, () => new Array<number>(p).fill(0));
  for (let i = 0; i < p; i++)
    for (let j = i; j < p; j++) {
      let s = 0;
      for (let r = 0; r < n; r++) s += Z[r][i] * Z[r][j];
      R[i][j] = R[j][i] = s / (n - 1);
    }
  const eig = jacobiEigen(R);
  const kk = Math.min(k, p);
  const vectors: Mat = Array.from({ length: p }, () => new Array<number>(kk).fill(0));
  for (let c = 0; c < kk; c++) {
    const vec = eig.vectors.map((row) => row[c]);
    const sg = signOfMaxAbs(vec);
    vec.forEach((x, j) => (vectors[j][c] = sg * x));
  }
  const scores = Z.map((row) => Array.from({ length: kk }, (_, c) => row.reduce((s, z, j) => s + z * vectors[j][c], 0)));
  return { scores, eigenvalues: eig.values, vectors, pct: eig.values.slice(0, kk).map((l) => (l / p) * 100) };
}

export interface PlsResult {
  /** n × ncomp 점수 t */
  scores: Mat;
  /** p × ncomp 가중치 w */
  weights: Mat;
  /** p × ncomp X 적재 p */
  xLoadings: Mat;
  q: number[];
  /** 성분이 설명한 표준화 변수 분산 % = tᵀt·‖p‖² / ‖Z₀‖²_F × 100 */
  xPct: number[];
  /** 성분이 설명한 값 분산 % = q²·tᵀt / ‖y₀‖² × 100 */
  yPct: number[];
  ncomp: number;
  /** 요청한 성분 수보다 적게 나옴(두 번째 성분 ‖Zcᵀyc‖ < 1e-10·첫 성분) */
  short: boolean;
}

/** PLS1 NIPALS. Z·y는 표준화된 자료, a = 성분 수. 부호: corr(t_c, y) ≥ 0(0이면 |w| 최대 성분 양수) */
export function plsNipals(Z: Mat, y: number[], a: number): PlsResult {
  const n = Z.length;
  const p = Z[0]?.length ?? 0;
  let Zc = Z.map((r) => [...r]);
  let yc = [...y];
  const zF = Z.reduce((s, r) => s + r.reduce((t, v) => t + v * v, 0), 0);
  const yF = y.reduce((s, v) => s + v * v, 0);
  const T: number[][] = [];
  const W: number[][] = [];
  const P: number[][] = [];
  const q: number[] = [];
  const xPct: number[] = [];
  const yPct: number[] = [];
  let norm0 = 0;
  let short = false;
  for (let c = 0; c < a; c++) {
    const v = Array.from({ length: p }, (_, j) => Zc.reduce((s, r, i) => s + r[j] * yc[i], 0));
    const norm = Math.sqrt(v.reduce((s, x) => s + x * x, 0));
    if (c === 0) norm0 = norm;
    if (!(norm > 0) || (c > 0 && norm < 1e-10 * norm0)) {
      short = true;
      break;
    }
    let w = v.map((x) => x / norm);
    let t = Zc.map((r) => r.reduce((s, z, j) => s + z * w[j], 0));
    const tt = t.reduce((s, x) => s + x * x, 0);
    let pv = Array.from({ length: p }, (_, j) => Zc.reduce((s, r, i) => s + r[j] * t[i], 0) / tt);
    let qc = yc.reduce((s, yv, i) => s + yv * t[i], 0) / tt;
    const r = corr(t, y);
    const flip = Math.abs(r) > 1e-12 ? r < 0 : signOfMaxAbs(w) < 0;
    if (flip) {
      w = w.map((x) => -x);
      t = t.map((x) => -x);
      pv = pv.map((x) => -x);
      qc = -qc;
    }
    T.push(t);
    W.push(w);
    P.push(pv);
    q.push(qc);
    xPct.push(((tt * pv.reduce((s, x) => s + x * x, 0)) / zF) * 100);
    yPct.push(((qc * qc * tt) / yF) * 100);
    Zc = Zc.map((row, i) => row.map((z, j) => z - t[i] * pv[j]));
    yc = yc.map((yv, i) => yv - qc * t[i]);
  }
  const k = T.length;
  return {
    scores: Array.from({ length: n }, (_, i) => T.map((t) => t[i])),
    weights: Array.from({ length: p }, (_, j) => W.map((w) => w[j])),
    xLoadings: Array.from({ length: p }, (_, j) => P.map((pv) => pv[j])),
    q,
    xPct,
    yPct,
    ncomp: k,
    short,
  };
}

/** 바이플롯 화살표(구조 상관): 변수 j마다 (corr(z_j, t₁)·s₁, corr(z_j, t₂)·s₂), s_c = 0.9·max|t_c| */
export function structureArrows(Z: Mat, scores: Mat): [number, number][] {
  const p = Z[0]?.length ?? 0;
  const t1 = column(scores, 0);
  const t2 = column(scores, 1);
  const s1 = 0.9 * Math.max(...t1.map(Math.abs));
  const s2 = 0.9 * Math.max(...t2.map(Math.abs));
  return Array.from({ length: p }, (_, j) => {
    const zj = column(Z, j);
    return [corr(zj, t1) * s1, corr(zj, t2) * s2];
  });
}
