import { type OptResponse } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Advanced, Card, Field, RunAction } from "../../components/ui";
import { FeatureGate } from "../../components/FeatureGate";
import { METHOD_DEFAULTS, type Method, type RunSettings, activeRules, cleanResponses } from "./rules";

// ---------------------------------------------------------------- ⑤-3
export function OptRunCard({
  s,
  setS,
  responses,
  modelId,
  runner,
}: {
  s: RunSettings;
  setS: (s: RunSettings) => void;
  responses: OptResponse[];
  modelId: string;
  runner: ReturnType<typeof useJobRunner>;
}) {
  const { currentParamSet: ps, models } = useStudy();
  const canExec = useCanExecute();
  const act = activeRules(s);
  const hasModel = !!modelId || models.some((m) => m.is_final && m.status === "ACTIVE");
  const hasObjective = responses.some((r) => r.goal === "MINIMIZE" || r.goal === "MAXIMIZE");
  const consOk = responses.every((r) => r.goal !== "CONSTRAINT" || (r.value !== undefined && Number.isFinite(r.value)));
  const maxOk = Number(s.maxDesigns) >= 1 && Number(s.maxDesigns) <= 100000;
  const reason = !ps
    ? "파라미터 세트가 필요합니다"
    : !hasModel
      ? "Final 모델을 먼저 지정하세요"
      : !responses.length
        ? "응답을 1개 이상 추가하세요"
        : s.approach === "OPT" && !hasObjective
          ? "MINIMIZE 또는 MAXIMIZE 응답이 필요합니다"
          : !consOk
            ? "CONSTRAINT 응답의 Value를 입력하세요"
            : !maxOk
              ? "평가 수는 1~100000"
              : null;

  const setMethod = (m: Method) => setS({ ...s, method: m, maxDesigns: String(METHOD_DEFAULTS[m].max_designs), dv: String(METHOD_DEFAULTS[m].dv) });
  const submit = () =>
    void runner.run({
      param_set_id: ps?.id ?? null,
      model_id: modelId || null,
      approach: s.approach,
      opt_method: s.method,
      max_designs: Number(s.maxDesigns),
      run_nominal: s.runNominal,
      study_folder: s.studyFolder,
      opt_settings: { abs_convergence: Number(s.abs), rel_convergence: Number(s.rel), dv_convergence: Number(s.dv) },
      on_failed: s.onFailed,
      responses: cleanResponses(responses),
    });

  return (
    <Card step="⑤-3" title="실행">
      <div className="form-grid">
        <Field label="Approach">
          <div className="seg" role="radiogroup" aria-label="Approach">
            {(["OPT", "DOE"] as const).map((a) => (
              <button key={a} type="button" role="radio" aria-checked={s.approach === a} className={s.approach === a ? "on" : ""} onClick={() => setS({ ...s, approach: a })}>
                {a}
              </button>
            ))}
          </div>
        </Field>
        <Field label="Opt Method">
          <select value={s.method} disabled={!act.method} onChange={(e) => setMethod(e.target.value as Method)} aria-label="Opt Method">
            {(["ARSM", "GRSM", "SQP"] as const).map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </Field>
        <Field label={s.approach === "OPT" && s.method === "SQP" ? "Maximum Iterations" : "Number of Evaluations"}>
          <input className="num" inputMode="numeric" value={s.maxDesigns} onChange={(e) => setS({ ...s, maxDesigns: e.target.value.replace(/[^0-9]/g, "") })} aria-label="최대 설계 수" />
        </Field>
      </div>
      <label className="check">
        <input type="checkbox" checked={s.runNominal} onChange={(e) => setS({ ...s, runNominal: e.target.checked })} /> Nominal run 먼저 실행
      </label>
      <Advanced>
        <div className="form-grid">
          <Field label="Study 폴더 이름">
            <input className="mono" value={s.studyFolder} onChange={(e) => setS({ ...s, studyFolder: e.target.value })} aria-label="Study 폴더 이름" />
          </Field>
          <Field label="Absolute Convergence">
            <input className="num" value={s.abs} disabled={!act.absRel} onChange={(e) => setS({ ...s, abs: e.target.value })} aria-label="Absolute Convergence" />
          </Field>
          <Field label="Relative Convergence (%)">
            <input className="num" value={s.rel} disabled={!act.absRel} onChange={(e) => setS({ ...s, rel: e.target.value })} aria-label="Relative Convergence" />
          </Field>
          <Field label="Design Variable Convergence">
            <input className="num" value={s.dv} disabled={!act.dv} onChange={(e) => setS({ ...s, dv: e.target.value })} aria-label="Design Variable Convergence" />
          </Field>
          <Field label="On Failed Evaluation">
            <select value={s.onFailed} disabled={!act.onFailed} onChange={(e) => setS({ ...s, onFailed: e.target.value as "IGNORE" })} aria-label="On Failed Evaluation">
              <option value="IGNORE">IGNORE</option>
              <option value="TERMINATE">TERMINATE</option>
            </select>
          </Field>
        </div>
      </Advanced>
      <FeatureGate feature="optimize">
        {(enabled) => (
          <RunAction
            canExecute={canExec}
            label={s.approach === "OPT" ? "최적화 실행" : "DOE 실행"}
            onRun={submit}
            job={runner.job}
            disabled={!enabled || !!reason}
            disabledReason={enabled ? reason ?? undefined : undefined}
            error={runner.error}
          />
        )}
      </FeatureGate>
    </Card>
  );
}
