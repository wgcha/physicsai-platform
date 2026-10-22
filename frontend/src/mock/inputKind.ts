// input-kind.md 목: 템플릿 능력(input_capability)·입력 선택 검사(422 INPUT_KIND_UNSUPPORTED)·저장값(assembly|mesh_only) ↔ 공개값(assembly|cushion) 변환.
import type { InputKind, ParamSet, PredictInput } from "../api/types";
import { err, type MockResp } from "./route";

export const toPublic = (k: string | null | undefined): PredictInput => (k === "mesh_only" ? "cushion" : "assembly");
export const toInternal = (i: PredictInput): InputKind => (i === "cushion" ? "mesh_only" : "assembly");

/** 시험이 ps.input_capability를 직접 정하면 그대로, 아니면 저장 입력 종류에서 계산 */
export function capability(ps: ParamSet): { cap: PredictInput[]; reason: string | null } {
  if (ps.input_capability) return { cap: ps.input_capability, reason: ps.input_capability_reason ?? null };
  if (ps.input_kind === "mesh_only") return { cap: ["cushion"], reason: "쿠션만 가능한 템플릿(조립 폴더 없음)" };
  return { cap: ["assembly", "cushion"], reason: null };
}

/** GET 응답용: 능력 필드를 채운 사본 */
export function withCapability(ps: ParamSet): ParamSet {
  const { cap, reason } = capability(ps);
  return { ...ps, input_capability: cap, input_capability_reason: reason };
}

/** 요청 input → 실행 입력(생략 = 서버 규칙). 능력 밖이면 422 INPUT_KIND_UNSUPPORTED */
export function resolveInput(ps: ParamSet, requested: unknown): { input: PredictInput } | { error: MockResp } {
  const { cap, reason } = capability(ps);
  if (requested == null) return { input: cap.includes("assembly") ? "assembly" : "cushion" };
  if (requested !== "assembly" && requested !== "cushion") return { error: err(422, "INVALID_PARAMS", "input은 assembly 또는 cushion입니다.") };
  if (!cap.includes(requested)) {
    const msg = `이 템플릿은 ${requested === "cushion" ? "쿠션" : "조립"} 입력을 쓸 수 없습니다${reason ? `(${reason})` : ""}`;
    return { error: err(422, "INPUT_KIND_UNSUPPORTED", msg, { reason, input_capability: cap, errors: [{ loc: ["params", "input"], msg }] }) };
  }
  return { input: requested };
}

/** prepared(준비된 입력) 실행의 표시 입력: starter가 eps_mesh면 쿠션 */
export const ofPrepared = (starter: string | null | undefined): PredictInput => (starter && /eps_mesh/i.test(starter) ? "cushion" : "assembly");
