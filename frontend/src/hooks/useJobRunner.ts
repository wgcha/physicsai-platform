import { useCallback, useState } from "react";
import { api, errorMessage, type Job, type JobType } from "../api";
import { useStudy } from "../app/StudyContext";
import { useLatestJob } from "./useLatestJob";

/** 작업 생성 + 최신 작업 추적 + 오류 문구 */
export function useJobRunner(jobType: JobType, onFinish?: (job: Job) => void) {
  const { study, reloadStudy } = useStudy();
  const { job, track, loaded } = useLatestJob(study.id, jobType, (j) => {
    void reloadStudy();
    onFinish?.(j);
  });
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const run = useCallback(
    async (params: Record<string, unknown>) => {
      setError(null);
      setSubmitting(true);
      try {
        const j = await api.createJob(study.id, jobType, params);
        track(j);
        return j;
      } catch (e) {
        setError(errorMessage(e));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [study.id, jobType, track],
  );

  return { job, loaded, run, error, setError, submitting };
}

export function useCanExecute(): boolean {
  const { study } = useStudy();
  return study.can_execute && study.status === "ACTIVE";
}
