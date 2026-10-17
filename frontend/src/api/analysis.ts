// S14 ⑤ 결과분석 API(phase3.md §19.5, D3-62): GET /train-does/{doe_id}/result-table — 해석 DOE의 파라미터 + 응답 표(읽기 전용, 캐시는 §17.4와 같음).
// api/index·endpoints·types는 고치지 않는다(§19.8). 타입은 generated/schema.d.ts(backend/openapi.json). rows[].state = train_runs.state 원값(COLLECTED 등, run 없으면 UNKNOWN), type = doe_type 원값.
import { request } from "./client";
import type { components } from "./generated/schema";

type S = components["schemas"];

/** S15(§20.6): influence_class(formal·reference·off)·influence_note(reference 문구·off 사유)·sampling(① 유형·옵션). influence_ok = influence_class ≠ off */
export type DoeResultTable = S["DoeResultTable"];
export type DoeResultTableRow = S["DoeResultRow"];

export const analysisApi = {
  doeResultTable: (doeId: string) => request<DoeResultTable>("GET", `/train-does/${doeId}/result-table`),
};
