// API 타입 공용 보조(R-F 분할): 생성 스키마 별칭 S·Override. types*.ts 안에서만 쓴다(화면 코드는 `api/types`만 import).
import type { components } from "./generated/schema";

export type S = components["schemas"];
export type Override<T, U> = Omit<T, keyof U> & U;
