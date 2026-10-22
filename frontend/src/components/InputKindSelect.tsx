// input-kind.md §10 후보 A: `입력: 조립 | 쿠션` 세그먼트 1개 + 템플릿 능력 배지 + 실행 목록용 입력 배지.
// 능력(input_capability)에 없는 쪽은 비활성 + 이유(input_capability_reason). 기본값은 서버 규칙(조립 가능 → 조립, 쿠션 전용 → 쿠션).
import { useEffect, useState } from "react";
import type { ParamSet, PredictInput } from "../api";
import { BADGE_TEXT, CUSHION_NOTE, INPUT_LABEL, badgeOf, capabilityOf, defaultInput } from "../lib/inputKind";

/** 템플릿에서 고르는 입력 종류. 사용자가 직접 고르기 전(picked null)에는 서버 기본 규칙 값을 보이고 요청에는 `input`을 싣지 않는다 */
export function useInputChoice(ps: ParamSet | null | undefined, initial?: PredictInput | null) {
  const cap = capabilityOf(ps);
  const [picked, setPicked] = useState<PredictInput | null>(initial ?? null);
  useEffect(() => setPicked(initial ?? null), [ps?.id]);
  const value: PredictInput = picked && cap.includes(picked) ? picked : defaultInput(cap);
  return { value, picked: picked && cap.includes(picked) ? picked : undefined, setPicked, cap };
}

/** 템플릿 능력 배지: `조립·쿠션 가능` / `쿠션만` / `조립만`. 사유(조립만·쿠션만의 이유)는 툴팁 */
export function TemplateBadge({ ps }: { ps: Pick<ParamSet, "input_capability" | "input_capability_reason" | "input_kind"> }) {
  const b = badgeOf(capabilityOf(ps));
  const reason = ps.input_capability_reason ?? undefined;
  return (
    <span className={`pill tpl-badge ${b === "both" ? "ok" : b === "cushion_only" ? "run" : "warn"}`} data-testid="template-badge" data-kind={b} title={reason}>
      {BADGE_TEXT[b]}
    </span>
  );
}

/** 실행 목록·상세용 입력 종류 배지 */
export function InputBadge({ input }: { input: PredictInput | null | undefined }) {
  if (!input) return <span className="muted">—</span>;
  return (
    <span className={`pill${input === "cushion" ? " run" : ""}`} data-testid="input-badge" data-input={input}>
      {INPUT_LABEL[input]}
    </span>
  );
}

/** `입력: 조립 | 쿠션` 세그먼트. ps가 없으면 그리지 않는다 */
export function InputKindSelect({
  ps,
  value,
  onChange,
  error,
  disabled,
}: {
  ps: ParamSet | null | undefined;
  value: PredictInput;
  onChange: (i: PredictInput) => void;
  /** 서버 422 INPUT_KIND_UNSUPPORTED 문구 */
  error?: string | null;
  disabled?: boolean;
}) {
  if (!ps) return null;
  const cap = capabilityOf(ps);
  const reason = ps.input_capability_reason ?? null;
  const off = (i: PredictInput) => disabled || !cap.includes(i);
  return (
    <div className="field input-kind" data-testid="input-kind">
      <span className="field-label">입력</span>
      <div className="run-action-row">
        <div className="seg" role="radiogroup" aria-label="입력 종류">
          {(["assembly", "cushion"] as const).map((i) => (
            <button
              key={i}
              type="button"
              role="radio"
              aria-checked={value === i}
              className={value === i ? "on" : ""}
              disabled={off(i)}
              title={!cap.includes(i) ? reason ?? "이 템플릿은 이 입력을 쓸 수 없습니다" : undefined}
              onClick={() => onChange(i)}
            >
              {INPUT_LABEL[i]}
            </button>
          ))}
        </div>
      </div>
      {cap.length < 2 && reason && (
        <span className="muted small" data-testid="input-reason">
          {INPUT_LABEL[cap.includes("assembly") ? "cushion" : "assembly"]} 입력 불가: {reason}
        </span>
      )}
      {value === "cushion" && (
        <span className="muted small" data-testid="cushion-note">
          {CUSHION_NOTE}
        </span>
      )}
      {error && (
        <span className="error-text small" role="alert" data-testid="input-error">
          {error}
        </span>
      )}
    </div>
  );
}
