import { useEffect, useState } from "react";
import { api, errorMessage, type DoeField, type DoeGenerator, type DoeType, type ParamSet } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Card, CodeLine, Field, RunAction } from "../../components/ui";
import { useApp } from "../../app/AppContext";
import { PathInput } from "../../components/PathInput";
import { FeatureGate } from "../../components/FeatureGate";
import { SamplingDescription } from "../../components/SamplingDescription";
import { HS_COMPAT_NOTE, HS_NOTE, PLATFORM_GROUPS, SAMPLING_LABEL, descIdOf, hsCalcNote } from "../../lib/sampling";
import { genCategoryText } from "../../lib/geometry";
import { useTrain } from "./TrainContext";
import { DoePlatformFields, Seg } from "./DoePlatformFields";
import {
  NATIVE_DOE_LABEL, buildHyperstudyParams, buildNativeParams, buildPlatformParams, doeLimits, genText, initialNative, initialPlatform, skippedRuns, stratumCounts,
  type NativeDoeState, type PlatformState,
} from "./doeGenParams";

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

/** native에서 쓸 수 없는 것의 사유(§7.3.3: 플랫폼 LHS만) */
const NATIVE_ONLY_LHS = "native 형상 엔진 DOE는 플랫폼 생성 LHS만 됩니다";

/** ①-3 native 입력(geometry-engine.md §8 ①-3): 생성 방식 PLATFORM·표본 LHS(native) 고정, run 수·시드·동시 수·실패 처리, 세트 기준이면 층화 안내 */
function NativeFields({ state, onChange, set, disabled }: { state: NativeDoeState; onChange: (s: NativeDoeState) => void; set: ParamSet | null; disabled: boolean }) {
  const nb = set?.baselines?.length ?? 0;
  const n = Number(state.count);
  const strata = nb > 1 && Number.isInteger(n) && n >= 2 ? stratumCounts(n, nb) : [];
  return (
    <div className="samp-pick" data-testid="doe-native">
      <label className="field">
        <span className="field-label">표본 방식</span>
        <select aria-label="표본 방식" value="lhs" disabled={disabled} onChange={() => undefined}>
          <option value="lhs">{NATIVE_DOE_LABEL}</option>
          {PLATFORM_GROUPS.flatMap((g) => g.kinds)
            .filter((k) => k !== "lhs")
            .map((k) => (
              <option key={k} value={k} disabled>
                {SAMPLING_LABEL[k]} — 사용 불가
              </option>
            ))}
        </select>
      </label>
      <p className="muted small" data-testid="native-only-note">
        {NATIVE_ONLY_LHS} — HyperStudy·다른 표본 방식은 SimLab(①-1 SimLab 추출)에서 씁니다.
      </p>
      <div className="fill-row">
        <label className="inline-field">
          run 수
          <input className="num-input" inputMode="numeric" aria-label="run 수" value={state.count} disabled={disabled} onChange={(e) => onChange({ ...state, count: e.target.value.replace(/[^0-9]/g, "") })} />
        </label>
        <label className="inline-field">
          시드
          <input className="num-input" inputMode="numeric" aria-label="시드" value={state.seed} disabled={disabled} onChange={(e) => onChange({ ...state, seed: e.target.value.replace(/[^0-9]/g, "") })} />
        </label>
      </div>
      {nb > 1 && (
        <p className="small samp-note" data-testid="native-strata">
          다중 baseline {nb}개 — 층화 LHS로 baseline마다 나눠 뽑습니다{strata.length ? ` (${set!.baselines!.map((b, i) => `${b.id} ${strata[i]}개`).join(" · ")})` : ""}.
          {set?.param_map_status !== "confirmed" && <span className="warn-text"> 매칭표 확정 필요 — ④ 템플릿 상세의 '다중 baseline(고급)'에서 확정하세요.</span>}
        </p>
      )}
    </div>
  );
}

/** 형상 기준(native 템플릿이 있을 때만): ①-1 추출 결과 또는 native 템플릿(쉘 두께·다중 baseline 포함, 세트 조립 폴더 사용) */
function BasisSelect({ sets, value, onChange, disabled }: { sets: ParamSet[]; value: string; onChange: (id: string) => void; disabled: boolean }) {
  return (
    <label className="field">
      <span className="field-label">형상 기준</span>
      <select aria-label="형상 기준" value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        <option value="">①-1 추출 피처(조립 폴더 지정)</option>
        {sets.map((p) => (
          <option key={p.id} value={p.id}>
            템플릿 {p.label ?? p.cad_file_name}
            {(p.baselines?.length ?? 0) > 1 ? ` · baseline ${p.baselines!.length}개` : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

export function DoeGenCard() {
  const { study, paramSets } = useStudy();
  const { setup, does, reloadDoes } = useTrain();
  const canExec = useCanExecute();
  const { job, run, error, errorDetail } = useJobRunner("TD_DOE_GEN", () => void reloadDoes());
  const lim = doeLimits(useApp().status);
  const [types, setTypes] = useState<DoeType[]>([]);
  const [typesError, setTypesError] = useState<string | null>(null);
  // S18 §23.9: 생성 방식 기본 = /status 설정값(저장하지 않는다). 사용자가 고르기 전에는 status 값을 따라간다
  const [pickedGen, setPickedGen] = useState<DoeGenerator | null>(null);
  const generator = pickedGen ?? lim.generatorDefault;
  const [plat, setPlat] = useState<PlatformState>(initialPlatform);
  const [platMulti, setPlatMulti] = useState<number | null>(null); // null = 설정 기본(4)을 따른다
  const [continueOnFail, setContinueOnFail] = useState(false);
  const [label, setLabel] = useState("");
  const [runs, setRuns] = useState("");
  const [opts, setOpts] = useState<Record<string, string | number | boolean>>({});
  const [multi, setMulti] = useState(1);
  const [path, setPath] = useState("");
  const [ok, setOk] = useState(false);
  // native(geometry-engine.md §7.3.3): ①-1 native 추출 또는 native 템플릿 기준이면 템플릿(tpl) 대기 없이 활성
  const [nat, setNat] = useState<NativeDoeState>(initialNative);
  const [setId, setSetId] = useState("");
  const nativeSets = paramSets.filter((p) => p.engine === "native");
  const nset = nativeSets.find((p) => p.id === setId) ?? null;

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
  const native = setup?.engine === "native" || !!nset;
  const tplReady = native || (!!setup?.tpl && !setup.tpl.stale);
  const latest = does.find((d) => d.job_id === job?.id) ?? does[0];
  const names = (setup?.parameters ?? []).filter((p) => p.use).map((p) => p.name);
  const isPlatform = generator === "platform";
  const platMultiShown = platMulti ?? lim.parallelDefault;

  const platformParams = () => buildPlatformParams(plat, names, { multi: platMultiShown, assemPath: path.trim(), maxRuns: lim.maxRuns, continueOnFailure: continueOnFail });
  const nativeParams = () => buildNativeParams(nat, { multi: platMultiShown, maxRuns: lim.maxRuns, assemPath: path.trim(), paramSetId: nset?.id ?? null });
  const submit = () => {
    if (native) {
      const params = nativeParams();
      if (params) void run(params);
      return;
    }
    if (isPlatform) {
      const params = platformParams();
      if (params) void run(params);
      return;
    }
    void run(buildHyperstudyParams({ label, options: opts, multi, assemPath: path.trim(), runsEditable: !!t?.runs_editable, runs }));
  };
  const inputBad = native ? nativeParams() === null : isPlatform ? platformParams() === null : !t || (t.runs_editable && !(Number(runs) >= 2));
  // 세트 기준 native: 조립 폴더는 세트 것(입력 없음), 준비본 READY·다중 baseline 매칭표 확정이 필요(409 GEOM_PREP_STALE·PARAM_MAP_UNCONFIRMED)
  const assemOk = nset ? true : ok;
  const setGate = !nset ? null : nset.native?.prep_status !== "READY" ? "템플릿 형상 준비를 다시 하세요(④)" : (nset.baselines?.length ?? 0) > 1 && nset.param_map_status !== "confirmed" ? "매칭표 확정 필요(④ 다중 baseline)" : null;
  const skipped = native ? skippedRuns(job?.result, does.find((d) => d.job_id === job?.id)?.id) : [];
  const problems = errorDetail?.code === "DOE_SAMPLING_INVALID" && Array.isArray(errorDetail.problems) ? (errorDetail.problems as { code?: string; message?: string }[]) : [];

  return (
    <Card span={9} foot={
        <>
          <FeatureGate feature={native ? "geometry_native" : isPlatform ? "train_doe_platform" : "train_doe"}>
            {(enabled) => (
              <RunAction
                canExecute={canExec}
                label="입력 생성"
                onRun={submit}
                job={job}
                disabled={!enabled || !assemOk || !tplReady || inputBad || !!setGate}
                disabledReason={
                  !enabled ? undefined : !tplReady ? (setup?.tpl ? "tpl을 다시 생성하세요(①-2)" : "①-2에서 tpl을 먼저 생성하세요") : setGate ?? (!assemOk ? "조립 폴더를 입력하고 확인하세요" : native ? `run 수(2~${lim.maxRuns})·시드를 확인하세요` : isPlatform ? "run 수·시드를 확인하세요" : "run 수는 2 이상")
                }
                error={error}
              />
            )}
          </FeatureGate>
          {errorDetail?.code === "PARAM_MAP_UNCONFIRMED" && (
            <p className="warn-text small" data-testid="map-unconfirmed">
              다중 baseline 매칭표가 확정되지 않았습니다 — ④ 템플릿 상세의 &apos;다중 baseline(고급)&apos;에서 결정하고 [확정]을 누른 뒤 다시 생성하세요.
            </p>
          )}
        </>
      } step="①-3" title="DOE · Radioss 입력">
      {nativeSets.length > 0 && <BasisSelect sets={nativeSets} value={setId} onChange={setSetId} disabled={!canExec} />}
      <div className="field">
        <span className="field-label">생성 방식</span>
        <Seg
          label="생성 방식"
          value={native ? "platform" : generator}
          disabled={!canExec}
          options={[
            { key: "platform", label: native ? `플랫폼 생성 · ${NATIVE_DOE_LABEL}` : "플랫폼 생성(동시 실행)" },
            { key: "hyperstudy", label: "원본 HyperStudy(호환)", disabled: native, title: native ? NATIVE_ONLY_LHS : undefined },
          ]}
          onChange={setPickedGen}
        />
      </div>
      {!nset && <PathInput
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
      />}
      {native ? (
        <>
          <NativeFields state={nat} onChange={setNat} set={nset} disabled={!canExec} />
          <div className="form-grid">
            <Field label="동시 실행 수" hint={`1~${lim.maxMulti} · run마다 형상 모핑·검사를 동시에 실행합니다`}>
              <input className="num" inputMode="numeric" value={platMultiShown} disabled={!canExec} onChange={(e) => setPlatMulti(Math.max(1, Math.min(lim.maxMulti, Number(e.target.value.replace(/[^0-9]/g, "")) || 1)))} aria-label="동시 실행 수" />
            </Field>
          </div>
          <label className="check">
            <input type="checkbox" checked={nat.continueOnFailure} disabled={!canExec} onChange={(e) => setNat({ ...nat, continueOnFailure: e.target.checked })} /> 형상 생성에 실패한 run은 건너뛰고 나머지로 DOE 완료
          </label>
          {problems.length > 0 && (
            <ul className="problems small error-text" data-testid="doe-problems" role="alert">
              {problems.map((p, i) => (
                <li key={i}>{p.message}</li>
              ))}
            </ul>
          )}
        </>
      ) : isPlatform ? (
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
          {skipped.length > 0 && (
            <ul className="problems small" aria-label="건너뛴 run" data-testid="doe-skipped">
              {skipped.map((k) => (
                <li key={k.run_key}>
                  <span className="mono">{k.run_key}</span> {k.category && <span className="pill bad">{genCategoryText(k.category)}</span>} <span className="muted">{k.message || k.reason}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}
