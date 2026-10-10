import { useEffect, useState } from "react";
import { api, errorMessage, type DoeField, type DoeType } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Advanced, Card, CodeLine, Field, RunAction } from "../../components/ui";
import { PathInput } from "../../components/PathInput";
import { FeatureGate } from "../../components/FeatureGate";
import { useTrain } from "./TrainContext";

// ---------------------------------------------------------------- ①-3
function defaultOptions(t: DoeType | undefined): Record<string, string | number | boolean> {
  return Object.fromEntries((t?.fields ?? []).map((f) => [f.key, f.default as string | number | boolean]));
}

function OptionInput({ f, value, onChange, disabled }: { f: DoeField; value: unknown; onChange: (v: string | number | boolean) => void; disabled: boolean }) {
  if (f.type === "bool")
    return (
      <label className="check">
        <input type="checkbox" checked={!!value} disabled={disabled} onChange={(e) => onChange(e.target.checked)} /> {f.label}
      </label>
    );
  if (f.type === "combo")
    return (
      <Field label={f.label}>
        <select value={String(value ?? "")} disabled={disabled} onChange={(e) => onChange(e.target.value)} aria-label={f.label}>
          {(f.items ?? []).map((it) => (
            <option key={it}>{it}</option>
          ))}
        </select>
      </Field>
    );
  return (
    <Field label={f.label} hint={f.min !== undefined || f.max !== undefined ? `${f.min ?? ""}~${f.max ?? ""}` : undefined}>
      <input className="num" aria-label={f.label} inputMode="numeric" value={String(value ?? "")} disabled={disabled} onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value.replace(/[^0-9-]/g, "")))} />
    </Field>
  );
}

const SAMPLE_TEXT: Record<string, string> = {
  PARSED: "샘플 표 있음",
  PARTIAL: "샘플 표 일부 run 누락",
  MISSING: "샘플 표 없음 — ④ '① 결과로 만들기'를 쓸 수 없습니다",
  PENDING: "샘플 표 확인 중",
};

export function DoeGenCard() {
  const { study } = useStudy();
  const { setup, does, reloadDoes } = useTrain();
  const canExec = useCanExecute();
  const { job, run, error } = useJobRunner("TD_DOE_GEN", () => void reloadDoes());
  const [types, setTypes] = useState<DoeType[]>([]);
  const [typesError, setTypesError] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [runs, setRuns] = useState("");
  const [opts, setOpts] = useState<Record<string, string | number | boolean>>({});
  const [multi, setMulti] = useState(1);
  const [path, setPath] = useState("");
  const [ok, setOk] = useState(false);

  useEffect(() => {
    api
      .doeTypes()
      .then((t) => {
        setTypes(t);
        if (t[0]) {
          setLabel(t[0].label);
          setRuns(String(t[0].default_runs));
          setOpts(defaultOptions(t[0]));
        }
      })
      .catch((e) => setTypesError(errorMessage(e)));
  }, []);

  const t = types.find((x) => x.label === label);
  const pick = (l: string) => {
    const nt = types.find((x) => x.label === l);
    setLabel(l);
    setRuns(String(nt?.default_runs ?? ""));
    setOpts(defaultOptions(nt));
  };
  const tplReady = !!setup?.tpl && !setup.tpl.stale;
  const latest = does.find((d) => d.job_id === job?.id) ?? does[0];

  const submit = () => {
    const params: Record<string, unknown> = { doe_label: label, options: opts, multi_execution: multi, radioss_assem_path: path.trim() };
    if (t?.runs_editable) params.num_runs = Number(runs);
    void run(params);
  };

  return (
    <Card step="①-3" title="DOE · Radioss 입력">
      <PathInput
        studyId={study.id}
        purpose="RADIOSS_ASSEM"
        label="Radioss 조립 폴더"
        placeholder="E:/shared/AI_WORK/cushion/00_inbox/radioss_assem"
        value={path}
        onChange={setPath}
        canExecute={canExec}
        onInspected={(r) => setOk(!!r?.ok)}
        renderSummary={(r) => (
          <div className="summary-line">
            starter <b className="mono">{((r.summary.starter as string[]) ?? []).join(", ") || "없음"}</b> · include {String(r.summary.inc_count ?? 0)}개
          </div>
        )}
      />
      {typesError ? (
        <p className="error-text small">{typesError}</p>
      ) : (
        <div className="form-grid">
          <Field label="DOE 유형">
            <select value={label} onChange={(e) => pick(e.target.value)} disabled={!canExec} aria-label="DOE 유형">
              {types.map((x) => (
                <option key={x.label}>{x.label}</option>
              ))}
            </select>
          </Field>
          <Field label="run 수" hint={t && !t.runs_editable ? "자동 계산(HyperStudy 결정)" : undefined}>
            <input className="num" aria-label="run 수" inputMode="numeric" value={t && !t.runs_editable ? "" : runs} placeholder={t && !t.runs_editable ? "자동" : ""} disabled={!canExec || (t ? !t.runs_editable : true)} onChange={(e) => setRuns(e.target.value.replace(/[^0-9]/g, ""))} />
          </Field>
          {(t?.fields ?? []).map((f) => (
            <OptionInput key={f.key} f={f} value={opts[f.key]} disabled={!canExec} onChange={(v) => setOpts((o) => ({ ...o, [f.key]: v }))} />
          ))}
        </div>
      )}
      <Advanced>
        <Field label="동시 실행 수(multiexec)" hint="기본 1 — Job Object 한도 안에서 동시에 도는 해석 수">
          <input className="num" inputMode="numeric" value={multi} onChange={(e) => setMulti(Math.max(1, Math.min(64, Number(e.target.value.replace(/[^0-9]/g, "")) || 1)))} aria-label="동시 실행 수" />
        </Field>
      </Advanced>
      <FeatureGate feature="train_doe">
        {(enabled) => (
          <RunAction
            canExecute={canExec}
            label="입력 생성"
            onRun={submit}
            job={job}
            disabled={!enabled || !ok || !tplReady || !t || (t.runs_editable && !(Number(runs) >= 2))}
            disabledReason={!enabled ? undefined : !tplReady ? (setup?.tpl ? "tpl을 다시 생성하세요(①-2)" : "①-2에서 tpl을 먼저 생성하세요") : !ok ? "조립 폴더를 입력하고 확인하세요" : "run 수는 2 이상"}
            error={error}
          />
        )}
      </FeatureGate>
      {latest && (
        <div className="doe-result small">
          <div>
            {latest.doe_label} · run <b>{latest.run_count ?? "–"}</b>개 · {latest.status === "READY" ? SAMPLE_TEXT[latest.sample_status] : latest.status === "BUILDING" ? "생성 중" : "실패"}
          </div>
          <CodeLine text={latest.dir_display_path} />
        </div>
      )}
    </Card>
  );
}
