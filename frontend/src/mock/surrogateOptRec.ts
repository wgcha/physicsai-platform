// phase3.md §18 S13·§22 S17 목(R-F 분할): 최적화 기록(SoRec)·설정 타입·라벨·공용 헬퍼.
import type { SoIteration, SoRun, SurrogateOpt } from "../api/surrogateOpt";

export interface Obj { metric: string; series: string | null; sense: "min" | "max" }
export interface Cons { metric: string; series: string | null; op: "<=" | ">=" | "range"; value?: number | null; lo?: number | null; hi?: number | null }
export interface Obs { metric: string; series: string | null }
interface ExtraRec { iter_no: number; points: Record<string, number>[]; capture: boolean; ticks: number }

export interface SoRec {
  id: string;
  study_id: string;
  opt_no: number;
  param_set_id: string;
  settings: Record<string, unknown> & {
    names: string[]; integer: string[]; bounds: Record<string, [number, number]>;
    objective: Obj;
    objectives: Obj[];
    constraints: Cons[];
    observe: Obs[];
    weights: number[];
    mode: "single" | "multi";
    performances: Record<string, { unit: string; spec: unknown }>;
    surrogate: string; iterations: number; candidates: number; tol_rel: number; seed: number; multi_execution: number; capture: boolean;
    explore: { kind: "new"; count: number; seed: number } | { kind: "reuse"; batch_id: string };
    algorithm?: string; verification?: string; algo_options?: Record<string, number | null>;
  };
  status: string;
  iter_no: number;
  iters: SoIteration[];
  runs: SoRun[];
  stop_reason: string | null;
  created_by: string;
  created_by_name: string;
  created_at: string;
  finished_at: string | null;
  batch_no: number;
  /** D3-61 마무리 캡처 */
  final?: SurrogateOpt["final"];
  /** S17 HV 정규화 틀(반복 0 자료로 고정) */
  frame?: { ideal: number[]; nadir: number[] };
  /** S17 추가 검증(EXTRA) 진행 */
  extra?: ExtraRec | null;
}

export const soLabel = (n: number) => `SO-${String(n).padStart(3, "0")}`;
export const ACTIVE = ["EXPLORING", "FITTING", "VERIFYING", "FINALIZING"];
export const fin = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** 지표 값(목 함수). perf:NAME = 템플릿 응답 이름(없으면 가속도 흉내 — 두께가 클수록 커져 응력과 상충) */
