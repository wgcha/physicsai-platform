import { render } from "@testing-library/react";
import { vi } from "vitest";
import { TestApp } from "../app/App";
import { MockServer, createMockFetch, type MockOptions } from "../mock/server";
import { POLL } from "../lib/poll";

/** 목 서버를 fetch로 꽂고 앱을 경로에서 렌더링 */
export function renderApp(path: string, opts: MockOptions = {}) {
  const ui = { poll_notifications_ms: 60, poll_queue_ms: 60, poll_job_running_ms: 60, poll_job_queued_ms: 60, poll_job_waiting_hpc_ms: 60, poll_status_ms: 60_000, poll_resources_ms: 60_000 };
  const server = new MockServer({ ui, ...opts });
  vi.stubGlobal("fetch", createMockFetch(server));
  Object.assign(POLL, { notifications: 60, queue: 60, jobActive: 60, jobQueued: 60, jobWaitingHpc: 60, checkDebounce: 10, status: 60_000, resources: 60_000 });
  const utils = render(<TestApp path={path} />);
  return { server, ...utils };
}

export const STUDY = "/p/p-cushion/s/s-cushion/stage";
