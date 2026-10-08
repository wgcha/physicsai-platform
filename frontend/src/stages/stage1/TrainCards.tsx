import { useEffect, useMemo, useState } from "react";
import { api, ApiError, errorMessage, type DoeField, type DoeType, type TrainParam } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Advanced, Card, CodeLine, Field, RunAction } from "../../components/ui";
import { PathInput } from "../../components/PathInput";
import { FeatureGate } from "../../components/FeatureGate";
import { fmtTime } from "../../lib/format";
import { useTrain } from "./TrainContext";

// ---------------------------------------------------------------- ①-1
export function CadExtractCard() {
  const { study } = useStudy();
  const { setup, reloadSetup } = useTrain();
  const canExec = useCanExecute();
  const { job, run, error } = useJobRunner("TD_EXTRACT_PARAMS", () => void reloadSetup());
  const [path, setPath] = useState("");
  const [ok, setOk] = useState(false);
  const params = setup?.parameters ?? [];

  return (
    <Card step="①-1" title="CAD 파라미터 추출">
      <PathInput
        studyId={study.id}
        purpose="CAD_FILE"
        label="CAD 파일 경로 (.prt)"
        placeholder="E:/shared/AI_WORK/cushion/00_inbox/cad/cushion_parametric_modeling.prt"
        value={path}
        onChange={setPath}
        canExecute={canExec}
        onInspected={(r) => setOk(!!r?.ok)}
        renderSummary={(r) => (
          <div className="summary-line">
            <span className="mono">{String(r.summary.file_name ?? "")}</span> · {Math.round(Number(r.summary.size ?? 0) / 1024).toLocaleString()} KB
            {r.summary.extension_ok === false && <span className="error-text small"> · 확장자 불가</span>}
          </div>
        )}
      />
      <FeatureGate feature="train_extract">
        {(enabled) => (
          <RunAction
            canExecute={canExec}
            label="파라미터 추출"
            onRun={() => void run({ cad_path: path.trim() })}
            job={job}
            disabled={!enabled || !ok}
            disabledReason={enabled ? "CAD 파일 경로를 입력하고 확인하세요" : undefined}
            error={error}
          />
        )}
      </FeatureGate>
      {setup?.cad && (
        <div className="result-line small">
          <span>
            추출 <b>{params.length}</b>개 (사용 가능 {params.filter((p) => p.valid).length})
          </span>
          <span className="mono ellipsis" title={setup.cad.display_path}>
            {setup.cad.file_name}
          </span>
          <span className="muted">{fmtTime(setup.updated_at)}</span>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- ①-2
interface Row {
  name: string;
  raw: string;
  nominal: number | null;
  min: string;
  max: string;
  use: boolean;
  format: string;
  unit: string;
  valid: boolean;
  problems: string[];
}

const probText = (p: TrainParam["problems"]): string[] => (p as unknown[]).map((x) => (typeof x === "string" ? x : String((x as { message?: string }).message ?? "")));
const toRow = (p: TrainParam): Row => ({
  name: p.name, raw: p.raw_nominal, nominal: p.nominal, min: p.min == null ? "" : String(p.min), max: p.max == null ? "" : String(p.max),
  use: p.use, format: p.format, unit: p.unit, valid: p.valid, problems: probText(p.problems),
});
const num = (s: string): number | null => (s.trim() === "" || !Number.isFinite(Number(s)) ? null : Number(s));

/** 클라이언트 표시용 행 문제(서버 검증과 같은 규칙, §6.3) */
function rowIssue(r: Row): string | null {
  if (!r.use) return null;
  const lo = num(r.min);
  const hi = num(r.max);
  if (lo === null || hi === null) return "하한·상한을 입력하세요";
  if (!(lo < hi)) return "하한 < 상한";
  if (r.nominal !== null && (r.nominal < lo || r.nominal > hi)) return "공칭값이 범위 밖";
  if (!/^%[-0-9.]*[idfeEgG]$/.test(r.format)) return "형식 오류";
  return null;
}

export function ParamTableCard() {
  const { study } = useStudy();
  const { setup, setSetup } = useTrain();
  const canExec = useCanExecute();
  const [rows, setRows] = useState<Row[]>([]);
  const [showAdv, setShowAdv] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [serverProblems, setServerProblems] = useState<Record<string, string>>({});

  useEffect(() => {
    setRows((setup?.parameters ?? []).map(toRow));
    setServerProblems({});
  }, [setup?.version, setup?.parameters]);

  const set = (i: number, patch: Partial<Row>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const used = rows.filter((r) => r.use);
  const issues = rows.map(rowIssue);
  const hasIssue = issues.some(Boolean) || used.length === 0;

  /** §14.2: PUT 저장 → POST 생성. 저장 실패 시 생성하지 않는다 */
  const generate = async () => {
    if (!setup) return;
    setBusy(true);
    setError(null);
    setServerProblems({});
    try {
      const saved = await api.saveTrainParams(study.id, {
        version: setup.version,
        parameters: rows.map((r) => ({ name: r.name, min: num(r.min), max: num(r.max), use: r.use, format: r.format, unit: r.unit })),
      });
      setSetup(saved);
      try {
        setSetup(await api.generateTpl(study.id, saved.version));
      } catch (e) {
        setError(errorMessage(e));
      }
    } catch (e) {
      if (e instanceof ApiError && Array.isArray((e.detail as { problems?: unknown }).problems)) {
        const m: Record<string, string> = {};
        for (const p of (e.detail as unknown as { problems: { name: string; message: string }[] }).problems) m[p.name] = p.message;
        setServerProblems(m);
      }
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const tpl = setup?.tpl;
  const dirty = useMemo(() => {
    const orig = (setup?.parameters ?? []).map(toRow);
    return JSON.stringify(orig.map((r) => [r.min, r.max, r.use, r.format, r.unit])) !== JSON.stringify(rows.map((r) => [r.min, r.max, r.use, r.format, r.unit]));
  }, [rows, setup?.parameters]);

  return (
    <Card
      step="①-2"
      title="파라미터 표"
      aside={
        rows.length > 0 ? (
          <button type="button" className={`btn small ghost ${showAdv ? "on" : ""}`} aria-pressed={showAdv} onClick={() => setShowAdv((v) => !v)}>
            고급 {showAdv ? "▾" : "▸"}
          </button>
        ) : undefined
      }
    >
      {!rows.length ? (
        <p className="muted">①-1에서 CAD 파라미터를 먼저 추출하세요.</p>
      ) : (
        <div className="table-wrap">
          <table className="table compact param-table" aria-label="파라미터 표">
            <thead>
              <tr>
                <th>사용</th>
                <th>이름</th>
                <th className="num">공칭</th>
                <th className="num">하한</th>
                <th className="num">상한</th>
                {showAdv && <th>형식</th>}
                {showAdv && <th>단위</th>}
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const note = serverProblems[r.name] ?? issues[i] ?? (!r.valid ? r.problems.join(" · ") || "사용 불가" : null);
                return (
                  <tr key={r.name} className={r.use ? "" : "unused"}>
                    <td>
                      <input type="checkbox" aria-label={`${r.name} 사용`} checked={r.use} disabled={!canExec || !r.valid || r.nominal === null} onChange={(e) => set(i, { use: e.target.checked })} />
                    </td>
                    <td className="mono">{r.name}</td>
                    <td className="num mono">{r.raw}</td>
                    <td className="num">
                      <input className="num-input" aria-label={`${r.name} 하한`} value={r.min} disabled={!canExec || !r.use} inputMode="decimal" onChange={(e) => set(i, { min: e.target.value })} />
                    </td>
                    <td className="num">
                      <input className="num-input" aria-label={`${r.name} 상한`} value={r.max} disabled={!canExec || !r.use} inputMode="decimal" onChange={(e) => set(i, { max: e.target.value })} />
                    </td>
                    {showAdv && (
                      <td>
                        <input className="fmt-input mono" aria-label={`${r.name} 형식`} value={r.format} disabled={!canExec || !r.use} onChange={(e) => set(i, { format: e.target.value })} />
                      </td>
                    )}
                    {showAdv && (
                      <td>
                        <input className="unit-input" aria-label={`${r.name} 단위`} value={r.unit} maxLength={16} disabled={!canExec} onChange={(e) => set(i, { unit: e.target.value })} />
                      </td>
                    )}
                    <td className="muted small row-note">{note}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <FeatureGate feature="train_tpl">
        {(enabled) => (
          <RunAction
            canExecute={canExec}
            label={busy ? "생성 중…" : "tpl 생성"}
            onRun={() => void generate()}
            disabled={!enabled || busy || !rows.length || hasIssue}
            disabledReason={enabled ? (!rows.length ? "추출된 파라미터가 없습니다" : used.length === 0 ? "사용 파라미터가 1개 이상 필요합니다" : "표의 회색 문구를 확인하세요") : undefined}
            error={error}
          />
        )}
      </FeatureGate>
      {tpl && (
        <div className="tpl-state small" data-testid="tpl-state">
          <div>
            tpl 생성됨 · 사용 <b>{tpl.params.length}</b>개 · {fmtTime(tpl.generated_at)}
          </div>
          {(tpl.stale || dirty) && <div className="warn-text">표가 바뀌었습니다 — tpl을 다시 생성하세요</div>}
          {tpl.warnings.map((w, i) => (
            <div key={i} className="muted">
              {w.message}
            </div>
          ))}
        </div>
      )}
      <p className="muted small">단위계 mm-ton-s. 사용하지 않는 파라미터는 tpl에서 빠지고 CAD 공칭값이 유지됩니다.</p>
    </Card>
  );
}

// ---------------------------------------------------------------- ①-3
function defaultOptions(t: DoeType | undefined): Record<string, string | number | boolean> {
  return Object.fromEntries((t?.fields ?? []).map((f) => [f.key, f.default]));
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
