// S17 가중 추천·비지배 판정(phase3.md §22.6, 순수 함수 — 서버 pareto.recommend와 같은 식, 골든 backend/tests/data/s17_recommend.json).
// 화면 슬라이더가 바뀔 때마다 서버 왕복 없이 여기서 계산한다. 값은 모두 원 단위(f), 방향은 목적마다 min|max.
export type Sense = "min" | "max";

export interface FrontPoint {
  key: string;
  /** 목적 값(원 단위, 목적 순서) */
  f: number[];
  iter_no?: number;
  doe_no?: number;
}

export interface ScoreResult {
  /** 입력 점 순서대로 가중합 점수 S_j */
  scores: number[];
  /** 점수 최소 점의 인덱스(동점 규칙 적용), 대상이 없으면 -1 */
  index: number;
  key: string | null;
  /** 정규화 가중치 w̄ */
  weights: number[];
}

const EPS = 1e-12;

/** 1. w̄_i = u_i/Σu, Σu = 0(또는 비유한)이면 균등 */
export function normalizeWeights(u: number[], m = u.length): number[] {
  const clean = Array.from({ length: m }, (_, i) => (Number.isFinite(u[i]) && u[i] > 0 ? u[i] : 0));
  const sum = clean.reduce((a, b) => a + b, 0);
  return sum > 0 ? clean.map((x) => x / sum) : Array.from({ length: m }, () => 1 / Math.max(1, m));
}

/** 2. 기준 전선 F 안의 목적별 lo·hi */
export function frontBounds(front: { f: number[] }[], m: number): { lo: number[]; hi: number[] } {
  const lo = Array.from({ length: m }, () => Infinity);
  const hi = Array.from({ length: m }, () => -Infinity);
  for (const p of front) {
    for (let i = 0; i < m; i++) {
      const v = p.f[i];
      if (!Number.isFinite(v)) continue;
      if (v < lo[i]) lo[i] = v;
      if (v > hi[i]) hi[i] = v;
    }
  }
  return { lo, hi };
}

/** g = 0(전선 내 최선) … 1(최악). 전선 폭이 사실상 0이면 0. 전선 밖(예측 점)은 0~1을 넘을 수 있다 */
export function goodness(f: number[], senses: Sense[], lo: number[], hi: number[]): number[] {
  return senses.map((s, i) => {
    const span = hi[i] - lo[i];
    if (!Number.isFinite(span) || span <= EPS * Math.max(1, Math.abs(lo[i]))) return 0;
    return s === "max" ? (hi[i] - f[i]) / span : (f[i] - lo[i]) / span;
  });
}

/** 3. S = Σ w̄_i·g_i (lo·hi는 검증 전선 기준) */
export function scoreOf(f: number[], senses: Sense[], w: number[], lo: number[], hi: number[]): number {
  const g = goodness(f, senses, lo, hi);
  return g.reduce((a, gi, i) => a + w[i] * gi, 0);
}

/**
 * 가중 추천(§22.6): front = 검증된 파레토 해. 추천 = argmin S.
 * 4. 동점(|ΔS| ≤ 1e-12)은 g₁이 작은 쪽 → (iter_no, doe_no) 작은 쪽.
 */
export function recommend(front: FrontPoint[], senses: Sense[], u: number[]): ScoreResult {
  const m = senses.length;
  const weights = normalizeWeights(u, m);
  const { lo, hi } = frontBounds(front, m);
  const scores = front.map((p) => scoreOf(p.f, senses, weights, lo, hi));
  let best = -1;
  for (let j = 0; j < front.length; j++) {
    if (best < 0) {
      best = j;
      continue;
    }
    const d = scores[j] - scores[best];
    if (d < -EPS) best = j;
    else if (Math.abs(d) <= EPS) {
      const gj = goodness(front[j].f, senses, lo, hi)[0] ?? 0;
      const gb = goodness(front[best].f, senses, lo, hi)[0] ?? 0;
      if (gj < gb - EPS) best = j;
      else if (Math.abs(gj - gb) <= EPS) {
        const a = [front[j].iter_no ?? 0, front[j].doe_no ?? 0];
        const b = [front[best].iter_no ?? 0, front[best].doe_no ?? 0];
        if (a[0] < b[0] || (a[0] === b[0] && a[1] < b[1])) best = j;
      }
    }
  }
  return { scores, index: best, key: best >= 0 ? front[best].key : null, weights };
}

/** a가 b를 지배(모든 목적에서 같거나 낫고 하나는 더 낫다) */
export function dominates(a: number[], b: number[], senses: Sense[]): boolean {
  let better = false;
  for (let i = 0; i < senses.length; i++) {
    const x = senses[i] === "max" ? -a[i] : a[i];
    const y = senses[i] === "max" ? -b[i] : b[i];
    if (x > y) return false;
    if (x < y) better = true;
  }
  return better;
}

/** 비지배 점의 인덱스 집합(같은 벡터는 앞 인덱스만 남긴다 — 서버 pareto.py와 같은 규칙, 입력 순서 유지) */
export function nonDominated(points: number[][], senses: Sense[]): number[] {
  const out: number[] = [];
  points.forEach((p, i) => {
    const dominated = points.some((q, j) => j !== i && (dominates(q, p, senses) || (j < i && q.every((v, k) => v === p[k]))));
    if (!dominated) out.push(i);
  });
  return out;
}
