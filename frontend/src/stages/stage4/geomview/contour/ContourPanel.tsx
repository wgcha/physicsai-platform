// [3D 컨투어] 버튼 + 열 때 생성 대기 안내 + 뷰어(geometry-view.md §13.6). 기존 PNG·영상 UI는 그대로 두고 아래에 접힘으로 붙인다.
// features.contour3d=false거나 WebGL 불가면 숨김. 생성 요청은 power(아니면 버튼 비활성 + 사유).
import { lazy, Suspense, useState } from "react";
import type { Contour3dCreate } from "../../../../api";
import { useFeature } from "../../../../components/FeatureGate";
import { useCanExecute } from "../../../../hooks/useJobRunner";
import { webglAvailable } from "../webgl";

// 대기 안내·뷰어는 열 때만 적재(별도 청크)
const ContourBody = lazy(() => import("./ContourBody").then((m) => ({ default: m.ContourBody })));

export function ContourPanel({ source, label = "3D 컨투어", defaultOpen = false }: { source: Contour3dCreate; label?: string; defaultOpen?: boolean }) {
  const f = useFeature("contour3d");
  const canExec = useCanExecute();
  const [gl] = useState(webglAvailable);
  const [open, setOpen] = useState(defaultOpen && canExec);
  if (!f.enabled || !gl) return null;
  return (
    <div className="c3-panel" data-testid="contour3d-panel">
      <div className="run-action-row">
        <button type="button" className={`btn small${open ? " on" : ""}`} aria-expanded={open} disabled={!canExec && !open} onClick={() => setOpen((o) => !o)} title={canExec ? "해석 결과 컨투어를 3D로 돌려 보고 시간 순서로 재생합니다" : "실행 권한(power 이상)이 필요합니다"}>
          {label}
        </button>
        {!open && <span className="muted small">처음 열 때 만들고, 다음부터는 바로 열립니다</span>}
      </div>
      {open && (
        <Suspense fallback={<div className="c3-box muted small">불러오는 중…</div>}>
          <ContourBody source={source} />
        </Suspense>
      )}
    </div>
  );
}
