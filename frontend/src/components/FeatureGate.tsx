import type { ReactNode } from "react";
import type { FeatureKey, FeatureState } from "../api";
import { useApp } from "../app/AppContext";

/**
 * phase2.md §14.1: `/status.features.<key>.enabled=false`면 버튼 비활성 + "관리자 설정 필요: <키 1~3개>".
 * /status를 아직 못 받았거나 features 자체가 없으면(1차 백엔드) 활성으로 본다.
 */
export function useFeature(key: FeatureKey): FeatureState {
  const { status } = useApp();
  const f = status?.features?.[key];
  if (!f) return { enabled: true, missing: [] };
  return { enabled: !!f.enabled, missing: f.missing ?? [] };
}

export function featureText(f: FeatureState): string {
  const keys = f.missing.slice(0, 3);
  return `관리자 설정 필요: ${keys.length ? keys.join(", ") : "설정 확인"}${f.missing.length > 3 ? " 외" : ""}`;
}

/** 카드의 실행 영역을 감싼다. children(enabled)로 버튼을 비활성화하고, 비활성이면 회색 문구 한 줄을 붙인다. */
export function FeatureGate({ feature, children }: { feature: FeatureKey; children: (enabled: boolean) => ReactNode }) {
  const f = useFeature(feature);
  return (
    <>
      {children(f.enabled)}
      {!f.enabled && (
        <p className="muted small feature-off" data-testid={`feature-off-${feature}`}>
          {featureText(f)}
        </p>
      )}
    </>
  );
}
