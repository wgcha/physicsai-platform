// ⑤ 새 내장 최적화(phase3.md §18.10): ① 템플릿·모델 ② 탐색(새 DOE / 완료 배치 재사용) ③ 목적 ④ 제약 ⑤ 변수 범위 ⑥ 설정 ⑦ 미리보기·시작.
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorMessage, type PredictBatchSummary } from "../../../api";
import { surrogateApi, type SurrogateOptPreview } from "../../../api/surrogateOpt";
import { designMapApi, type DesignMap } from "../../../api/designMap";
import { useApp } from "../../../app/AppContext";
import { useStudy } from "../../../app/StudyContext";
import { useCanExecute } from "../../../hooks/useJobRunner";
import { Card, Field, NO_PERMISSION_TIP } from "../../../components/ui";
import { fmtNum, fmtTime } from "../../../lib/format";
import { TemplatePicker, templateName, useTemplateChoice } from "../../stage4/TemplatePicker";
import { ModelLine, useModelChoice } from "../../stage4/predictRun";
import { maxMultiExecution } from "../../stage4/batch/BatchSetup";
import { buildBody, newDoeMetrics, previewText, rowIssue, varRows, type Constraint, type SoForm, type VarRow } from "./soRules";

const MAX_CONSTRAINTS = 5;

export function SurrogateSetup({ active, onStarted }: { active: boolean; onStarted?: () => void }) {
  const { status } = useApp();
  const { study } = useStudy();
  const navigate = useNavigate();
  const canExec = useCanExecute();
  const { list, ps, setPicked } = useTemplateChoice();
  const choice = useModelChoice();
  const defs = (status as { surrogate_opt?: { defaults?: { iterations: number; candidates: number; tol_rel: number; surrogate: string } } } | null)
    ?.surrogate_opt?.defaults;
  const maxMulti = maxMultiExecution(status);
  const [f, setF] = useState<SoForm>(() => ({
    paramSetId: ps?.id ?? null, modelId: null, explore: "new", count: "", exploreSeed: "1", batchId: "",
    metric: "", series: null, sense: "min", constraints: [], rows: varRows(ps),
    surrogate: defs?.surrogate === "rbf" ? "rbf" : "gp", iterations: String(defs?.iterations ?? 3), candidates: String(defs?.candidates ?? 4),
    tolPct: String((defs?.tol_rel ?? 0.01) * 100), seed: "1", multi: String(Math.min(4, maxMulti)), capture: false,
  }));
  const set = (p: Partial<SoForm>) => setF((x) => ({ ...x, ...p }));
  const [batches, setBatches] = useState<PredictBatchSummary[]>([]);
  const [dm, setDm] = useState<DesignMap | null>(null);
  const [preview, setPreview] = useState<SurrogateOptPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => set({ paramSetId: ps?.id ?? null, rows: varRows(ps), batchId: "" }), [ps?.id]);
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

  const metrics = f.explore === "reuse" ? dm?.metrics ?? [] : newDoeMetrics(ps);
  useEffect(() => {
    if (!metrics.some((m) => m.id === f.metric)) set({ metric: metrics[0]?.id ?? "", series: null });
  }, [metrics.map((m) => m.id).join("|")]);
  const curMetric = metrics.find((m) => m.id === f.metric) ?? null;
  const seriesList = f.explore === "reuse" && curMetric?.needs_series ? dm?.series ?? [] : [];

  const rowProblems = f.rows.map(rowIssue);
  const body = useMemo(() => buildBody(f), [f]);
  const bodyKey = JSON.stringify(body);
  const ready = !!ps && !!f.metric && rowProblems.every((x) => !x) && (f.explore === "new" || !!f.batchId);
  useEffect(() => {
    if (!ready) {
      setPreview(null);
      return;
    }
    let live = true;
    const t = setTimeout(() => {
      surrogateApi.preview(study.id, body).then((p) => live && (setPreview(p), setError(null))).catch((e) => live && (setPreview(null), setError(errorMessage(e))));
    }, 300);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [bodyKey, ready, study.id]);

  const setRow = (i: number, p: Partial<VarRow>) => set({ rows: f.rows.map((r, j) => (j === i ? { ...r, ...p } : r)) });
  const setCons = (i: number, p: Partial<Constraint>) => set({ constraints: f.constraints.map((c, j) => (j === i ? { ...c, ...p } : c)) });
  const reason = !ps ? "템플릿이 필요합니다" : !choice.chosenModel ? "Final 모델을 먼저 지정하세요" : active ? "진행 중인 내장 최적화가 있습니다" :
    !ready ? "입력값을 확인하세요" : preview?.problems.length ? "문제를 해결하세요" : null;
  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const o = await surrogateApi.create(study.id, body);
      onStarted?.();
      navigate(`/p/${study.project_id}/s/${study.id}/stage/5/surrogate/${o.id}`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Card span={3} step="①" title="템플릿·모델">
        <TemplatePicker list={list} value={ps?.id ?? ""} onChange={setPicked} compact />
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
      <Card span={3} step="③" title="목적">
        <div className="form-grid">
          <Field label="지표">
            <select value={f.metric} onChange={(e) => set({ metric: e.target.value, series: null })} aria-label="목적 지표">
              {!metrics.length && <option value="">지표 없음</option>}
              {metrics.map((m) => <option key={m.id} value={m.id}>{m.label}{m.unit ? ` [${m.unit}]` : ""}</option>)}
            </select>
          </Field>
          {seriesList.length > 1 && (
            <Field label="커브">
              <select value={f.series ?? seriesList[0]} onChange={(e) => set({ series: e.target.value })} aria-label="커브 계열">
                {seriesList.map((s) => <option key={s}>{s}</option>)}
              </select>
            </Field>
          )}
          <Field label="방향">
            <div className="seg" role="radiogroup" aria-label="방향">
              {(["min", "max"] as const).map((k) => (
                <button key={k} type="button" role="radio" aria-checked={f.sense === k} className={f.sense === k ? "on" : ""} onClick={() => set({ sense: k })}>
                  {k === "min" ? "최소화" : "최대화"}
                </button>
              ))}
            </div>
          </Field>
        </div>
      </Card>
      <Card span={6} step="④" title="제약(선택)">
        {f.constraints.map((c, i) => (
          <div key={i} className="form-grid so-cons-row" data-testid={`cons-${i}`}>
            <select value={c.metric} onChange={(e) => setCons(i, { metric: e.target.value })} aria-label={`제약 ${i + 1} 지표`}>
              {metrics.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
            <select value={c.op} onChange={(e) => setCons(i, { op: e.target.value as "<=" | ">=" })} aria-label={`제약 ${i + 1} 부호`}>
              <option value="<=">≤</option>
              <option value=">=">≥</option>
            </select>
            <input className="num" value={c.value} onChange={(e) => setCons(i, { value: e.target.value })} aria-label={`제약 ${i + 1} 값`} />
            <button type="button" className="btn small ghost" onClick={() => set({ constraints: f.constraints.filter((_, j) => j !== i) })}>삭제</button>
          </div>
        ))}
        {f.constraints.length < MAX_CONSTRAINTS && (
          <button type="button" className="btn small" disabled={!metrics.length} onClick={() => set({ constraints: [...f.constraints, { metric: metrics[0]?.id ?? "", op: "<=", value: "" }] })}>
            제약 추가
          </button>
        )}
      </Card>
      <Card span={9} step="⑤" title="변수 범위" aside={<span className="muted small">학습 범위 안만 · 하한 = 상한이면 고정</span>}>
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
                  <td className="small error-text">{rowProblems[i] ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card span={9} step="⑥" title="설정" foot={
        <div className="run-action">
          <div className="run-action-row">
            {canExec ? (
              <button type="button" className="btn primary" onClick={() => void start()} disabled={!!reason || busy} title={reason ?? undefined}>최적화 시작</button>
            ) : (
              <span className="readonly" title={NO_PERMISSION_TIP}>조회 전용 <span className="muted small">· {NO_PERMISSION_TIP}</span></span>
            )}
            {preview && <span className="small" data-testid="so-preview">{previewText(preview, Number(f.iterations) || 0, Number(f.candidates) || 0)}</span>}
            {canExec && reason && <span className="muted small">{reason}</span>}
          </div>
          {preview?.problems.map((p, i) => <p key={i} className="muted small" data-testid="so-problem">{p.message}</p>)}
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
          <Field label="반복"><input className="num" value={f.iterations} onChange={(e) => set({ iterations: e.target.value.replace(/[^0-9]/g, "") })} aria-label="반복" /></Field>
          <Field label="후보"><input className="num" value={f.candidates} onChange={(e) => set({ candidates: e.target.value.replace(/[^0-9]/g, "") })} aria-label="후보" /></Field>
          <Field label="개선 기준(%)"><input className="num" value={f.tolPct} onChange={(e) => set({ tolPct: e.target.value })} aria-label="개선 기준" /></Field>
          <Field label="시드"><input className="num" value={f.seed} onChange={(e) => set({ seed: e.target.value.replace(/[^0-9]/g, "") })} aria-label="시드" /></Field>
          <Field label={`동시 실행 수(1~${maxMulti})`}><input className="num" value={f.multi} onChange={(e) => set({ multi: e.target.value.replace(/[^0-9]/g, "") })} aria-label="동시 실행 수" /></Field>
        </div>
        <label className="check">
          <input type="checkbox" checked={f.capture} onChange={(e) => set({ capture: e.target.checked })} /> 검증 run 컨투어 캡처
        </label>
        <p className="muted small">최적 설계는 끝난 뒤 다시 캡처(④)할 수 있습니다. 목적 값 자체가 예측이므로 FEM 검증 버튼으로 조립 상태 해석과 비교할 수 있습니다.</p>
      </Card>
    </>
  );
}
