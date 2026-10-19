// S15 표본 방식(phase3.md §20, D3-63): ④ 방식 목록·묶음·설명문(§20.4 문구 그대로)·권장 run 계산식(프런트 `recommendedCount` = 서버 `sampling.recommended_count`)·
// 설계별 run 수 `expectedRuns`(§20.5.9 표)·배치 머리 요약. 순수 함수·상수만(React 없음). 설명문은 이 파일 한 곳 — 서버는 desc_id만 준다(S10).
import type { BatchSampling, BatchSamplingBrief } from "../api/types";

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

const BASE_DESCRIPTIONS: Record<SamplingKind | "hs_lhs" | "hs_sobol" | "hs_fullfact" | "hs_fracfact" | "generic", SamplingDesc> = {
  lhs_opt: {
    name: "최적화 LHS",
    lines: [
      "범위를 고르게 채우는 표본입니다. AI 학습·대리모델·영향도에 두루 맞아 기본으로 추천합니다.",
      "일반 LHS를 다시 배치해 점 사이 최소 거리를 넓히거나(기본) 변수끼리의 상관을 줄입니다. 나중에 점을 이어 붙일 수는 없습니다.",
      "영향도: 정식(PRCC·SRC). 상관이 작아 영향도 순위가 안정적입니다.",
      "run 수: 자유(2~200). 권장 10 × 변수 수(최소 변수 수 + 2).",
    ],
  },
  sobol: {
    name: "Sobol(스크램블 QMC)",
    lines: [
      "저불일치 수열로 공간을 균일하게 채웁니다. 같은 시드로 나중에 run을 이어서 추가할 수 있습니다.",
      "균형을 지키려면 run 수가 2의 거듭제곱(4·8·16·32·64·128)이어야 합니다. run이 적으면 최적화 LHS보다 덜 고를 수 있습니다.",
      "영향도: 정식. AI 학습·대리모델 표본을 단계적으로 늘려 갈 때 추천합니다.",
      "run 수: 2^m. 권장 = 10 × 변수 수 이상인 가장 작은 2^m(최대 128). 이어서 추가는 기존 개수만큼(합계 2배) 권장.",
    ],
  },
  lhs: {
    name: "LHS(무작위 층화)",
    lines: [
      "변수마다 범위를 n칸으로 나눠 칸마다 1점씩 무작위로 뽑는 기본 표본입니다.",
      "빠르고 run 수가 자유롭지만 무작위라 점이 몰리거나 변수끼리 상관이 생길 수 있습니다(최적화 LHS가 보완).",
      "영향도: 정식. AI 학습에 쓸 수 있습니다.",
      "run 수: 자유(2~200). 권장 10 × 변수 수.",
    ],
  },
  fullfact: {
    name: "전체 요인",
    lines: [
      "변수마다 수준 수를 정해 모든 조합을 계산합니다. 변수 2~4개의 경향을 격자로 볼 때 씁니다.",
      "주효과·교호작용을 빠짐없이 보지만 run 수가 수준 수의 곱으로 급격히 늘고, 격자 사이가 비어 AI 학습 표본으로는 비효율적입니다.",
      "영향도: 정식.",
      "run 수 = 수준 수의 곱(최대 200). 수준 2~10, 정수 변수는 범위 안 정수 개수까지.",
    ],
  },
  fracfact: {
    name: "부분 요인(2수준)",
    lines: [
      "최소·최대 2수준만 써서 변수가 많을 때 중요한 변수를 적은 run으로 거릅니다(선별용).",
      "해상도 V는 주효과·2인자 교호작용이 서로 섞이지 않고, 해상도 IV는 주효과는 깨끗하지만 2인자 교호작용끼리 섞입니다(교락).",
      "영향도: 참고용(교락 안내). 양 끝값만 쓰므로 AI 학습 표본으로는 맞지 않습니다.",
      "run 수 = 2^(k−p): IV 8~32, V 4~128(변수 2~11개). 부분 요인이 필요 없는 변수 수에서는 전체 2수준 요인이 됩니다.",
    ],
  },
  pb: {
    name: "Plackett–Burman",
    lines: [
      "변수가 아주 많을 때 가장 적은 run으로 주효과만 거르는 2수준 선별 설계입니다.",
      "run 수가 변수 수 + 1 근처로 가장 적지만, 주효과가 2인자 교호작용과 부분적으로 섞입니다.",
      "영향도: 참고용(교락 안내). AI 학습 표본으로는 맞지 않습니다.",
      "run 수 = 변수 수 + 1 이상인 가장 작은 크기(8·12·16·20·24·32·44·48…). 변수 2개 이상.",
    ],
  },
  bbd: {
    name: "Box–Behnken",
    lines: [
      "최소·중간·최대 3수준의 2차 응답면 설계입니다. 모든 변수가 동시에 극값인 꼭짓점 조합을 피합니다.",
      "곡률(2차 효과)을 적은 run으로 보지만 공간 내부가 비어 AI 학습 표본으로는 부족합니다. 변수 3개 이상이 필요합니다.",
      "영향도: 참고용(2차 설계 — 곡률 효과는 선형 영향도에 작게 보일 수 있음).",
      "run 수 = 2·k·(k−1) + 1(중심점 1개 — AI 예측은 같은 입력이면 같은 값이라 반복하지 않음). 변수 3~10개.",
    ],
  },
  ccd: {
    name: "중심 합성(CCD)",
    lines: [
      "2수준 요인점 + 축점 + 중심점으로 2차 응답면을 맞추는 고전 설계입니다.",
      "면중심(기본)은 3수준으로 범위 안이고, 내접은 5수준으로 요인점이 범위 안쪽으로 줄어듭니다. 범위 밖으로 나가는 외접은 AI 학습 범위를 벗어나 제공하지 않습니다.",
      "영향도: 참고용(2차 설계 안내). AI 학습 표본으로는 부족합니다.",
      "run 수 = 요인점(변수 4개 이하 2^k, 5개 이상 해상도 V 부분 요인) + 2k + 1. 변수 2~11개.",
    ],
  },
  table: {
    name: "표 붙여넣기 / CSV",
    lines: [
      "직접 정한 조합(엑셀 붙여넣기·CSV)을 그대로 예측합니다.",
      "원하는 점을 정확히 넣을 수 있지만, 표본이 어떻게 퍼져 있는지 플랫폼은 알 수 없습니다.",
      "영향도: 참고용.",
      "run 수 = 표 행 수(1~200). 첫 줄 = 파라미터 이름.",
    ],
  },
  train_doe: {
    name: "① 학습 DOE 그대로 재사용",
    lines: [
      "① 학습 DOE와 같은 점을 AI로 예측해 해석 결과와 1:1로 비교(검증)합니다.",
      "해석값과 바로 겹쳐 볼 수 있지만 run 수·점 위치는 ① DOE를 따릅니다.",
      "영향도: ① DOE 방식을 따름(LHS·Sobol·전체 요인 = 정식, 부분 요인 = 참고용).",
      "run 수 = ① DOE run 수(최대 200). 파라미터 이름이 템플릿과 같아야 합니다.",
    ],
  },
  hs_lhs: {
    name: "LatinHyperCube(①)",
    lines: [
      "학습 데이터 기본 추천입니다. HyperStudy LHS로 범위를 고르게 층화합니다.",
      "run 수를 자유롭게 정하고 Random Seed로 같은 표본을 다시 만듭니다. 무작위라 점이 일부 몰릴 수 있습니다.",
      "영향도: 정식. AI 학습에 적합합니다.",
      "run 수: 권장 10 × 변수 수(해석 비용이 크면 최소 변수 수 + 2).",
    ],
  },
  hs_sobol: {
    name: "Sobol(①)",
    lines: [
      "HyperStudy Sobol 수열로 공간을 균일하게 채웁니다.",
      "Scramble을 켜면 격자 무늬가 줄어듭니다(권장). Sequence Offset·Seed로 같은 표본을 다시 만듭니다.",
      "영향도: 정식. AI 학습에 적합합니다.",
      "run 수: 자유, 가능하면 2의 거듭제곱(16·32·64…). 권장 10 × 변수 수 이상.",
    ],
  },
  hs_fullfact: {
    name: "FullFact(①)",
    lines: [
      "모든 수준 조합을 해석합니다. 변수가 적을 때 경향을 확인하는 용도입니다.",
      "run 수는 HyperStudy가 변수 수준으로 정하고 변수가 늘면 급격히 늘어납니다. 격자라 학습 표본으로는 비효율적입니다.",
      "영향도: 정식.",
      "run 수: HyperStudy가 결정(화면에서 지정 불가).",
    ],
  },
  hs_fracfact: {
    name: "FracFact(①)",
    lines: [
      "2수준 부분 요인으로 중요한 변수를 거르는 선별용입니다.",
      "Resolution 3은 주효과가 2인자 교호작용과 섞이고, 4는 2인자 교호작용끼리, 5는 3인자 이상과만 섞입니다.",
      "영향도: 참고용(교락 안내). AI 학습 표본으로는 맞지 않습니다.",
      "run 수: HyperStudy가 결정(Resolution에 따라).",
    ],
  },
  generic: {
    name: "(설명 없는 ① 유형)",
    lines: [
      "원본 DOE 유형 정의 파일에 있는 방식입니다.",
      "이 방식의 설명은 등록되지 않았습니다.",
      "영향도: 참고용.",
      "run 수: 정의 파일 설정을 따릅니다.",
    ],
  },
};

const tdFrom = (base: PlatformKind, over: Record<number, string>): SamplingDesc => ({ name: BASE_DESCRIPTIONS[base].name, lines: BASE_DESCRIPTIONS[base].lines.map((l, i) => over[i] ?? l) });
export const DESCRIPTIONS: Record<DescId, SamplingDesc> = {
  ...BASE_DESCRIPTIONS,
  // ---- S18 ① 플랫폼 생성(§23.10): ④ 문구를 쓰고 아래 줄만 바꾼다(lhs·lhs_opt·bbd·fullfact = 4줄, sobol = 1·3·4줄). fracfact·pb·ccd는 ④ 문구 그대로
  td_lhs: tdFrom("lhs", { 3: "run 수: 자유(2 이상, 상한은 입력란에 표시). 권장 10 × 변수 수." }),
  td_lhs_opt: tdFrom("lhs_opt", { 3: "run 수: 자유(2 이상, 상한은 입력란에 표시). 권장 10 × 변수 수(최소 변수 수 + 2). run이 많으면 생성 준비에 수십 초 걸릴 수 있습니다." }),
  td_sobol: tdFrom("sobol", {
    0: "저불일치 수열로 공간을 균일하게 채웁니다(스크램블, 같은 시드로 같은 표본).",
    1: "균형을 지키려면 run 수가 2의 거듭제곱(4·8·16·32·64·128·256)이어야 합니다. run이 적으면 최적화 LHS보다 덜 고를 수 있습니다.",
    2: "영향도: 정식. AI 학습에 적합합니다.",
    3: "run 수: 2^m(4·8·16·32·64·128·256). 권장 = 10 × 변수 수 이상인 가장 작은 2^m.",
  }),
  td_fullfact: tdFrom("fullfact", { 3: "run 수 = 수준 수의 곱(상한 이내). 수준 2~10, 정수 변수는 범위 안 정수 개수까지." }),
  td_fracfact: tdFrom("fracfact", {}),
  td_pb: tdFrom("pb", {}),
  td_bbd: tdFrom("bbd", { 3: "run 수 = 2·k·(k−1) + 1(중심점 1개 — 같은 입력의 해석은 같은 결과라 반복하지 않음). 변수 3개 이상." }),
  td_ccd: tdFrom("ccd", {}),
};
export const HS_NOTE = "최적화 LHS·Box–Behnken·CCD·Plackett–Burman은 '플랫폼 생성'에서 고를 수 있습니다(원본 HyperStudy 방식은 유형 정의 파일의 방식만).";
/** S18 §23.9: 원본 HyperStudy(호환) 모드 회색 줄 하나 더 */
export const HS_COMPAT_NOTE = "호환 모드 — hstbatch -multiexec로 실행합니다. 실제 동시 실행 수는 HyperStudy가 정하며 입력 생성이 run마다 순차로 될 수 있습니다.";

/** ① 설명 id: 서버 desc_id(없거나 모르면 일반 문구) */
export function descIdOf(descId: string | null | undefined): DescId {
  return descId && descId in DESCRIPTIONS ? (descId as DescId) : "generic";
}

// ---------------------------------------------------------------- run 수 (§20.4 권장식·§20.5.9 표)

/** 부분 요인 기본 요인 수 r(run = 2^r), 인덱스 = 변수 수 k. 해상도 IV·V (§20.5.5 생성자 표) */
const FRAC_R: Record<4 | 5, Record<number, number>> = {
  4: { 2: 2, 3: 3, 4: 3, 5: 4, 6: 4, 7: 4, 8: 4, 9: 5, 10: 5, 11: 5 },
  5: { 2: 2, 3: 3, 4: 4, 5: 4, 6: 5, 7: 6, 8: 6, 9: 7, 10: 7, 11: 7 },
};
export const FRAC_MIN_K = 2;
export const FRAC_MAX_K = 11;

export function fracRuns(k: number, resolution: 4 | 5): number | null {
  const r = FRAC_R[resolution][k];
  return r === undefined ? null : 2 ** r;
}

const isPrime = (n: number) => {
  if (n < 2) return false;
  for (let d = 2; d * d <= n; d++) if (n % d === 0) return false;
  return true;
};
/** Plackett–Burman 크기 집합(≤ max): {q+1 : q 소수, q ≡ 3 (mod 4), q+1 ≥ 8} ∪ {2^m : m ≥ 3} */
export function pbSizes(max: number): number[] {
  const set = new Set<number>();
  for (let q = 3; q + 1 <= max; q++) if (isPrime(q) && q % 4 === 3 && q + 1 >= 8) set.add(q + 1);
  for (let n = 8; n <= max; n *= 2) set.add(n);
  return [...set].sort((a, b) => a - b);
}
/** k+1 이상인 가장 작은 PB 크기. k < 2이거나 R을 넘으면 null */
export function pbRuns(k: number, maxRuns = DEFAULT_MAX_RUNS): number | null {
  if (k < 2) return null;
  return pbSizes(maxRuns).find((n) => n >= k + 1) ?? null;
}

const bbdRuns = (k: number, maxRuns: number) => (k < 3 ? null : 2 * k * (k - 1) + 1 <= maxRuns ? 2 * k * (k - 1) + 1 : null);
function ccdRuns(k: number, maxRuns: number): number | null {
  if (k < FRAC_MIN_K || k > FRAC_MAX_K) return null;
  const f = k <= 4 ? 2 ** k : fracRuns(k, 5);
  const n = f === null ? null : f + 2 * k + 1;
  return n !== null && n <= maxRuns ? n : null;
}

/** Sobol 허용 run 수: 4·8·…·2^m ≤ R */
export function sobolCounts(maxRuns = DEFAULT_MAX_RUNS): number[] {
  const out: number[] = [];
  for (let n = 4; n <= maxRuns; n *= 2) out.push(n);
  return out;
}

/** 권장 run 수(§20.4): 서버 `sampling.recommended_count`와 같은 값. 설계로 정해지는 방식은 null */
export function recommendedCount(kind: SamplingKind, k: number, maxRuns = DEFAULT_MAX_RUNS): number | null {
  if (k < 1) return null;
  if (kind === "lhs" || kind === "lhs_opt") return Math.min(maxRuns, Math.max(10, 10 * k));
  if (kind === "sobol") {
    const opts = sobolCounts(maxRuns);
    if (!opts.length) return null;
    return opts.find((n) => n >= 10 * k) ?? opts[opts.length - 1];
  }
  return null;
}

export interface RunOptions {
  resolution?: 4 | 5;
  /** 전체 요인 수준(활성 변수 순서, 길이 k) */
  levels?: number[];
  maxRuns?: number;
}
/** 설계가 정하는 run 수(§20.5.9). 지원 범위 밖·상한 초과는 null. 자유 run 수 방식(lhs·lhs_opt·sobol)·표·① DOE도 null */
export function expectedRuns(kind: SamplingKind, k: number, o: RunOptions = {}): number | null {
  const R = o.maxRuns ?? DEFAULT_MAX_RUNS;
  if (k < 1) return null;
  const within = (n: number | null) => (n !== null && n <= R ? n : null);
  switch (kind) {
    case "fullfact": {
      const lv = o.levels ?? Array.from({ length: k }, () => 2);
      return within(lv.reduce((a, b) => a * b, 1));
    }
    case "fracfact":
      return within(fracRuns(k, o.resolution ?? 5));
    case "pb":
      return pbRuns(k, R);
    case "bbd":
      return bbdRuns(k, R);
    case "ccd":
      return ccdRuns(k, R);
    default:
      return null;
  }
}

/** 전체 요인 기본 수준: 3^k ≤ R이면 3, 아니면 2 (§20.10) */
export const defaultLevel = (k: number, maxRuns = DEFAULT_MAX_RUNS) => (3 ** k <= maxRuns ? 3 : 2);

/** 설명 상자 4번째 줄에 덧붙이는 계산값("현재 변수 4개 → 권장 40"). 값이 없으면 null */
export function calcNote(kind: SamplingKind, k: number, o: RunOptions = {}): string | null {
  if (k < 1) return null;
  const R = o.maxRuns ?? DEFAULT_MAX_RUNS;
  if (kind === "lhs" || kind === "lhs_opt" || kind === "sobol") {
    const n = recommendedCount(kind, k, R);
    return n === null ? null : `현재 변수 ${k}개 → 권장 ${n}`;
  }
  const n = expectedRuns(kind, k, o);
  if (n === null) return null;
  if (kind === "fullfact" && o.levels) return `현재 수준 ${o.levels.join("×")} → ${n} run`;
  if (kind === "fracfact") return `현재 변수 ${k}개 · 해상도 ${o.resolution === 4 ? "IV" : "V"} → ${n} run`;
  return `현재 변수 ${k}개 → ${n} run`;
}

/** ① 설명 상자의 계산값: hs_lhs·hs_sobol만 "권장 10 × 변수 수"(그 밖 null) */
export function hsCalcNote(descId: DescId, k: number): string | null {
  return k >= 1 && (descId === "hs_lhs" || descId === "hs_sobol") ? `현재 변수 ${k}개 → 권장 ${10 * k}` : null;
}

// ---------------------------------------------------------------- 배치 머리 한 줄 (§20.10)

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** ④ 배치 결과 머리 "표본: …" 뒤에 오는 요약. 예: "Sobol 16개 · 시드 1 · B-003에 이어서", "부분 요인 해상도 IV · 16개" */
export function samplingSummary(s: BatchSampling | null | undefined, runCount: number): string | null {
  if (!s) return null;
  const m = s.meta ?? {};
  const n = num(m.count) ?? runCount;
  const seed = num(m.seed);
  switch (s.kind.toLowerCase()) {
    case "lhs_opt":
      return `최적화 LHS ${n}개${seed !== null ? ` · 시드 ${seed}` : ""} · ${m.criterion === "corr" ? "상관 최소" : "최소 거리"}`;
    case "sobol": {
      const from = m.continue_from as { label?: unknown } | null | undefined;
      return `Sobol ${n}개${seed !== null ? ` · 시드 ${seed}` : ""}${from && typeof from.label === "string" ? ` · ${from.label}에 이어서` : ""}`;
    }
    case "lhs":
      return `LHS ${n}개${seed !== null ? ` · 시드 ${seed}` : ""}`;
    case "fullfact": {
      const lv = m.levels && typeof m.levels === "object" ? Object.values(m.levels as Record<string, unknown>).map(num).filter((x): x is number => x !== null) : [];
      return `전체 요인 ${n}개${lv.length ? ` · 수준 ${lv.join("×")}` : ""}`;
    }
    case "fracfact":
      return `부분 요인 해상도 ${num(m.resolution) === 4 ? "IV" : "V"} · ${num(m.runs) ?? n}개`;
    case "pb":
      return `Plackett–Burman ${num(m.runs) ?? n}개`;
    case "bbd":
      return `Box–Behnken ${n}개`;
    case "ccd":
      return `CCD ${m.alpha_kind === "inscribed" ? "내접" : "면중심"} · ${n}개`;
    case "table":
      return `표 붙여넣기 ${n}개`;
    case "train_doe":
      return `① 학습 DOE ${n}개`;
    default:
      return `${s.label} ${n}개`;
  }
}

/** ⑤ 출처 라벨의 방식 이름(짧게). 모르면 서버 label */
export function methodShortLabel(b: Pick<BatchSamplingBrief, "kind" | "label"> | null | undefined): string | null {
  if (!b) return null;
  const k = b.kind.toLowerCase();
  const short: Record<string, string> = { lhs_opt: "최적화 LHS", sobol: "Sobol", lhs: "LHS", fullfact: "전체 요인", fracfact: "부분 요인", pb: "Plackett–Burman", bbd: "Box–Behnken", ccd: "CCD", table: "표", train_doe: "① DOE" };
  return short[k] ?? b.label;
}
