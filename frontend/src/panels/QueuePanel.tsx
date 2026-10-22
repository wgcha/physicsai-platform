import { useState, type ReactNode } from "react";
import { api, errorMessage, type CpuQueue, type GpuQueue, type JobSummary } from "../api";
import { useApp } from "../app/AppContext";
import { JOB_TYPE_LABEL, stageDisplayNo, stageMark, attentionText, fmtElapsed, hpcSummaryText } from "../lib/format";
import { ProgressBar, StateDot } from "../components/ui";
import { useOpenJob } from "../hooks/useOpenJob";
import { useRunStatus } from "../shell/RunStatus";
import { DrawerSection } from "./DrawerSection";
import { currentStepText } from "../lib/steps";

/** 실행 대기열(§16.2 ①) — 상태 서랍 안. 순서 이동·취소는 전역 관리자만(§5.3). 데이터는 RunStatusProvider 폴링 */
export function QueuePanel() {
  const { me } = useApp();
  const { queue: q, queueError, reloadQueue: load } = useRunStatus();
  const [actError, setError] = useState<string | null>(null);
  const error = actError ?? queueError;
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const admin = me.is_global_admin;
  const openJob = useOpenJob();

  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setConfirmId(null);
      setError(null);
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
          <span className="stage-badge" title={j.stage === 0 ? "Study 관리" : `${stageDisplayNo(j.stage)}단계`} data-testid="stage-badge">
            {stageMark(j)}
          </span>
          <button type="button" className="qtitle link" onClick={() => void openJob({ job_id: j.id, study_id: j.study_id, project_id: j.project_id })} title="작업 화면으로">
            {JOB_TYPE_LABEL[j.job_type]}
          </button>
          <span className="qmeta ellipsis">
            {j.study_title} · {j.created_by_name}
            {mine && <span className="mine-tag">내 작업</span>}
            {!opts.running && j.resumed && (
              <span data-testid="queue-resumed">
                {" · "}이어서{j.progress_pct != null ? ` · ${Math.round(j.progress_pct)}%` : ""}
                {currentStepText(j) ? ` · ${currentStepText(j)}` : ""}
              </span>
            )}
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
              {j.attention_code && (
                <span className="warn-text" data-testid="queue-attention">
                  {" · "}
                  {attentionText(j.attention_code)}
                </span>
              )}
            </span>
            <span className="muted small ellipsis">
              {fmtElapsed(j.started_at)} 경과{currentStepText(j) ? ` · ${currentStepText(j)}` : ""}
            </span>
          </div>
        ) : opts.running && (
          <div className="qrow-progress">
            <ProgressBar pct={j.progress_pct} />
            <span className="muted small ellipsis">
              {j.progress_pct != null ? `${Math.round(j.progress_pct)}% · ` : ""}
              {fmtElapsed(j.started_at)} 경과
              {currentStepText(j) ? ` · ${currentStepText(j)}` : ""}
              {j.progress_label ? ` · ${j.progress_label}` : ""}
            </span>
          </div>
        )}
      </li>
    );
  };

  /** GPU·CPU 구역 하나: 머리말 + 실행 중 행 + 대기 행(대기 순번은 그 대기열 안 순번) */
  const zone = (key: "gpu" | "cpu", title: string, d: GpuQueue | CpuQueue, head: ReactNode) => (
    <div role="group" aria-label={title} data-testid={`queue-${key}`}>
      <div className="qsec-label">
        {title} <span className="muted small">{head}</span>
      </div>
      <ul className="qlist">
        {d.running.length + d.queued.length === 0 && <li className="empty small">없음</li>}
        {d.running.map((j) => row(j, { running: true }))}
        {d.queued.map((j, i) => row(j, { pos: j.queue_position ?? i + 1, total: d.queued.length }))}
      </ul>
    </div>
  );

  const queued = q?.queued ?? [];
  const lightJobs = q ? [...(q.light.running ? [q.light.running] : []), ...q.light.queued] : [];
  const hpc = q ? [...q.waiting_hpc, ...q.collecting] : [];
  // 옛 응답(gpu·cpu 없음)은 단일 대기열로 그대로 보인다(job-queues.md §8.1 deprecated 필드)
  const split = q?.gpu && q?.cpu ? { gpu: q.gpu, cpu: q.cpu } : null;

  return (
    <DrawerSection label="실행 대기열" refText={split ? undefined : `로컬 슬롯 1개 · 대기 ${queued.length}건`}>
      {error && <div className="error-text small">{error}</div>}
      {!q ? (
        <div className="empty small">불러오는 중…</div>
      ) : (
        <>
          {split ? (
            <>
              {zone("gpu", "GPU 대기열", split.gpu, `${split.gpu.limit}개씩 · 대기 ${split.gpu.queued.length}건`)}
              {zone(
                "cpu",
                "CPU 대기열",
                split.cpu,
                <>
                  동시 {split.cpu.limit}개 · 실행 {split.cpu.running.length} · 대기 {split.cpu.queued.length}건
                  {split.cpu.memory_gate === "low" && (
                    <span className="warn-text" data-testid="queue-memory-gate">
                      {" · "}여유 메모리 부족으로 대기
                    </span>
                  )}
                </>,
              )}
            </>
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
            </>
          )}
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
    </DrawerSection>
  );
}
