import { useState } from "react";
import { type TrainRun, type TrainRunState } from "../../api";
import { useApp } from "../../app/AppContext";
import { fmtElapsed } from "../../lib/format";

const RUN_STATE_LABEL: Record<TrainRunState, string> = {
  GENERATED: "생성됨",
  SUBMITTED: "제출됨",
  SOLVED: "해석 완료",
  SOLVE_FAILED: "해석 실패",
  COLLECTED: "회수됨",
  COLLECT_FAILED: "회수 실패",
};

const HPC_STATE_TEXT: Record<string, string> = { SUBMITTING: "제출 중", QUEUED: "대기", UNKNOWN: "확인 중", RUNNING: "실행" };

export function RunTable({
  runs,
  onResubmit,
  onCancel,
  canCancel,
  cancelFailed = false,
}: {
  runs: TrainRun[];
  onResubmit?: (key: string) => void;
  onCancel?: () => void;
  canCancel: boolean;
  /** C18: 작업 attention_code=HPC_CANCEL_FAILED */
  cancelFailed?: boolean;
}) {
  const { me } = useApp();
  const admin = me.is_global_admin;
  const [confirm, setConfirm] = useState(false);
  return (
    <div className="table-wrap runtable">
      <table className="table compact" aria-label="PBS 제출 표">
        <thead>
          <tr>
            <th>run</th>
            <th>PBS job</th>
            <th>상태</th>
            <th className="num">경과</th>
            {admin && <th />}
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => {
            const failed = r.state === "SOLVE_FAILED" || r.state === "COLLECT_FAILED";
            return (
              <tr key={r.run_key} className={`run-${r.state.toLowerCase()}`}>
                <td className="mono">{r.run_key}</td>
                <td className="mono small">
                  {r.hpc?.external_job_id ?? "–"}
                  {r.hpc && r.hpc.attempt_no > 1 ? <span className="muted"> · {r.hpc.attempt_no}차</span> : null}
                </td>
                <td>
                  <span className={`run-state ${r.state.toLowerCase()}`}>{RUN_STATE_LABEL[r.state]}</span>
                  {r.state === "SUBMITTED" && r.hpc?.state === "CANCEL_REQUESTED" ? (
                    <span className="warn-text small" data-testid="run-cancel-failed">
                      {" "}
                      ({cancelFailed ? "취소 실패, 재시도 중" : "취소 요청됨"})
                    </span>
                  ) : (
                    r.state === "SUBMITTED" && r.hpc?.state && <span className="muted small"> ({HPC_STATE_TEXT[r.hpc.state] ?? r.hpc.state})</span>
                  )}
                </td>
                <td className="num small">{r.state === "SUBMITTED" ? fmtElapsed(r.updated_at) : "–"}</td>
                {admin && (
                  <td className="row-actions">
                    {failed && onResubmit && (
                      <button type="button" className="btn small ghost" onClick={() => onResubmit(r.run_key)}>
                        재제출
                      </button>
                    )}
                    {r.state === "SUBMITTED" && canCancel && onCancel && (
                      confirm ? (
                        <button type="button" className="btn small danger" onClick={onCancel} title="run별 취소 API가 없어 이 PBS 제출 작업 전체를 취소합니다">
                          작업 전체 취소
                        </button>
                      ) : (
                        <button type="button" className="btn small ghost" onClick={() => setConfirm(true)}>
                          취소
                        </button>
                      )
                    )}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
