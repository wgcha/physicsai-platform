// 3D 패널 지연 적재(geometry-view.md §7.1 첫 화면 청크 증가 최소): 패널 UI는 별도 청크, three는 그 안에서 다시 동적 import.
// 적재 전·청크 로드 실패(이전 캐시·네트워크)·패널 예외 시에는 그림 폴백(이유 한 줄 + [다시 시도])을 보인다 — 빈 패널 없음.
import { Component, useEffect, useState, type ComponentType, type ReactNode } from "react";
import type { GeomView3DProps } from "./GeomView3D";
import { ViewFallback } from "./ViewFallback";
import { errCode, type GvFailure } from "./webgl";

type Panel = ComponentType<GeomView3DProps>;
let panel: Promise<Panel> | null = null;
/** 한 번 받은 청크는 재사용, 실패하면 다음 시도에서 다시 받는다 */
function loadPanel(): Promise<Panel> {
  panel ??= import("./GeomView3D")
    .then((m) => m.GeomView3D as Panel)
    .catch((e) => {
      panel = null;
      throw e;
    });
  return panel;
}

/** 패널 렌더 중 예외 → 폴백(다시 시도 = 경계 초기화) */
class ViewBoundary extends Component<{ render: (err: GvFailure | null, reset: () => void) => ReactNode; children: ReactNode }, { err: GvFailure | null }> {
  state: { err: GvFailure | null } = { err: null };
  static getDerivedStateFromError(e: unknown) {
    return { err: { kind: "init", code: errCode(e) } as GvFailure };
  }
  render() {
    return this.state.err ? this.props.render(this.state.err, () => this.setState({ err: null })) : this.props.children;
  }
}

export function GeomView3DLazy(props: GeomView3DProps) {
  const [Comp, setComp] = useState<Panel | null>(null);
  const [fail, setFail] = useState<GvFailure | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let alive = true;
    setFail(null);
    loadPanel()
      .then((c) => alive && setComp(() => c))
      .catch((e) => alive && setFail({ kind: "chunk", code: errCode(e) }));
    return () => {
      alive = false;
    };
  }, [attempt]);
  const png = { rows: props.rows, pngOf: props.pngOf, firstRow: props.firstRow, onRows: props.onRows };
  if (fail) return <ViewFallback reason={fail} onRetry={() => setAttempt((n) => n + 1)} {...png} />;
  if (!Comp) return <ViewFallback reason={{ kind: "loading" }} {...png} />;
  return (
    <ViewBoundary render={(err, reset) => <ViewFallback reason={err!} onRetry={reset} {...png} />}>
      <Comp {...props} />
    </ViewBoundary>
  );
}
