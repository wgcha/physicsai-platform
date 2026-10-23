// 결과 3D 컨투어 본문(geometry-view.md §13.6): 열 때 생성 → 대기 안내(단계 스테퍼·진행률·경과/예상·취소) → 뷰어, 실패·취소·만료 처리.
import { useEffect, useState, type ComponentProps, type ReactNode } from "react";
import { api, type Contour3d, type Contour3dCreate } from "../../../../api";
import { ContourViewer } from "./ContourViewer";
import { ReasonLine } from "./ContourReason";
import { BUSY_TEXT, contourView, etaText, fmtSeconds, jobFailText, progressPercent, requestReason, resultFailText, STEPPER, stepMarks, type ContourManifest } from "./contourCore";
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
  const { c, error, errInfo, busy, queued, denied, start, cancel } = ctl;
  const view = contourView(c);
  // 서버 캐시가 정리된 결과(EXPIRED)는 자동으로 다시 만든다
  useEffect(() => {
    if (view === "expired") void start();
  }, [view, start]);

  if (denied)
    return (
      <>
        <ReasonLine text={requestReason({ c, error, denied, errInfo }) ?? ""} testid="contour3d-denied" />
        {media}
      </>
    );
  if (error && (!c || view !== "waiting")) {
    // 결정적 사유(기능 꺼짐·원본 없음)는 다시 요청해도 같으므로 [다시]를 두지 않는다
    const fixed = errInfo?.status === 409 && (errInfo.code === "CONTOUR3D_NOT_CONFIGURED" || errInfo.code === "PREREQUISITE_MISSING");
    return (
      <>
        <div className="c3-box" role="alert">
          <ReasonLine text={requestReason({ c, error, denied, errInfo }) ?? error} tone={fixed ? undefined : "error"} />
          {!fixed && (
            <button type="button" className="btn small" onClick={() => void start()}>
              다시
            </button>
          )}
        </div>
        {media}
      </>
    );
  }
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
        <ResultFail c={c} />
        {media}
      </>
    );
  return (
    <>
      <div className="c3-box" data-testid="contour3d-stopped">
        {view === "canceled" ? <ReasonLine text="3D 컨투어 생성을 취소했습니다." /> : <ReasonLine text={jobFailText(c)} tone="error" />}
        <button type="button" className="btn small" onClick={() => void start()}>
          {view === "canceled" ? "다시 만들기" : "다시"}
        </button>
      </div>
      {view === "failed" && media}
    </>
  );
}

/** 결과 FAIL(결정적, 같은 키에서 다시 만들지 않음 — [다시] 없음): 상한 비교는 FAIL manifest의 `limits`로, 읽지 못하면 message_ko만 */
function ResultFail({ c }: { c: Contour3d }) {
  const [m, setM] = useState<ContourManifest | null>(null);
  const id = c.manifest_artifact_id;
  useEffect(() => {
    if (!id) return;
    let alive = true;
    api
      .artifactJson<ContourManifest>(id)
      .then((x) => alive && setM(x))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [id]);
  return <ReasonLine text={resultFailText(c, m)} testid="contour3d-fail" />;
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
