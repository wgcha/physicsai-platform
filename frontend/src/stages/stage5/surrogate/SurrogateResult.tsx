// ⑤ 내장 최적화 결과(phase3.md §18.10, 라우트 …/stage/5/surrogate/:optId, 진행 중 POLL.surrogate):
// 상태·진행 문구·일괄 취소·이어서 실행 / 최적안 — 기준안 대비 · 결과 요약 / 컨투어 비교(D3-61) / 수렴 그래프 / 대리모델 품질 / 검증 run 표(CSV) / 파일 위치.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../../../api";
import { isSoActive, surrogateApi, type SoIteration, type SoRun, type SurrogateOpt } from "../../../api/surrogateOpt";
import { useStudy } from "../../../app/StudyContext";
import { usePolling } from "../../../hooks/usePolling";
import { Card, CopyButton } from "../../../components/ui";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { fmtNum } from "../../../lib/format";
import { POLL } from "../../../lib/poll";
import { ROW_STATE_LABEL, rowTone } from "../../stage4/batch/batchTable";
import { ConvergenceChart } from "./ConvergenceChart";
import { ContourCompareCard, OptimumCompareCard, ResultSummaryCard } from "./ResultCards";
import { FemEntryButton } from "../../stage4/verify/useFemVerifyButton";
import "../../../styles/surrogateOpt.css";
import { SO_STATUS_LABEL, metricLabel, qualityGrade, soTone } from "./soRules";


export function SurrogateResult({ optId }: { optId: string }) {
  const { study } = useStudy();
  const [o, setO] = useState<SurrogateOpt | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const load = useCallback(async () => {
    try {
      setO(await surrogateApi.get(optId));
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [optId]);
  useEffect(() => {
    void load();
  }, [load]);
  usePolling(load, o && isSoActive(o.status) ? POLL.surrogate : null, false, [optId]);

  if (error && !o) return <Card span={9} title="내장 최적화"><p className="error-text">{error}</p></Card>;
  if (!o) return <Card span={9} title="내장 최적화"><p className="muted">불러오는 중…</p></Card>;

  const base = `/p/${study.project_id}/s/${study.id}`;
  const s = o.settings as { names: string[]; objective: { metric: string; series?: string | null; sense: string }; constraints: { metric: string; series?: string | null; op: string; value: number }[]; iterations: number };
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
      const blob = await surrogateApi.runsCsv(o.id);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${study.folder_name}_${o.label}_runs.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    });
  const objLabel = metricLabel(s.objective.metric, s.objective.series);
  const b = o.best;
  const runs = (o.runs ?? []) as SoRun[];

  return (
    <>
      <Card span={9} title={`내장 최적화 ${o.label}`} className="so-head" aside={<Link className="small" to={`${base}/stage/5`}>⑥ 실행 목록</Link>}>
        <div className="run-action-row">
          <span className={`pill ${soTone(o.status)}`} data-testid="so-status">{SO_STATUS_LABEL[o.status] ?? o.status}</span>
          <span data-testid="so-progress">{o.progress_text}</span>
          <span className="muted small">{objLabel} {s.objective.sense === "max" ? "최대화" : "최소화"} · 반복 {o.iter_no}/{s.iterations} · {(o.param_set as { label?: string }).label ?? "템플릿"} · {(o.model as { name?: string }).name}</span>
        </div>
        <div className="run-action-row">
          {o.can_cancel && <button type="button" className="btn small danger" onClick={() => setConfirm(true)}>일괄 취소</button>}
          {o.can_resume && <button type="button" className="btn small primary" onClick={() => void act(() => surrogateApi.resume(o.id))}>이어서 실행</button>}
        </div>
        {o.warnings?.map((w, i) => <p key={i} className="muted small">{w.message}</p>)}
        {actionError && <p className="error-text small" role="alert">{actionError}</p>}
      </Card>
      <OptimumCompareCard o={o} base={base} />
      <ResultSummaryCard o={o} />
      <ContourCompareCard o={o} />
      <Card span={9} title="수렴 그래프">
        <ConvergenceChart opt={o} />
      </Card>
      <Card span={9} title="대리모델 품질" aside={<span className="muted small">LOO(하나 빼기) · 등급 Q² ≥ 0.9 좋음 · 0.7~0.9 보통</span>}>
        <QualityTable iterations={o.iterations as SoIteration[]} />
      </Card>
      <Card span={9} title="검증 run" aside={<button type="button" className="btn small" onClick={() => void downloadCsv()}>CSV 받기</button>}>
        <RunsTable optId={optId} runs={runs} names={s.names} constraints={s.constraints.map((c) => metricLabel(c.metric, c.series))} best={b} />
      </Card>
      <Card span={9} title="파일 위치">
        <div className="run-action-row">
          <span className="mono small" data-testid="so-dir">{o.dir}</span>
          <CopyButton text={o.dir} label="경로 복사" />
        </div>
      </Card>
      {confirm && (
        <ConfirmDialog
          title={`${o.label} 일괄 취소`}
          body="반복 작업·검증 배치(입력 생성·대기 중 예측)를 모두 취소합니다. 끝난 run 결과와 파일은 남습니다."
          confirmLabel="일괄 취소"
          danger
          onCancel={() => setConfirm(false)}
          onConfirm={() => {
            setConfirm(false);
            void act(() => surrogateApi.cancel(o.id));
          }}
        />
      )}
    </>
  );
}

function QualityTable({ iterations }: { iterations: SoIteration[] }) {
  const rows = iterations.filter((it) => it.fit);
  if (!rows.length) return <p className="muted small">아직 학습한 대리모델이 없습니다.</p>;
  return (
    <div className="table-wrap">
      <table className="table compact" aria-label="대리모델 품질">
        <thead>
          <tr><th className="num">반복</th><th>종류</th><th className="num">n</th><th className="num">LOO RMSE</th><th className="num">NRMSE</th><th className="num">Q²</th><th className="num">예측-검증 MAE</th><th>등급</th></tr>
        </thead>
        <tbody>
          {rows.map((it) => {
            const f = it.fit!;
            const g = qualityGrade(f.q2);
            return (
              <tr key={it.iter_no} data-testid={`fit-${it.iter_no}`}>
                <td className="num">{it.iter_no}</td>
                <td>{f.kind === "gp" ? "GP" : "RBF"}</td>
                <td className="num">{f.n_train}</td>
                <td className="num mono">{fmtNum(f.loo_rmse)}</td>
                <td className="num mono">{fmtNum(f.loo_nrmse, 3)}</td>
                <td className="num mono">{fmtNum(f.q2, 3)}</td>
                <td className="num mono">{fmtNum(f.pred_vs_verified_mae)}</td>
                <td className="small"><span className={`pill ${g.tone}`}>{g.label}</span>{g.hint && <span className="muted"> {g.hint}</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RunsTable({ optId, runs, names, constraints, best }: { optId: string; runs: SoRun[]; names: string[]; constraints: string[]; best: SurrogateOpt["best"] }) {
  if (!runs.length) return <p className="muted small">아직 run이 없습니다.</p>;
  return (
    <div className="table-wrap">
      <table className="table compact" aria-label="검증 run">
        <thead>
          <tr>
            <th className="num">반복</th><th>배치</th><th className="num">DOE #</th>
            {names.map((n) => <th key={n} className="num mono">{n}</th>)}
            <th className="num">목적</th>
            {constraints.map((c, i) => <th key={i} className="num">{c}</th>)}
            <th className="num">예측</th><th>만족</th><th>상태</th><th></th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => {
            const isBest = !!best && best.batch_id === r.batch_id && best.doe_no === r.doe_no;
            return (
              <tr key={`${r.batch_id}-${r.doe_no}`} className={isBest ? "selected" : ""} data-testid={`run-${r.iter_no}-${r.doe_no}`}>
                <td className="num">{r.iter_no}</td>
                <td>{r.batch_label}</td>
                <td className="num">{r.doe_no}</td>
                {names.map((n) => <td key={n} className="num mono">{fmtNum((r.values as Record<string, number>)[n])}</td>)}
                <td className="num mono">{fmtNum(r.objective)}</td>
                {constraints.map((_, i) => <td key={i} className="num mono">{fmtNum(r.constraints?.[i] ?? null)}</td>)}
                <td className="num mono muted">{fmtNum(r.predicted)}</td>
                <td className="small">{r.feasible == null ? "—" : r.feasible ? "만족" : "위반"}</td>
                <td className="small"><span className={`pill ${rowTone(r.state as never)}`}>{ROW_STATE_LABEL[r.state as keyof typeof ROW_STATE_LABEL] ?? r.state}</span></td>
                <td><FemEntryButton source={{ kind: "opt_design", opt_id: optId, pick: "run", iter_no: r.iter_no, doe_no: r.doe_no }} hasResult={r.state === "SUCCEEDED"} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
