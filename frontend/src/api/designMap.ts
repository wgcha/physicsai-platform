// S12 설계공간 지도 API(phase3.md §17.4, D3-59): GET /predict-batches/{bid}/design-map.
// 타입은 generated/schema.d.ts(backend/openapi.json)에서. api/index·endpoints·types는 고치지 않는다(§18.13 — S13 화면도 이 파일을 import).
import type { components } from "./generated/schema";
import { request } from "./client";

type S = components["schemas"];

export type DesignMap = S["DesignMap"];
export type DesignMapRun = S["DesignMapRun"];
export type DesignMapMetric = S["DesignMapMetric"];
export type DesignMapParameter = S["DesignMapParameter"];
export type DesignMapCurveStats = S["DesignMapCurveStats"];
export type DesignMapCounts = S["DesignMapCounts"];

/** §17.2 지표 id 문법(백엔드 run_metrics.METRIC_RE와 같음, S17 §22.3.2 perf: 추가) */
export const METRIC_RE = /^(curve:(max|min|absmax)|resp:[A-Za-z][A-Za-z0-9_]{0,63}_(MIN|MAX)|tbl:[A-Za-z][A-Za-z0-9_]{0,63}|perf:[A-Za-z][A-Za-z0-9_]{0,63})$/;
export const DEFAULT_METRIC = "curve:max";

export const designMapApi = {
  get: (batchId: string) => request<DesignMap>("GET", `/predict-batches/${batchId}/design-map`),
};
