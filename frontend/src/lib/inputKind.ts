// input-kind.md: 예측 입력 종류 공용 규칙 — 공개 값 `assembly | cushion`(저장 값 input_kind assembly|mesh_only와 다름 — 화면은 공개 값만 쓴다).
import type { InputKind, ParamSet, PredictInput } from "../api";

export const INPUT_LABEL: Record<PredictInput, string> = { assembly: "조립", cushion: "쿠션" };
export const INPUT_DETAIL: Record<PredictInput, string> = {
  assembly: "조립 입력(m_3, 전체 모델)",
  cushion: "쿠션 입력(쿠션 rad만 — GPU 메모리 적음)",
};
/** 쿠션 선택 시 한 줄 안내 */
export const CUSHION_NOTE = "m1 쿠션 메시로 예측 — GPU 메모리 적음 · 제품 부품 응답은 값이 없을 수 있음";
/** 422 INPUT_KIND_UNSUPPORTED 기본 문구(서버 문구가 있으면 서버 것을 쓴다) */
export const UNSUPPORTED_TEXT = "이 템플릿은 선택한 입력을 쓸 수 없습니다";

export function inputText(i: PredictInput | null | undefined): string {
  return i ? INPUT_LABEL[i] : "—";
}

/** 템플릿 능력: 서버 `input_capability`(없으면 저장 입력 종류에서: mesh_only → 쿠션만, 아니면 조립만) */
export function capabilityOf(ps: Pick<ParamSet, "input_capability" | "input_kind"> | null | undefined): PredictInput[] {
  if (!ps) return ["assembly"];
  if (ps.input_capability && ps.input_capability.length) return ps.input_capability;
  return (ps.input_kind as InputKind | undefined) === "mesh_only" ? ["cushion"] : ["assembly"];
}

/** 서버 기본 규칙(IK-1): 조립 가능 → 조립, 쿠션 전용 → 쿠션 */
export function defaultInput(cap: PredictInput[]): PredictInput {
  return cap.includes("assembly") ? "assembly" : "cushion";
}

export type CapabilityBadge = "both" | "cushion_only" | "assembly_only";
export const BADGE_TEXT: Record<CapabilityBadge, string> = { both: "조립·쿠션 가능", cushion_only: "쿠션만", assembly_only: "조립만" };
export function badgeOf(cap: PredictInput[]): CapabilityBadge {
  const a = cap.includes("assembly");
  const c = cap.includes("cushion");
  return a && c ? "both" : c ? "cushion_only" : "assembly_only";
}

/** 요청 실패 본문이 INPUT_KIND_UNSUPPORTED(422, field input)이면 그 문구(서버 한국어), 아니면 null — 입력 세그먼트 옆에 표시 */
export function inputKindError(detail: { code?: string; message?: string } | null | undefined): string | null {
  return detail?.code === "INPUT_KIND_UNSUPPORTED" ? detail.message || UNSUPPORTED_TEXT : null;
}
