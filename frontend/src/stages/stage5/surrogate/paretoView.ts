// S17 결과 화면 자료(phase3.md §22.10·§22.12, 순수 함수): 서버 상세(pareto·runs·objectives) → 산점도·쌍 그림·파레토 표가 공유하는 점 목록.
// 검증된 해(실제 예측 체인 값)와 대리모델 예측 전선(미검증)을 늘 구분한다(P9). 추천은 검증된 해에서만 고른다.
import type { SurrogateOpt } from "../../../api/surrogateOpt";
import { objectiveDefs, type ObjDef } from "./soRules";
import { frontBounds, normalizeWeights, recommend, scoreOf, type ScoreResult, type Sense } from "./pareto";

export type PtKind = "front" | "dom" | "viol" | "pred";

export interface ParetoPt {
  /** 검증 해 "iter:doe"(서버 front.key와 같은 형식), 예측 점 "p:<index>" */
  key: string;
  kind: PtKind;
  f: number[];
  iter_no: number | null;
  doe_no: number | null;
  values: Record<string, number>;
  /** 가중 점수(전선 기준 lo·hi로 계산 — 예측 점은 0~1 밖일 수 있다). 지배·위반 점은 null */
  score: number | null;
  /** 검증 해: 하위 PREDICT 작업(FEM 검증·단일 예측으로 열기) / 예측 점은 null */
  job_id: string | null;
  batch_label: string | null;
  run_kind: string | null;
  constraints: Record<string, number | null>;
  observed: Record<string, number | null>;
  /** 예측 점: 목적별 표준편차·만족 확률 */
  std?: number[];
  pof?: number;
}

export interface ParetoModel {
  defs: ObjDef[];
  senses: Sense[];
  front: ParetoPt[];
  others: ParetoPt[];
  predicted: ParetoPt[];
  rec: ScoreResult;
  /** 점수 순위(검증 전선만, 1부터) */
  rank: Record<string, number>;
}

const fin = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** u = 슬라이더 가중치(0~100, 목적 순서). 서버 pareto가 없으면(단일 목적·옛 최적화) null */
export function buildParetoModel(o: SurrogateOpt, u: number[]): ParetoModel | null {
  const defs = objectiveDefs(o);
  if (o.mode !== "multi" || !o.pareto || defs.length < 2) return null;
  const senses = defs.map((d) => d.sense);
  const m = defs.length;
  const kindOf = new Map((o.runs ?? []).map((r) => [`${r.iter_no}:${r.doe_no}`, r.kind ?? null]));
  const front: ParetoPt[] = (o.pareto.front ?? []).map((p) => ({
    key: p.key, kind: "front", f: p.objectives, iter_no: p.iter_no, doe_no: p.doe_no, values: p.values, score: null, job_id: p.job_id ?? null,
    batch_label: p.batch_label, run_kind: kindOf.get(p.key) ?? null, constraints: p.constraints ?? {}, observed: p.observed ?? {},
  }));
  const rec = recommend(front.map((p) => ({ key: p.key, f: p.f, iter_no: p.iter_no ?? 0, doe_no: p.doe_no ?? 0 })), senses, u);
  front.forEach((p, i) => (p.score = rec.scores[i]));
  const frontKeys = new Set(front.map((p) => p.key));
  const others: ParetoPt[] = [];
  for (const r of o.runs ?? []) {
    const f = r.objectives ?? [];
    if (f.length < m || !f.every(fin)) continue;
    const key = `${r.iter_no}:${r.doe_no}`;
    if (frontKeys.has(key) || r.on_front) continue;
    others.push({
      key, kind: r.feasible === false ? "viol" : "dom", f: f as number[], iter_no: r.iter_no, doe_no: r.doe_no, values: r.values, score: null,
      job_id: r.job_id ?? null, batch_label: r.batch_label, run_kind: r.kind ?? null, constraints: {}, observed: r.observed ?? {},
    });
  }
  const { lo, hi } = frontBounds(front, m);
  const w = rec.weights.length ? rec.weights : normalizeWeights(u, m);
  const predicted: ParetoPt[] = (o.pareto.predicted ?? []).map((p, i) => ({
    key: `p:${i}`, kind: "pred", f: p.mean, iter_no: null, doe_no: null, values: p.values, std: p.std, pof: p.pof,
    score: front.length ? scoreOf(p.mean, senses, w, lo, hi) : null, job_id: null, batch_label: null, run_kind: null, constraints: {}, observed: {},
  }));
  const order = front.map((p, i) => [i, p.score ?? Infinity] as const).sort((a, b) => a[1] - b[1] || a[0] - b[0]);
  const rank: Record<string, number> = {};
  order.forEach(([i], r) => (rank[front[i].key] = r + 1));
  return { defs, senses, front, others, predicted, rec, rank };
}

/** 저장된 가중치(settings.weights 정규화값 w̄ 또는 0~100) → 슬라이더 초기값 0~100(5 단위 반올림) */
export function initialSliders(o: Pick<SurrogateOpt, "weights" | "settings">, m: number): number[] {
  const w = (o.weights?.length ? o.weights : (o.settings as { weights?: number[] }).weights) ?? [];
  if (w.length !== m || !w.every(fin) || w.reduce((a, b) => a + b, 0) <= 0) return Array.from({ length: m }, () => 50);
  const max = Math.max(...w);
  return w.map((x) => Math.round(((x / max) * 100) / 5) * 5);
}

export const WEIGHTS_KEY = (optId: string) => `physicsai.stage6.weights.${optId}`;

/** localStorage에서 읽기(try/catch, 길이가 다르면 무시) */
export function readWeights(optId: string, m: number): number[] | null {
  try {
    const raw = globalThis.localStorage?.getItem(WEIGHTS_KEY(optId));
    if (!raw) return null;
    const v = JSON.parse(raw) as unknown;
    return Array.isArray(v) && v.length === m && v.every((x) => fin(x) && x >= 0 && x <= 100) ? (v as number[]) : null;
  } catch {
    return null;
  }
}
export function writeWeights(optId: string, v: number[] | null) {
  try {
    if (v) globalThis.localStorage?.setItem(WEIGHTS_KEY(optId), JSON.stringify(v));
    else globalThis.localStorage?.removeItem(WEIGHTS_KEY(optId));
  } catch {
    /* 저장 실패는 무시 */
  }
}

export const SCORE_TIP =
  "가중합 점수 = Σ 가중치 × (전선 안에서 0=최선·1=최악으로 맞춘 목적 값). 가중합은 전선의 오목한 부분의 해를 고를 수 없어 파레토 표에서 직접 고르는 것이 기본입니다.";
export const PRED_NOTE = "대리모델 예측(미검증)";
export const VERIFY_FIRST_TEXT = "먼저 예측 검증";

/** 점 키 → 점(표·그림 공유 선택용) */
export function pointIndex(m: ParetoModel): Map<string, ParetoPt> {
  return new Map([...m.front, ...m.others, ...m.predicted].map((p) => [p.key, p]));
}
