// 결과 컨투어 칸(contour3d-default §3.1 ContourSlot): ④⑤ 결과 컨투어 자리의 기본 = 3D 뷰어. 칸이 화면에 보이면 자동 요청(C3D-3), 행 선택은 머무른 뒤(C3D-4),
// 429면 간격을 두고 재요청(C3D-5). features.contour3d=false·WebGL 불가·원본 없음 → media(PNG·영상)가 그 자리에 바로 나온다(C3D-2, 요청 없음).
// 3D일 때만 카드 머리 aside용 [그림/영상] 버튼(MediaButton)을 함께 낸다 — 대기·실패 화면에도(실패는 PNG가 이미 인라인이라 버튼을 숨김).
// children은 render prop: 카드 머리(aside)와 본문(body)을 한 번에 받아 Card에 꽂는다.
import { Suspense, useState, type ReactNode } from "react";
import type { Contour3dCreate } from "../../../../api";
import { useFeature } from "../../../../components/FeatureGate";
import { useInView } from "../../../../hooks/useInView";
import { ChunkErrorBoundary, lazyWithReload } from "../../../../lib/lazyWithReload";
import { webglAvailable } from "../webgl";
import { featureOffText, NO_SOURCE_TEXT, showsMedia, WEBGL_TEXT } from "./contourCore";
import { ReasonLine } from "./ContourReason";
import { MediaButton } from "./MediaDialog";
import { useContour3d } from "./useContour3d";

// 대기 안내·뷰어는 칸이 3D일 때만 적재(three는 loadThree가 따로 적재)
export const ContourStateView = lazyWithReload(() => import("./ContourBody").then((m) => ({ default: m.ContourStateView })));

/** 3D를 쓸 수 있는가: features.contour3d 켬 + WebGL2 (아니면 PNG 인라인) */
export function useContour3dEnabled(): boolean {
  const f = useFeature("contour3d");
  const [gl] = useState(webglAvailable);
  return f.enabled && gl;
}

/** 3D를 쓸 수 없을 때 PNG 위에 보일 사유(§12): 기능 꺼짐(missing 첫 키) → WebGL 불가 → 원본 없음. 쓸 수 있으면 null */
export function useContour3dOff(hasSource: boolean): string | null {
  const f = useFeature("contour3d");
  const [gl] = useState(webglAvailable);
  if (!f.enabled) return featureOffText(f.missing);
  if (!gl) return WEBGL_TEXT;
  return hasSource ? null : NO_SOURCE_TEXT;
}

export interface SlotRender {
  /** 카드 머리 aside([그림/영상] 버튼) — 3D가 아니거나 media가 없으면 null */
  aside: ReactNode;
  body: ReactNode;
  mode: "3d" | "media";
}

export function ContourSlot({ source, media = null, mediaTitle, delayMs, children }: { source: Contour3dCreate | null; media?: ReactNode; mediaTitle?: string; delayMs?: number; children: (r: SlotRender) => ReactNode }) {
  const enabled = useContour3dEnabled();
  const off = useContour3dOff(!!source);
  const [inView, ref] = useInView();
  const live = enabled && !!source;
  const ctl = useContour3d(live ? source : null, { visible: inView, delayMs });
  if (!live)
    return (
      <>
        {children({
          aside: null,
          mode: "media",
          body: (
            <div className="contour-slot media">
              {off && <ReasonLine text={off} />}
              {media}
            </div>
          ),
        })}
      </>
    );
  const aside = media != null && !showsMedia(ctl) ? <MediaButton title={mediaTitle}>{media}</MediaButton> : null;
  const body = (
    <div className="contour-slot" ref={ref} data-testid="contour-slot">
      <ChunkErrorBoundary extra={media}>
        <Suspense fallback={<div className="c3-box muted small">불러오는 중…</div>}>
          <ContourStateView ctl={ctl} media={media} />
        </Suspense>
      </ChunkErrorBoundary>
    </div>
  );
  return <>{children({ aside, mode: "3d", body })}</>;
}
