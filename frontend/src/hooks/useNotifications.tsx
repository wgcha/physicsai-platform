import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type NotificationItem } from "../api";
import { usePolling } from "./usePolling";
import { POLL } from "../lib/poll";

export interface Toast {
  key: number;
  item: NotificationItem;
}

interface NotificationsValue {
  unread: number;
  toasts: Toast[];
  dismissToast: (key: number) => void;
  markRead: (seqs: number[]) => Promise<void>;
  markAllRead: () => Promise<void>;
  /** 이력 패널이 새 항목을 다시 읽도록 증가 */
  revision: number;
}

const Ctx = createContext<NotificationsValue | null>(null);

export const TOAST_MS = 5000;
export const TOAST_MAX = 3;

/**
 * 계약 §13.2: 로드 시 unread-count로 max_seq를 받고, 이후 주기마다 after_seq 이후 항목을 받아
 * 새 항목만 토스트(로드 이전 알림은 토스트 없음). 벨은 미읽음 수.
 */
export function NotificationsProvider({ children }: { children: ReactNode }) {
  const [unread, setUnread] = useState(0);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [revision, setRevision] = useState(0);
  const maxSeq = useRef<number | null>(null);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismissToast = useCallback((key: number) => {
    setToasts((t) => t.filter((x) => x.key !== key));
    const tm = timers.current.get(key);
    if (tm) clearTimeout(tm);
    timers.current.delete(key);
  }, []);

  const poll = useCallback(async () => {
    if (maxSeq.current === null) {
      const r = await api.unreadCount();
      maxSeq.current = r.max_seq;
      setUnread(r.unread_count);
      return;
    }
    const r = await api.notifications(maxSeq.current);
    setUnread(r.unread_count);
    const fresh = r.items.filter((i) => i.seq > (maxSeq.current ?? 0)).sort((a, b) => a.seq - b.seq);
    maxSeq.current = Math.max(maxSeq.current, r.max_seq);
    if (fresh.length) {
      setRevision((v) => v + 1);
      setToasts((prev) => {
        const next = [...prev, ...fresh.map((item) => ({ key: item.seq, item }))];
        return next.slice(-TOAST_MAX);
      });
      for (const item of fresh) {
        const tm = setTimeout(() => dismissToast(item.seq), TOAST_MS);
        timers.current.set(item.seq, tm);
      }
    }
  }, [dismissToast]);

  usePolling(poll, POLL.notifications);

  useEffect(() => {
    const t = timers.current;
    return () => t.forEach((tm) => clearTimeout(tm));
  }, []);

  const markRead = useCallback(async (seqs: number[]) => {
    if (!seqs.length) return;
    const r = await api.markRead({ seqs });
    setUnread(r.unread_count);
    setRevision((v) => v + 1);
  }, []);

  const markAllRead = useCallback(async () => {
    const r = await api.markRead({ all: true });
    setUnread(r.unread_count);
    setRevision((v) => v + 1);
  }, []);

  return (
    <Ctx.Provider value={{ unread, toasts, dismissToast, markRead, markAllRead, revision }}>
      {children}
    </Ctx.Provider>
  );
}

export function useNotifications(): NotificationsValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("NotificationsProvider 없음");
  return v;
}
