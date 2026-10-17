// ⑤ 맨 위 모드 선택(phase3.md §18.10): 플랫폼 내장(쿠션만 가능, 기본) | 원본 최적화(조립 필요). 선택은 브라우저별 기억.
import { Card } from "../../components/ui";
import { useFeature, featureText } from "../../components/FeatureGate";
import type { OptMode } from "./surrogate/soRules";

const MODES: { key: OptMode; label: string; hint: string }[] = [
  { key: "builtin", label: "플랫폼 내장(쿠션만 가능)", hint: "④ 예측 체인으로 설계를 검증하며 대리모델(GP·RBF)로 다음 후보를 고릅니다 — 메시 단독 템플릿도 동작" },
  { key: "original", label: "원본 최적화(조립 필요)", hint: "원본 HyperStudy 런처로 최적화합니다 — 조립 폴더가 있는 템플릿만" },
];

export function OptModeTabs({ mode, onChange }: { mode: OptMode; onChange: (m: OptMode) => void }) {
  const f = useFeature("optimize_builtin");
  const cur = MODES.find((m) => m.key === mode)!;
  return (
    <Card span={9} title="최적화 방식" className="opt-mode">
      <div className="seg" role="radiogroup" aria-label="최적화 방식">
        {MODES.map((m) => {
          const off = m.key === "builtin" && !f.enabled;
          return (
            <button key={m.key} type="button" role="radio" aria-checked={mode === m.key} className={mode === m.key ? "on" : ""}
              disabled={off} title={off ? featureText(f) : undefined} onClick={() => onChange(m.key)}>
              {m.label}
            </button>
          );
        })}
      </div>
      <p className="muted small" data-testid="opt-mode-hint">
        {cur.hint}
        {!f.enabled && <> · 내장 모드: {featureText(f)}</>}
      </p>
    </Card>
  );
}
