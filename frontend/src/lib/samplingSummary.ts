// S15 표본 방식(phase3.md §20, D3-63): 배치 머리 요약(§20.10)·⑤ 출처 방식 이름. 순수 함수·상수만(React 없음). 옛 import 경로 `lib/sampling`은 이 파일들을 재노출한다(R-F 분할, 동작 불변).
import type { BatchSampling, BatchSamplingBrief } from "../api/types";

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
