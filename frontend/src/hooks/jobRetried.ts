// phase3.md §3.4: 재시도로 새 작업이 생기면 그 작업을 추적 중이던 카드(useLatestJob)가 새 작업으로 갈아탄다.
import type { Job } from "../api";

type Listener = (fromJobId: string, job: Job) => void;
const listeners = new Set<Listener>();

export function onJobRetried(fn: Listener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function emitJobRetried(fromJobId: string, job: Job): void {
  for (const fn of Array.from(listeners)) fn(fromJobId, job);
}
