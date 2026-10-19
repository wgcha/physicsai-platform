// ⑤ 플랫폼 내장 최적화 API(phase3.md §18.6 S13) — 타입 + 요청 함수. api/index.ts·endpoints.ts는 고치지 않는다(§18.13).
// 재사용 배치의 지표 목록은 S12 `api/designMap.ts`(GET /predict-batches/{bid}/design-map, §17.4)의 metrics·series를 읽기만 한다.
import { fetchBlob, request } from "./client";
export type { DesignMap, DesignMapMetric } from "./designMap";
import type { components } from "./generated/schema";

type S = components["schemas"];

export type SurrogateOptCreate = S["SurrogateOptCreate"];
export type SurrogateOptPreview = S["SurrogateOptPreview"];
export type SurrogateOptSummary = S["SurrogateOptSummary"];
export type SurrogateOpt = S["SurrogateOpt"];
export type SoIteration = S["SoIteration"];
export type SoRun = S["SoRun"];
export type SoBest = S["SoBest"];
export type SoFit = S["SoFit"];
export type SoCandidate = S["SoCandidate"];
export type SurrogateOptResume = S["SurrogateOptResume"];
export type SoFinal = S["SoFinal"];
export type SoFinalRun = S["SoFinalRun"];
export type SoParameter = S["SoParameter"];
export type SoConstraint = S["SoConstraint"];
export type SoObjective = S["SoObjective"];
export type SoObserve = S["SoObserve"];
export type SoObjectiveDef = S["SoObjectiveDef"];
export type SoConstraintDef = S["SoConstraintDef"];
export type SoObserveDef = S["SoObserveDef"];
export type SoPareto = S["SoPareto"];
export type SoFrontPoint = S["SoFrontPoint"];
export type SoPredictedPoint = S["SoPredictedPoint"];
export type SoHvPoint = S["SoHvPoint"];
export type SoPerformance = S["SoPerformance"];
export type SoProblem = S["SoProblem"];
export type SurrogateOptVerify = S["SurrogateOptVerify"];
export type SurrogateOptVerifyResult = S["SurrogateOptVerifyResult"];
export type SoStatus = "EXPLORING" | "FITTING" | "VERIFYING" | "FINALIZING" | "DONE" | "FAILED" | "CANCELED";

export const surrogateApi = {
  preview: (studyId: string, body: SurrogateOptCreate) =>
    request<SurrogateOptPreview>("POST", `/studies/${studyId}/surrogate-opts/preview`, { body }),
  create: (studyId: string, body: SurrogateOptCreate) => request<SurrogateOpt>("POST", `/studies/${studyId}/surrogate-opts`, { body }),
  list: (studyId: string) => request<SurrogateOptSummary[]>("GET", `/studies/${studyId}/surrogate-opts`),
  get: (id: string) => request<SurrogateOpt>("GET", `/surrogate-opts/${id}`),
  runsCsv: (id: string) => fetchBlob(`/surrogate-opts/${id}/runs.csv`),
  cancel: (id: string) => request<SurrogateOpt>("POST", `/surrogate-opts/${id}/cancel`),
  resume: (id: string) => request<SurrogateOptResume>("POST", `/surrogate-opts/${id}/resume`),
  /** S17 §22.7 추가 검증(EXTRA 배치) — DONE만, power */
  verify: (id: string, body: SurrogateOptVerify) => request<SurrogateOptVerifyResult>("POST", `/surrogate-opts/${id}/verify`, { body }),
};

export const SO_ACTIVE: SoStatus[] = ["EXPLORING", "FITTING", "VERIFYING", "FINALIZING"];
export const isSoActive = (s: string) => (SO_ACTIVE as string[]).includes(s);
