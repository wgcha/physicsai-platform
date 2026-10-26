// phase3 §16 S11 SCX 잡(D3-58): 게이트웨이 중립 단계 글자·드라이브 잡 폴더(표시·복사)·결과 모름(SUBMISSION_UNKNOWN) 조치.
// API는 요청만 기록하고(202, resolve_pending) 워커가 다음 확인 때 처리한다(§16.5) — 화면은 행을 다시 읽어 결과를 보여 준다.
import { useCallback, useEffect, useState } from "react";
import { ApiError, api, errorMessage, type HpcJob, type HpcResolveAction, type Job } from "../api";
import { useApp } from "../app/AppContext";
import { usePolling } from "../hooks/usePolling";
import { isTerminal } from "../lib/format";
import { POLL } from "../lib/poll";
import { ConfirmDialog } from "./ConfirmDialog";
import { CodeLine, CopyButton } from "./ui";

export const SCX_UNKNOWN_TEXT = "제출 응답이 끊겨 제출 여부를 모릅니다. 드라이브/SCX에서 확인 후 선택하세요";
export const SCX_MARK_WARNING = "SCX에 잡이 실제로 있는데 '제출 안 됨'으로 표시하면 같은 해석이 두 번 돌 수 있습니다(폴더는 따로).";

/** /status.hpc.mode가 scx인지(availability API) */
export function useScxMode(): boolean {
  const { status } = useApp();
  return status?.hpc.mode === "scx";
}

export function isScxRow(row: HpcJob | null | undefined): row is HpcJob {
  return !!row && row.gateway_mode === "scx";
}

export function needsCheck(row: HpcJob | null | undefined): boolean {
  return !!row && row.state === "UNKNOWN" && row.submission_unknown;
}

/** 게이트웨이 중립 단계: 업로드 중 → 대기 → 실행 → 완료 → 결과 회수 */
export function hpcPhaseText(row: Pick<HpcJob, "state" | "collect_state" | "submission_unknown">): string {
  if (row.state === "UNKNOWN" && row.submission_unknown) return "확인 필요";
  switch (row.state) {
    case "SUBMITTING":
      return "업로드 중";
    case "QUEUED":
      return "대기";
    case "RUNNING":
      return "실행";
    case "SUCCEEDED":
      if (row.collect_state === "COLLECTING") return "결과 회수 중";
      if (row.collect_state === "COLLECTED") return "결과 회수됨";
      if (row.collect_state === "FAILED") return "회수 실패";
      return "완료";
    case "FAILED":
      return "실패";
    case "CANCEL_REQUESTED":
      return "취소 요청됨";
    case "CANCELED":
      return "취소됨";
    case "LOST":
      return "확인 불가";
    case "UNKNOWN":
      return "확인 중";
    default:
      return row.state;
  }
}

/** 작업의 HPC 행 — scx일 때만 읽고, 작업이 끝나지 않았으면 대기 주기로 다시 읽는다 */
export function useHpcRows(job: Job | null | undefined, enabled: boolean) {
  const jobId = job?.id ?? null;
  const [rows, setRows] = useState<HpcJob[]>([]);
  const load = useCallback(async () => {
    if (!jobId || !enabled) {
      setRows([]);
      return;
    }
    try {
      setRows(await api.hpcJobs(jobId));
    } catch {
      /* 다음 주기에 다시 */
    }
  }, [jobId, enabled]);
  useEffect(() => {
    void load();
  }, [load, job?.version]);
  const active = !!job && enabled && !isTerminal(job.state);
  usePolling(load, active ? POLL.jobWaitingHpc : null, false, [load]);
  const replace = useCallback((r: HpcJob) => setRows((rs) => rs.map((x) => (x.id === r.id ? r : x))), []);
  return { rows, reload: load, replace };
}

/** run별 최신 시도 행 */
export function latestByRun(rows: HpcJob[]): Record<string, HpcJob> {
  const out: Record<string, HpcJob> = {};
  for (const r of rows) if (!out[r.run_key] || out[r.run_key].attempt_no < r.attempt_no) out[r.run_key] = r;
  return out;
}

export function CheckPill() {
  return (
    <span className="run-state needs-check" title={SCX_UNKNOWN_TEXT} data-testid="hpc-needs-check">
      확인 필요
    </span>
  );
}

/** 표 칸용 잡 폴더: 마지막 구간만 보이고(전체는 title) 복사는 전체 경로 */
export function FolderCell({ path }: { path: string | null | undefined }) {
  if (!path) return <span className="muted">–</span>;
  return (
    <span className="folder-cell">
      <code className="mono small" title={path}>
        {path.split("/").filter(Boolean).pop()}
      </code>
      <CopyButton text={path} />
    </span>
  );
}

/** 결과 모름 조치 3개: 다시 확인 · 잡 ID 연결 · 제출 안 됨으로 처리(확인 대화상자) */
export function HpcResolvePanel({
  jobId,
  row,
  canAct,
  onChange,
  onReload,
  showPath = false,
}: {
  jobId: string;
  row: HpcJob;
  canAct: boolean;
  onChange: (r: HpcJob) => void;
  onReload: () => unknown;
  /** 단독 표시(④): 배지·잡 폴더를 함께 보인다. 표(①)는 행에 이미 있음 */
  showPath?: boolean;
}) {
  const [extId, setExtId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);

  const send = async (action: HpcResolveAction, external_job_id?: string): Promise<boolean> => {
    setBusy(true);
    setError(null);
    setConfirmError(null);
    try {
      const r = await api.resolveHpcJob(jobId, row.id, { action, ...(external_job_id ? { external_job_id } : {}), version: row.version ?? 1 });
      onChange(r);
      setExtId("");
      return true;
    } catch (e) {
      const msg = errorMessage(e);
      if (action === "mark_not_submitted") setConfirmError(msg);
      else setError(msg);
      if (e instanceof ApiError && e.status === 409) void onReload();
      return false;
    } finally {
      setBusy(false);
    }
  };

  const extra = row.error_message && !row.error_message.startsWith("SCX 제출 결과를 알 수 없습니다") ? row.error_message : null;
  return (
    <div className="hpc-resolve" data-testid="hpc-resolve">
      <p className="small">
        {showPath && (
          <>
            <CheckPill />{" "}
          </>
        )}
        {SCX_UNKNOWN_TEXT}
      </p>
      {showPath && <CodeLine text={row.remote_dir} />}
      {extra && <p className="warn-text small">{extra}</p>}
      {row.resolve_pending ? (
        <p className="muted small" data-testid="hpc-resolve-pending">
          조치 요청됨 — 다음 확인 때 처리합니다
        </p>
      ) : (
        canAct && (
          <div className="hpc-resolve-actions">
            <button type="button" className="btn small" disabled={busy} onClick={() => void send("recheck")}>
              다시 확인
            </button>
            <span className="hpc-attach">
              <input value={extId} onChange={(e) => setExtId(e.target.value)} placeholder="SCX 잡 ID" aria-label="SCX 잡 ID" maxLength={128} disabled={busy} />
              <button type="button" className="btn small" disabled={busy || !extId.trim()} onClick={() => void send("attach", extId.trim())}>
                잡 ID 연결
              </button>
            </span>
            <button type="button" className="btn small ghost" disabled={busy} onClick={() => setConfirm(true)}>
              제출 안 됨으로 처리
            </button>
          </div>
        )
      )}
      {error && (
        <div className="error-text small" role="alert">
          {error}
        </div>
      )}
      {confirm && (
        <ConfirmDialog
          danger
          title="제출 안 됨으로 처리"
          body={`${SCX_MARK_WARNING}\n드라이브와 SCX 잡 목록에 이 잡이 없는 것을 확인한 뒤 진행하세요.`}
          confirmLabel="제출 안 됨으로 처리"
          error={confirmError}
          onConfirm={async () => {
            if (await send("mark_not_submitted")) setConfirm(false);
          }}
          onCancel={() => {
            setConfirm(false);
            setConfirmError(null);
          }}
        />
      )}
    </div>
  );
}

/** ④ 검증 해석 1건(행 1개): 단계·잡 폴더·결과 위치, 결과 모름이면 조치 */
export function ScxJobStatus({ job, canAct }: { job: Job; canAct: boolean }) {
  const { rows, reload, replace } = useHpcRows(job, true);
  const row = rows.filter(isScxRow).sort((a, b) => b.attempt_no - a.attempt_no)[0];
  if (!row) return null;
  return (
    <div className="scx-job" data-testid="scx-job">
      {needsCheck(row) ? (
        <HpcResolvePanel jobId={job.id} row={row} canAct={canAct} onChange={replace} onReload={reload} showPath />
      ) : (
        <>
          <p className="small">
            SCX 잡 {row.external_job_id ?? "–"} · <span data-testid="scx-phase">{hpcPhaseText(row)}</span>
          </p>
          <CodeLine text={row.remote_dir} />
          {row.output_path && row.output_path !== row.remote_dir && <p className="muted small">결과 위치 {row.output_path}</p>}
          {row.external_state_raw && <p className="muted small" data-testid="scx-raw">SCX 상태 원문: {row.external_state_raw}</p>}
          {row.error_message && <p className="warn-text small">{row.error_message}</p>}
        </>
      )}
    </div>
  );
}
