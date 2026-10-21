// native-vars.md §6: Native 템플릿 변수 정의(선택·범위) API 타입 — 생성 타입 별칭 + 실행 스냅숏(§4.1) 모양.
import type { S } from "./typesBase";

export type NativeVars = S["NativeVars"];
export type NativeVarPoolRow = S["NativeVarPoolRow"];
export type NativeVarItem = S["NativeVarItem"];
export type NativeVarHistory = S["NativeVarHistory"];
export type NativeVarsUpdate = S["NativeVarsUpdate"];
/** 경고(name 있음: VAR_*)·안내(name 없음: TRAIN_RANGE_*·VARS_FROM_DOE) */
export type VarNote = S["VarNote"];
export type VarRow = S["VarRow"];
export type VarRange = S["VarRange"];
export type VarFeasible = S["VarFeasible"];
/** 요청 선택 필드 vars — 그 실행에만 적용 */
export type VarsEdit = S["VarsEdit"];

/** §4.1 실행 스냅숏(`PredictBatch.vars`·`settings.vars`) — 화면은 요약에 필요한 키만 읽는다 */
export interface VarsSnapshot {
  set_revision?: number | null;
  edited?: boolean;
  variables?: { name: string; origin?: string; min?: number; max?: number }[];
  excluded?: string[];
}
