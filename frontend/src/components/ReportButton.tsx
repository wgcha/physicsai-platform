// "HTML 보고서" 보조 버튼(upload-report.md §9.4): 서버가 현재 화면 선택 기준으로 만든 단일 HTML 을 fetch → blob → 내려받기(서버가 준 파일 이름 사용).
// 대상이 끝나지 않았으면(notReady 사유 또는 서버 409 REPORT_NOT_READY) 비활성 + 이유 표시. resetKey 가 바뀌면(선택 변경) 서버 409 로 막힌 상태를 푼다.
import { useEffect, useState } from "react";
import { ApiError, errorMessage } from "../api";
import { saveBlob } from "../lib/download";

export const NOT_READY_TEXT = "끝난 뒤 받을 수 있습니다";

export function ReportButton({
  load,
  fallbackName,
  notReady,
  resetKey,
  disabled,
}: {
  load: () => Promise<{ blob: Blob; filename: string | null }>;
  /** 서버가 파일 이름을 안 줄 때 */
  fallbackName: string;
  /** 화면이 아는 미완료 사유(있으면 비활성) */
  notReady?: string | null;
  resetKey?: string;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [blocked, setBlocked] = useState<string | null>(null);
  useEffect(() => {
    setBlocked(null);
    setError(null);
  }, [resetKey]);
  const reason = notReady ?? blocked;
  const click = async () => {
    setBusy(true);
    setError(null);
    try {
      const { blob, filename } = await load();
      saveBlob(blob, filename ?? fallbackName);
    } catch (e) {
      if (e instanceof ApiError && e.code === "REPORT_NOT_READY") setBlocked(e.message || NOT_READY_TEXT);
      else setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="report-btn run-action-row">
      <button type="button" className="btn small" data-testid="report-btn" disabled={busy || !!reason || disabled} title={reason ?? "단일 파일 HTML 보고서를 받습니다(외부 연결 없이 열림)"} onClick={() => void click()}>
        {busy ? "만드는 중…" : "HTML 보고서"}
      </button>
      {reason && <span className="muted small" data-testid="report-reason">{reason}</span>}
      {error && <span className="error-text small" role="alert" data-testid="report-error">{error}</span>}
    </span>
  );
}
