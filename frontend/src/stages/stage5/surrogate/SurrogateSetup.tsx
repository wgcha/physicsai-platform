// ⑥ 새 내장 최적화(phase3.md §18.10, S17 §22.12): ① 템플릿·모델 ② 탐색(새 DOE / 완료 배치 재사용) ③ 성능 표(정의 편집·역할·가중치) ④ 변수 범위 ⑤ 설정·미리보기·시작.
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api, errorMessage, type PredictBatchSummary } from "../../../api";
import { surrogateApi, type SurrogateOptPreview } from "../../../api/surrogateOpt";
import { designMapApi, type DesignMap } from "../../../api/designMap";
import { useApp } from "../../../app/AppContext";
import { useStudy } from "../../../app/StudyContext";
import { useCanExecute } from "../../../hooks/useJobRunner";
import { useLatestJob } from "../../../hooks/useLatestJob";
import { Card, Field, NO_PERMISSION_TIP } from "../../../components/ui";
import { fmtNum, fmtTime, isTerminal } from "../../../lib/format";
import { addRow, rowError, type NativeRow } from "../../../lib/nativeVars";
import { useNativeRunRows } from "../../stage4/geometry/useNativeRunRows";
import { NativeVarsCard } from "./NativeVarsCard";
import { TemplatePicker, templateName, useTemplateChoice } from "../../stage4/TemplatePicker";
import { ModelLine, useModelChoice } from "../../stage4/predictRun";
import { InputKindSelect, useInputChoice } from "../../../components/InputKindSelect";
import { inputKindError } from "../../../lib/inputKind";
import { maxMultiExecution } from "../../stage4/batch/BatchSetup";
import {
  ALGO_REVERT_NOTE, EMPTY_ALGO, algoIssues, algoTip, baselineIds, buildBody, previewText, rowIssue, varRows,
  type AlgoDefaults, type Algorithm, type SoForm, type VarRow,
} from "./soRules";
import { AlgoOptions, AlgorithmField, NoneNote, VerificationField } from "./AlgoOptions";
import { PerfTable } from "./PerfTable";
import { DEFAULT_MAX_OBJECTIVES, DEFAULT_MAX_OBSERVE, perfRows, pruneSels, rolesIssue, roleCounts, type RoleSel } from "./perfRules";
import "../../../styles/surrogateMulti.css";

export function SurrogateSetup({ active, onStarted }: { active: boolean; onStarted?: () => void }) {
  const { status } = useApp();
  const { study } = useStudy();
  const navigate = useNavigate();
  const canExec = useCanExecute();
  const { list, ps, setPicked } = useTemplateChoice();
  const choice = useModelChoice();
  const ic = useInputChoice(ps);
  const [inputErr, setInputErr] = useState<string | null>(null);
  const soStatus = (status as { surrogate_opt?: { defaults?: { iterations: number; candidates: number; tol_rel: number; surrogate: string }; max_objectives?: number; max_observe?: number;
    default_algorithm?: string; algo_defaults?: Record<string, AlgoDefaults>; ga_max_evals?: number } } | null)?.surrogate_opt;
  const defs = soStatus?.defaults;
  const limits = { maxObjectives: soStatus?.max_objectives ?? DEFAULT_MAX_OBJECTIVES, maxObserve: soStatus?.max_observe ?? DEFAULT_MAX_OBSERVE };
  const maxMulti = maxMultiExecution(status);
  const [f, setF] = useState<SoForm>(() => ({
    paramSetId: ps?.id ?? null, modelId: null, explore: "new", count: "", exploreSeed: "1", batchId: "",
    sels: {}, weights: {}, rows: varRows(ps),
    surrogate: defs?.surrogate === "rbf" ? "rbf" : "gp", iterations: String(defs?.iterations ?? 3), candidates: String(defs?.candidates ?? 4),
    tolPct: String((defs?.tol_rel ?? 0.01) * 100), seed: "1", multi: String(Math.min(4, maxMulti)), capture: false,
    algorithm: soStatus?.default_algorithm === "ga" ? "ga" : "ego", verification: "loop", algo: { ...EMPTY_ALGO },
  }));
  const [algoNote, setAlgoNote] = useState<string | null>(null);
  const set = (p: Partial<SoForm>) => setF((x) => ({ ...x, ...p }));
  const [batches, setBatches] = useState<PredictBatchSummary[]>([]);
  const [dm, setDm] = useState<DesignMap | null>(null);
  const [preview, setPreview] = useState<SurrogateOptPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const [extractErr, setExtractErr] = useState<string | null>(null);
  // S17 §22.3.5: 재사용 배치의 H3D 성능 다시 추출(PB_RESP_EXTRACT) — 끝나면 미리보기를 다시 받는다
  const extract = useLatestJob(study.id, "PB_RESP_EXTRACT", () => setTick((n) => n + 1));
  const extractActive = !!extract.job && !isTerminal(extract.job.state);

  useEffect(() => set({ paramSetId: ps?.id ?? null, rows: varRows(ps), batchId: "", sels: {}, weights: {}, levels: null }), [ps?.id]);
  // native-vars.md §7.2: Native 템플릿은 세트 정의로 표를 초기화하고 풀에서 추가·제외한다(단일 baseline만 — 아니면 기존 표). 학습 범위는 고른 모델 기준
  const { native, pending, nv, rows: nrows, setRows: setN } = useNativeRunRows(ps, choice.chosenModel?.id ?? null);
  const bids = baselineIds(ps);
  const topo = !!preview?.levels?.baseline; // 위상 변형 세트만 범주 baseline(서버 미리보기 levels)
  const chosenLv = f.levels ?? bids;
  const toggleLevel = (b: string) => {
    const next = chosenLv.includes(b) ? chosenLv.filter((x) => x !== b) : bids.filter((x) => x === b || chosenLv.includes(x));
    set({ levels: next.length === bids.length ? null : next });
  };
  const perfs = useMemo(() => perfRows(ps?.responses), [ps?.responses]);
  // 템플릿 정의가 바뀌어 사라진 성능의 역할은 버린다
  useEffect(() => setF((x) => ({ ...x, sels: pruneSels(x.sels, perfs) })), [perfs]);
  useEffect(() => set({ modelId: choice.modelId || null }), [choice.modelId]);
  useEffect(() => {
    api.batches(study.id).then(setBatches).catch(() => setBatches([]));
  }, [study.id]);
  const reusable = batches.filter((b) => b.status === "DONE" && b.param_set?.id === ps?.id);
  useEffect(() => {
    if (f.explore === "reuse" && !f.batchId && reusable[0]) set({ batchId: reusable[0].id });
  }, [f.explore, reusable.length]);
  useEffect(() => {
    setDm(null);
    if (f.explore !== "reuse" || !f.batchId) return;
    designMapApi.get(f.batchId).then(setDm).catch(() => setDm(null));
  }, [f.explore, f.batchId]);

  const rowProblems = nrows ? nrows.map(rowError) : f.rows.map((r) => rowIssue(r, native));
  const body = useMemo(() => buildBody({ ...f, input: ic.picked, nrows }, perfs), [f, ic.picked, perfs, nrows]);
  const bodyKey = JSON.stringify(body);
  const roleProblem = rolesIssue(perfs, f.sels, f.weights);
  const ready = !!ps && !roleProblem && rowProblems.every((x) => !x) && (f.explore === "new" || !!f.batchId);
  useEffect(() => {
    if (!ready) {
      setPreview(null);
      return;
    }
    let live = true;
    const t = setTimeout(() => {
      surrogateApi.preview(study.id, body).then((p) => live && (setPreview(p), setError(null), setInputErr(null))).catch((e) => live && (setPreview(null), e instanceof ApiError && inputKindError(e.detail) ? (setInputErr(inputKindError(e.detail)), setError(null)) : setError(errorMessage(e))));
    }, 300);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [bodyKey, ready, study.id, tick]);

  const setRow = (i: number, p: Partial<VarRow>) => set({ rows: f.rows.map((r, j) => (j === i ? { ...r, ...p } : r)) });
  const patchN = (name: string, p: Partial<Pick<NativeRow, "use" | "lo" | "hi" | "fixed">>) => setN((rs) => rs.map((r) => (r.name === name ? { ...r, ...p } : r)));
  const setSel = (name: string, s: RoleSel) => setF((x) => ({ ...x, sels: { ...x.sels, [name]: s } }));
  const setWeight = (name: string, v: number | undefined) => setF((x) => {
    const w = { ...x.weights };
    if (v === undefined) delete w[name];
    else w[name] = v;
    return { ...x, weights: w };
  });
  const startExtract = async (batchId: string) => {
    setExtractErr(null);
    try {
      extract.track(await api.extractBatchResponses(batchId));
    } catch (e) {
      setExtractErr(errorMessage(e));
    }
  };
  const extractNote = extractErr ?? (extractActive ? `성능 다시 추출 진행 중${extract.job?.progress_pct != null ? ` ${Math.round(extract.job.progress_pct)}%` : ""} — 작업 대기열에서 확인하세요` : null);
  const nObj = roleCounts(f.sels, perfs.map((p) => p.name)).objectives;
  const algorithm: Algorithm = f.algorithm ?? "ego";
  // opt-native §10: 목적 수가 바뀌어 선택이 무효가 되면 EGO로 되돌리고 회색 한 줄로 알린다
  useEffect(() => {
    if (nObj > 0 && algoTip(algorithm, nObj)) {
      set({ algorithm: "ego" });
      setAlgoNote(ALGO_REVERT_NOTE);
    }
  }, [nObj, algorithm]);
  const nG = nrows ? nrows.filter((r) => r.use && !r.fixed).length : f.rows.filter((r) => !r.fixed).length;
  const algoProblems = algoIssues(algorithm, f.algo ?? EMPTY_ALGO, nG, soStatus?.algo_defaults?.[algorithm], soStatus?.ga_max_evals ?? 100000);
  const none = f.verification === "none";
  const reason = !ps ? "템플릿이 필요합니다" : !choice.chosenModel ? "Final 모델을 먼저 지정하세요" : active ? "진행 중인 내장 최적화가 있습니다" :
    roleProblem ? roleProblem : !ready ? "입력값을 확인하세요" : algoProblems.length ? "고급 옵션을 확인하세요" : preview?.problems.length ? "문제를 해결하세요" : null;
  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const o = await surrogateApi.create(study.id, body);
      onStarted?.();
      navigate(`/p/${study.project_id}/s/${study.id}/stage/5/surrogate/${o.id}`);
    } catch (e) {
      if (e instanceof ApiError && inputKindError(e.detail)) setInputErr(inputKindError(e.detail));
      else setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Card span={3} step="①" title="템플릿·모델">
        <TemplatePicker list={list} value={ps?.id ?? ""} onChange={setPicked} compact />
        <InputKindSelect ps={ps} value={ic.value} onChange={(i) => (ic.setPicked(i), setInputErr(null))} error={inputErr} />
        <ModelLine choice={choice} />
      </Card>
      <Card span={6} step="②" title="탐색">
        <div className="seg" role="radiogroup" aria-label="탐색">
          {(["new", "reuse"] as const).map((k) => (
            <button key={k} type="button" role="radio" aria-checked={f.explore === k} className={f.explore === k ? "on" : ""} onClick={() => set({ explore: k })}>
              {k === "new" ? "새 DOE" : "기존 배치 재사용"}
            </button>
          ))}
        </div>
        {f.explore === "new" ? (
          <div className="form-grid">
            <Field label="탐색 run 수" hint="빈 값 = max(10, 4 × 자유 변수)">
              <input className="num" inputMode="numeric" value={f.count} placeholder={preview ? String(preview.explore_count) : "자동"} onChange={(e) => set({ count: e.target.value.replace(/[^0-9]/g, "") })} aria-label="탐색 run 수" />
            </Field>
            <Field label="시드">
              <input className="num" inputMode="numeric" value={f.exploreSeed} onChange={(e) => set({ exploreSeed: e.target.value.replace(/[^0-9]/g, "") })} aria-label="탐색 시드" />
            </Field>
          </div>
        ) : reusable.length ? (
          <Field label="완료된 배치(같은 템플릿)">
            <select value={f.batchId} onChange={(e) => set({ batchId: e.target.value })} aria-label="재사용 배치">
              {reusable.map((b) => (
                <option key={b.id} value={b.id}>{b.label} · {b.run_count} run · {fmtTime(b.created_at).split(" ")[0]}</option>
              ))}
            </select>
          </Field>
        ) : (
          <p className="muted small">{ps ? `${templateName(ps)}로 완료된 일괄 예측이 없습니다 — ④에서 먼저 실행하세요` : "템플릿이 없습니다"}</p>
        )}
      </Card>
      <Card span={9} step="③" title="성능" aside={<span className="muted small">성능 = 템플릿 응답 정의(H3D·커브) · 역할은 이 최적화에만 적용됩니다</span>}>
        {ps ? (
          <PerfTable
            ps={ps} canEdit={canExec} sels={f.sels} onSel={setSel} weights={f.weights} onWeight={setWeight} limits={limits}
            preview={preview} reuse={f.explore === "reuse"} problems={preview?.problems ?? []} seriesHints={dm?.series ?? []}
            onExtract={(id) => void startExtract(id)} extractNote={extractNote} extractBusy={extractActive}
          />
        ) : (
          <p className="muted small">템플릿이 없습니다</p>
        )}
      </Card>
      {nrows && (
        <NativeVarsCard
          rows={nrows} nv={nv} canEdit={canExec} notes={preview?.var_notes}
          onPatch={patchN} onBulkUse={(names, use) => setN((rs) => rs.map((r) => (names.includes(r.name) ? { ...r, use } : r)))}
          onRemove={(name) => setN((rs) => rs.filter((r) => r.name !== name))} onAdd={(name) => nv && setN((rs) => addRow(nv, name, rs))}
        />
      )}
      {pending && (
        <Card span={9} step="④" title="변수 범위"><p className="muted small">변수 정의를 불러오는 중…</p></Card>
      )}
      {!nrows && !pending && (
      <Card span={9} step="④" title="변수 범위" aside={<span className="muted small">학습 범위 안만 · 하한 = 상한이면 고정</span>}>
        <div className="table-wrap">
          <table className="table compact" aria-label="변수 범위">
            <thead>
              <tr><th>변수</th><th className="num">학습 범위</th><th className="num">하한</th><th className="num">상한</th><th>정수</th><th>고정</th><th /></tr>
            </thead>
            <tbody>
              {f.rows.map((r, i) => (
                <tr key={r.name} data-testid={`var-${r.name}`}>
                  <td className="mono">{r.name}</td>
                  <td className="num muted">{fmtNum(r.min)} ~ {fmtNum(r.max)}</td>
                  <td className="num"><input className="num" value={r.lo} onChange={(e) => setRow(i, { lo: e.target.value })} aria-label={`${r.name} 하한`} /></td>
                  <td className="num">{r.fixed ? <span className="muted">고정</span> : <input className="num" value={r.hi} onChange={(e) => setRow(i, { hi: e.target.value })} aria-label={`${r.name} 상한`} />}</td>
                  <td className="small">{r.integer ? "정수" : ""}</td>
                  <td><input type="checkbox" checked={r.fixed} onChange={(e) => setRow(i, { fixed: e.target.checked })} aria-label={`${r.name} 고정`} /></td>
                  <td className="small error-text">{rowProblems[i] ?? ""}{r.na?.length ? <span className="muted" data-testid={`na-${r.name}`}> N/A: {r.na.join(", ")}</span> : null}</td>
                </tr>
              ))}
              {topo && (
                <tr data-testid="var-baseline">
                  <td className="mono">baseline</td>
                  <td className="muted small">범주(위상 변형)</td>
                  <td colSpan={4}>
                    {bids.map((b) => (
                      <label key={b} className="check small">
                        <input type="checkbox" checked={chosenLv.includes(b)} onChange={() => toggleLevel(b)} aria-label={`baseline ${b}`} /> {b}
                      </label>
                    ))}
                  </td>
                  <td className="small error-text">{chosenLv.length ? (chosenLv.length === 1 ? <span className="muted">1개 = 고정</span> : "") : "1개 이상 고르세요"}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
      )}
      <Card span={9} step="⑤" title="설정" foot={
        <div className="run-action">
          <div className="run-action-row">
            {canExec ? (
              <button type="button" className="btn primary" onClick={() => void start()} disabled={!!reason || busy} title={reason ?? undefined}>최적화 시작</button>
            ) : (
              <span className="readonly" title={NO_PERMISSION_TIP}>조회 전용 <span className="muted small">· {NO_PERMISSION_TIP}</span></span>
            )}
            {preview && <span className="small" data-testid="so-preview">{previewText(preview, Number(f.iterations) || 0, Number(f.candidates) || 0, nObj)}</span>}
            {canExec && reason && <span className="muted small">{reason}</span>}
          </div>
          {preview?.problems.filter((p) => !(p.code === "PERF_MISSING_IN_BATCH" && perfs.some((x) => x.name === p.performance))).map((p, i) => <p key={i} className="muted small" data-testid="so-problem">{p.message}</p>)}
          {nObj > 1 && <p className="muted small" data-testid="multi-hint">다목적은 탐색 run을 늘리면 전선이 안정됩니다</p>}
          {error && <div className="error-text small" role="alert">{error}</div>}
        </div>
      }>
        <div className="form-grid">
          <Field label="대리모델">
            <div className="seg" role="radiogroup" aria-label="대리모델">
              {(["gp", "rbf"] as const).map((k) => (
                <button key={k} type="button" role="radio" aria-checked={f.surrogate === k} className={f.surrogate === k ? "on" : ""} onClick={() => set({ surrogate: k })}>
                  {k === "gp" ? "GP(Kriging)" : "RBF"}
                </button>
              ))}
            </div>
          </Field>
          <AlgorithmField value={algorithm} nObj={nObj} note={algoNote} onChange={(a) => { set({ algorithm: a }); setAlgoNote(null); }} />
          <VerificationField value={f.verification ?? "loop"} onChange={(v) => set({ verification: v })} />
          {!none && <Field label="반복"><input className="num" value={f.iterations} onChange={(e) => set({ iterations: e.target.value.replace(/[^0-9]/g, "") })} aria-label="반복" /></Field>}
          <Field label="후보"><input className="num" value={f.candidates} onChange={(e) => set({ candidates: e.target.value.replace(/[^0-9]/g, "") })} aria-label="후보" /></Field>
          {!none && <Field label="개선 기준(%)"><input className="num" value={f.tolPct} onChange={(e) => set({ tolPct: e.target.value })} aria-label="개선 기준" /></Field>}
          <Field label="시드"><input className="num" value={f.seed} onChange={(e) => set({ seed: e.target.value.replace(/[^0-9]/g, "") })} aria-label="시드" /></Field>
          <Field label={`동시 실행 수(1~${maxMulti})`}><input className="num" value={f.multi} onChange={(e) => set({ multi: e.target.value.replace(/[^0-9]/g, "") })} aria-label="동시 실행 수" /></Field>
        </div>
        {none && <NoneNote />}
        <AlgoOptions algorithm={algorithm} value={f.algo ?? EMPTY_ALGO} onChange={(a) => set({ algo: a })} defs={soStatus?.algo_defaults?.[algorithm]} nG={nG} issues={algoProblems} />
        <label className="check">
          <input type="checkbox" checked={f.capture} onChange={(e) => set({ capture: e.target.checked })} /> 검증 run 컨투어 캡처
        </label>
        <p className="muted small">최적 설계는 끝난 뒤 다시 캡처(④)할 수 있습니다. 목적 값 자체가 예측이므로 FEM 검증 버튼으로 조립 상태 해석과 비교할 수 있습니다.</p>
      </Card>
    </>
  );
}
