// 레이아웃 A(2026-10-17): 우측 고정 열 대신 상단 바 상태 칩 2개 → 오른쪽 서랍(실행 대기열·워커 자원).
// 대기열·자원은 여기서 한 번만 폴링하고 칩·서랍 패널이 함께 쓴다(RunStatusProvider).
import { createPortal } from "react-dom";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, errorMessage, type QueueInfo, type Resources } from "../api";
import { useApp } from "../app/AppContext";
import { usePolling } from "../hooks/usePolling";
import { POLL } from "../lib/poll";
import { QueuePanel } from "../panels/QueuePanel";
import { WorkerResourcePanel } from "../panels/WorkerResourcePanel";

export interface RunStatusData {
  queue: QueueInfo | null;
  queueError: string | null;
  reloadQueue: () => Promise<void>;
  resources: Resources | null;
  resourcesNone: boolean;
}

const RunStatusCtx = createContext<RunStatusData | null>(null);

export function useRunStatus(): RunStatusData {
  const v = useContext(RunStatusCtx);
  if (!v) throw new Error("RunStatusProvider 밖에서 useRunStatus");
  return v;
}

export function RunStatusProvider({ children }: { children: ReactNode }) {
  const [queue, setQueue] = useState<QueueInfo | null>(null);
  const [queueError, setQueueError] = useState<string | null>(null);
  const [resources, setResources] = useState<Resources | null>(null);
  const [resourcesNone, setResourcesNone] = useState(false);
  const reloadQueue = useCallback(async () => {
    try {
      setQueue(await api.queue());
      setQueueError(null);
    } catch (e) {
      setQueueError(errorMessage(e));
    }
  }, []);
  const loadResources = useCallback(async () => {
    try {
      setResources(await api.resources());
      setResourcesNone(false);
    } catch {
      setResourcesNone(true);
    }
  }, []);
  usePolling(reloadQueue, POLL.queue);
  usePolling(loadResources, POLL.resources);
  return <RunStatusCtx.Provider value={{ queue, queueError, reloadQueue, resources, resourcesNone }}>{children}</RunStatusCtx.Provider>;
}

/** 칩 문구: 실행 = 로컬 슬롯 + 가벼운 작업 실행 중, 대기 = 로컬 대기 + 가벼운 대기 */
export function queueCounts(q: QueueInfo): { running: number; waiting: number } {
  return {
    running: (q.running ? 1 : 0) + (q.light.running ? 1 : 0),
    waiting: q.queued.length + q.light.queued.length,
  };
}

export function resourceChipText(r: Resources): string {
  const parts: string[] = [];
  parts.push(`CPU ${r.cpu_pct != null ? `${Math.round(r.cpu_pct)}%` : "—"}`);
  parts.push(`RAM ${r.ram_used_gb != null && r.ram_total_gb ? `${r.ram_used_gb.toFixed(0)}/${r.ram_total_gb.toFixed(0)}` : "—"}`);
  const util = r.gpu.map((g) => g.util_pct).filter((v): v is number => v != null);
  parts.push(r.gpu.length === 0 ? "GPU —" : `GPU ${util.length ? `${Math.round(Math.max(...util))}%` : "—"}`);
  return parts.join(" · ");
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** 상단 바 상태 칩 2개 + 서랍 */
export function StatusChips() {
  const { me, status } = useApp();
  const { queue, resources, resourcesNone } = useRunStatus();
  const [open, setOpen] = useState<"queue" | "resources" | null>(null);
  const queueBtn = useRef<HTMLButtonElement>(null);
  const resBtn = useRef<HTMLButtonElement>(null);
  const opener = useRef<HTMLButtonElement | null>(null);

  const counts = queue ? queueCounts(queue) : null;
  const mineRunning = !!queue && [queue.running, queue.light.running].some((j) => j && j.created_by === me.user_id);
  const offline = !!status && !status.worker.online;
  const resText = offline ? "워커 오프라인" : resources ? resourceChipText(resources) : resourcesNone ? "자원 정보 없음" : "자원 불러오는 중…";

  const close = useCallback(() => {
    setOpen(null);
    opener.current?.focus();
  }, []);
  const show = (which: "queue" | "resources", btn: HTMLButtonElement | null) => {
    if (open) return close();
    opener.current = btn;
    setOpen(which);
  };

  return (
    <>
      <button
        ref={queueBtn}
        type="button"
        className={`chip${counts && counts.running > 0 ? " running" : ""}${mineRunning ? " mine" : ""}${open ? " open" : ""}`}
        aria-haspopup="dialog"
        aria-expanded={open !== null}
        aria-controls="run-status-drawer"
        data-testid="chip-queue"
        title={mineRunning ? "내 작업이 실행 중입니다" : "실행 대기열 열기"}
        onClick={() => show("queue", queueBtn.current)}
      >
        <span className="chip-dot" aria-hidden="true" />
        {counts ? `대기열 실행 ${counts.running} · 대기 ${counts.waiting}` : "대기열 불러오는 중…"}
      </button>
      <button
        ref={resBtn}
        type="button"
        className={`chip${offline ? " bad" : ""}${open ? " open" : ""}`}
        aria-haspopup="dialog"
        aria-expanded={open !== null}
        aria-controls="run-status-drawer"
        data-testid="chip-resources"
        title="워커 자원 열기"
        onClick={() => show("resources", resBtn.current)}
      >
        {resText}
      </button>
      {open && <StatusDrawer focus={open} onClose={close} />}
    </>
  );
}

function StatusDrawer({ focus, onClose }: { focus: "queue" | "resources"; onClose: () => void }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const first = el.querySelector<HTMLElement>(".drawer-close");
    first?.focus();
    if (focus === "resources") el.querySelector<HTMLElement>('[aria-label="워커 자원"]')?.scrollIntoView?.({ block: "nearest" });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const items = Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (!items.length) return;
      const a = items[0];
      const z = items[items.length - 1];
      if (e.shiftKey && (document.activeElement === a || !el.contains(document.activeElement))) {
        e.preventDefault();
        z.focus();
      } else if (!e.shiftKey && (document.activeElement === z || !el.contains(document.activeElement))) {
        e.preventDefault();
        a.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
    // focus는 처음 열 때만 반영
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onClose]);
  // 상단 바(backdrop-filter)가 fixed의 기준이 되지 않도록 body로 내보낸다
  return createPortal(
    <>
      <div className="drawer-scrim status-scrim" data-testid="status-scrim" onClick={onClose} />
      <aside ref={ref} id="run-status-drawer" className="drawer status-drawer" role="dialog" aria-modal="true" aria-labelledby="run-status-title">
        <header className="drawer-head">
          <h2 id="run-status-title">실행 상태</h2>
          <button type="button" className="icon-btn drawer-close" aria-label="닫기" onClick={onClose}>
            ✕
          </button>
        </header>
        <div className="drawer-body">
          <QueuePanel />
          <WorkerResourcePanel />
          <p className="muted small">바깥을 누르거나 Esc로 닫힙니다. 모델 목록은 ③ 화면에 있습니다.</p>
        </div>
      </aside>
    </>,
    document.body,
  );
}
