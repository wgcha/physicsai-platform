// S15 표본 방식(phase3.md §20, D3-63): ④ 방식 종류·묶음·표시 이름·상한 기본값. 순수 함수·상수만(React 없음). 옛 import 경로 `lib/sampling`은 이 파일들을 재노출한다(R-F 분할, 동작 불변).
export type SamplingKind = "lhs_opt" | "sobol" | "halton" | "lhs" | "random" | "fullfact" | "fracfact" | "pb" | "bbd" | "ccd" | "table" | "train_doe";
/** ① 플랫폼 생성 방식(doe-methods.md DM-C3): ④ 방식에서 `train_doe`(재사용 선택으로 따로 고름)를 뺀 것 — `table`은 ①에도 있다 */
export type PlatformKind = Exclude<SamplingKind, "train_doe">;
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
  { label: "공간 채움(AI 학습·대리모델)", kinds: ["lhs_opt", "sobol", "halton", "lhs", "random"] },
  { label: "요인 설계(경향·선별)", kinds: ["fullfact", "fracfact", "pb"] },
  { label: "2차 응답면", kinds: ["bbd", "ccd"] },
  { label: "직접 지정", kinds: ["table", "train_doe"] },
];
export const SAMPLING_KINDS: SamplingKind[] = SAMPLING_GROUPS.flatMap((g) => g.kinds);

// ---------------------------------------------------------------- 지점별 허용 목록(doe-methods.md §3 SITE_KINDS, DM-C1) — 백엔드 registry.SITE_KINDS와 같은 표
export type SiteId = "train_platform" | "train_native" | "train_native_multi" | "batch" | "batch_multi" | "opt_explore";
const FULL_LIST: SamplingKind[] = ["lhs_opt", "sobol", "halton", "lhs", "random", "fullfact", "fracfact", "pb", "bbd", "ccd", "table", "train_doe"];
const MULTI_LIST: SamplingKind[] = ["lhs_opt", "halton", "lhs", "random"];
export const SITE_KINDS: Record<SiteId, SamplingKind[]> = {
  train_platform: FULL_LIST,
  train_native: FULL_LIST,
  train_native_multi: MULTI_LIST,
  batch: FULL_LIST,
  batch_multi: MULTI_LIST,
  opt_explore: ["lhs", "lhs_opt", "sobol", "halton", "random"],
};
/** 지점별 화면 기본(DM-C8): ①-3 Altair·④ = lhs_opt, ①-3 Native·⑥ = lhs */
export const SITE_DEFAULT: Record<SiteId, SamplingKind> = {
  train_platform: "lhs_opt", train_native: "lhs", train_native_multi: "lhs", batch: "lhs_opt", batch_multi: "lhs", opt_explore: "lhs",
};
/** 다중 baseline 세트에서 층 안 생성기 밖 방식을 막는 사유(DM-C4 문구) */
export const MULTI_BASELINE_REASON = "다중 baseline 세트는 baseline별 층화라 LHS·최적화 LHS·Halton·균일 랜덤만 됩니다";
/** 방식 드롭다운 묶음: 묶음 머리·순서는 SAMPLING_GROUPS(§3), 지점에 허용되지 않는 방식은 뺀다. all=true면 허용 밖도 남긴다(회색 처리용) */
export function siteGroups(site: SiteId, all = false): { label: string; kinds: SamplingKind[] }[] {
  const ok = SITE_KINDS[site];
  return SAMPLING_GROUPS.map((g) => ({ label: g.label, kinds: all ? g.kinds : ok.filter((k) => g.kinds.includes(k)) })).filter((g) => g.kinds.length);
}
export const PLATFORM_GROUPS: { label: string; kinds: SamplingKind[] }[] = siteGroups("train_platform");
export const PLATFORM_KINDS: PlatformKind[] = PLATFORM_GROUPS.flatMap((g) => g.kinds).filter((k): k is PlatformKind => k !== "train_doe");
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
  halton: "Halton(스크램블 QMC)",
  random: "균일 랜덤",
  fullfact: "전체 요인",
  fracfact: "부분 요인(2수준)",
  pb: "Plackett–Burman",
  bbd: "Box–Behnken",
  ccd: "중심 합성(CCD)",
  table: "표 붙여넣기 / CSV",
  train_doe: "① 학습 DOE 그대로 재사용",
};
export const isSamplingKind = (k: string): k is SamplingKind => (SAMPLING_KINDS as string[]).includes(k);
