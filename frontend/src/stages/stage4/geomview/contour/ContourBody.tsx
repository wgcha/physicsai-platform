// 결과 3D 컨투어 본문(geometry-view.md §13.6): 열 때 생성 → 대기 안내(단계 스테퍼·진행률·경과/예상·취소) → 뷰어, 실패·취소·만료 처리.
import { useEffect, type ComponentProps, type ReactNode } from "react";
import type { Contour3d, Contour3dCreate } from "../../../../api";
import { ContourViewer } from "./ContourViewer";
import { BUSY_TEXT, contourView, DENIED_TEXT, etaText, fmtSeconds, progressPercent, STEPPER, stepMarks } from "./contourCore";
import { useContour3d, type ContourCtl } from "./useContour3d";

/** [3D 컨투어] 버튼으로 연 패널(① run 표·접힘 패널): 열 때 생성 */
export function ContourBody({ source }: { source: Contour3dCreate }) {
  const ctl = useContour3d(source);
  const { start } = ctl;
  useEffect(() => {
    void start();
  }, [start]);
  return <ContourStateView ctl={ctl} />;
}

/**
 * 3D 상태 화면(geometry-view.md §13.6): 요청 대기 → 대기 안내(단계 스테퍼·진행률·경과/예상·취소) → 뷰어, 실패·취소·만료 처리.
 * media = 3D를 못 보일 때 그 자리에 함께 나오는 PNG·영상(contour3d-default C3D-2). viewer = 비교 모드 제어 props.
 */
export function ContourStateView({ ctl, media, viewer }: { ctl: ContourCtl; media?: ReactNode; viewer?: Omit<ComponentProps<typeof ContourViewer>, "c" | "onExpired"> }) {
  const { c, error, busy, queued, denied, start, cancel } = ctl;
  const view = contourView(c);
  // 서버 캐시가 정리된 결과(EXPIRED)는 자동으로 다시 만든다
  useEffect(() => {
    if (view === "expired") void start();
  }, [view, start]);

  if (denied)
    return (
      <>
        <p className="muted small c3-box" data-testid="contour3d-denied">
          {DENIED_TEXT}
        </p>
        {media}
      </>
    );
  if (error && (!c || view !== "waiting"))
    return (
      <>
        <div className="c3-box" role="alert">
          <p className="error-text small">3D 컨투어를 요청하지 못했습니다 — {error}</p>
          <button type="button" className="btn small" onClick={() => void start()}>
            다시
          </button>
        </div>
        {media}
      </>
    );
  if (queued && !c)
    return (
      <div className="c3-box muted small" data-testid="contour3d-busy" aria-live="polite">
        {BUSY_TEXT}
      </div>
    );
  if (!c || busy) return <div className="c3-box muted small">요청 중…</div>;
  if (view === "waiting" || view === "expired") return <WaitScreen c={c} onCancel={() => void cancel()} />;
  if (view === "ready") return <ContourViewer key={c.id} c={c} onExpired={() => void start()} {...viewer} />;
  if (view === "result_fail")
    return (
      <>
        <div className="c3-box" data-testid="contour3d-fail">
          <span className="pill bad">결과 없음</span> <span className="small">{c.message_ko ?? c.code}</span> <span className="mono muted small">{c.code}</span>
        </div>
        {media}
      </>
    );
  return (
    <>
      <div className="c3-box" data-testid="contour3d-stopped">
        <p className={view === "failed" ? "error-text small" : "muted small"}>
          {view === "canceled" ? "3D 컨투어 생성을 취소했습니다." : `3D 컨투어를 만들지 못했습니다 — ${c.message_ko ?? c.code ?? "작업 실패"}`}
        </p>
        <button type="button" className="btn small" onClick={() => void start()}>
          {view === "canceled" ? "다시 만들기" : "다시"}
        </button>
      </div>
      {view === "failed" && media}
    </>
  );
}

/** 대기 안내: 단계 스테퍼 · 진행률 바 · 경과/예상 시간 · 취소 */
export function WaitScreen({ c, onCancel }: { c: Contour3d; onCancel: () => void }) {
  const p = c.progress;
  const phase = p?.phase ?? "waiting";
  const marks = stepMarks(phase, (p?.step_key as typeof phase | null) ?? null);
  const pct = progressPercent(c);
  return (
    <div className="c3-wait" data-testid="contour3d-wait" aria-live="polite">
      <div className="c3-wait-head">
        <b>3D 컨투어를 만드는 중입니다</b>
        <span className="muted small">결과 파일에서 외부 면과 프레임별 값을 읽어 3D로 바꿉니다 — 처음 한 번만 걸리고 다음부터는 바로 열립니다</span>
      </div>
      <ol className="c3-stepper" aria-label="진행 단계">
        {STEPPER.map((s, k) => (
          <li key={s.phase} className={`c3-step ${marks[k]}`} aria-current={marks[k] === "active" ? "step" : undefined}>
            <span className="c3-dot">{k + 1}</span>
            <span className="small">{s.label}</span>
          </li>
        ))}
      </ol>
      <div className="progress c3-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct ?? undefined} aria-label="진행률">
        <div className={`progress-fill${pct == null ? " indeterminate" : ""}`} style={pct == null ? undefined : { width: `${pct}%` }} />
      </div>
      <div className="c3-wait-foot small">
        <span>
          <b>{p?.phase_label ?? "대기"}</b>
          {pct != null ? ` · ${Math.round(pct)}%` : ""}
        </span>
        <span className="muted">경과 {fmtSeconds(p?.elapsed_s ?? 0)}</span>
        <span className="muted">{etaText(c)}</span>
        <button type="button" className="btn small ghost" onClick={onCancel} disabled={!p?.can_cancel}>
          취소
        </button>
      </div>
    </div>
  );
}
