import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type ParamSet, type PredictCheck, type PredictParamsParametric, type PredictResult as PR } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Card, RunAction } from "../../components/ui";
import { FeatureGate } from "../../components/FeatureGate";
import { POLL } from "../../lib/poll";
import { isIntegerFormat } from "../../lib/format";
import { ParamInputTable, ParamScatter, RangeNote, RoundingNote } from "./ParamInputs";
import { PredictChain, PredictResultCard } from "./PredictResult";
import { ModelLine, useModelChoice, usePredictVerify } from "./predictRun";
import { useSamples } from "./useSamples";

export { PBS_DISABLED_TEXT } from "./predictRun";

export function PredictWorkspace({ ps }: { ps: ParamSet }) {
  const { study } = useStudy();
  const canExec = useCanExecute();
  const samples = useSamples(ps);
  const nominal = useMemo(() => Object.fromEntries(ps.parameters.map((p) => [p.name, p.nominal])), [ps]);
  const [values, setValues] = useState<Record<string, number>>(nominal);
  const [source, setSource] = useState<{ kind: "nominal" | "run" | "manual"; run?: string }>({ kind: "nominal" });
  const [runPick, setRunPick] = useState("");
  const [check, setCheck] = useState<PredictCheck | null>(null);
  const [axes, setAxes] = useState<[string, string]>([ps.parameters[0]?.name ?? "", ps.parameters[1]?.name ?? ps.parameters[0]?.name ?? ""]);
  const choice = useModelChoice();
  const { modelId, chosenModel } = choice;
  const predict = useJobRunner("PREDICT");

  const integerNames = useMemo(
    () => new Set(ps.tpl_params.filter((t) => isIntegerFormat(t.format)).map((t) => t.name)),
    [ps],
  );

  // 디바운스 predict/check(§16.5)
  const seq = useRef(0);
  useEffect(() => {
    const allFinite = ps.parameters.every((p) => Number.isFinite(values[p.name]));
    if (!allFinite) return;
    const my = ++seq.current;
    const t = setTimeout(() => {
      api
        .predictCheck(study.id, { param_set_id: ps.id, values })
        .then((r) => my === seq.current && setCheck(r))
        .catch(() => undefined);
    }, POLL.checkDebounce);
    return () => clearTimeout(t);
  }, [values, ps, study.id]);

  const setOne = useCallback((name: string, v: number) => {
    setValues((prev) => ({ ...prev, [name]: v }));
    setSource({ kind: "manual" });
  }, []);

  const loadRun = (runKey: string) => {
    setRunPick(runKey);
    const r = samples.find((s) => s.run_key === runKey);
    if (!r) return;
    setValues({ ...nominal, ...r.values });
    setSource({ kind: "run", run: runKey });
  };

  const allFinite = ps.parameters.every((p) => Number.isFinite(values[p.name]));

  const runPredict = () => {
    const params: PredictParamsParametric = {
      param_set_id: ps.id,
      model_id: modelId || null,
      values,
      value_source: source.kind,
      source_run_key: source.kind === "run" ? source.run ?? null : null,
    };
    void predict.run({ ...params });
  };

  const pjob = predict.job;
  const result = pjob?.state === "SUCCEEDED" ? (pjob.result as unknown as PR | null) : null;
  const pbs = usePredictVerify(pjob, !!result);

  return (
    <>
      <Card span={9} title="입력 · 실행" className="inputs">
        <div className="input-split">
          <div className="input-left">
        <div className="fill-row">
          <span className="field-label">값 채우기</span>
          <div className="seg" role="group" aria-label="값 채우기">
            <button
              type="button"
              className={source.kind === "nominal" ? "on" : ""}
              onClick={() => {
                setValues(nominal);
                setSource({ kind: "nominal" });
              }}
            >
              공칭
            </button>
            <button type="button" className={source.kind === "manual" ? "on" : ""} onClick={() => setSource({ kind: "manual" })}>
              직접 입력
            </button>
          </div>
          <label className="inline-field">
            학습 run 불러오기
            <select value={source.kind === "run" ? runPick : ""} onChange={(e) => e.target.value && loadRun(e.target.value)} disabled={!samples.length} aria-label="학습 run 불러오기">
              <option value="">{samples.length ? "run 선택…" : "샘플 없음"}</option>
              {samples.map((s) => (
                <option key={s.run_key}>{s.run_key}</option>
              ))}
            </select>
          </label>
        </div>
          <div className="input-table">
            <ParamInputTable params={ps.parameters} values={values} samples={samples} integerNames={integerNames} onChange={setOne} readOnly={false} />
            <RangeNote check={check} />
            <RoundingNote check={check} />
          </div>
            <div className="run-block">
              <ModelLine choice={choice} />
              <FeatureGate feature="predict">
                {(enabled) => (
                  <RunAction
                    canExecute={canExec}
                    label="예측 실행"
                    onRun={runPredict}
                    job={pjob}
                    disabled={!enabled || !chosenModel || !allFinite}
                    disabledReason={!enabled ? undefined : !chosenModel ? "Final 모델이 필요합니다" : "모든 파라미터 값을 입력하세요"}
                    error={predict.error}
                    extra={pbs.button}
                  />
                )}
              </FeatureGate>
              {pbs.notes}
              <PredictChain job={pjob} mode="parametric" />
            </div>
          </div>
          <div className="input-scatter">
            {ps.parameters.length >= 2 ? (
              <ParamScatter
                params={ps.parameters}
                samples={samples}
                values={values}
                nearestRun={check?.nearest?.run_key ?? null}
                xName={axes[0]}
                yName={axes[1]}
                onAxes={(x, y) => setAxes([x, y])}
              />
            ) : (
              <p className="muted small">파라미터가 2개 이상일 때 산점도를 표시합니다.</p>
            )}
          </div>
        </div>
      </Card>

      <PredictResultCard job={pjob} verifyValues={pbs.verifyValues} />
    </>
  );
}
