// S15 표본 방식(phase3.md §20, D3-63): ④ 방식 종류·묶음·표시 이름·상한 기본값. 순수 함수·상수만(React 없음). 옛 import 경로 `lib/sampling`은 이 파일들을 재노출한다(R-F 분할, 동작 불변).
export type SamplingKind = "lhs_opt" | "sobol" | "lhs" | "fullfact" | "fracfact" | "pb" | "bbd" | "ccd" | "table" | "train_doe";
/** S18 ① 플랫폼 생성 방식 8종(§23.9): ④ 방식에서 `table`·`train_doe`를 뺀 것 */
export type PlatformKind = Exclude<SamplingKind, "table" | "train_doe">;
export type TdDescId = `td_${PlatformKind}`;
export type DescId = SamplingKind | TdDescId | "hs_lhs" | "hs_sobol" | "hs_fullfact" | "hs_fracfact" | "generic";
export interface SamplingDesc {
  /** 설명 상자 머리(선택창 표시 이름과 같은 말) */
  name: string;
  /** 용도 / 장단점 / 영향도·AI 학습 / run 수·제약 — 계약 문구 그대로 */
  lines: string[];
}

/** 설정 predict_batch.max_runs 기본값(서버 상한과 같아야 함 — /status에 없으면 이 값) */
export const DEFAULT_MAX_RUNS = 200;
/** ④ 처음 열 때 고르는 방식(추천) */
export const RECOMMENDED_KIND: SamplingKind = "lhs_opt";

export const SAMPLING_GROUPS: { label: string; kinds: SamplingKind[] }[] = [
  { label: "공간 채움(AI 학습·대리모델)", kinds: ["lhs_opt", "sobol", "lhs"] },
  { label: "요인 설계(경향·선별)", kinds: ["fullfact", "fracfact", "pb"] },
  { label: "2차 응답면", kinds: ["bbd", "ccd"] },
  { label: "직접 지정", kinds: ["table", "train_doe"] },
];
export const SAMPLING_KINDS: SamplingKind[] = SAMPLING_GROUPS.flatMap((g) => g.kinds);

/** S18 ①-3 플랫폼 생성 드롭다운: ④ 묶음·순서에서 직접 지정 묶음(table·train_doe)만 뺀 8개(§23.9) */
export const PLATFORM_GROUPS: { label: string; kinds: PlatformKind[] }[] = SAMPLING_GROUPS.filter((g) => g.label !== "직접 지정") as { label: string; kinds: PlatformKind[] }[];
export const PLATFORM_KINDS: PlatformKind[] = PLATFORM_GROUPS.flatMap((g) => g.kinds);
export const isPlatformKind = (k: string): k is PlatformKind => (PLATFORM_KINDS as string[]).includes(k);
export const tdDescId = (k: PlatformKind): TdDescId => `td_${k}`;
/** ①-3 플랫폼 run 상한 기본값(설정 train_data.platform_max_runs = /status.limits.configured.doe_platform_max_runs, 없으면 이 값) */
export const DEFAULT_PLATFORM_MAX_RUNS = 500;
/** ①-3 플랫폼 동시 실행 수 기본값(설정 train_data.platform_parallel_default) */
export const DEFAULT_PLATFORM_PARALLEL = 4;

/** 선택창 표시 이름(§20.4 표) */
export const SAMPLING_LABEL: Record<SamplingKind, string> = {
  lhs_opt: "최적화 LHS",
  sobol: "Sobol(스크램블 QMC)",
  lhs: "LHS(무작위 층화)",
  fullfact: "전체 요인",
  fracfact: "부분 요인(2수준)",
  pb: "Plackett–Burman",
  bbd: "Box–Behnken",
  ccd: "중심 합성(CCD)",
  table: "표 붙여넣기 / CSV",
  train_doe: "① 학습 DOE 그대로 재사용",
};
export const isSamplingKind = (k: string): k is SamplingKind => (SAMPLING_KINDS as string[]).includes(k);
