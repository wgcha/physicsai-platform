import { useEffect, useState } from "react";
import { api, errorMessage, type DoeField, type DoeGenerator, type DoeType } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Card, CodeLine, Field, RunAction } from "../../components/ui";
import { useApp } from "../../app/AppContext";
import { PathInput } from "../../components/PathInput";
import { FeatureGate, useFeature } from "../../components/FeatureGate";
import { SamplingDescription } from "../../components/SamplingDescription";
import { HS_COMPAT_NOTE, HS_NOTE, descIdOf, hsCalcNote } from "../../lib/sampling";
import { useTrain } from "./TrainContext";
import { DoePlatformFields, Seg } from "./DoePlatformFields";
import { buildHyperstudyParams, buildPlatformParams, doeLimits, genText, initialPlatform, type PlatformState } from "./doeGenParams";

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

const GEN_LABEL: Record<DoeGenerator, string> = { platform: "플랫폼", hyperstudy: "HyperStudy" };

export function DoeGenCard() {
  const { study } = useStudy();
  const { setup, does, reloadDoes } = useTrain();
  const canExec = useCanExecute();
  const { job, run, error, errorDetail } = useJobRunner("TD_DOE_GEN", () => void reloadDoes());
  const lim = doeLimits(useApp().status);
  const [types, setTypes] = useState<DoeType[]>([]);
  const [typesError, setTypesError] = useState<string | null>(null);
  // S18 §23.9: 생성 방식 기본 = /status 설정값(저장하지 않는다). 사용자가 고르기 전에는 status 값을 따라간다
  const [pickedGen, setPickedGen] = useState<DoeGenerator | null>(null);
  // opt-native §4.4: HyperStudy(레거시) 생성은 features.train_doe가 꺼져 있으면 숨긴다(플랫폼만)
  const hstOn = useFeature("train_doe").enabled;
  const generator = !hstOn ? "platform" : pickedGen ?? lim.generatorDefault;
  const [plat, setPlat] = useState<PlatformState>(initialPlatform);
  const [platMulti, setPlatMulti] = useState<number | null>(null); // null = 설정 기본(4)을 따른다
  const [continueOnFail, setContinueOnFail] = useState(false);
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
        // S15 §20.10: 기본 = 서버가 추천한 유형(없으면 첫 항목)
        const first = t.find((x) => x.recommended) ?? t[0];
        if (first) {
          setLabel(first.label);
          setRuns(String(first.default_runs));
          setOpts(defaultOptions(first));
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
  const names = (setup?.parameters ?? []).filter((p) => p.use).map((p) => p.name);
  const isPlatform = generator === "platform";
  const platMultiShown = platMulti ?? lim.parallelDefault;

  const platformParams = () => buildPlatformParams(plat, names, { multi: platMultiShown, assemPath: path.trim(), maxRuns: lim.maxRuns, continueOnFailure: continueOnFail });
  const submit = () => {
    if (isPlatform) {
      const params = platformParams();
      if (params) void run(params);
      return;
    }
    void run(buildHyperstudyParams({ label, options: opts, multi, assemPath: path.trim(), runsEditable: !!t?.runs_editable, runs }));
  };
  const inputBad = isPlatform ? platformParams() === null : !t || (t.runs_editable && !(Number(runs) >= 2));
  const problems = errorDetail?.code === "DOE_SAMPLING_INVALID" && Array.isArray(errorDetail.problems) ? (errorDetail.problems as { code?: string; message?: string }[]) : [];

  return (
    <Card span={9} foot={
        <>
          <FeatureGate feature={isPlatform ? "train_doe_platform" : "train_doe"}>
            {(enabled) => (
              <RunAction
                canExecute={canExec}
                label="입력 생성"
                onRun={submit}
                job={job}
                disabled={!enabled || !ok || !tplReady || inputBad}
                disabledReason={!enabled ? undefined : !tplReady ? (setup?.tpl ? "tpl을 다시 생성하세요(①-2)" : "①-2에서 tpl을 먼저 생성하세요") : !ok ? "조립 폴더를 입력하고 확인하세요" : isPlatform ? "run 수·시드를 확인하세요" : "run 수는 2 이상"}
                error={error}
              />
            )}
          </FeatureGate>
        </>
      } step="①-3" title="DOE · Radioss 입력">
      <div className="field">
        <span className="field-label">생성 방식</span>
        <Seg
          label="생성 방식"
          value={generator}
          disabled={!canExec}
          options={[
            { key: "platform", label: "플랫폼 생성(동시 실행)" },
            ...(hstOn ? [{ key: "hyperstudy" as const, label: "HyperStudy(레거시)" }] : []),
          ]}
          onChange={setPickedGen}
        />
      </div>
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
      {isPlatform ? (
        <>
          <DoePlatformFields state={plat} onChange={setPlat} names={names} maxRuns={lim.maxRuns} disabled={!canExec} />
          <div className="form-grid">
            <Field label="동시 실행 수" hint={`1~${lim.maxMulti} · run마다 SimLab·HyperMesh를 동시에 실행합니다 — Altair 라이선스와 메모리 한도 안에서 정하세요`}>
              <input className="num" inputMode="numeric" value={platMultiShown} disabled={!canExec} onChange={(e) => setPlatMulti(Math.max(1, Math.min(lim.maxMulti, Number(e.target.value.replace(/[^0-9]/g, "")) || 1)))} aria-label="동시 실행 수" />
            </Field>
          </div>
          <label className="check">
            <input type="checkbox" checked={continueOnFail} disabled={!canExec} onChange={(e) => setContinueOnFail(e.target.checked)} /> 실패한 run이 있어도 성공한 run으로 DOE 완료
          </label>
          {problems.length > 0 && (
            <ul className="problems small error-text" data-testid="doe-problems" role="alert">
              {problems.map((p, i) => (
                <li key={i}>{p.message}</li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <>
          {typesError ? (
            <p className="error-text small">{typesError}</p>
          ) : (
            <div className="form-grid">
              <Field label="DOE 유형">
                <select value={label} onChange={(e) => pick(e.target.value)} disabled={!canExec} aria-label="DOE 유형">
                  {types.map((x) => (
                    <option key={x.label} value={x.label}>
                      {x.label}
                      {x.recommended ? " · 추천" : ""}
                    </option>
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
          {!typesError && t && (
            <div className="samp-pick">
              <SamplingDescription id={descIdOf(t.desc_id)} recommended={!!t.recommended} calc={hsCalcNote(descIdOf(t.desc_id), names.length)} />
              <p className="muted small hs-note" data-testid="hs-note">
                {HS_NOTE}
              </p>
            </div>
          )}
          <p className="muted small hs-note" data-testid="hs-compat-note">
            {HS_COMPAT_NOTE}
          </p>
          <div className="form-grid">
            <Field label="동시 실행 수(multiexec)" hint={`1~${lim.maxMulti} · 높일수록 빠르지만 CPU·라이선스를 더 씀`}>
              <input className="num" inputMode="numeric" value={multi} disabled={!canExec} onChange={(e) => setMulti(Math.max(1, Math.min(lim.maxMulti, Number(e.target.value.replace(/[^0-9]/g, "")) || 1)))} aria-label="동시 실행 수" />
            </Field>
          </div>
        </>
      )}
      {latest && (
        <div className="doe-result small">
          <div data-testid="doe-result-line">
            {latest.doe_label} · {GEN_LABEL[latest.generator]} · run <b>{latest.run_count ?? "–"}</b>개 · {latest.status === "READY" ? SAMPLE_TEXT[latest.sample_status] : latest.status === "BUILDING" ? "생성 중" : "실패"}
            {latest.generator === "platform" && genText(latest.gen) && ` · ${genText(latest.gen)}`}
          </div>
          <CodeLine text={latest.dir_display_path} />
        </div>
      )}
    </Card>
  );
}
