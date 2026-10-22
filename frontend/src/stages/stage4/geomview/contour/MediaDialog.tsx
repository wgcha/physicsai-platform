// [그림/영상] 대화상자(contour3d-default §4): 결과 컨투어 칸의 기본이 3D가 되면서 PNG·영상은 이 창에서 보고·받고·다시 캡처한다.
// 본문은 기존 부품(ContourMedia·ContourCompare·두 ContourMedia)을 그대로 받는다. 폭 min(1400px, 92vw), Esc·닫기, 열 때 닫기 버튼 포커스·닫으면 원래 버튼으로 복귀.
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

export function MediaDialog({ title = "그림/영상", onClose, children }: { title?: string; onClose: () => void; children: ReactNode }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    return () => prev?.focus?.();
  }, []);
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab" || !boxRef.current) return;
    const items = Array.from(boxRef.current.querySelectorAll<HTMLElement>("button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex='-1'])"));
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
  return (
    <div className="dialog-backdrop">
      <div className="dialog media-dialog" role="dialog" aria-modal="true" aria-labelledby="media-dialog-title" ref={boxRef} onKeyDown={onKeyDown}>
        <div className="media-dialog-head">
          <h2 id="media-dialog-title" className="dialog-title">
            {title}
          </h2>
          <button type="button" className="btn small" ref={closeRef} onClick={onClose}>
            닫기
          </button>
        </div>
        <div className="media-dialog-body">{children}</div>
      </div>
    </div>
  );
}

/** 카드 머리 aside용 [그림/영상] 버튼 + 대화상자(열림 상태를 이 안에서 쥔다) */
export function MediaButton({ title, children }: { title?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="btn small" aria-haspopup="dialog" onClick={() => setOpen(true)} title="저장된 컨투어 그림·영상을 보고 받습니다">
        그림/영상
      </button>
      {open && (
        <MediaDialog title={title} onClose={() => setOpen(false)}>
          {children}
        </MediaDialog>
      )}
    </>
  );
}
