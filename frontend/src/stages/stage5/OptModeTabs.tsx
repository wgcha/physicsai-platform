// ⑥ 맨 위 모드 선택(phase3.md §18.10 + opt-native §4.4): 플랫폼 내장(기본) | 원본 최적화(HyperStudy·레거시). 선택은 브라우저별 기억.
// 원본 탭은 features.optimize가 꺼져 있으면(HyperStudy 미설정) 숨긴다. 내장이 꺼져 있어도 원본으로 떨어지지 않고 사유를 보인다.
import { Card } from "../../components/ui";
import { useFeature, featureText } from "../../components/FeatureGate";
import type { OptMode } from "./surrogate/soRules";

export const MODES: { key: OptMode; label: string; hint: string }[] = [
  { key: "builtin", label: "플랫폼 내장", hint: "④ 예측 체인으로 설계를 검증하며 대리모델(GP·RBF)과 EGO·GA·NSGA-II로 다음 후보를 고릅니다 — 메시 단독 템플릿도 동작" },
  { key: "original", label: "원본 최적화(HyperStudy·레거시)", hint: "원본 HyperStudy 런처로 최적화합니다 — 조립 폴더가 있는 템플릿만" },
];

/** 원본(HyperStudy) 탭을 보일지: features.optimize.enabled(레거시 — 미설정이면 숨김) */
export function useOriginalVisible(): boolean {
  return useFeature("optimize").enabled;
}

export function OptModeTabs({ mode, onChange }: { mode: OptMode; onChange: (m: OptMode) => void }) {
  const f = useFeature("optimize_builtin");
  const showOriginal = useOriginalVisible();
  const modes = MODES.filter((m) => m.key !== "original" || showOriginal);
  const cur = modes.find((m) => m.key === mode) ?? modes[0];
  return (
    <Card span={9} title="최적화 방식" className="opt-mode">
      <div className="seg" role="radiogroup" aria-label="최적화 방식">
        {modes.map((m) => (
          <button key={m.key} type="button" role="radio" aria-checked={cur.key === m.key} className={cur.key === m.key ? "on" : ""}
            title={m.key === "builtin" && !f.enabled ? featureText(f) : undefined} onClick={() => onChange(m.key)}>
            {m.label}
          </button>
        ))}
      </div>
      <p className="muted small" data-testid="opt-mode-hint">
        {cur.hint}
        {!f.enabled && <> · 내장 모드: {featureText(f)}</>}
      </p>
    </Card>
  );
}
