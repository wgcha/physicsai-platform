import { useState, type ReactNode } from "react";
import type { Job, JobState } from "../api";
import { JOB_STATE_LABEL, isTerminal } from "../lib/format";
import { JobLogViewer } from "./JobLogViewer";

export const NO_PERMISSION_TIP = "실행 권한(power 이상)이 필요합니다";

export function Card({
  step,
  title,
  children,
  aside,
  className,
}: {
  step?: string;
  title: string;
  children: ReactNode;
  aside?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className ?? ""}`} aria-label={title}>
      <header className="card-head">
        <h3>
          {step && <span className="card-step">{step}</span>}
          {title}
        </h3>
        {aside}
      </header>
      <div className="card-body">{children}</div>
    </section>
  );
}

export function ProgressBar({ pct: pctIn, label }: { pct: number | null | undefined; label?: string }) {
  const pct = pctIn ?? null;
  return <ProgressBarInner pct={pct} label={label} />;
}

function ProgressBarInner({ pct, label }: { pct: number | null; label?: string }) {
  return (
    <div className="progress" role="progressbar" aria-valuenow={pct ?? undefined} aria-label={label ?? "진행률"}>
      <div className={pct === null ? "progress-fill indeterminate" : "progress-fill"} style={pct === null ? undefined : { width: `${Math.max(0, Math.min(100, pct))}%` }} />
    </div>
  );
}

export function StateDot({ state }: { state: JobState | null | undefined }) {
  if (!state) return null;
  const cls =
    state === "SUCCEEDED" ? "ok" : state === "FAILED" || state === "INTERRUPTED" ? "bad" : state === "QUEUED" ? "wait" : state === "CANCELED" ? "off" : "run";
  return <span className={`dot ${cls}`} title={JOB_STATE_LABEL[state]} />;
}

export function JobStatusBadge({ state }: { state: JobState }) {
  return (
    <span className={`state state-${state.toLowerCase()}`}>
      <StateDot state={state} />
      {JOB_STATE_LABEL[state]}
    </span>
  );
}

/** 버튼 옆 작업 상태: "대기 2번째" / 진행률 / 실패 사유 / 로그 */
export function JobInline({ job }: { job: Job }) {
  const [showLog, setShowLog] = useState(false);
  const active = !isTerminal(job.state);
  return (
    <div className="job-inline">
      <div className="job-inline-row">
        <JobStatusBadge state={job.state} />
        {job.state === "QUEUED" && job.queue_position != null && (
          <span className="muted">대기 {job.queue_position}번째</span>
        )}
        {job.cancel_requested && active && <span className="muted">취소 중</span>}
        {job.state === "RUNNING" && (
          <span className="job-inline-progress">
            <ProgressBar pct={job.progress_pct} />
            <span className="muted small ellipsis">
              {job.progress_pct != null ? `${Math.round(job.progress_pct)}%` : ""} {job.progress_label ?? ""}
            </span>
          </span>
        )}
        {(job.state === "FAILED" || job.state === "INTERRUPTED") && (
          <span className="error-text small">
            {job.failure_code}
            {job.failure_message ? ` — ${job.failure_message}` : ""}
          </span>
        )}
        <button type="button" className="link small" onClick={() => setShowLog((v) => !v)}>
          {showLog ? "로그 닫기" : "로그"}
        </button>
      </div>
      {showLog && <JobLogViewer jobId={job.id} running={active} />}
    </div>
  );
}

/**
 * 단계별 실행 버튼 1개(§16.3). 권한이 없으면 버튼 대신 "조회 전용" 안내.
 */
export function RunAction({
  canExecute,
  label,
  onRun,
  job,
  disabled,
  disabledReason,
  error,
  extra,
}: {
  canExecute: boolean;
  label: string;
  onRun: () => void;
  job?: Job | null;
  disabled?: boolean;
  disabledReason?: string;
  error?: string | null;
  extra?: ReactNode;
}) {
  const busy = !!job && !isTerminal(job.state);
  return (
    <div className="run-action">
      <div className="run-action-row">
        {canExecute ? (
          <button
            type="button"
            className="btn primary"
            onClick={onRun}
            disabled={disabled || busy}
            title={busy ? "이미 실행 중이거나 대기 중입니다" : disabled ? disabledReason : undefined}
          >
            {label}
          </button>
        ) : (
          <span className="readonly" title={NO_PERMISSION_TIP}>
            조회 전용 <span className="muted small">· {NO_PERMISSION_TIP}</span>
          </span>
        )}
        {extra}
        {canExecute && disabled && disabledReason && !busy && <span className="muted small">{disabledReason}</span>}
        {job && <JobInline job={job} />}
      </div>
      {error && <div className="error-text small" role="alert">{error}</div>}
    </div>
  );
}

export function CopyButton({ text, label = "복사" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
      else {
        const ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    } catch {
      /* 무시 */
    }
  };
  return (
    <button type="button" className="btn small ghost" onClick={copy} aria-label={`${label}: ${text.slice(0, 40)}`}>
      {done ? "복사됨" : label}
    </button>
  );
}

export function CodeLine({ text }: { text: string }) {
  return (
    <div className="codeline">
      <code>{text}</code>
      <CopyButton text={text} />
    </div>
  );
}

export function Advanced({ children, label = "고급" }: { children: ReactNode; label?: string }) {
  return (
    <details className="advanced">
      <summary>{label}</summary>
      <div className="advanced-body">{children}</div>
    </details>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}
