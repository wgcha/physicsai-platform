import { useState } from "react";
import { api, errorMessage, type Job } from "../api";

/** phase2.md §10·§14.1: 실패·취소·중단(또는 attention_code) 작업의 "오류 묶음 받기" — 등록자 본인·전역 관리자만(can_download_error_bundle) */
export function errorBundleAvailable(job: Job): boolean {
  if (!job.can_download_error_bundle) return false;
  return job.state === "FAILED" || job.state === "CANCELED" || job.state === "INTERRUPTED" || !!job.attention_code;
}

export function ErrorBundleButton({ job }: { job: Job }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!errorBundleAvailable(job)) return null;
  const download = async () => {
    setBusy(true);
    setError(null);
    try {
      const blob = await api.errorBundle(job.id);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${job.id.slice(0, 8)}_error_bundle.zip`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <button type="button" className="btn small" onClick={download} disabled={busy} title="로그·명령·설정 요약을 zip으로 받습니다(비밀값 마스킹)">
        {busy ? "준비 중…" : "오류 묶음 받기"}
      </button>
      {error && <span className="error-text small">{error}</span>}
    </>
  );
}
