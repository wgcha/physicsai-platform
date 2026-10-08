import { useEffect, useState } from "react";
import { api, errorMessage, type TrainDoe, type TrainRun, type TrainRunState } from "../../api";
import { useApp } from "../../app/AppContext";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Advanced, Card, CodeLine, Field, RunAction } from "../../components/ui";
import { PathInput } from "../../components/PathInput";
import { FeatureGate } from "../../components/FeatureGate";
import { fmtElapsed, fmtTime, isTerminal } from "../../lib/format";
import { useTrain } from "./TrainContext";

export const PBS_NONE_TEXT = "PBS 연결 안 됨 — DOE 입력 폴더를 직접 해석한 뒤 ①-5에서 결과 폴더를 지정하세요";

const RUN_STATE_LABEL: Record<TrainRunState, string> = {
  GENERATED: "생성됨",
  SUBMITTED: "제출됨",
  SOLVED: "해석 완료",
  SOLVE_FAILED: "해석 실패",
  COLLECTED: "회수됨",
  COLLECT_FAILED: "회수 실패",
};
const BAR: { key: string; label: string; states: TrainRunState[] }[] = [
  { key: "gen", label: "생성", states: ["GENERATED"] },
  { key: "sub", label: "제출", states: ["SUBMITTED"] },
  { key: "solved", label: "해석 완료", states: ["SOLVED"] },
  { key: "fail", label: "실패", states: ["SOLVE_FAILED", "COLLECT_FAILED"] },
  { key: "col", label: "회수", states: ["COLLECTED"] },
];

function DoePicker({ label = "DOE" }: { label?: string }) {
  const { does, doe, selectDoe } = useTrain();
  const ready = does.filter((d) => d.status === "READY");
  if (!ready.length) return <p className="muted">준비된 DOE가 없습니다. ①-3에서 입력을 먼저 생성하세요.</p>;
  return (
    <Field label={label}>
      <select value={doe?.id ?? ""} onChange={(e) => selectDoe(e.target.value)} aria-label={label}>
        {ready.map((d) => (
          <option key={d.id} value={d.id}>
            {d.doe_label} · run {d.run_count} · {fmtTime(d.created_at)}
          </option>
        ))}
      </select>
    </Field>
  );
}

/** run 상태 막대(§14.2 ①-4) */
export function RunStateBar({ doe }: { doe: TrainDoe }) {
  const c = doe.run_state_counts;
  const total = Object.values(c).reduce((a, b) => a + b, 0) || 1;
  return (
    <div className="runbar-wrap">
      <div className="runbar" role="img" aria-label="run 상태 막대">
        {BAR.map((b) => {
          const n = b.states.reduce((a, s) => a + (c[s] ?? 0), 0);
          return n ? <span key={b.key} className={`runbar-seg ${b.key}`} style={{ flexGrow: n }} title={`${b.label} ${n}`} /> : null;
        })}
      </div>
      <div className="runbar-legend small">
        {BAR.map((b) => {
          const n = b.states.reduce((a, s) => a + (c[s] ?? 0), 0);
          return (
            <span key={b.key} data-testid={`runbar-${b.key}`}>
              <span className={`lg runbar-seg ${b.key}`} /> {b.label} <b>{n}</b>
            </span>
          );
        })}
        <span className="muted">/ {total}</span>
      </div>
    </div>
  );
}

/** PBS 제출 표: run · PBS job · 상태 · 경과 · (전역 관리자) 취소/재제출 */
export function RunTable({ runs, onResubmit, onCancel, canCancel }: { runs: TrainRun[]; onResubmit?: (key: string) => void; onCancel?: () => void; canCancel: boolean }) {
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
                  {r.state === "SUBMITTED" && r.hpc?.state && <span className="muted small"> ({r.hpc.state === "Q" ? "대기" : "실행"})</span>}
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
            onCancel={cancel}
            onResubmit={hpcOn && canExec ? (k) => submit([k]) : undefined}
          />
        </details>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- ①-5
const COLLECT_TEXT: Record<string, string> = {
  in_place: "PBS 결과 폴더에서 자동 회수(in_place)",
  shared_folder: "공유 폴더에서 Study로 자동 복사(shared_folder)",
  drive: "네트워크 드라이브에서 Study로 자동 복사(drive)",
};

export function ResultCollectCard() {
  const { status } = useApp();
  const { study } = useStudy();
  const { doe, runs, reloadRuns } = useTrain();
  const canExec = useCanExecute();
  const imp = useJobRunner("TD_RESULT_IMPORT", () => void reloadRuns());
  const [path, setPath] = useState("");
  const [ok, setOk] = useState(false);
  const hpcOn = !!status?.hpc.configured;
  const c = doe?.run_state_counts;
  const total = runs.length || doe?.run_count || 0;
  const collected = c?.COLLECTED ?? 0;
  const failed = (c?.SOLVE_FAILED ?? 0) + (c?.COLLECT_FAILED ?? 0);
  const missing = runs.filter((r) => r.state !== "COLLECTED");

  useEffect(() => {
    void reloadRuns();
  }, [imp.job?.id, imp.job?.version, reloadRuns]);

  return (
    <Card step="①-5" title="결과 회수">
      <p className="small">
        {hpcOn ? COLLECT_TEXT[status?.hpc.collect_mode ?? "in_place"] ?? `자동 회수(${status?.hpc.collect_mode})` : "PBS 연결 안 됨 — 해석한 결과 폴더를 직접 지정하세요"}
      </p>
      <DoePicker />
      <PathInput
        studyId={study.id}
        purpose="RESULT_FOLDER"
        label="결과 폴더 경로 (수동 지정)"
        placeholder="E:/shared/AI_WORK/cushion/00_inbox/pbs_results"
        value={path}
        onChange={setPath}
        canExecute={canExec && !!doe}
        extra={doe ? { doe_id: doe.id } : undefined}
        onInspected={(r) => setOk(!!r?.ok)}
        renderSummary={(r) => (
          <div className="summary-line">
            매칭 run <b>{String(r.summary.matched_runs ?? 0)}</b>개 · 파일 {String(r.summary.file_count ?? 0)}개
          </div>
        )}
      />
      <FeatureGate feature="train_import">
        {(enabled) => (
          <RunAction
            canExecute={canExec}
            label="결과 가져오기"
            onRun={() => doe && void imp.run({ doe_id: doe.id, source_path: path.trim() })}
            job={imp.job}
            disabled={!enabled || !doe || !ok}
            disabledReason={enabled ? "결과 폴더를 입력하고 확인하세요" : undefined}
            error={imp.error}
          />
        )}
      </FeatureGate>
      {doe && (
        <div className="tiles" aria-label="회수 상태 요약">
          <div className="tile-stat ok">
            <span className="tile-num" data-testid="tile-collected">
              {collected}
              <span className="tile-den">/{total}</span>
            </span>
            <span className="tile-cap">회수</span>
          </div>
          <div className={`tile-stat ${failed ? "bad" : ""}`}>
            <span className="tile-num">{failed}</span>
            <span className="tile-cap">실패</span>
          </div>
          <div className="tile-stat">
            <span className="tile-num">{Math.max(0, total - collected - failed)}</span>
            <span className="tile-cap">미회수</span>
          </div>
        </div>
      )}
      {missing.length > 0 && (
        <details className="advanced">
          <summary>회수 안 된 run ({missing.length})</summary>
          <div className="mono small wrap-list">{missing.map((r) => r.run_key).join(", ")}</div>
        </details>
      )}
      <p className="note">회수한 결과는 ② 데이터 정리의 원천으로, 파라미터·샘플은 ④ "① 결과로 만들기"에 쓰입니다.</p>
    </Card>
  );
}

// ---------------------------------------------------------------- ①-6 (선택)
interface RespRow {
  name: string;
  unit: string;
  spec: string;
}

export function RunResponseCard() {
  const { doe } = useTrain();
  const canExec = useCanExecute();
  const rx = useJobRunner("TD_RESP_EXTRACT");
  const [rows, setRows] = useState<RespRow[]>([{ name: "MaxStress", unit: "MPa", spec: "{}" }]);
  const parsed = rows.map((r) => {
    try {
      return { name: r.name.trim(), unit: r.unit.trim(), spec: JSON.parse(r.spec || "{}") as unknown };
    } catch {
      return null;
    }
  });
  const valid = parsed.every((p) => p && /^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(p.name));
  return (
    <Card step="①-6" title="run 응답 추출 (선택)" className="optional-card">
      <details className="advanced">
        <summary>열기</summary>
        <div className="advanced-body grid-gap">
          <table className="table compact" aria-label="응답 정의">
            <thead>
              <tr>
                <th>이름</th>
                <th>단위</th>
                <th>spec (JSON)</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>
                    <input className="mono" value={r.name} aria-label="응답 이름" onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
                  </td>
                  <td>
                    <input className="unit-input" value={r.unit} aria-label="응답 단위" onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, unit: e.target.value } : x)))} />
                  </td>
                  <td>
                    <input className="mono" value={r.spec} aria-label="spec" onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, spec: e.target.value } : x)))} />
                  </td>
                  <td>
                    <button type="button" className="icon-btn" aria-label="행 삭제" onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button type="button" className="btn small ghost" onClick={() => setRows([...rows, { name: "", unit: "", spec: "{}" }])}>
            행 추가
          </button>
          <FeatureGate feature="train_resp">
            {(enabled) => (
              <RunAction
                canExecute={canExec}
                label="run 응답 추출"
                onRun={() => doe && void rx.run({ doe_id: doe.id, responses: parsed })}
                job={rx.job}
                disabled={!enabled || !doe || !rows.length || !valid || !(doe.run_state_counts.COLLECTED > 0)}
                disabledReason={enabled ? "회수된 run과 올바른 응답 정의가 필요합니다" : undefined}
                error={rx.error}
              />
            )}
          </FeatureGate>
          {doe?.has_run_responses && <p className="small">run 응답 표 있음</p>}
        </div>
      </details>
    </Card>
  );
}
