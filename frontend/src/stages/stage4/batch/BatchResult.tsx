// ④ B 일괄 예측 진행·결과(phase3.md §14.8, 시안 04, 라우트 …/stage/4/batch/:batchId):
// 위 3칸(입력 생성 x/N · 예측 실행 중·대기·완료 · 파일 위치) + 결과 표(정렬·CSV·행 선택·실패만 다시·일괄 취소)
// + 오른쪽(1:1, contour3d-default C3D-9): 고른 DOE(3D 컨투어 기본 — 그림/영상은 창(S10)·결과 목록·경로 복사·단일 예측으로 열기·PBS 검증). "⑤ 결과분석에서 열기"는 결과 표 카드 머리 링크.
// S14(D3-62, §19.7): 변수–응답 그래프·설계공간 지도·커브 겹쳐보기(분석)는 ⑤ 결과분석(/stage/analysis?source=batch&id=<batchId>)으로 이동했다.
import { snapshotText } from "../../../lib/nativeVars";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, errorMessage, type Job, type PredictBatch, type ViewKey } from "../../../api";
import { useStudy } from "../../../app/StudyContext";
import { useCanExecute } from "../../../hooks/useJobRunner";
import { usePolling } from "../../../hooks/usePolling";
import { useFeature } from "../../../components/FeatureGate";
import { Card, CopyButton, ProgressBar } from "../../../components/ui";
import { InputBadge } from "../../../components/InputKindSelect";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { POLL } from "../../../lib/poll";
import { samplingSummary } from "../../../lib/sampling";
import { fmtDuration } from "../PredictSteps";
import { ResultRow } from "./BatchResultRow";
import { RunPanel } from "./BatchRunPanel";
import { writeBatchTab } from "./BatchMode";
import { writeInputMode } from "../InputModeTabs";
import { BATCH_STATUS_LABEL, isBatchActive, isRowFailed, sortOptions, sortRows, type SortKey } from "./batchTable";

export const FILE_NOTE = "파일 이름은 모두 같고 폴더 번호로 구분합니다";
export const NO_RESP_TEXT = "응답 추출 미구성";

export function BatchResult({ batchId }: { batchId: string }) {
  const { study } = useStudy();
  const canExec = useCanExecute();
  const respFeature = useFeature("predict_responses");
  const [b, setB] = useState<PredictBatch | null>(null);
  const [parent, setParent] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortKey | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [confirmCancel, setConfirmCancel] = useState(false);
  /** S10: 컨투어 방향은 run을 바꿔도 유지(비교용) */
  const [mediaView, setMediaView] = useState<ViewKey | null>(null);

  const load = useCallback(async () => {
    try {
      const x = await api.batch(batchId);
      setB(x);
      setError(null);
      api.job(x.job_id).then(setParent).catch(() => undefined);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [batchId]);
  useEffect(() => {
    void load();
  }, [load]);
  usePolling(load, b && isBatchActive(b.status) ? POLL.batch : null, false, [batchId]);

  const showResp = !!b && b.responses.length > 0 && respFeature.enabled;
  const respNames = useMemo(() => (showResp ? b!.responses.map((r) => r.name) : []), [showResp, b]);
  const sortKey: SortKey = sort ?? (respNames[0] ? `${respNames[0]}:asc` : "doe");
  const rows = useMemo(() => (b ? sortRows(b.rows, sortKey) : []), [b, sortKey]);
  const selRow = b?.rows.find((r) => r.doe_no === selected) ?? null;
  useEffect(() => {
    if (selected === null && rows.length) setSelected((rows.find((r) => r.state === "SUCCEEDED") ?? rows[0]).doe_no);
  }, [rows, selected]);

  if (error && !b) return <Card span={9} title="일괄 예측"><p className="error-text">{error}</p></Card>;
  if (!b) return <Card span={9} title="일괄 예측"><p className="muted">불러오는 중…</p></Card>;

  const active = isBatchActive(b.status);
  const total = b.rows.length;
  const finished = b.predict.succeeded + b.predict.failed + b.predict.canceled;
  const anyFailed = b.rows.some((r) => isRowFailed(r.state));
  const genElapsed = parent?.started_at && parent?.finished_at ? fmtDuration(Date.parse(parent.finished_at) - Date.parse(parent.started_at)) : null;
  const base = `/p/${study.project_id}/s/${study.id}/stage/4`;
  const sampleLine = samplingSummary(b.sampling, b.rows.length); // S15 §20.10
  const varsLine = snapshotText(b.vars); // native-vars.md §4.1 사용 변수 스냅숏 요약(Native만)

  const act = async (f: () => Promise<unknown>) => {
    setActionError(null);
    try {
      await f();
      await load();
    } catch (e) {
      setActionError(errorMessage(e));
    }
  };
  const downloadCsv = () =>
    act(async () => {
      const blob = await api.batchCsv(b.id);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${study.folder_name}_${b.label}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    });

  return (
    <>
      <Card span={3} title="입력 생성" aside={<span className="muted small">동시 {b.multi_execution}</span>} className="batch-stat">
        <div className="D" data-testid="gen-count">
          {b.gen.done} / {b.gen.total}
        </div>
        <p className="muted small">
          {b.status === "GENERATING" ? `생성 중 ${b.gen.running} · 대기 ${b.gen.waiting}` : "완료"}
          {genElapsed && b.status !== "GENERATING" ? ` · ${genElapsed}` : ""} · 실패 {b.gen.failed}
        </p>
      </Card>
      <Card span={3} title="예측" aside={<span className="muted small">대기열 1슬롯</span>} className="batch-stat">
        <div className="batch-counts" data-testid="predict-counts">
          <span className="D accent">{b.predict.running}</span>
          <span className="small muted">실행 중</span>
          <span className="D">{b.predict.queued}</span>
          <span className="small muted">대기</span>
          <span className="D">{b.predict.succeeded}</span>
          <span className="small muted">완료</span>
        </div>
        <ProgressBar pct={total ? (finished / total) * 100 : 0} label="예측 진행률" />
        <p className="muted small">
          {b.label} · {BATCH_STATUS_LABEL[b.status]}
          {b.predict.failed ? ` · 실패 ${b.predict.failed}` : ""}
          {b.predict.canceled ? ` · 취소 ${b.predict.canceled}` : ""}
        </p>
      </Card>
      <Card span={3} title="파일 위치" className="batch-stat">
        <div className="codeline small" title={b.dir}>
          <code>{b.dir}</code>
          <CopyButton text={b.dir} label="경로 복사" />
        </div>
        <p className="muted small">
          {FILE_NOTE}. 표의 DOE # = 폴더 번호. 템플릿 {b.param_set.label ?? b.param_set.id} · 모델 {b.model.name} · 입력 <InputBadge input={b.input} />
        </p>
        {varsLine && (
          <p className="muted small" data-testid="batch-vars">
            사용 변수 — {varsLine}
          </p>
        )}
      </Card>

      <Card
        span="half"
        title={`결과 표 — ${b.label}`}
        className="batch-table-card"
        aside={
          <span className="run-action-row">
            <Link to={base} className="small" onClick={() => (writeInputMode("batch"), writeBatchTab("list"))}>
              ← 실행 목록
            </Link>
            <Link className="small" to={`/p/${study.project_id}/s/${study.id}/stage/analysis?source=batch&id=${b.id}`} data-testid="analysis-link" title="변수–응답 그래프, 설계공간 지도, 영향도, 커브 겹쳐보기">
              ⑤ 결과분석에서 열기
            </Link>
            <label className="inline-field small">
              정렬
              <select value={sortKey} onChange={(e) => setSort(e.target.value as SortKey)}>
                {sortOptions(respNames).map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="btn small" onClick={downloadCsv}>
              CSV 받기
            </button>
            {canExec && anyFailed && !active && (
              <button type="button" className="btn small" onClick={() => act(() => api.retryFailedBatch(b.id))}>
                실패만 다시 실행
              </button>
            )}
            {canExec && active && (
              <button type="button" className="btn small danger" onClick={() => setConfirmCancel(true)}>
                일괄 취소
              </button>
            )}
          </span>
        }
      >
        {actionError && (
          <p className="error-text small" role="alert">
            {actionError}
          </p>
        )}
        {sampleLine && (
          <p className="muted small batch-sampling" data-testid="batch-sampling">
            표본: {sampleLine}
          </p>
        )}
        {!showResp && <p className="muted small" data-testid="no-resp">{NO_RESP_TEXT}</p>}
        {(b.warnings ?? []).map((w, i) => (
          <p key={i} className="warn-text small" data-testid="input-warning" title={w.code}>
            {w.message}
          </p>
        ))}
        <div className="table-wrap">
          <table className="table compact batch-table" aria-label="일괄 예측 결과">
            <thead>
              <tr>
                <th>DOE #</th>
                <th>폴더</th>
                {b.parameters.map((n) => (
                  <th key={n} className="num">
                    {n}
                  </th>
                ))}
                {showResp &&
                  b.responses.map((r) => (
                    <th key={r.name} className="num">
                      {r.name}
                      {r.unit && <span className="muted"> {r.unit}</span>}
                    </th>
                  ))}
                <th className="num">상태</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <ResultRow
                  key={r.doe_no}
                  r={r}
                  b={b}
                  showResp={showResp}
                  selected={r.doe_no === selected}
                  onSelect={() => setSelected(r.doe_no)}
                  canRetry={canExec && !!r.job_id && (r.state === "FAILED" || r.state === "CANCELED")}
                  onRetry={() => act(() => api.retryJob(r.job_id!))}
                />
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small">행을 누르면 오른쪽에 그 DOE의 결과가 열립니다. DOE # 옆 카메라 표시 = 컨투어 캡처 있음(방향은 run을 바꿔도 유지). 학습 범위 밖 값은 숫자 옆 작은 회색 점.</p>
        <p className="small">
          <Link to={base}>← 일괄 예측 설정</Link>
        </p>
      </Card>

      <RunPanel row={selRow} base={base} canCapture={canExec} view={mediaView} onView={setMediaView} psId={b.param_set.id} batchId={batchId} />
      {confirmCancel && (
        <ConfirmDialog
          title={`일괄 예측 ${b.label} 취소`}
          body={"입력 생성과 아직 끝나지 않은 예측을 모두 취소합니다.\n끝난 run의 결과는 남습니다."}
          confirmLabel="일괄 취소"
          cancelLabel="닫기"
          danger
          onCancel={() => setConfirmCancel(false)}
          onConfirm={async () => {
            await act(() => api.cancelBatch(b.id));
            setConfirmCancel(false);
          }}
        />
      )}
    </>
  );
}
