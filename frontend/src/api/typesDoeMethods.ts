// v0.2.9 DOE 표본 방식 확대(docs/contracts/doe-methods.md): schema.d.ts(재생성 전)에 아직 없는 새 필드의 로컬 보강 타입.
// BE openapi 반영 후 `npm run gen:api`로 schema.d.ts가 따라오면 이 파일의 타입을 생성 타입으로 바꾸고 지운다. 계약 그대로 옮긴 것이다.
import type { Override, S } from "./typesBase";

/** ④ 새 방식 halton·random(§4.1): 입력 키는 lhs와 같다(count·seed·ranges) */
export interface BatchSourceHalton {
  kind: "halton";
  count: number;
  seed: number;
  ranges?: Record<string, number[]> | null;
}
export interface BatchSourceRandom {
  kind: "random";
  count: number;
  seed: number;
  ranges?: Record<string, number[]> | null;
}
export type BatchSourceMore = BatchSourceHalton | BatchSourceRandom;

/** ⑥ 탐색 새 DOE 방식(DM-C5): lhs(기본·생략) · lhs_opt · sobol · halton · random. 요인·응답면·표는 ⑥에 없다 */
export type ExploreMethod = "lhs" | "lhs_opt" | "sobol" | "halton" | "random";
/** SoExploreNew + method·criterion(DM-C5). criterion은 lhs_opt만(그 밖이면 422) */
export type SoExploreNewDm = S["SoExploreNew"] & { method?: ExploreMethod; criterion?: "maximin" | "corr" };
export type SurrogateOptCreateDm = Override<S["SurrogateOptCreate"], { explore: SoExploreNewDm | S["SoExploreReuse"] }>;
