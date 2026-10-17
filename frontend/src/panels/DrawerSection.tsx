import type { ReactNode } from "react";

/** 상태 서랍 안 구획(제목 + 참조 문구 + 내용). 접근 이름 = label(region) */
export function DrawerSection({ label, refText, children }: { label: string; refText?: ReactNode; children: ReactNode }) {
  return (
    <section className="dsec panel" aria-label={label}>
      <header className="dsec-head">
        <h3>{label}</h3>
        {refText !== undefined && <span className="cell-ref R">{refText}</span>}
      </header>
      <div className="dsec-body">{children}</div>
    </section>
  );
}
