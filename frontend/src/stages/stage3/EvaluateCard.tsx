import { useEffect, useMemo, useState } from "react";
import { FeatureGate } from "../../components/FeatureGate";
import { api, errorMessage, type Model } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Card, Field, RunAction } from "../../components/ui";
import { Chart, Sparkline } from "../../components/Chart";
import { fmtNum, fmtTime } from "../../lib/format";
import { scoreSummary } from "../../panels/ModelPanel";
import { LogStatusText } from "./ModelRegisterCard";

function useModelDetails(models: Model[]) {
  const [details, setDetails] = useState<Record<string, Model>>({});
  const key = models.map((m) => `${m.id}:${m.row_version}:${m.curve_points ?? 0}`).join("|");
  useEffect(() => {
    let alive = true;
    Promise.all(models.filter((m) => (m.curve_points ?? 0) > 0).map((m) => api.model(m.id).catch(() => null))).then((list) => {
      if (!alive) return;
      const next: Record<string, Model> = {};
      for (const m of list) if (m) next[m.id] = m;
      setDetails(next);
    });
    return () => {
      alive = false;
    };
  }, [key]);
  return details;
}

export function EvaluateCard() {
  const { study, models, datasets, reloadModels } = useStudy();
  const canExec = useCanExecute();
  const active = models.filter((m) => m.status === "ACTIVE");
  const [modelId, setModelId] = useState("");
  const [chartId, setChartId] = useState<string | null>(null);
  const [logY, setLogY] = useState(true);
  const [finalError, setFinalError] = useState<string | null>(null);
  const { job, run, error } = useJobRunner("EVALUATE", () => void reloadModels());
  const details = useModelDetails(models);

  const selected = active.find((m) => m.id === modelId) ?? active.find((m) => m.is_final) ?? active[0];
  const dsReady = (m: Model | undefined) => !!m?.dataset_id && datasets.some((d) => d.id === m.dataset_id && d.status === "READY");
  const shown = useMemo(() => models.filter((m) => m.status !== "ARCHIVED"), [models]);
  const chartModel = details[chartId ?? ""] ?? details[selected?.id ?? ""] ?? Object.values(details)[0];

  const setFinal = async (id: string | null) => {
    try {
      setFinalError(null);
      await api.setFinalModel(study.id, id);
      await reloadModels();
    } catch (e) {
      setFinalError(errorMessage(e));
    }
  };

  const dsLabel = (id: string | null | undefined) => {
    const d = datasets.find((x) => x.id === id);
    return d ? `${fmtTime(d.created_at)} (평가 ${d.eval_count})` : "–";
  };

  return (
    <Card step="③-5" title="평가 · Final 지정" className="wide">
      <div className="eval-row">
        <Field label="평가할 모델">
          <select value={selected?.id ?? ""} onChange={(e) => setModelId(e.target.value)} disabled={active.length === 0}>
            {active.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} v{m.version}
                {m.is_final ? " (Final)" : ""}
              </option>
            ))}
          </select>
        </Field>
        <FeatureGate feature="evaluate">
          {(enabled) => (
            <RunAction
              canExecute={canExec}
              label="평가"
              onRun={() => selected && void run({ model_id: selected.id })}
              job={job}
              disabled={!enabled || !selected || !dsReady(selected)}
              disabledReason={!enabled ? undefined : !selected ? "등록된 모델이 없습니다" : "모델의 데이터셋이 준비되지 않았습니다(평가 불가)"}
              error={error}
            />
          )}
        </FeatureGate>
      </div>
      {finalError && <div className="error-text small" role="alert">{finalError}</div>}
      {shown.length === 0 ? (
        <p className="muted">등록된 모델이 없습니다.</p>
      ) : (
        <div className="table-wrap">
          <table className="table models" aria-label="모델 표">
            <thead>
              <tr>
                <th>모델</th>
                <th>데이터셋</th>
                <th className="num">epoch</th>
                <th className="num">최종 loss</th>
                <th className="num">최소 loss (epoch)</th>
                <th>loss 곡선</th>
                <th>평가 점수</th>
                <th>로그</th>
                <th>Final</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((m) => {
                const d = details[m.id];
                return (
                  <tr key={m.id} className={m.is_final ? "is-final" : ""}>
                    <td>
                      <b title={m.stored_display_path ?? undefined}>{m.name}</b> <span className="muted">v{m.version}</span>
                      {m.label && <div className="muted small">{m.label}</div>}
                      {m.status === "INVALID" && <div className="error-text small">파일 변경 감지(사용 불가)</div>}
                    </td>
                    <td className="small">{dsLabel(m.dataset_id)}</td>
                    <td className="num">{m.epochs_total ?? "–"}</td>
                    <td className="num">{fmtNum(m.final_loss)}</td>
                    <td className="num">
                      {fmtNum(m.min_loss)} {m.min_loss_epoch != null && <span className="muted">({m.min_loss_epoch})</span>}
                    </td>
                    <td>
                      {d?.loss_curve ? (
                        <button type="button" className={`spark-btn ${chartModel?.id === m.id ? "on" : ""}`} onClick={() => setChartId(m.id)} aria-label={`${m.name} loss 곡선 크게 보기`}>
                          <Sparkline pts={d.loss_curve} />
                        </button>
                      ) : (
                        <span className="muted small">{m.log_status === "PARSED" ? "–" : "없음"}</span>
                      )}
                    </td>
                    <td className="small">{scoreSummary(m)}</td>
                    <td>
                      <LogStatusText m={m} />
                    </td>
                    <td>
                      {m.is_final ? (
                        <span className="final-cell">
                          <span className="final-badge">Final</span>
                          {canExec && (
                            <button type="button" className="link small" onClick={() => setFinal(null)}>
                              해제
                            </button>
                          )}
                        </span>
                      ) : canExec && m.status === "ACTIVE" ? (
                        <button type="button" className="btn small ghost" onClick={() => setFinal(m.id)}>
                          Final 지정
                        </button>
                      ) : (
                        <span className="muted small">–</span>
                      )}
                      {m.is_final && m.eval_status !== "DONE" && <div className="muted small">평가 전</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {chartModel?.loss_curve && (
        <div className="losschart">
          <div className="losschart-head">
            <span className="field-label">
              loss 곡선 · {chartModel.name} v{chartModel.version}
            </span>
            <div className="seg" role="group" aria-label="축">
              <button type="button" className={!logY ? "on" : ""} onClick={() => setLogY(false)}>
                선형
              </button>
              <button type="button" className={logY ? "on" : ""} onClick={() => setLogY(true)}>
                로그
              </button>
            </div>
          </div>
          <Chart
            height={220} aspect={0.22} maxHeight={420}
            ariaLabel="loss 곡선"
            logY={logY}
            xLabel="epoch"
            yLabel="loss"
            lines={[{ name: "loss", pts: chartModel.loss_curve }]}
            points={
              chartModel.min_loss != null && chartModel.min_loss_epoch != null
                ? [{ x: chartModel.min_loss_epoch, y: chartModel.min_loss, className: "chart-pt accent", r: 4, title: `최소 ${fmtNum(chartModel.min_loss)}` }]
                : []
            }
          />
        </div>
      )}
    </Card>
  );
}
