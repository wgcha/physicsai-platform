import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Job, type JobType } from "../api";
import { usePolling } from "./usePolling";
import { POLL } from "../lib/poll";
import { isTerminal } from "../lib/format";

function intervalFor(job: Job | null): number | null {
  if (!job) return null;
  switch (job.state) {
    case "RUNNING":
    case "COLLECTING":
      return POLL.jobActive;
    case "QUEUED":
      return POLL.jobQueued;
    case "WAITING_HPC":
      return POLL.jobWaitingHpc;
    default:
      return null; // 종료면 중지(§10.9)
  }
}

/** Study의 job_type별 최신 작업을 추적. 종료로 바뀌는 순간 onFinish 호출. */
export function useLatestJob(studyId: string, jobType: JobType, onFinish?: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const [loaded, setLoaded] = useState(false);
  const prev = useRef<Job | null>(null);
  const finishRef = useRef(onFinish);
  finishRef.current = onFinish;

  const accept = useCallback((j: Job | null) => {
    const before = prev.current;
    prev.current = j;
    setJob(j);
    if (j && before && before.id === j.id && !isTerminal(before.state) && isTerminal(j.state)) {
      finishRef.current?.(j);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    setLoaded(false);
    api
      .jobs({ study_id: studyId, job_type: jobType, limit: 1 })
      .then(async (list) => {
        if (!alive) return;
        if (list.length) {
          const j = await api.job(list[0].id);
          if (alive) accept(j);
        } else accept(null);
      })
      .catch(() => undefined)
      .finally(() => alive && setLoaded(true));
    return () => {
      alive = false;
    };
  }, [studyId, jobType, accept]);

  const refresh = useCallback(async () => {
    const id = prev.current?.id;
    if (!id) return;
    accept(await api.job(id));
  }, [accept]);

  usePolling(refresh, intervalFor(job), false, [job?.id]);

  /** 방금 만든 작업을 추적 시작 */
  const track = useCallback((j: Job) => accept(j), [accept]);

  return { job, loaded, track, refresh };
}
