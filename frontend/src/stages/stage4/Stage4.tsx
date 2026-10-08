import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, errorMessage, type Job, type ParamSet, type PredictCheck, type PredictResult as PR, type SampleRow } from "../../api";
import { useApp } from "../../app/AppContext";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Advanced, Card, CopyButton, RunAction } from "../../components/ui";
import { PathInput } from "../../components/PathInput";
import { POLL } from "../../lib/poll";
import { fmtTime, isIntegerFormat } from "../../lib/format";
import { ParamInputTable, ParamScatter, RangeNote, RoundingNote } from "./ParamInputs";
import { ContourPreview, CurveChart, PredictChain, ResponseTable } from "./PredictResult";

const MAX_SAMPLE_ROWS = 5000;
export const PBS_DISABLED_TEXT = "PBS 연결 안 됨 — 2차에서 제공(관리자 설정 필요)";

function ParamSetCard() {
  const { study, currentParamSet: ps, reloadParamSets } = useStudy();
  const canExec = useCanExecute();
  const [open, setOpen] = useState(false);
  const [path, setPath] = useState("");
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const register = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.registerParamSet(study.id, path.trim());
      await reloadParamSets();
      setOpen(false);
      setPath("");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card
      title="파라미터 세트"
      className="wide paramset"
      aside={
        canExec ? (
          <button type="button" className="btn small ghost" onClick={() => setOpen((v) => !v)}>
            {open ? "닫기" : ps ? "새 폴더 등록" : "폴더 등록"}
          </button>
        ) : (
          <span className="readonly small">조회 전용</span>
        )
      }
    >
      {ps ? (
        <div className="ps-summary">
          <span>
            파라미터 <b>{ps.parameters.length}</b>
          </span>
          <span>
            학습 샘플 <b>{ps.sample_count}</b>
            {ps.sample_has_measured ? " (실측 포함)" : ""}
          </span>
          <span>
            응답 <b>{ps.responses.length}</b>
          </span>
          <span>단위계 {ps.unit_system}</span>
          <span className="mono small muted ellipsis" title={ps.source_path}>
            {ps.source_path}
          </span>
          <span className="small muted">
            {ps.registered_by_name} · {fmtTime(ps.registered_at)}
          </span>
        </div>
      ) : (
        <p className="muted">등록된 파라미터 세트가 없습니다. 파라미터 정의·학습 샘플·CAD·tpl·조립 파일이 든 폴더를 등록하세요.</p>
      )}
      {open && canExec && (
        <div className="ps-register">
          <PathInput
            studyId={study.id}
            purpose="PARAM_SET"
            label="파라미터 세트 폴더 경로"
            placeholder="E:/shared/AI_WORK/cushion/00_inbox/params"
            value={path}
            onChange={setPath}
            canExecute={canExec}
            onInspected={(r) => setOk(!!r?.ok)}
            renderSummary={(r) => (
              <div className="small">
                {Object.entries(r.summary)
                  .filter(([, v]) => typeof v !== "object")
                  .map(([k, v]) => (
                    <span key={k} className="kv">
                      {k} <b>{String(v)}</b>
                    </span>
                  ))}
              </div>
            )}
          />
          <div className="run-action-row">
            <button type="button" className="btn primary" disabled={!ok || busy} onClick={register}>
              {busy ? "등록 중…" : "등록"}
            </button>
            {error && <span className="error-text small" role="alert">{error}</span>}
          </div>
        </div>
      )}
    </Card>
  );
}

function useSamples(ps: ParamSet | null) {
  const [rows, setRows] = useState<SampleRow[]>([]);
  useEffect(() => {
    setRows([]);
    if (!ps || ps.sample_count === 0) return;
    let alive = true;
    (async () => {
      const all: SampleRow[] = [];
      let cursor: string | null | undefined = undefined;
      do {
        const page = await api.samples(ps.id, 200, cursor);
        all.push(...page.rows);
        cursor = page.next_cursor;
      } while (cursor && all.length < MAX_SAMPLE_ROWS && alive);
      if (alive) setRows(all);
    })().catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [ps?.id]);
  return rows;
}

function PredictWorkspace({ ps }: { ps: ParamSet }) {
  const { status } = useApp();
  const { study, models } = useStudy();
  const canExec = useCanExecute();
  const samples = useSamples(ps);
  const nominal = useMemo(() => Object.fromEntries(ps.parameters.map((p) => [p.name, p.nominal])), [ps]);
  const [values, setValues] = useState<Record<string, number>>(nominal);
  const [source, setSource] = useState<{ kind: "nominal" | "run" | "manual"; run?: string }>({ kind: "nominal" });
  const [runPick, setRunPick] = useState("");
  const [check, setCheck] = useState<PredictCheck | null>(null);
  const [axes, setAxes] = useState<[string, string]>([ps.parameters[0]?.name ?? "", ps.parameters[1]?.name ?? ps.parameters[0]?.name ?? ""]);
  const [modelId, setModelId] = useState("");
  const predict = useJobRunner("PREDICT");
  const verify = useJobRunner("PREDICT_VERIFY");

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

  const activeModels = models.filter((m) => m.status === "ACTIVE");
  const finalModel = activeModels.find((m) => m.is_final) ?? null;
  const chosenModel = activeModels.find((m) => m.id === modelId) ?? finalModel;
  const allFinite = ps.parameters.every((p) => Number.isFinite(values[p.name]));

  const runPredict = () =>
    void predict.run({
      param_set_id: ps.id,
      model_id: modelId || null,
      values,
      value_source: source.kind,
      source_run_key: source.kind === "run" ? source.run : null,
    });

  const pjob = predict.job;
  const result = pjob?.state === "SUCCEEDED" ? (pjob.result as unknown as PR | null) : null;
  const hpcConfigured = !!status?.hpc.configured;
  const vjob: Job | null = verify.job && (verify.job.params as { predict_job_id?: string }).predict_job_id === pjob?.id ? verify.job : null;
  const verifyValues = vjob?.state === "SUCCEEDED" ? ((vjob.result as { verify_values?: Record<string, number> } | null)?.verify_values ?? null) : null;

  const pbsButton = (
    <button
      type="button"
      className="btn"
      disabled={!hpcConfigured || !result || !canExec}
      title={!hpcConfigured ? PBS_DISABLED_TEXT : !result ? "성공한 예측 결과가 필요합니다" : undefined}
      onClick={() => pjob && void verify.run({ predict_job_id: pjob.id, hpc: { queue: null, ncpus: null, walltime: null } })}
    >
      PBS 검증 해석
    </button>
  );

  // B16·B17: 입력파일은 RAD_ASSEMBLE 이후 준비(input_display_path가 채워짐) → input.zip
  const inputReady = !!pjob?.input_display_path;
  const [inputError, setInputError] = useState<string | null>(null);
  const downloadInput = async () => {
    if (!pjob) return;
    setInputError(null);
    try {
      const blob = await api.inputZip(pjob.id);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${study.folder_name}_${pjob.id.slice(0, 8)}_INPUT.zip`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      setInputError(errorMessage(e));
    }
  };

  return (
    <>
      <Card title="입력 · 실행" className="wide inputs">
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
              <div className="model-line">
                <span className="field-label">모델</span>
                {chosenModel ? (
                  <span>
                    <b>{chosenModel.name}</b> v{chosenModel.version} {chosenModel.is_final && <span className="final-badge">Final</span>}
                  </span>
                ) : (
                  <span className="muted">Final 모델이 없습니다 — ③-5에서 지정하세요</span>
                )}
                <Advanced label="다른 모델">
                  <select value={modelId} onChange={(e) => setModelId(e.target.value)} aria-label="모델 선택">
                    <option value="">Final 모델(기본)</option>
                    {activeModels.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name} v{m.version}
                      </option>
                    ))}
                  </select>
                </Advanced>
              </div>
              <RunAction
                canExecute={canExec}
                label="예측 실행"
                onRun={runPredict}
                job={pjob}
                disabled={!chosenModel || !allFinite}
                disabledReason={!chosenModel ? "Final 모델이 필요합니다" : "모든 파라미터 값을 입력하세요"}
                error={predict.error}
                extra={canExec ? pbsButton : undefined}
              />
              {canExec && !hpcConfigured && <p className="muted small pbs-note" data-testid="pbs-note">{PBS_DISABLED_TEXT}</p>}
              {verify.error && <p className="error-text small">{verify.error}</p>}
              {vjob && <p className="small">PBS 검증: {vjob.state}</p>}
              <PredictChain job={pjob} />
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

      <Card
        title="결과"
        className="wide result"
        aside={
          pjob ? (
            <span className="run-action-row">
              {inputError && <span className="error-text small">{inputError}</span>}
              <button type="button" className="btn small" onClick={downloadInput} disabled={!inputReady} title={inputReady ? "INPUT 폴더의 .rad·.inc를 zip으로 받습니다" : "입력파일이 아직 준비되지 않았습니다"}>
                입력파일 받기
              </button>
            </span>
          ) : undefined
        }
      >
        {!result ? (
          <p className="muted">{pjob && pjob.state !== "SUCCEEDED" ? "예측이 끝나면 결과가 여기에 표시됩니다." : "예측 결과가 없습니다."}</p>
        ) : (
          <>
            <div className="result-head small">
              입력{" "}
              {Object.entries(result.applied_values ?? result.values)
                .map(([k, v]) => `${k}=${v}`)
                .join(", ")}
              {" · "}
              {result.out_of_range?.length ? `학습 범위 밖${result.nearest ? ` · 최근접 ${result.nearest.run_key}` : ""}` : result.nearest ? `최근접 ${result.nearest.run_key} (거리 ${result.nearest.distance.toFixed(2)})` : ""}
            </div>
            {pjob?.input_display_path && (
              <div className="codeline small" title="입력 폴더(탐색기에 붙여넣기)">
                <code>{pjob.input_display_path}</code>
                <CopyButton text={pjob.input_display_path} label="경로 복사" />
              </div>
            )}
            <div className="result-grid">
              <ContourPreview result={result} />
              <div className="result-side">
                {result.curve_artifact_id && <CurveChart artifactId={result.curve_artifact_id} />}
                <div>
                  <div className="field-label">응답값</div>
                  <ResponseTable rows={result.response_table ?? []} verify={verifyValues} nearestRun={result.nearest?.run_key ?? null} />
                </div>
              </div>
            </div>
          </>
        )}
      </Card>
    </>
  );
}

/** ④ 단일 예측(§16.5) */
export function Stage4() {
  const { currentParamSet } = useStudy();
  return (
    <div className="stage-grid stage4">
      <ParamSetCard />
      {currentParamSet && <PredictWorkspace key={currentParamSet.id} ps={currentParamSet} />}
    </div>
  );
}
