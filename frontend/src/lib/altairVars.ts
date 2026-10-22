// altair-vars.md §3·§6·AV-11: ①-2 tpl 요약 한 줄, from-train tpl 출처(doe|current) 선택·오류 안내 — 순수 함수만(시험 대상).
import { ApiError, errorMessage } from "../api";
import type { TplSummary } from "../api/types";

export type TplSource = "doe" | "current";
export const TPL_SOURCE_LABEL: Record<TplSource, string> = { doe: "DOE 기준", current: "현재 tpl" };

/** from-train(tpl_source) 오류 코드 → 사람이 읽을 안내 */
export const TPL_ERROR_TEXT: Record<string, string> = {
  TPL_DOE_MISMATCH: "현재 tpl의 사용 파라미터(이름·공칭·범위)가 이 DOE와 다릅니다 — 'DOE 기준'으로 만들거나, ①-2 표를 DOE와 같게 맞춘 뒤 tpl을 다시 생성하세요",
  TPL_SCOPE_PARTIAL: "현재 tpl이 옛 형식(사용 파라미터만 포함)입니다 — ①-2에서 tpl을 다시 생성한 뒤 시도하세요",
  TPL_REQUIRED: "현재 tpl이 없습니다 — ①-2에서 tpl을 먼저 생성하세요",
};
export const tplErrorText = (e: unknown): string => (e instanceof ApiError && TPL_ERROR_TEXT[e.code]) || errorMessage(e);

/** ①-2 tpl 생성 결과 한 줄: 전체 · 사용(DOE 범위) · 미사용(공칭 고정). 옛 부분 tpl이면 사용 개수만 */
export function tplSummaryText(s: TplSummary): string {
  if (s.scope !== "full") return `옛 tpl — 사용 ${s.used}개만 포함(미사용 파라미터 없음)`;
  const parts = [`전체 ${s.total}개 포함`, `사용 ${s.used}개 = DOE 범위`, `미사용 ${Math.max(0, s.total - s.used)}개 공칭 고정`];
  return `${parts[0]}(${parts[1]}, ${parts[2]})`;
}

/** 요약 아래 경고 줄들: 표기 손실(④ 변수로 못 씀)·제외된 무효 미사용 행 */
export function tplSummaryNotes(s: TplSummary): string[] {
  const out: string[] = [];
  if (s.format_loss.length) out.push(`공칭 표기 손실 ${s.format_loss.length}개(${s.format_loss.join(", ")}) — 원래 값 그대로 고정하며 ④ 변수로는 쓸 수 없습니다`);
  if (s.skipped.length) out.push(`유효하지 않은 미사용 ${s.skipped.length}개는 tpl에서 뺐습니다(${s.skipped.join(", ")})`);
  return out;
}
