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
