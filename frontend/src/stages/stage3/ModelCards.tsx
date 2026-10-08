import { useEffect, useMemo, useState } from "react";
import { api, errorMessage, type Model } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Advanced, Card, Field, RunAction } from "../../components/ui";
import { PathInput } from "../../components/PathInput";
import { Chart, Sparkline } from "../../components/Chart";
import { fmtNum, fmtTime } from "../../lib/format";
import { scoreSummary } from "../../panels/ModelPanel";

const NAME_RE = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;

export function LogStatusText({ m }: { m: Pick<Model, "log_status" | "log_parser"> }) {
  if (m.log_status === "PARSED") return <span className="small">파싱됨{m.log_parser ? ` (${m.log_parser})` : ""}</span>;
  if (m.log_status === "UNRECOGNIZED") return <span className="muted small">로그 형식 미확인</span>;
  return <span className="muted small">로그 없음</span>;
}

export function ModelRegisterCard() {
  const { study, datasets, models, reloadModels } = useStudy();
  const canExec = useCanExecute();
  const [path, setPath] = useState("");
  const [logs, setLogs] = useState<string[]>([]);
  const [ok, setOk] = useState(false);
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [dsId, setDsId] = useState("");
  const [logFile, setLogFile] = useState("");
  const { job, run, error } = useJobRunner("MODEL_REGISTER", () => void reloadModels());
  // 최신 등록 작업의 결과 모델(로그 상태 표시)
  const registeredId = job?.state === "SUCCEEDED" ? (job.result as { model_id?: string } | null)?.model_id : undefined;
  const registered = registeredId ? models.find((x) => x.id === registeredId) ?? null : null;

  const readyDs = datasets.filter((d) => d.status === "READY");
  const nameOk = NAME_RE.test(name);
  const needLogChoice = logs.length > 1 && !logFile;

  const submit = () =>
    void run({
      model_path: path.trim(),
      name,
      label: label.trim() || null,
      dataset_id: dsId || null,
      log_file: logFile || null,
    });

  return (
    <Card step="③-4" title="모델 등록">
      <PathInput
        studyId={study.id}
        purpose="MODEL_FOLDER"
        label="모델 폴더 경로 (.psmdl·.pscfg·로그)"
        placeholder="E:/shared/AI_WORK/cushion/00_inbox/model_v3"
        value={path}
        onChange={setPath}
        canExecute={canExec}
        onInspected={(r) => {
          setOk(!!r?.ok);
          const l = r?.summary.logs ?? [];
          setLogs(l);
          setLogFile(l.length === 1 ? l[0] : "");
          const stem = r?.summary.psmdl?.[0]?.replace(/\.psmdl$/i, "");
          if (stem && !name) setName(stem);
        }}
        renderSummary={(r) => (
          <div className="summary-grid small">
            <span>psmdl</span>
            <span className="mono">{r.summary.psmdl?.join(", ") || "없음"}</span>
            <span>pscfg</span>
            <span className="mono">{r.summary.pscfg?.join(", ") || "없음"}</span>
            <span>로그</span>
            <span className="mono">{r.summary.logs?.join(", ") || "없음 (등록은 가능)"}</span>
          </div>
        )}
      />
      <div className="form-grid">
        <Field label="모델 이름" hint={name && !nameOk ? "영문으로 시작, 영문·숫자·_ 64자 이내" : "같은 이름이면 버전이 올라갑니다"}>
          <input className="mono" value={name} onChange={(e) => setName(e.target.value)} disabled={!canExec} aria-invalid={!!name && !nameOk} />
        </Field>
        {logs.length > 1 && (
          <Field label="학습 로그 파일" hint="로그 후보가 여러 개입니다. 하나를 고르세요">
            <select value={logFile} onChange={(e) => setLogFile(e.target.value)}>
              <option value="">선택…</option>
              {logs.map((l) => (
                <option key={l}>{l}</option>
              ))}
            </select>
          </Field>
        )}
      </div>
      <Advanced>
        <div className="form-grid">
          <Field label="표시명">
            <input value={label} maxLength={120} onChange={(e) => setLabel(e.target.value)} />
          </Field>
          <Field label="학습 데이터셋" hint="평가는 이 데이터셋의 평가용(홀드아웃)으로 합니다">
            <select value={dsId} onChange={(e) => setDsId(e.target.value)}>
              <option value="">최신 준비된 데이터셋</option>
              {readyDs.map((d) => (
                <option key={d.id} value={d.id}>
                  {fmtTime(d.created_at)} · 학습 {d.train_count} / 평가 {d.eval_count}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </Advanced>
      <RunAction
        canExecute={canExec}
        label="모델 등록"
        onRun={submit}
        job={job}
        disabled={!ok || !nameOk || needLogChoice}
        disabledReason={!ok ? "경로를 입력하고 확인하세요" : !nameOk ? "모델 이름을 확인하세요" : "로그 파일을 고르세요"}
        error={error}
      />
      {registered && (
        <div className="result-line" data-testid="register-result">
          등록됨: <b>{registered.name}</b> v{registered.version} · <LogStatusText m={registered} />
          {registered.log_status === "PARSED" && registered.epochs_total != null && (
            <span className="small"> · {registered.epochs_total} epoch</span>
          )}
        </div>
      )}
      <p className="muted small">등록 시 파일을 Study 폴더로 복사합니다. 등록 후 원본 폴더는 지워도 됩니다.</p>
    </Card>
  );
}

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

  const dsLabel = (id: string | null) => {
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
        <RunAction
          canExecute={canExec}
          label="평가"
          onRun={() => selected && void run({ model_id: selected.id })}
          job={job}
          disabled={!selected || !dsReady(selected)}
          disabledReason={!selected ? "등록된 모델이 없습니다" : "모델의 데이터셋이 준비되지 않았습니다(평가 불가)"}
          error={error}
        />
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
                      <b>{m.name}</b> <span className="muted">v{m.version}</span>
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
