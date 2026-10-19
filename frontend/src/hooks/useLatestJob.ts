import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Job, type JobType } from "../api";
import { usePolling } from "./usePolling";
import { POLL } from "../lib/poll";
import { isTerminal } from "../lib/format";
import { onJobRetried } from "./jobRetried";

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
      // S9 §14.5: 일괄 예측 하위 PREDICT(batch 있음)는 단일 예측 화면의 "최신 작업"이 아니다
      .jobs({ study_id: studyId, job_type: jobType, limit: jobType === "PREDICT" ? 20 : 1 })
      .then(async (all) => {
        if (!alive) return;
        const list = all.filter((s) => !s.batch);
        // S16: FEM 검증이 함께 돌리는 동반 PREDICT(params.fem_verify_id)도 단일 예측 화면의 "최신 작업"이 아니다
        let found: Job | null = null;
        for (const s of list) {
          const j = await api.job(s.id);
          if (jobType === "PREDICT" && (j.params as { fem_verify_id?: string } | null)?.fem_verify_id) continue;
          found = j;
          break;
        }
        if (alive) accept(found);
      })
      .catch(() => undefined)
      .finally(() => alive && setLoaded(true));
    return () => {
      alive = false;
    };
  }, [studyId, jobType, accept]);

  // 재시도 버튼(JobInline)이 만든 새 작업으로 갈아탄다(phase3 §3.4)
  useEffect(() => onJobRetried((fromId, j) => prev.current?.id === fromId && accept(j)), [accept]);

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
