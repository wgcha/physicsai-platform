// 계약 §10.9 폴링 주기(ms). 시험에서 짧게 바꿀 수 있도록 가변 객체로 둔다.
export const POLL = {
  jobActive: 2000, // RUNNING·COLLECTING
  jobQueued: 5000,
  jobWaitingHpc: 15000,
  log: 2000,
  queue: 5000,
  resources: 10000,
  notifications: 10000,
  status: 30000,
  checkDebounce: 300,
};

/** B1: /status.ui 값(ms)을 반영 */
export function applyUiPoll(ui: Partial<Record<string, number>> | null | undefined) {
  if (!ui) return;
  const map: Record<string, keyof typeof POLL> = {
    poll_job_running_ms: "jobActive",
    poll_job_queued_ms: "jobQueued",
    poll_job_waiting_hpc_ms: "jobWaitingHpc",
    poll_log_ms: "log",
    poll_queue_ms: "queue",
    poll_resources_ms: "resources",
    poll_notifications_ms: "notifications",
    poll_status_ms: "status",
  };
  for (const [k, target] of Object.entries(map)) {
    const v = ui[k];
    if (typeof v === "number" && Number.isFinite(v) && v >= 200) POLL[target] = v;
  }
}
