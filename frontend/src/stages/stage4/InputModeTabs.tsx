// ④ 맨 위 "입력 방식" 3개(phase3.md §14.8): 템플릿 값 입력(기본) / 일괄 예측(DOE) / 준비된 입력 파일. 선택은 브라우저별로 기억한다.
import { Link } from "react-router-dom";
import type { InputMode } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { Card } from "../../components/ui";

/** 입력 방식 기억(브라우저별 편의). 접근 실패해도 기본값으로 정상 렌더 */
export const INPUT_MODE_KEY = "physicsai.stage4.inputMode";
export const TEMPLATE_OFF_TEXT = "형상 갱신 설정 필요(관리자)";

/** 저장 값 읽기. 옛 값 parametric(S6) → template */
export function readInputMode(): InputMode {
  try {
    const v = globalThis.localStorage?.getItem(INPUT_MODE_KEY);
    return v === "batch" || v === "prepared" ? v : "template";
  } catch {
    return "template";
  }
}

export function writeInputMode(m: InputMode) {
  try {
    globalThis.localStorage?.setItem(INPUT_MODE_KEY, m);
  } catch {
    /* 저장 실패는 무시(이번 화면에서만 유지) */
  }
}

export const INPUT_MODES: { key: InputMode; label: string; note: string }[] = [
  { key: "template", label: "템플릿 값 입력", note: "값 몇 개로 형상 1개를 바로 예측합니다." },
  { key: "batch", label: "일괄 예측(DOE)", note: "여러 조합을 한 번에 만들어 예측하고, 결과를 표로 비교합니다." },
  { key: "prepared", label: "준비된 입력 파일", note: "준비된 Radioss starter(.rad) 또는 .hm으로 바로 예측합니다." },
];

export function InputModeTabs({ mode, templateEnabled, onChange }: { mode: InputMode; templateEnabled: boolean; onChange: (m: InputMode) => void }) {
  const { study } = useStudy();
  return (
    <Card span={9} title="입력 방식" className="input-mode">
      <div className="input-mode-row">
        <div className="seg" role="radiogroup" aria-label="입력 방식">
          {INPUT_MODES.map((m) => {
            const off = m.key !== "prepared" && !templateEnabled;
            return (
              <button
                key={m.key}
                type="button"
                role="radio"
                aria-checked={mode === m.key}
                className={mode === m.key ? "on" : ""}
                disabled={off}
                title={off ? TEMPLATE_OFF_TEXT : undefined}
                onClick={() => onChange(m.key)}
              >
                {m.label}
              </button>
            );
          })}
        </div>
        <span className="muted small" data-testid="input-mode-note">
          {INPUT_MODES.find((m) => m.key === mode)!.note}
        </span>
        <Link className="small" to={`/p/${study.project_id}/s/${study.id}/stage/4/verify`} data-testid="fv-list-link">
          FEM 검증 목록
        </Link>
        {!templateEnabled && (
          <span className="muted small" data-testid="template-off">
            {TEMPLATE_OFF_TEXT}
          </span>
        )}
      </div>
    </Card>
  );
}
