// 3D를 쓸 수 없을 때의 패널: 이유 한 줄(항상) + 그림(선택 변수 PNG) + [다시 시도] + 접힌 진단 한 줄.
// 어떤 PC에서도 빈 패널이 없도록 3D 패널·지연 적재·예외 경계가 모두 이 컴포넌트로 떨어진다.
import { diagText, gvReasonText, noteGvError, retryable, webglInfo, type GvFailure } from "./webgl";
import { PngGrid } from "./PngGrid";

export interface PngProps {
  rows: string[];
  pngOf: (row: string) => string | null;
  firstRow?: string | null;
  onRows?: (rows: string[], focus?: string | null) => void;
}

export function ViewFallback({ reason, onRetry, ...png }: { reason: GvFailure; onRetry?: () => void } & PngProps) {
  if (reason.kind !== "loading") noteGvError(reason.kind, reason.code);
  return (
    <div className="gv-wrap" data-testid="gv-fallback-panel">
      <p className="muted small" data-testid="gv-fallback" role={reason.kind === "loading" ? undefined : "status"}>
        {gvReasonText(reason)}
        {onRetry && retryable(reason) && (
          <>
            {" "}
            <button type="button" className="link small" onClick={onRetry}>
              다시 시도
            </button>
          </>
        )}
      </p>
      <PngGrid {...png} />
      {reason.kind !== "loading" && (
        <details className="gv-diag small muted" data-testid="gv-diag">
          <summary>진단 정보</summary>
          <div className="mono">{diagText(webglInfo())}</div>
        </details>
      )}
    </div>
  );
}
