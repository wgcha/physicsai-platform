import { useState } from "react";
import { api, errorMessage, type Job } from "../api";
import { useStudyOptional } from "../app/StudyContext";
import { JOB_TYPE_LABEL } from "../lib/format";
import { emitJobRetried } from "../hooks/jobRetried";
import { ConfirmDialog } from "./ConfirmDialog";

/** HPC 제출 이력을 재사용하지 않아 항상 처음부터 다시 하는 유형(서버 retry_job과 같음) */
const ALWAYS_FROM_START = new Set(["TD_SOLVE", "PREDICT_VERIFY"]);
const RESUME_STATES = new Set(["FAILED", "CANCELED", "PENDING", "RUNNING"]);

/** 확인 대화상자의 시작 지점: 첫 FAILED·CANCELED·PENDING·RUNNING step의 "{step_no}. {표시명}" */
export function retryStartText(job: Job): string {
  if (ALWAYS_FROM_START.has(job.job_type)) return "처음(1단계)";
  const st = job.steps.find((s) => RESUME_STATES.has(s.state));
  if (!st || st.step_no <= 1) return "처음(1단계)";
  // JobStep에는 표시명이 없다: 현재 step이면 서버 current_step_label, 아니면 step_key (변경 메모 D3-1)
  const label = st.step_key === job.current_step_key && job.current_step_label ? job.current_step_label : st.step_key;
  return `${st.step_no}. ${label}`;
}

/** phase3.md §3.4: `job.can_retry && study.status === "ACTIVE"`일 때만 보이는 재시도 버튼 */
export function JobRetryButton({ job }: { job: Job }) {
  const sd = useStudyOptional();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!job.can_retry || sd?.study.status !== "ACTIVE") return null;

  const name = JOB_TYPE_LABEL[job.job_type] ?? job.job_type;
  const retry = async () => {
    setError(null);
    try {
      const nj = await api.retryJob(job.id);
      setOpen(false);
      emitJobRetried(job.id, nj);
    } catch (e) {
      setOpen(false);
      setError(errorMessage(e));
    }
  };

  return (
    <span className="job-retry">
      <button type="button" className="btn small" onClick={() => setOpen(true)}>
        재시도
      </button>
      {error && (
        <span className="error-text small" role="alert">
          {error}
        </span>
      )}
      {open && (
        <ConfirmDialog
          title="작업 재시도"
          body={`‘${name}’을 다시 실행할까요?\n${retryStartText(job)}부터 새 작업으로 대기열에 등록됩니다. 이전 작업 기록은 그대로 남습니다.`}
          confirmLabel="재시도"
          onConfirm={retry}
          onCancel={() => setOpen(false)}
        />
      )}
    </span>
  );
}
