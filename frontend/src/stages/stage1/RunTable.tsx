import { Fragment, useState } from "react";
import { type HpcJob, type TrainRun, type TrainRunState } from "../../api";
import { useApp } from "../../app/AppContext";
import { CheckPill, FolderCell, HpcResolvePanel, hpcPhaseText, isScxRow, needsCheck } from "../../components/HpcScx";
import { fmtElapsed } from "../../lib/format";
import { useFeature } from "../../components/FeatureGate";
import { useCanExecute } from "../../hooks/useJobRunner";
import { ContourPanel } from "../stage4/geomview/contour/ContourPanel";
import { webglAvailable } from "../stage4/geomview/webgl";

const RUN_STATE_LABEL: Record<TrainRunState, string> = {
  GENERATED: "생성됨",
  SUBMITTED: "제출됨",
  SOLVED: "해석 완료",
  SOLVE_FAILED: "해석 실패",
  COLLECTED: "회수됨",
  COLLECT_FAILED: "회수 실패",
};

const HPC_STATE_TEXT: Record<string, string> = { SUBMITTING: "제출 중", QUEUED: "대기", UNKNOWN: "확인 중", RUNNING: "실행" };

/** phase3 §16 SCX(D3-58): run별 HPC 행과 결과 모름 조치 */
export interface ScxRows {
  jobId: string;
  rows: Record<string, HpcJob>;
  canAct: boolean;
  onChange: (r: HpcJob) => void;
  onReload: () => unknown;
}

export function RunTable({
  runs,
  onResubmit,
  onCancel,
  canCancel,
  cancelFailed = false,
  scx,
  studyId,
}: {
  runs: TrainRun[];
  onResubmit?: (key: string) => void;
  onCancel?: () => void;
  canCancel: boolean;
  /** C18: 작업 attention_code=HPC_CANCEL_FAILED */
  cancelFailed?: boolean;
  /** hpc.mode=scx일 때만 */
  scx?: ScxRows;
  /** geometry-view GV-C3: 있으면 결과 h3d가 있는 run에 [3D 컨투어](SOLVER_H3D {study_id, h3d_rel}) */
  studyId?: string;
}) {
  const { me } = useApp();
  const admin = me.is_global_admin;
  const [confirm, setConfirm] = useState(false);
  const c3 = useFeature("contour3d");
  const canExec = useCanExecute();
  const want3d = !!studyId && c3.enabled;
  const [gl] = useState(() => want3d && webglAvailable());
  const [c3Key, setC3Key] = useState<string | null>(null);
  const c3On = want3d && gl;
  const cols = 4 + (scx ? 1 : 0) + (c3On ? 1 : 0) + (admin ? 1 : 0);
  return (
    <div className="table-wrap runtable">
      <table className="table compact" aria-label="PBS 제출 표">
        <thead>
          <tr>
            <th>run</th>
            <th>{scx ? "잡 ID" : "PBS job"}</th>
            {scx && <th>드라이브 폴더</th>}
            <th>상태</th>
            <th className="num">경과</th>
            {c3On && <th>결과</th>}
            {admin && <th />}
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => {
            const failed = r.state === "SOLVE_FAILED" || r.state === "COLLECT_FAILED";
            const row = scx?.rows[r.run_key];
            const scxRow = isScxRow(row) ? row : null;
            const check = needsCheck(scxRow);
            return (
              <Fragment key={r.run_key}>
              <tr className={`run-${r.state.toLowerCase()}`}>
                <td className="mono">{r.run_key}</td>
                <td className="mono small">
                  {r.hpc?.external_job_id ?? "–"}
                  {r.hpc && r.hpc.attempt_no > 1 ? <span className="muted"> · {r.hpc.attempt_no}차</span> : null}
                </td>
                {scx && (
                  <td>
                    <FolderCell path={scxRow?.remote_dir} />
                  </td>
                )}
                <td>
                  {check ? <CheckPill /> : <span className={`run-state ${r.state.toLowerCase()}`}>{RUN_STATE_LABEL[r.state]}</span>}
                  {check ? null : r.state === "SUBMITTED" && r.hpc?.state === "CANCEL_REQUESTED" ? (
                    <span className="warn-text small" data-testid="run-cancel-failed">
                      {" "}
                      ({cancelFailed ? "취소 실패, 재시도 중" : "취소 요청됨"})
                    </span>
                  ) : (
                    (r.state === "SUBMITTED" || (!!scxRow && r.state === "SOLVED" && scxRow.collect_state === "COLLECTING")) &&
                    r.hpc?.state && <span className="muted small"> ({scxRow ? hpcPhaseText(scxRow) : HPC_STATE_TEXT[r.hpc.state] ?? r.hpc.state})</span>
                  )}
                </td>
                <td className="num small">{r.state === "SUBMITTED" ? fmtElapsed(r.updated_at) : "–"}</td>
                {c3On && (
                  <td>
                    {r.h3d_rel ? (
                      <button type="button" className={`btn small ghost${c3Key === r.run_key ? " on" : ""}`} aria-expanded={c3Key === r.run_key}
                        disabled={!canExec && c3Key !== r.run_key} title={canExec ? "이 run의 해석 결과 컨투어를 3D로 봅니다" : "실행 권한(power 이상)이 필요합니다"}
                        onClick={() => setC3Key((k) => (k === r.run_key ? null : r.run_key))}>
                        3D 컨투어
                      </button>
                    ) : (
                      <span className="muted small">–</span>
                    )}
                  </td>
                )}
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
              {c3On && studyId && r.h3d_rel && c3Key === r.run_key && (
                <tr className="run-detail" data-testid="run-contour3d">
                  <td colSpan={cols}>
                    <ContourPanel key={r.run_key} source={{ source_kind: "SOLVER_H3D", source_ref: { study_id: studyId, h3d_rel: r.h3d_rel } }} label={`3D 컨투어(해석 ${r.run_key})`} defaultOpen />
                  </td>
                </tr>
              )}
              {check && scx && scxRow && (
                <tr className="run-detail">
                  <td colSpan={admin ? 6 : 5}>
                    <HpcResolvePanel jobId={scx.jobId} row={scxRow} canAct={scx.canAct} onChange={scx.onChange} onReload={scx.onReload} />
                  </td>
                </tr>
              )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
