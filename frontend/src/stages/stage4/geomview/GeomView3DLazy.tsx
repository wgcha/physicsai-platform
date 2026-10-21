// 3D 패널 지연 적재(geometry-view.md §7.1 첫 화면 청크 증가 최소): 패널 UI는 별도 청크, three는 그 안에서 다시 동적 import.
// 적재 전·실패 시에는 그림(기존 PNG)을 보인다.
import { Suspense } from "react";
import { ChunkErrorBoundary, lazyWithReload } from "../../../lib/lazyWithReload";
import type { GeomView3DProps } from "./GeomView3D";

const Panel = lazyWithReload(() => import("./GeomView3D").then((m) => ({ default: m.GeomView3D })));

export function GeomView3DLazy(props: GeomView3DProps) {
  return (
    <ChunkErrorBoundary extra={props.picture}>
      <Suspense fallback={props.picture}>
        <Panel {...props} />
      </Suspense>
    </ChunkErrorBoundary>
  );
}
