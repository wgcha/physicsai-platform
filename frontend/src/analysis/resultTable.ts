// S14 결과 표(phase3.md §19.4, D3-62): ⑤ 결과분석의 공통 입력. 출처 둘 — solver(① 해석 DOE)·predict(④ 일괄 예측 배치) — 을 같은 모양으로 변환해
// 같은 분석 컴포넌트(analysis/viz)에 넣는다. 변환은 adapters/fromBatch.ts·fromDoe.ts. 순수 타입·함수만(React 없음).
import type { DesignMap, DesignMapCurveStats } from "../api/designMap";

export type TableSource = "solver" | "predict";

export interface RtParameter {
  name: string;
  integer: boolean;
  /** 모르면 null(표의 최솟값·최댓값으로 대체) */
  min: number | null;
  max: number | null;
  unit: string | null;
}
export interface RtResponse {
  name: string;
  unit: string | null;
}
export interface RtRow {
  /** 출처의 run_key(run__00014) */
  run_id: string;
  /** doe_no / run 번호 — 화면 선택 모델 `selected`의 값 */
  no: number;
  state: string;
  params: Record<string, number | null>;
  /** 없음·실패·비유한 = null */
  responses: Record<string, number | null>;
  /** predict 출처만(design-map 요약), solver는 null */
  curve: Record<string, DesignMapCurveStats> | null;
}
export interface RtMeta {
  engine_version: string | null;
  baseline_id: string | null;
  scene: string | null;
}
export interface RtCounts {
  total: number;
  usable: number;
  no_response: number;
}
export interface ResultTable {
  source: TableSource;
  origin: { kind: "train_doe" | "predict_batch"; id: string; label: string };
  parameters: RtParameter[];
  responses: RtResponse[];
  meta: RtMeta;
  rows: RtRow[];
  counts: RtCounts;
  /** 영향도(PRCC·SRC) 사용 가능 여부와 사유 — 출처별 규칙은 influenceGate */
  influence: { ok: boolean; lhs: boolean; reason: string | null };
  /** 한국어 안내(예: "응답 파일이 없습니다") */
  notes: string[];
  /** predict 출처만: GET …/design-map 원본(§17.2 지표 전체 보존 — 단독 보기의 색 값 목록) */
  designMap?: DesignMap | null;
}

export const NO_META: RtMeta = { engine_version: null, baseline_id: null, scene: null };

/** 분석에 쓸 수 있는 run 상태: predict = SUCCEEDED, solver = 해석 완료(SOLVED)·결과 수집(COLLECTED) 또는 SUCCEEDED(서버가 정규화한 경우) */
export const OK_STATES = ["SUCCEEDED", "SOLVED", "COLLECTED"];
export const isOkState = (s: string) => OK_STATES.includes(s);

export const isFin = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** 유한 수만, 아니면 null */
export const finOrNull = (v: unknown): number | null => (isFin(v) ? v : null);

/** 응답 값이 있는 행으로 만든 그래프 점(변수 반영값 전부 유한한 행만) */
export function tablePlotPoints(rt: ResultTable, vars: string[], resp: string) {
  const out: { doe_no: number; run_key: string; v: number[]; r: number }[] = [];
  for (const row of rt.rows) {
    const r = row.responses[resp];
    if (!isFin(r) || !isOkState(row.state)) continue;
    const v = vars.map((n) => row.params[n]);
    if (v.some((x) => !isFin(x))) continue;
    out.push({ doe_no: row.no, run_key: row.run_id, v: v as number[], r });
  }
  return out;
}

/** 파라미터 min·max가 null이면 표 값의 최솟값·최댓값으로 */
export function paramRange(rt: ResultTable, name: string): [number, number] | null {
  const p = rt.parameters.find((x) => x.name === name);
  if (p && isFin(p.min) && isFin(p.max)) return [p.min, p.max];
  const vs = rt.rows.map((r) => r.params[name]).filter(isFin);
  return vs.length ? [Math.min(...vs), Math.max(...vs)] : null;
}

export function usableRowCount(rt: ResultTable, resp: string | null): number {
  if (!resp) return 0;
  return rt.rows.filter((r) => isOkState(r.state) && isFin(r.responses[resp]) && rt.parameters.every((p) => isFin(r.params[p.name]))).length;
}
