import { useState } from "react";
import type { PredictInputMode } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useFeature } from "../../components/FeatureGate";
import { Card } from "../../components/ui";
import { ParamSetCard } from "./ParamSetCard";
import { PredictWorkspace } from "./PredictWorkspace";
import { PreparedPredictCard } from "./PreparedPredictCard";

/** 입력 방식 기억(브라우저별 편의). 접근 실패해도 기본값으로 정상 렌더 */
export const INPUT_MODE_KEY = "physicsai.stage4.inputMode";
export const PARAMETRIC_OFF_TEXT = "형상 갱신 설정 필요(관리자)";

function readMode(): PredictInputMode {
  try {
    return globalThis.localStorage?.getItem(INPUT_MODE_KEY) === "prepared" ? "prepared" : "parametric";
  } catch {
    return "parametric";
  }
}

function writeMode(m: PredictInputMode) {
  try {
    globalThis.localStorage?.setItem(INPUT_MODE_KEY, m);
  } catch {
    /* 저장 실패는 무시(이번 화면에서만 유지) */
  }
}

const MODES: { key: PredictInputMode; label: string; note: string }[] = [
  { key: "parametric", label: "파라미터로 형상 생성", note: "파라미터 세트로 형상·메시·입력파일을 만든 뒤 예측합니다." },
  { key: "prepared", label: "준비된 입력 파일", note: "준비된 Radioss starter(.rad) 또는 .hm으로 바로 예측합니다." },
];

function InputModeCard({ mode, parametricEnabled, onChange }: { mode: PredictInputMode; parametricEnabled: boolean; onChange: (m: PredictInputMode) => void }) {
  return (
    <Card span={9} title="입력 방식" className="input-mode">
      <div className="input-mode-row">
        <div className="seg" role="radiogroup" aria-label="입력 방식">
          {MODES.map((m) => {
            const off = m.key === "parametric" && !parametricEnabled;
            return (
              <button
                key={m.key}
                type="button"
                role="radio"
                aria-checked={mode === m.key}
                className={mode === m.key ? "on" : ""}
                disabled={off}
                title={off ? PARAMETRIC_OFF_TEXT : undefined}
                onClick={() => onChange(m.key)}
              >
                {m.label}
              </button>
            );
          })}
        </div>
        {!parametricEnabled && (
          <span className="muted small" data-testid="parametric-off">
            {PARAMETRIC_OFF_TEXT}
          </span>
        )}
      </div>
      <p className="muted small">{MODES.find((m) => m.key === mode)!.note}</p>
    </Card>
  );
}

/** ④ 단일 예측(§16.5) — 입력 방식: 파라미터로 형상 생성(기본) / 준비된 입력 파일(phase3.md §11.5) */
export function Stage4() {
  const { currentParamSet } = useStudy();
  const parametric = useFeature("predict_parametric");
  const [stored, setStored] = useState<PredictInputMode>(readMode);
  const mode: PredictInputMode = parametric.enabled ? stored : "prepared";
  const choose = (m: PredictInputMode) => {
    setStored(m);
    writeMode(m);
  };
  return (
    <>
      <InputModeCard mode={mode} parametricEnabled={parametric.enabled} onChange={choose} />
      {mode === "parametric" ? (
        <>
          <ParamSetCard />
          {currentParamSet && <PredictWorkspace key={currentParamSet.id} ps={currentParamSet} />}
        </>
      ) : (
        <PreparedPredictCard />
      )}
    </>
  );
}
