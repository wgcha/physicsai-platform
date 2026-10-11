import { useEffect, useRef, useState, type KeyboardEvent } from "react";

/**
 * 공용 확인 대화상자(phase3.md §3.4). role="dialog"·aria-modal, 초점 가두기, Esc=취소,
 * 주 버튼은 요청 중 비활성(중복 클릭 방지). 본문의 줄바꿈(\n)은 문단으로 나눈다.
 */
export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  cancelLabel = "취소",
  onConfirm,
  onCancel,
  error,
  danger,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => Promise<unknown> | unknown;
  onCancel: () => void;
  error?: string | null;
  danger?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    const prev = document.activeElement as HTMLElement | null;
    confirmRef.current?.focus();
    return () => {
      alive.current = false;
      prev?.focus?.();
    };
  }, []);

  const confirm = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      if (!busy) onCancel();
      return;
    }
    if (e.key !== "Tab" || !boxRef.current) return;
    const items = Array.from(boxRef.current.querySelectorAll<HTMLElement>("button:not(:disabled), [href], input, [tabindex]:not([tabindex='-1'])"));
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  const titleId = "confirm-dialog-title";
  return (
    <div className="dialog-backdrop">
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={boxRef} onKeyDown={onKeyDown}>
        <h2 id={titleId} className="dialog-title">
          {title}
        </h2>
        <div className="dialog-body">
          {body.split("\n").map((line, i) => (
            <p key={i}>{line}</p>
          ))}
        </div>
        {error && (
          <div className="error-text small" role="alert">
            {error}
          </div>
        )}
        <div className="dialog-actions">
          <button type="button" className="btn ghost" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </button>
          <button type="button" ref={confirmRef} className={`btn ${danger ? "danger" : "primary"}`} onClick={confirm} disabled={busy}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
