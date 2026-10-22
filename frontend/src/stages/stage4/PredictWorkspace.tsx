// ④ A "템플릿 값 입력"(phase3.md §14.8, 시안 01): 템플릿 칸(형상 템플릿·값 표·참고 문구·공칭·학습 run·모델·예측 실행) + 진행 칸 + 결과 칸.
// 요청 body는 S6 parametric 그대로(param_set_id = 고른 템플릿).
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, type ParamSet, type PredictCheck, type PredictJobParams, type PredictParamsParametric, type PredictResult as PR } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Advanced, Card, RunAction } from "../../components/ui";
import { FeatureGate, FeatureOffNote, useFeature } from "../../components/FeatureGate";
import { POLL } from "../../lib/poll";
import { isIntegerFormat } from "../../lib/format";
import { ParamInputTable, ParamScatter, RangeNote, RoundingNote } from "./ParamInputs";
import { PredictChain, PredictResultCard, jobInputMode } from "./PredictResult";
import { PredictSteps } from "./PredictSteps";
import { inputKindOf } from "./TemplatePicker";
import { InputKindSelect, useInputChoice } from "../../components/InputKindSelect";
import { inputKindError } from "../../lib/inputKind";
import { ModelLine, useModelChoice } from "./predictRun";
import { useFemVerifyButton } from "./verify/useFemVerifyButton";

import { useSamples } from "./useSamples";
import { EngineMismatchNote } from "../../components/EngineSelect";
import { GEOM_ERROR_TEXT } from "../../lib/geometry";


export function PredictWorkspace({ ps, picker, aside }: { ps: ParamSet; picker: ReactNode; aside?: ReactNode }) {
  const { study } = useStudy();
  const canExec = useCanExecute();
  const samples = useSamples(ps);
  const ic = useInputChoice(ps);
  // 쿠션 입력(Altair)은 geom_update만 필요 — mesh_only 기능 확인. Native는 서버가 쿠션 명령을 확인한다
  const kind = ps.engine === "native" ? inputKindOf(ps) : ic.value === "cushion" ? "mesh_only" : "assembly";
  const tplFeature = kind === "mesh_only" ? "predict_mesh_only" : "predict_parametric";
  const tplF = useFeature(tplFeature);
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
      ...(ic.picked ? { input: ic.picked } : {}),
    };
    void predict.run({ ...params });
  };

  const pjob = predict.job;
  const result = pjob?.state === "SUCCEEDED" ? (pjob.result as unknown as PR | null) : null;
  const pbs = useFemVerifyButton(pjob ? { kind: "predict_job", job_id: pjob.id } : null, !!result, pjob);
  // 진행 표시: 작업이 기록한 template_kind(서버 확정) → 없으면 지금 템플릿
  const stepKind = (pjob?.params as PredictJobParams | undefined)?.template_kind ?? kind;
  const inputErr = inputKindError(predict.errorDetail);

  return (
    <>
      <Card span={6} title="템플릿" className="inputs template-card" aside={aside}>
        {picker}
        <div className="input-table">
          <ParamInputTable params={ps.parameters} values={values} samples={samples} integerNames={integerNames} onChange={setOne} readOnly={false} />
          <RangeNote check={check} />
          <RoundingNote check={check} />
        </div>
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
        <div className="run-block">
          <InputKindSelect ps={ps} value={ic.value} onChange={(i) => (ic.setPicked(i), predict.clearError())} error={inputErr} />
          <ModelLine choice={choice} />
          <EngineMismatchNote modelEngine={chosenModel?.engine} ps={ps} />
          {ps.engine === "native" && ps.native && ps.native.prep_status !== "READY" && <p className="warn-text small">{GEOM_ERROR_TEXT.GEOM_PREP_STALE}</p>}
          <FeatureGate feature="predict">
            {(enabled) => (
              <RunAction
                canExecute={canExec}
                label="예측 실행"
                onRun={runPredict}
                job={pjob}
                disabled={!enabled || !tplF.enabled || !chosenModel || !allFinite}
                disabledReason={!enabled || !tplF.enabled ? undefined : !chosenModel ? "Final 모델이 필요합니다" : "모든 파라미터 값을 입력하세요"}
                error={inputErr ? null : predict.error}
                extra={pbs.button}
              />
            )}
          </FeatureGate>
          {!tplF.enabled && <FeatureOffNote feature={tplFeature} f={tplF} />}
          {pbs.notes}
        </div>
        {ps.parameters.length >= 2 && samples.length > 0 && (
          <Advanced label="학습 샘플 산점도">
            <ParamScatter
              params={ps.parameters}
              samples={samples}
              values={values}
              nearestRun={check?.nearest?.run_key ?? null}
              xName={axes[0]}
              yName={axes[1]}
              onAxes={(x, y) => setAxes([x, y])}
            />
          </Advanced>
        )}
      </Card>

      <Card span={3} title="진행" className="progress-card">
        {jobInputMode(pjob) === "prepared" ? <PredictChain job={pjob} mode="prepared" /> : <PredictSteps job={pjob} kind={stepKind} />}
        <p className="muted small">끝나면 아래에 컨투어·커브·응답 표가 나옵니다. 알림으로도 알려 줍니다.</p>
      </Card>

      <PredictResultCard job={pjob} verifyValues={pbs.verifyValues} />
    </>
  );
}
