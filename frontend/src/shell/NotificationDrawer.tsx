import { useCallback, useEffect, useState } from "react";
import { api, type NotificationItem } from "../api";
import { useNotifications } from "../hooks/useNotifications";
import { fmtTime } from "../lib/format";
import { useOpenJob } from "./useOpenJob";

/** 알림 이력 패널(최근 30일, 최신순). 항목 클릭 → 읽음 + 이동, "모두 읽음" */
export function NotificationDrawer({ onClose }: { onClose: () => void }) {
  const { markRead, markAllRead, revision } = useNotifications();
  const [items, setItems] = useState<NotificationItem[] | null>(null);
  const [limit, setLimit] = useState(50);
  const openJob = useOpenJob();

  const load = useCallback(async () => {
    const r = await api.notifications(undefined, limit);
    setItems(r.items);
  }, [limit]);

  useEffect(() => {
    void load();
  }, [load, revision]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const onScroll = (e: React.UIEvent<HTMLUListElement>) => {
    const el = e.currentTarget;
    if (items && items.length >= limit && el.scrollTop + el.clientHeight > el.scrollHeight - 40) setLimit((l) => Math.min(200, l + 50));
  };

  return (
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="알림 이력">
        <header className="drawer-head">
          <h2>알림</h2>
          <span className="muted small">최근 30일</span>
          <button type="button" className="btn small ghost" onClick={() => void markAllRead()}>
            모두 읽음
          </button>
          <button type="button" className="icon-btn" aria-label="닫기" onClick={onClose}>
            ✕
          </button>
        </header>
        {items === null ? (
          <div className="empty">불러오는 중…</div>
        ) : items.length === 0 ? (
          <div className="empty">알림이 없습니다</div>
        ) : (
          <ul className="notif-list" onScroll={onScroll}>
            {items.map((n) => (
              <li key={n.seq}>
                <button
                  type="button"
                  className={n.read_at ? "notif read" : "notif unread"}
                  onClick={async () => {
                    if (!n.read_at) await markRead([n.seq]);
                    onClose();
                    if (n.job_id || n.event === "ENV_CHECK_DONE") void openJob(n);
                  }}
                >
                  <span className={`notif-dot ev-${n.event.toLowerCase()}`} />
                  <span className="notif-main">
                    <span className="notif-title">{n.title}</span>
                    {n.body && <span className="notif-body">{n.body}</span>}
                  </span>
                  <span className="notif-time">{fmtTime(n.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </>
  );
}
