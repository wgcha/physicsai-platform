// 손으로 쓴 S16 API 타입이 생성 스키마(openapi)와 어긋나지 않는지 컴파일 때 확인한다(gen:api 뒤 tsc가 잡는다).
import type { components as C } from "./generated/schema";
import type { FemVerification, FemVerifySummary, FemCompare, FemResponseRow } from "./femVerify";
import type { PredictRunDetail, PredictRunSummary } from "./predictRuns";

type S = C["schemas"];
/** (중첩 객체는 키 이름만 눈으로 맞춘다 — 서버 스키마가 옵셔널을 많이 써서 얕은 비교만 한다)
 * 손 타입 H는 생성 타입 G의 좁힌 모양이어야 한다(옵셔널은 required|null로, string은 유니온으로 좁히는 것만 허용) — 키 누락·넓은 타입을 낸다 */
type Compat<G, H> = { [K in keyof G & keyof H]-?: Required<G>[K] extends object ? true : H[K] extends Required<G>[K] ? true : K };
type Bad<T> = { [K in keyof T]: T[K] extends true ? never : K }[keyof T];
type Missing<G, H> = Exclude<keyof G, keyof H>;

export type _FvSummary = Bad<Compat<S["FemVerifyListItem"], FemVerifySummary>>;
export type _FvSummaryMissing = Missing<S["FemVerifyListItem"], FemVerifySummary>;
export type _FvDetail = Bad<Compat<S["FemVerification"], FemVerification>>;
export type _FvDetailMissing = Missing<S["FemVerification"], FemVerification>;
export type _FvCompare = Bad<Compat<S["FvCompare"], FemCompare>>;
export type _FvRow = Bad<Compat<S["FvCompareRow"], FemResponseRow>>;
export type _RunSummary = Bad<Compat<S["PredictRunSummary"], PredictRunSummary>>;
export type _RunSummaryMissing = Missing<S["PredictRunSummary"], PredictRunSummary>;
export type _RunDetail = Bad<Compat<S["PredictRunDetail"], PredictRunDetail>>;
export type _RunDetailMissing = Missing<S["PredictRunDetail"], PredictRunDetail>;

type All = _FvSummary | _FvSummaryMissing | _FvDetail | _FvDetailMissing | _FvCompare | _FvRow | _RunSummary | _RunSummaryMissing | _RunDetail | _RunDetailMissing;
/** All이 never가 아니면 여기서 tsc 오류(어긋난 키 이름이 메시지에 나온다) */
export const _compat: [All] extends [never] ? true : All = true;
