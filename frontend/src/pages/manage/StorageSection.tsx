import { useCallback, useEffect, useState } from "react";
import { api, errorMessage, type Job, type Study, type StorageReport } from "../../api";
import { Card, CodeLine, JobInline, NO_PERMISSION_TIP } from "../../components/ui";
import { usePolling } from "../../hooks/usePolling";
import { fmtBytes, fmtElapsed, fmtTime } from "../../lib/format";
import { CleanupPreview } from "./CleanupPreview";
import { StorageBars, TopFiles } from "./StorageBars";
import { BACKUP_NOTICE } from "./storage";

/** 실행 중 재조회 주기(phase3.md §5.8: 3초). 시험에서 줄일 수 있도록 가변 객체 */
export const STORAGE_POLL = { ms: 3000 };

/** phase3.md §5.8 ③ 용량·정리 */
export function StorageSection({ study }: { study: Study }) {
  const [report, setReport] = useState<StorageReport | null>(null);
  const [active, setActive] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const rep = await api.studyStorage(study.id);
      const id = rep.active_cleanup_job_id ?? rep.active_scan_job_id;
      setActive(id ? await api.job(id) : null);
      setReport(rep);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [study.id]);

  useEffect(() => void load(), [load]);
  const running = !!(report?.active_scan_job_id || report?.active_cleanup_job_id);
  usePolling(load, running ? STORAGE_POLL.ms : null, false, [study.id]);

  const recalc = async () => {
    setError(null);
    try {
      await api.createJob(study.id, "STUDY_STORAGE_SCAN", {});
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const scan = report?.scan ?? null;
  return (
    <Card step="③" title="용량·정리">
      {!report ? (
        error ? <div className="error-text small" role="alert">{error}</div> : <div className="empty">불러오는 중…</div>
      ) : (
        <>
          <div className="storage-summary" data-testid="storage-summary">
            {scan ? (
              <>
                <strong>
                  전체 {fmtBytes(scan.total_bytes)} · 파일 {scan.total_files}개 · 백업 {fmtBytes(scan.backup_bytes)}
                </strong>
                <span className="muted small">
                  계산 시각 {fmtTime(scan.finished_at)} ({fmtElapsed(scan.finished_at)} 전)
                  {scan.partial && " · 부분 스캔"}
                  {scan.skipped_links > 0 && ` · 링크 ${scan.skipped_links}개 제외`}
                  {scan.errors > 0 && ` · 읽지 못한 항목 ${scan.errors}개`}
                </span>
              </>
            ) : (
              <span>아직 계산하지 않았습니다</span>
            )}
            {scan && report.stale && <div className="warn-text small">주의: {report.stale_reason} — 정리하려면 다시 계산하세요</div>}
          </div>
          <div className="run-action-row">
            {study.can_execute ? (
              <button type="button" className="btn" disabled={!!report.active_scan_job_id || !!report.active_cleanup_job_id} onClick={recalc}>
                다시 계산
              </button>
            ) : (
              <span className="muted small" title={NO_PERMISSION_TIP}>
                계산·정리: {NO_PERMISSION_TIP}
              </span>
            )}
            {active && <JobInline job={active} />}
          </div>
          {error && (
            <div className="error-text small" role="alert">
              {error}
            </div>
          )}
          {scan && (
            <>
              <StorageBars scan={scan} />
              <h4 className="cleanup-title">큰 파일</h4>
              <TopFiles files={scan.top_files} />
              <CleanupPreview studyId={study.id} report={report} canExecute={study.can_execute} onStarted={load} />
            </>
          )}
          {report.last_cleanup && <LastCleanup c={report.last_cleanup} />}
          <p className="muted small backup-notice" data-testid="backup-notice">
            {BACKUP_NOTICE}
          </p>
          {report.backup_display_path && <CodeLine text={report.backup_display_path} />}
        </>
      )}
    </Card>
  );
}

function LastCleanup({ c }: { c: NonNullable<StorageReport["last_cleanup"]> }) {
  return (
    <div className="last-cleanup" data-testid="last-cleanup">
      <div>
        최근 정리: {fmtTime(c.finished_at)} · {c.moved_count}개 {fmtBytes(c.moved_bytes)} 이동 · 건너뜀 {c.skipped_count}개
        {c.state !== "SUCCEEDED" && <span className="warn-text small"> ({c.state})</span>}
      </div>
      {c.backup_display_path && <CodeLine text={c.backup_display_path} />}
      {c.skipped.length > 0 && (
        <details>
          <summary>건너뛴 항목 사유</summary>
          <ul className="small">
            {c.skipped.map((s) => (
              <li key={s.rel}>
                <span className="mono">{s.rel}</span> — {s.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
