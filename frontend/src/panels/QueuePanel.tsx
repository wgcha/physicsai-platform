import { useCallback, useState } from "react";
import { api, errorMessage, type JobSummary, type QueueInfo } from "../api";
import { useApp } from "../app/AppContext";
import { usePolling } from "../hooks/usePolling";
import { POLL } from "../lib/poll";
import { JOB_TYPE_LABEL, STAGE_MARK, fmtElapsed, hpcSummaryText } from "../lib/format";
import { ProgressBar, StateDot } from "../components/ui";
import { useOpenJob } from "../shell/useOpenJob";

/** 실행 대기열(§16.2 ①). 순서 이동·취소는 전역 관리자만(§5.3). */
export function QueuePanel() {
  const { me } = useApp();
  const [q, setQ] = useState<QueueInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const admin = me.is_global_admin;
  const openJob = useOpenJob();

  const load = useCallback(async () => {
    try {
      setQ(await api.queue());
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  usePolling(load, POLL.queue);

  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setConfirmId(null);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const row = (j: JobSummary, opts: { pos?: number; total?: number; running?: boolean; hpc?: boolean }) => {
    const mine = j.created_by === me.user_id;
    return (
      <li key={j.id} className={`qrow ${mine ? "mine" : ""}`} data-testid="queue-row">
        <div className="qrow-main">
          <span className="qpos">{opts.running ? <StateDot state={j.state} /> : opts.pos}</span>
          <span className="stage-badge" title={`${j.stage}단계`} data-testid="stage-badge">
            {j.stage_label || STAGE_MARK[j.stage] || j.stage}
          </span>
          <button type="button" className="qtitle link" onClick={() => void openJob({ job_id: j.id, study_id: j.study_id, project_id: j.project_id })} title="작업 화면으로">
            {JOB_TYPE_LABEL[j.job_type]}
          </button>
          <span className="qmeta ellipsis">
            {j.study_title} · {j.created_by_name}
            {mine && <span className="mine-tag">내 작업</span>}
          </span>
          {admin && (
            <span className="qctl">
              {opts.pos !== undefined && (
                <>
                  <button type="button" className="icon-btn" aria-label="위로" disabled={opts.pos <= 1} onClick={() => act(() => api.moveQueue(j.id, opts.pos! - 1))}>
                    ▲
                  </button>
                  <button type="button" className="icon-btn" aria-label="아래로" disabled={opts.pos >= (opts.total ?? 0)} onClick={() => act(() => api.moveQueue(j.id, opts.pos! + 1))}>
                    ▼
                  </button>
                </>
              )}
              {confirmId === j.id ? (
                <button type="button" className="btn small danger" onClick={() => act(() => api.cancelJob(j.id))}>
                  취소 확인
                </button>
              ) : (
                <button type="button" className="btn small ghost" onClick={() => setConfirmId(j.id)} disabled={j.cancel_requested}>
                  {j.cancel_requested ? "취소 중" : "취소"}
                </button>
              )}
            </span>
          )}
        </div>
        {opts.hpc ? (
          <div className="qrow-progress hpc">
            <span className="small" data-testid="hpc-summary">
              {j.hpc_summary ? hpcSummaryText(j.hpc_summary) : j.state === "COLLECTING" ? "결과 회수 중" : "PBS 대기"}
            </span>
            <span className="muted small ellipsis">
              {fmtElapsed(j.started_at)} 경과{j.current_step_label ? ` · ${j.current_step_label}` : ""}
            </span>
          </div>
        ) : opts.running && (
          <div className="qrow-progress">
            <ProgressBar pct={j.progress_pct} />
            <span className="muted small ellipsis">
              {j.progress_pct != null ? `${Math.round(j.progress_pct)}% · ` : ""}
              {fmtElapsed(j.started_at)} 경과
              {j.current_step_label ? ` · ${j.current_step_label}` : ""}
              {j.progress_label ? ` · ${j.progress_label}` : ""}
            </span>
          </div>
        )}
      </li>
    );
  };

  const queued = q?.queued ?? [];
  const lightJobs = q ? [...(q.light.running ? [q.light.running] : []), ...q.light.queued] : [];
  const hpc = q ? [...q.waiting_hpc, ...q.collecting] : [];

  return (
    <section className="panel" aria-label="실행 대기열">
      <header className="panel-head">
        <h2>실행 대기열</h2>
        <span className="muted small">로컬 슬롯 1개 · 대기 {queued.length}건</span>
      </header>
      {error && <div className="error-text small">{error}</div>}
      {!q ? (
        <div className="empty small">불러오는 중…</div>
      ) : (
        <>
          <div className="qsec-label">실행 중</div>
          <ul className="qlist">{q.running ? row(q.running, { running: true }) : <li className="empty small">없음</li>}</ul>
          <div className="qsec-label">대기</div>
          <ul className="qlist">
            {queued.length === 0 ? (
              <li className="empty small">없음</li>
            ) : (
              queued.map((j, i) => row(j, { pos: j.queue_position ?? i + 1, total: queued.length }))
            )}
          </ul>
          {lightJobs.length > 0 && (
            <>
              <div className="qsec-label">가벼운 작업(슬롯 불필요)</div>
              <ul className="qlist">{lightJobs.map((j) => row(j, { running: j.state === "RUNNING" }))}</ul>
            </>
          )}
          {hpc.length > 0 && (
            <>
              <div className="qsec-label">PBS 대기·회수</div>
              <ul className="qlist">{hpc.map((j) => row(j, { running: true, hpc: true }))}</ul>
            </>
          )}
        </>
      )}
    </section>
  );
}
