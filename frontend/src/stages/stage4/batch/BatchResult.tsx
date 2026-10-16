// ④ B 일괄 예측 진행·결과(phase3.md §14.8, 시안 04, 라우트 …/stage/4/batch/:batchId):
// 위 3칸(입력 생성 x/N · 예측 실행 중·대기·완료 · 파일 위치) + 결과 표(정렬·CSV·행 선택·실패만 다시·일괄 취소)
// + 오른쪽: 응답 그래프(표 머리에서 변수 체크·응답 라디오 → 2D/3D/안내) · 커브 겹쳐보기 · 고른 DOE(컨투어 방향별 스크린샷·영상(S10)·결과 목록·경로 복사·단일 예측으로 열기·PBS 검증).
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, errorMessage, type Job, type PredictBatch, type PredictBatchRow, type PredictResult as PR, type ViewKey } from "../../../api";
import { useStudy } from "../../../app/StudyContext";
import { useCanExecute } from "../../../hooks/useJobRunner";
import { usePolling } from "../../../hooks/usePolling";
import { useFeature } from "../../../components/FeatureGate";
import { Card, CopyButton, ProgressBar } from "../../../components/ui";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { POLL } from "../../../lib/poll";
import { fmtNum } from "../../../lib/format";
import { usePredictVerify } from "../predictRun";
import { ContourMedia } from "../ContourMedia";
import { ResultListTree } from "../PredictResult";
import { fmtDuration } from "../PredictSteps";
import { OutDot } from "./BatchPreview";
import { CurveOverlay } from "./CurveOverlay";
import { ResponsePlot2D } from "./ResponsePlot2D";
import { ResponsePlot3D } from "./ResponsePlot3D";
import { writeBatchTab } from "./BatchMode";
import { writeInputMode } from "../InputModeTabs";
import { BATCH_STATUS_LABEL, PLOT_HINT, ROW_STATE_LABEL, isBatchActive, isRowFailed, plotKind, plotPoints, sortOptions, sortRows, type SortKey } from "./batchTable";

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
  const [vars, setVars] = useState<string[] | null>(null);
  const [resp, setResp] = useState<string | null>(null);
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
  const pickVars = vars ?? (b?.parameters.slice(0, 1) ?? []);
  const pickResp = resp ?? respNames[0] ?? null;
  const kind = plotKind(pickVars, pickResp ? [pickResp] : []);
  const selRow = b?.rows.find((r) => r.doe_no === selected) ?? null;
  useEffect(() => {
    if (selected === null && rows.length) setSelected((rows.find((r) => r.state === "SUCCEEDED") ?? rows[0]).doe_no);
  }, [rows, selected]);

  const pts = useMemo(() => (b && pickResp && kind !== "none" ? plotPoints(b.rows, pickVars, pickResp) : []), [b, pickResp, kind, pickVars.join("|")]);
  const labels3 = useMemo(() => [pickVars[0] ?? "", pickVars[1] ?? "", pickResp ?? ""] as [string, string, string], [pickVars.join("|"), pickResp]);
  const pts3 = useMemo(() => pts.map((p) => ({ doe_no: p.doe_no, run_key: p.run_key, x: p.v[0], y: p.v[1], z: p.r })), [pts]);

  if (error && !b) return <Card span={9} title="일괄 예측"><p className="error-text">{error}</p></Card>;
  if (!b) return <Card span={9} title="일괄 예측"><p className="muted">불러오는 중…</p></Card>;

  const active = isBatchActive(b.status);
  const total = b.rows.length;
  const finished = b.predict.succeeded + b.predict.failed + b.predict.canceled;
  const anyFailed = b.rows.some((r) => isRowFailed(r.state));
  const genElapsed = parent?.started_at && parent?.finished_at ? fmtDuration(Date.parse(parent.finished_at) - Date.parse(parent.started_at)) : null;
  const base = `/p/${study.project_id}/s/${study.id}/stage/4`;

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
  const toggleVar = (n: string) => setVars((v) => ((v ?? pickVars).includes(n) ? (v ?? pickVars).filter((x) => x !== n) : [...(v ?? pickVars), n]));

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
          <span className="D red">{b.predict.running}</span>
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
          {FILE_NOTE}. 표의 DOE # = 폴더 번호. 템플릿 {b.param_set.label ?? b.param_set.id} · 모델 {b.model.name}
        </p>
      </Card>

      <Card
        span={6}
        title={`결과 표 — ${b.label}`}
        className="batch-table-card"
        aside={
          <span className="run-action-row">
            <Link to={base} className="small" onClick={() => (writeInputMode("batch"), writeBatchTab("list"))}>
              ← 실행 목록
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
        {!showResp && <p className="muted small" data-testid="no-resp">{NO_RESP_TEXT}</p>}
        <div className="table-wrap">
          <table className="table compact batch-table" aria-label="일괄 예측 결과">
            <thead>
              <tr>
                <th>DOE #</th>
                <th>폴더</th>
                {b.parameters.map((n) => (
                  <th key={n} className="num">
                    <label className="th-pick" title="응답 그래프 변수로 쓰기">
                      <input type="checkbox" checked={pickVars.includes(n)} onChange={() => toggleVar(n)} />
                      {n}
                    </label>
                  </th>
                ))}
                {showResp &&
                  b.responses.map((r) => (
                    <th key={r.name} className="num">
                      <label className="th-pick" title="응답 그래프 응답으로 쓰기">
                        <input type="radio" name={`plot-resp-${b.id}`} checked={pickResp === r.name} onChange={() => setResp(r.name)} />
                        {r.name}
                      </label>
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
        <p className="muted small">행을 누르면 오른쪽에 그 DOE의 결과가 열립니다. DOE # 옆 카메라 표시 = 컨투어 캡처 있음(방향은 run을 바꿔도 유지). 학습 범위 밖 값은 숫자 옆 작은 회색 점. 열 이름의 체크(변수)·동그라미(응답)로 그래프를 고릅니다.</p>
        <p className="small">
          <Link to={base}>← 일괄 예측 설정</Link>
        </p>
      </Card>

      <RunPanel row={selRow} base={base} canCapture={canExec} view={mediaView} onView={setMediaView} psId={b.param_set.id} />
      <Card span={3} title="응답 그래프" className="batch-plot">
        {kind === "none" || !pickResp ? (
          <p className="muted small" data-testid="plot-hint">
            {showResp ? PLOT_HINT : NO_RESP_TEXT}
          </p>
        ) : kind === "2d" ? (
          <ResponsePlot2D pts={pts.map((p) => ({ doe_no: p.doe_no, run_key: p.run_key, x: p.v[0], y: p.r }))} xLabel={pickVars[0]} yLabel={pickResp} selected={selected} onSelect={setSelected} />
        ) : (
          <ResponsePlot3D pts={pts3} labels={labels3} selected={selected} onSelect={setSelected} />
        )}
      </Card>
      <Card span={3} title="커브 겹쳐보기" className="batch-curves">
        <CurveOverlay batchId={b.id} selected={selected} version={b.predict.succeeded} />
      </Card>

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

function ResultRow({ r, b, showResp, selected, onSelect, canRetry, onRetry }: { r: PredictBatchRow; b: PredictBatch; showResp: boolean; selected: boolean; onSelect: () => void; canRetry: boolean; onRetry: () => void }) {
  const failed = isRowFailed(r.state);
  return (
    <tr className={`clickable${selected ? " selected" : ""}`} onClick={onSelect} data-testid={`row-${r.doe_no}`}>
      <td>
        <button type="button" className={selected ? "link strong red" : "link strong"} aria-pressed={selected} aria-label={`DOE #${r.doe_no} 선택`} onClick={(e) => (e.stopPropagation(), onSelect())}>
          {r.doe_no}
        </button>
        {!!r.media_views?.length && <CaptureMark views={r.media_views} />}
      </td>
      <td className="mono small">{r.run_key}</td>
      {b.parameters.map((n) => (
        <td key={n} className="num">
          {fmtNum(r.applied_values[n] ?? r.values[n])}
          <OutDot on={r.out_of_range.includes(n)} />
        </td>
      ))}
      {showResp &&
        b.responses.map((x) => (
          <td key={x.name} className={selected ? "num strong" : "num"}>
            {r.responses?.[x.name] == null ? <span className="muted">—</span> : fmtNum(r.responses[x.name])}
          </td>
        ))}
      <td className={`num row-state ${r.state.toLowerCase()}`}>
        {ROW_STATE_LABEL[r.state]}
        {failed && (r.code || r.message) && (
          <span className="muted small row-reason" title={r.message ?? ""}>
            {" "}
            {r.code ?? ""}
            {r.message ? ` — ${r.message}` : ""}
          </span>
        )}
        {canRetry && (
          <button type="button" className="btn small ghost" onClick={(e) => (e.stopPropagation(), onRetry())}>
            다시 실행
          </button>
        )}
      </td>
    </tr>
  );
}

/** 미디어 있는 행 표시(작은 카메라 SVG, 이모지 아님) */
function CaptureMark({ views }: { views: string[] }) {
  const t = `캡처 ${views.length}방향`;
  return (
    <svg className="capture-mark" width="14" height="12" viewBox="0 0 14 12" role="img" aria-label={t} data-testid="capture-mark">
      <title>{t}</title>
      <path d="M1 3h3l1.5-2h3L10 3h3v8H1z" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <circle cx="7" cy="7" r="2.2" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

/** 고른 DOE: 머리 DOE #N · run_key, 컨투어(방향별 스크린샷·영상) + 접힌 결과 목록, 경로 복사·단일 예측으로 열기·PBS 검증 해석 */
function RunPanel({ row, base, canCapture, view, onView, psId }: { row: PredictBatchRow | null; base: string; canCapture: boolean; view: ViewKey | null; onView: (v: ViewKey) => void; psId: string }) {
  const navigate = useNavigate();
  const { paramSets } = useStudy();
  const [job, setJob] = useState<Job | null>(null);
  useEffect(() => {
    setJob(null);
    if (!row?.job_id || row.state !== "SUCCEEDED") return;
    let alive = true;
    api.job(row.job_id).then((j) => alive && setJob(j)).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [row?.job_id, row?.state]);
  const result = job?.state === "SUCCEEDED" ? (job.result as unknown as PR | null) : null;
  const pbs = usePredictVerify(job, !!result);
  if (!row)
    return (
      <Card span={3} title="DOE" className="batch-run-panel">
        <p className="muted small">표나 그래프에서 run을 고르세요.</p>
      </Card>
    );
  const done = row.state === "SUCCEEDED" && !!row.job_id;
  return (
    <Card span={3} title={`DOE #${row.doe_no}`} step={row.run_key} className="batch-run-panel">
      {!done ? (
        <p className="muted small">{ROW_STATE_LABEL[row.state]} — 예측이 끝나면 컨투어와 결과 목록이 나옵니다.</p>
      ) : (
        <>
          <ContourMedia key={row.job_id} jobId={row.job_id!} view={view} onView={onView} canCapture={canCapture} captureViews={paramSets.find((p) => p.id === psId)?.display?.views ?? null} />
          {result ? <ResultListTree artifactId={result.preview_json_artifact_id} /> : <p className="muted small">불러오는 중…</p>}
        </>
      )}
      <div className="run-action-row">
        <CopyButton text={row.folder} label="경로 복사" />
        <button type="button" className="btn small" disabled={!row.job_id || row.state !== "SUCCEEDED"} onClick={() => navigate(`${base}?job=${row.job_id}`)}>
          단일 예측으로 열기
        </button>
        {pbs.button}
      </div>
      {pbs.notes}
    </Card>
  );
}
