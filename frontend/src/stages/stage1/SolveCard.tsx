import { useEffect, useState } from "react";
import { api, errorMessage } from "../../api";
import { useApp } from "../../app/AppContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Advanced, Card, CodeLine, Field, RunAction } from "../../components/ui";
import { FeatureGate } from "../../components/FeatureGate";
import { isTerminal } from "../../lib/format";
import { useTrain } from "./TrainContext";
import { DoePicker } from "./DoePicker";
import { RunStateBar } from "./RunStateBar";
import { RunTable } from "./RunTable";

export const PBS_NONE_TEXT = "PBS 연결 안 됨 — DOE 입력 폴더를 직접 해석한 뒤 ①-5에서 결과 폴더를 지정하세요";

// ---------------------------------------------------------------- ①-4
export function SolveCard() {
  const { status } = useApp();
  const { doe, runs, reloadRuns } = useTrain();
  const canExec = useCanExecute();
  const solve = useJobRunner("TD_SOLVE", () => void reloadRuns());
  const [hpc, setHpc] = useState({ queue: "", ncpus: "", walltime: "" });
  const [onFail, setOnFail] = useState<"collect_partial" | "fail">("collect_partial");
  const [actionError, setActionError] = useState<string | null>(null);
  const hpcOn = !!status?.hpc.configured;
  const job = solve.job;

  useEffect(() => {
    void reloadRuns();
  }, [job?.id, job?.version, reloadRuns]);

  const submit = (runKeys: string[] | null) =>
    doe &&
    void solve.run({
      doe_id: doe.id,
      run_keys: runKeys,
      hpc: { queue: hpc.queue || null, ncpus: hpc.ncpus ? Number(hpc.ncpus) : null, walltime: hpc.walltime || null },
      on_run_failure: onFail,
    });
  const pending = runs.filter((r) => r.state === "GENERATED" || r.state === "SOLVE_FAILED" || r.state === "COLLECT_FAILED").length;
  const cancel = async () => {
    if (!job) return;
    setActionError(null);
    try {
      await api.cancelJob(job.id);
      await reloadRuns();
    } catch (e) {
      setActionError(errorMessage(e));
    }
  };

  return (
    <Card step="①-4" title="PBS 해석 제출" className="solve-card">
      <DoePicker />
      <Advanced>
        <div className="form-grid">
          <Field label="queue">
            <input value={hpc.queue} onChange={(e) => setHpc({ ...hpc, queue: e.target.value })} aria-label="queue" />
          </Field>
          <Field label="ncpus">
            <input className="num" inputMode="numeric" value={hpc.ncpus} onChange={(e) => setHpc({ ...hpc, ncpus: e.target.value.replace(/[^0-9]/g, "") })} aria-label="ncpus" />
          </Field>
          <Field label="walltime" hint="예 24:00:00">
            <input value={hpc.walltime} onChange={(e) => setHpc({ ...hpc, walltime: e.target.value })} aria-label="walltime" />
          </Field>
          <Field label="일부 run 실패 시">
            <select value={onFail} onChange={(e) => setOnFail(e.target.value as "fail")} aria-label="일부 run 실패 시">
              <option value="collect_partial">성공한 run 회수</option>
              <option value="fail">작업 실패</option>
            </select>
          </Field>
        </div>
      </Advanced>
      {hpcOn ? (
        <FeatureGate feature="train_solve">
          {(enabled) => (
            <RunAction
              canExecute={canExec}
              label="PBS 제출"
              onRun={() => submit(null)}
              job={job}
              disabled={!enabled || !doe || pending === 0}
              disabledReason={enabled ? (!doe ? "준비된 DOE가 필요합니다" : "제출할 run이 없습니다") : undefined}
              error={solve.error}
              extra={doe && pending > 0 ? <span className="muted small">대상 {pending}개</span> : undefined}
            />
          )}
        </FeatureGate>
      ) : (
        <div className="pbs-none" data-testid="pbs-none">
          <div className="run-action-row">
            {canExec ? (
              <button type="button" className="btn primary" disabled title={PBS_NONE_TEXT}>
                PBS 제출
              </button>
            ) : (
              <span className="readonly">조회 전용</span>
            )}
            <span className="muted small">{PBS_NONE_TEXT}</span>
          </div>
          {doe && <CodeLine text={doe.dir_display_path} />}
        </div>
      )}
      {actionError && <div className="error-text small">{actionError}</div>}
      {doe && <RunStateBar doe={doe} />}
      {doe && runs.length > 0 && (
        <details className="advanced" open={hpcOn}>
          <summary>run 목록 ({runs.length})</summary>
          <RunTable
            runs={runs}
            canCancel={!!job && !isTerminal(job.state)}
            cancelFailed={!!job && !isTerminal(job.state) && job.attention_code === "HPC_CANCEL_FAILED"}
            onCancel={cancel}
            onResubmit={hpcOn && canExec ? (k) => submit([k]) : undefined}
          />
        </details>
      )}
    </Card>
  );
}
