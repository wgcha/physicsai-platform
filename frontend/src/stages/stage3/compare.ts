// ③-5 모델 비교 순수 함수(phase3.md §4.3). React·API 의존 없음 — 단위 시험 대상.
import type { Model } from "../../api";

export type Direction = "lower" | "higher";
export const MAX_COMPARE = 5;
export const MIN_COMPARE = 2;

export interface MetricRow {
  key: string;
  label: string;
  /** loss 행은 낮을수록 좋음 고정, metric 행은 사용자가 방향을 바꿀 수 있다 */
  kind: "loss" | "metric";
  values: (number | null)[];
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** 평가 점수를 비교에 쓸 수 있는 모델인지(평가 완료 + 점수 형식 확인) */
function usableMetrics(m: Model | null): Record<string, number> | null {
  if (!m || m.eval_status !== "DONE" || !m.eval_score || m.eval_score.status !== "PARSED") return null;
  return m.eval_score.metrics ?? null;
}

/** 행 = 최종 loss, 최소 loss, 그 뒤 metrics 키 합집합(사전순). 열 = models 순서(null은 찾을 수 없는 모델). */
export function metricRows(models: (Model | null)[]): MetricRow[] {
  const keys = new Set<string>();
  for (const m of models) for (const k of Object.keys(usableMetrics(m) ?? {})) keys.add(k);
  const metricKeys = [...keys].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  return [
    { key: "final_loss", label: "최종 loss", kind: "loss", values: models.map((m) => num(m?.final_loss)) },
    { key: "min_loss", label: "최소 loss", kind: "loss", values: models.map((m) => num(m?.min_loss)) },
    ...metricKeys.map((k): MetricRow => ({ key: k, label: k, kind: "metric", values: models.map((m) => num(usableMetrics(m)?.[k])) })),
  ];
}

/** 최고값 위치(동률이면 모두). 유효한 값이 1개 이하면 강조하지 않는다. */
export function bestIndices(values: (number | null | undefined)[], direction: Direction): number[] {
  const valid = values.map((v, i) => [num(v), i] as const).filter((p): p is readonly [number, number] => p[0] !== null);
  if (valid.length <= 1) return [];
  const best = direction === "lower" ? Math.min(...valid.map((p) => p[0])) : Math.max(...valid.map((p) => p[0]));
  return valid.filter((p) => p[0] === best).map((p) => p[1]);
}

/** 열 머리 상태 문구(평가 전·평가 중·평가 실패·점수 형식 미확인). 정상이면 null. */
export function evalStatusText(m: Model): string | null {
  if (m.eval_status === "NONE") return "평가 전";
  if (m.eval_status === "RUNNING") return "평가 중";
  if (m.eval_status === "FAILED") return "평가 실패";
  if (m.eval_score?.status === "UNRECOGNIZED") return "점수 형식 미확인";
  return null;
}

export function modelLegend(m: Pick<Model, "name" | "version" | "label">): string {
  return `${m.name} v${m.version}${m.label ? ` (${m.label})` : ""}`;
}

export interface CompareSeries {
  id: string;
  /** 범례·접근성 이름 */
  name: string;
  /** 1~5 — CSS `--series-n` */
  color: number;
  pts: [number, number][];
  min: { x: number; y: number } | null;
}

function curveOf(m: Model): [number, number][] {
  return (m.loss_curve ?? []).filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
}

/** 선택 순서대로 색 번호를 붙인다(곡선 없는 모델도 번호를 차지해 표 열과 색이 맞는다). 곡선 없는 모델은 pts=[]. */
export function seriesFor(models: (Model | null)[]): (CompareSeries | null)[] {
  return models.map((m, i) => {
    if (!m) return null;
    const pts = curveOf(m);
    let min: CompareSeries["min"] = null;
    if (pts.length) {
      if (num(m.min_loss) !== null && num(m.min_loss_epoch) !== null) min = { x: m.min_loss_epoch!, y: m.min_loss! };
      else {
        const p = pts.reduce((a, b) => (b[1] < a[1] ? b : a));
        min = { x: p[0], y: p[1] };
      }
    }
    return { id: m.id, name: modelLegend(m), color: (i % MAX_COMPARE) + 1, pts, min };
  });
}

/** 곡선에 0 이하 loss가 하나라도 있으면 로그 축을 쓸 수 없다 */
export function canUseLog(models: (Model | null)[]): boolean {
  return models.every((m) => !m || curveOf(m).every(([, y]) => y > 0));
}

/** 서로 다른 dataset_id(첫 등장 순서) */
export function distinctDatasetIds(models: (Model | null)[]): string[] {
  return [...new Set(models.map((m) => m?.dataset_id).filter((d): d is string => !!d))];
}

/** 선택 토글: 선택 순서 유지, 최대 5개 */
export function toggleSelection(sel: string[], id: string): string[] {
  if (sel.includes(id)) return sel.filter((x) => x !== id);
  return sel.length >= MAX_COMPARE ? sel : [...sel, id];
}

/** 로컬 날짜·시각 "YYYY-MM-DD HH:MM" */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function epochText(m: Pick<Model, "last_epoch" | "epochs_total">): string {
  if (m.last_epoch == null && m.epochs_total == null) return "—";
  return `${m.last_epoch ?? "—"}/${m.epochs_total ?? "—"}`;
}

// 지표 방향 기억(A3-4): 지표 이름별 localStorage, 접근 실패해도 기본값으로 동작
const dirKey = (name: string) => `physicsai.metricDirection.${name}`;

export function loadDirection(name: string): Direction {
  try {
    return globalThis.localStorage?.getItem(dirKey(name)) === "higher" ? "higher" : "lower";
  } catch {
    return "lower";
  }
}

export function saveDirection(name: string, d: Direction): void {
  try {
    globalThis.localStorage?.setItem(dirKey(name), d);
  } catch {
    /* 저장 불가(사생활 모드 등) — 이번 화면에서만 유지 */
  }
}
