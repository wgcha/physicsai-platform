import { useNotifications } from "../hooks/useNotifications";
import { useOpenJob } from "./useOpenJob";

/** 우하단 토스트(5초 자동 닫힘, 최대 3개, 클릭 시 작업 화면) — §13.2 */
export function ToastHost() {
  const { toasts, dismissToast, markRead } = useNotifications();
  const openJob = useOpenJob();
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map(({ key, item }) => (
        <div key={key} className={`toast ev-${item.event.toLowerCase()}`} role="status">
          <button
            type="button"
            className="toast-main"
            onClick={() => {
              dismissToast(key);
              void markRead([item.seq]);
              void openJob(item);
            }}
          >
            <span className="toast-title">{item.title}</span>
            {item.body && <span className="toast-body">{item.body}</span>}
          </button>
          <button type="button" className="icon-btn" aria-label="토스트 닫기" onClick={() => dismissToast(key)}>
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
