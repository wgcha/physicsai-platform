import { useState } from "react";
import { useNotifications } from "../hooks/useNotifications";
import { NotificationDrawer } from "./NotificationDrawer";

export function NotificationBell() {
  const { unread } = useNotifications();
  const [open, setOpen] = useState(false);
  const badge = unread > 99 ? "99+" : String(unread);
  return (
    <>
      <button
        type="button"
        className="bell"
        aria-label={`알림 ${unread}건 미읽음`}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 3a6 6 0 0 0-6 6v3.6L4.3 16a.7.7 0 0 0 .6 1h14.2a.7.7 0 0 0 .6-1L18 12.6V9a6 6 0 0 0-6-6Zm-2.2 15.5a2.3 2.3 0 0 0 4.4 0" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
        </svg>
        {unread > 0 && (
          <span className="bell-badge" data-testid="bell-badge">
            {badge}
          </span>
        )}
      </button>
      {open && <NotificationDrawer onClose={() => setOpen(false)} />}
    </>
  );
}
