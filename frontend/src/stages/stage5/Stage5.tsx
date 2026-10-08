import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Artifact, type Job, type Optimization, type OptResponse, type ResponseCandidates } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { useArtifactJson } from "../../hooks/useArtifact";
import { Advanced, Card, CodeLine, Field, RunAction } from "../../components/ui";
import { FeatureGate } from "../../components/FeatureGate";
import { Chart } from "../../components/Chart";
import { CsvView } from "../../components/CsvView";
import { fmtBytes, fmtNum, fmtTime, isTerminal } from "../../lib/format";
import { ResponseAddRow, ResponseTable } from "./ResponseTable";

type Method = "ARSM" | "GRSM" | "SQP";
/** 원본 GUI:110-114 METHOD_DEFAULTS */
export const METHOD_DEFAULTS: Record<Method, { max_designs: number; dv: number }> = {
  ARSM: { max_designs: 25, dv: 0.001 },
  GRSM: { max_designs: 50, dv: 0.001 },
  SQP: { max_designs: 25, dv: 0.0 },
};

interface RunSettings {
  approach: "OPT" | "DOE";
  method: Method;
  maxDesigns: string;
  runNominal: boolean;
  studyFolder: string;
  abs: string;
  rel: string;
  dv: string;
  onFailed: "IGNORE" | "TERMINATE";
}

/** 원본 GUI:799-811 사용 가능 규칙 */
export function activeRules(s: Pick<RunSettings, "approach" | "method">) {
  const opt = s.approach === "OPT";
  return { method: opt, absRel: opt && s.method === "ARSM", dv: opt && (s.method === "ARSM" || s.method === "SQP"), onFailed: opt };
}

/** 계약 §6.12: CONSTRAINT가 아니면 bound·value 제거, 소스별 키만 */
function cleanResponses(rows: OptResponse[]): OptResponse[] {
  return rows.map((r) => {
    const base = { name: r.name, source: r.source, component: r.component, stat: r.stat, goal: r.goal };
    const src = r.source === "H3D" ? { subcase: r.subcase, datatype: r.datatype, layer: r.layer ?? "" } : { request: r.request };
    const cons = r.goal === "CONSTRAINT" ? { bound: r.bound ?? "<=", value: r.value } : {};
    return { ...base, ...src, ...cons } as OptResponse;
  });
}

// ---------------------------------------------------------------- ⑤-1
function OptInputCard({ modelId, setModelId }: { modelId: string; setModelId: (v: string) => void }) {
  const { currentParamSet: ps, models } = useStudy();
  const active = models.filter((m) => m.status === "ACTIVE");
  const final = active.find((m) => m.is_final);
  const chosen = active.find((m) => m.id === modelId) ?? final;
  return (
    <Card step="⑤-1" title="입력">
      {ps ? (
        <div className="ps-summary small">
          <span>
            파라미터 세트 · 파라미터 <b>{ps.parameters.length}</b>
          </span>
          <span>
            학습 샘플 <b>{ps.sample_count}</b>
          </span>
          <span>단위계 {ps.unit_system}</span>
          <span className="mono muted ellipsis" title={ps.source_path}>
            {ps.source_path}
          </span>
        </div>
      ) : (
        <p className="muted">파라미터 세트가 없습니다 — ④에서 먼저 등록하세요.</p>
      )}
      <div className="model-line">
        <span className="field-label">모델</span>
        {chosen ? (
          <span>
            <b>{chosen.name}</b> v{chosen.version} {chosen.is_final && <span className="final-badge">Final</span>}
          </span>
        ) : (
          <span className="muted">Final 모델을 먼저 지정하세요</span>
        )}
      </div>
      <Advanced label="다른 모델">
        <select value={modelId} onChange={(e) => setModelId(e.target.value)} aria-label="모델 선택">
          <option value="">Final 모델(기본)</option>
          {active.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name} v{m.version}
            </option>
          ))}
        </select>
      </Advanced>
    </Card>
  );
}

// ---------------------------------------------------------------- ⑤-3
function OptRunCard({
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

// ---------------------------------------------------------------- ⑤-4
interface SummaryTable {
  columns: string[];
  rows: unknown[][];
}

function toTable(data: unknown): SummaryTable | null {
  const d = data as { columns?: unknown; rows?: unknown };
  if (!d || !Array.isArray(d.columns) || !Array.isArray(d.rows)) return null;
  const columns = d.columns.map(String);
  const rows = d.rows.map((r) => (Array.isArray(r) ? r : columns.map((c) => (r as Record<string, unknown>)?.[c])));
  return { columns, rows };
}

function fileEntries(data: unknown): { rel: string; size: number | null }[] {
  const arr = Array.isArray(data) ? data : Array.isArray((data as { files?: unknown })?.files) ? (data as { files: unknown[] }).files : [];
  return arr.map((f) =>
    typeof f === "string" ? { rel: f, size: null } : { rel: String((f as { rel?: string; path?: string; name?: string }).rel ?? (f as { path?: string }).path ?? (f as { name?: string }).name ?? ""), size: Number((f as { size?: number }).size ?? NaN) || null },
  );
}

/** 설계 이력 차트: 행 번호(설계) × 선택 열, 목적이 MINIMIZE/MAXIMIZE면 최적값 추이 함께 */
function HistoryChart({ table, responses }: { table: SummaryTable; responses: OptResponse[] }) {
  const numericCols = table.columns.filter((_c, i) => i > 0 && table.rows.some((r) => Number.isFinite(Number(r[i]))));
  const objective = responses.find((r) => (r.goal === "MINIMIZE" || r.goal === "MAXIMIZE") && numericCols.includes(r.name));
  const [col, setCol] = useState(objective?.name ?? numericCols[0] ?? "");
  const ci = table.columns.indexOf(col);
  if (ci < 0) return null;
  const goal = responses.find((r) => r.name === col)?.goal;
  const pts: [number, number][] = table.rows.map((r, i) => [i + 1, Number(r[ci])] as [number, number]).filter(([, y]) => Number.isFinite(y));
  const best: [number, number][] = [];
  if (goal === "MINIMIZE" || goal === "MAXIMIZE") {
    let b = goal === "MINIMIZE" ? Infinity : -Infinity;
    for (const [x, y] of pts) {
      b = goal === "MINIMIZE" ? Math.min(b, y) : Math.max(b, y);
      best.push([x, b]);
    }
  }
  return (
    <div className="history">
      <div className="history-head">
        <span className="field-label">설계 이력</span>
        <select value={col} onChange={(e) => setCol(e.target.value)} aria-label="이력 열">
          {numericCols.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
        {best.length > 0 && (
          <span className="small muted">
            최적 {fmtNum(best[best.length - 1][1])} ({goal === "MINIMIZE" ? "최소" : "최대"})
          </span>
        )}
      </div>
      <Chart
        height={220}
        aspect={0.3}
        maxHeight={520}
        ariaLabel="설계 이력"
        xLabel="설계"
        yLabel={col}
        lines={best.length ? [{ name: "best", pts: best, className: "chart-line s1" }] : []}
        points={pts.map(([x, y]) => ({ x, y, className: "chart-pt", title: `설계 ${x}: ${y}` }))}
      />
      {best.length > 0 && (
        <div className="legend small">
          <span>
            <span className="lg sample" /> 설계별 값
          </span>
          <span>
            <span className="lg line s1" /> 최적값 추이
          </span>
        </div>
      )}
    </div>
  );
}

function OptResult({ opt, job }: { opt: Optimization | null; job: Job | null }) {
  const summary = useArtifactJson<unknown>(opt?.summary_status === "PARSED" ? opt.summary_artifact_id : null);
  const fileList = useArtifactJson<unknown>(opt?.file_list_artifact_id);
  const [viewable, setViewable] = useState<Artifact[]>([]);
  const [view, setView] = useState<{ name: string; text: string; csv: boolean } | null>(null);
  const table = useMemo(() => toTable(summary), [summary]);

  useEffect(() => {
    setViewable([]);
    setView(null);
    if (!opt || opt.status !== "DONE") return;
    let alive = true;
    api
      .artifacts(opt.job_id)
      .then((a) => alive && setViewable(a.filter((x) => x.kind === "OPT_FILE")))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [opt?.job_id, opt?.status]);

  const open = async (a: Artifact) => {
    const text = await (await api.artifactBlob(a.id)).text();
    setView({ name: a.file_name, text, csv: /\.csv$/i.test(a.file_name) || a.content_type === "text/csv" });
  };

  if (!opt) return <p className="muted">최적화 결과가 없습니다.</p>;
  const running = opt.status === "RUNNING" || (!!job && !isTerminal(job.state) && job.id === opt.job_id);
  const n = opt.runs_started;
  const progress = opt.approach === "DOE" ? `run ${n ?? 0} 시작` : `run ${n ?? 0} / ${opt.max_designs} 시작`;
  const files = fileEntries(fileList);

  return (
    <div className="opt-result">
      <div className="result-head small" data-testid="opt-progress">
        {opt.approach} {opt.approach === "OPT" ? `· ${opt.opt_method}` : ""} · {opt.model_name} · {fmtTime(opt.created_at)} · {running ? progress : opt.status === "DONE" ? `완료 · ${progress.replace(" 시작", "")}` : "실패"}
      </div>
      {opt.status === "DONE" &&
        (table ? (
          <>
            <HistoryChart table={table} responses={opt.responses} />
            <details className="advanced">
              <summary>요약 표 ({table.rows.length}행)</summary>
              <div className="table-wrap summary-table">
                <table className="table compact" aria-label="결과 요약 표">
                  <thead>
                    <tr>
                      {table.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {table.rows.slice(0, 1000).map((r, i) => (
                      <tr key={i}>
                        {table.columns.map((_, j) => (
                          <td key={j} className={typeof r[j] === "number" ? "num" : ""}>
                            {typeof r[j] === "number" ? fmtNum(r[j] as number, 5) : String(r[j] ?? "")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </>
        ) : (
          <p className="muted" data-testid="summary-unknown">
            결과 요약 형식 미확인 — 원본 파일 목록을 확인하세요
          </p>
        ))}
      {opt.status === "DONE" && (
        <details className="advanced" open={!table}>
          <summary>원본 파일 목록 ({opt.file_count ?? files.length})</summary>
          <ul className="file-list small">
            {files.map((f) => {
              const a = viewable.find((v) => f.rel.endsWith(v.file_name));
              return (
                <li key={f.rel}>
                  {a ? (
                    <button type="button" className="link mono" onClick={() => void open(a)}>
                      {f.rel}
                    </button>
                  ) : (
                    <span className="mono">{f.rel}</span>
                  )}
                  <span className="muted"> {fmtBytes(f.size)}</span>
                </li>
              );
            })}
          </ul>
          {view && (
            <div className="file-view">
              <div className="field-label">
                {view.name}{" "}
                <button type="button" className="link small" onClick={() => setView(null)}>
                  닫기
                </button>
              </div>
              {view.csv ? <CsvView text={view.text} label={view.name} /> : <pre className="textview">{view.text.slice(0, 200_000)}</pre>}
            </div>
          )}
        </details>
      )}
      <CodeLine text={opt.folder_display_path} />
    </div>
  );
}

/** ⑤ 최적화(phase2.md §14.5) */
export function Stage5() {
  const { study } = useStudy();
  const canExec = useCanExecute();
  const [modelId, setModelId] = useState("");
  const [responses, setResponses] = useState<OptResponse[]>([]);
  const [cands, setCands] = useState<ResponseCandidates | null>(null);
  const [opts, setOpts] = useState<Optimization[]>([]);
  const [s, setS] = useState<RunSettings>({
    approach: "OPT", method: "ARSM", maxDesigns: "25", runNominal: true, studyFolder: "HST_PHYSICSAI_OPTIMIZATION", abs: "0.001", rel: "1.0", dv: "0.001", onFailed: "IGNORE",
  });
  const loadOpts = useCallback(() => api.optimizations(study.id).then(setOpts).catch(() => undefined), [study.id]);
  const runner = useJobRunner("OPTIMIZE", () => void loadOpts());

  useEffect(() => {
    api.responseCandidates(study.id, modelId || null).then(setCands).catch(() => setCands(null));
  }, [study.id, modelId]);
  useEffect(() => {
    void loadOpts();
  }, [loadOpts, runner.job?.id, runner.job?.version]);

  const latest = [...opts].sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null;

  return (
    <div className="stage-grid stage5">
      <OptInputCard modelId={modelId} setModelId={setModelId} />
      <Card step="⑤-2" title="응답">
        <ResponseTable rows={responses} onChange={setResponses} readOnly={!canExec} />
        {canExec && <ResponseAddRow candidates={cands} rows={responses} onAdd={(r) => setResponses([...responses, r])} />}
        <p className="muted small">Goal이 CONSTRAINT일 때만 Bound·Value를 씁니다. 단위계 mm-ton-s.</p>
      </Card>
      <OptRunCard s={s} setS={setS} responses={responses} modelId={modelId} runner={runner} />
      <Card step="⑤-4" title="결과">
        <OptResult opt={latest} job={runner.job} />
      </Card>
    </div>
  );
}
